"""MCP-1 Foundation Behavioral Contract Tests.

Engineering Quality Asset. Validates behavioral contracts for 4 core MCP tools
against the MCP Contract Inventory (OPENCB_MCP_CONTRACT_INVENTORY.md).

Tools under test:
  - memory_lab_health            :: callable; shape {status, service, version}
  - memory_lab_content_create_id :: callable; content_id in shape; WS isolation
  - memory_lab_content_get       :: callable; content_id in shape; 404→structured error; WS isolation
  - query_memory                 :: callable; {answer, status} shape; WS isolation; graceful no-context

Architecture:
  MCPHermeticClient   — MemoryLabApiClient subclass backed by FastAPI TestClient;
                        no real HTTP, no real DB, no provider calls.
  FakePersistenceAdapter — in-memory workspace-scoped content store (replaces ApiAdapter).
  FakeQueryService    — workspace-scoped deterministic answer generator (replaces QueryService).
  WS-aware auth       — reads X-Workspace-ID header; returns matching AuthContext for WS_A / WS_B.

The hermetic_client fixture is designed to be reusable across MCP-1..N contract slices.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from fastapi import Request
from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app
from memory_lab.mcp.client import MemoryLabApiClient, MemoryLabApiError
from memory_lab.reasoning.models import AskRequest, AskResponse

import memory_lab.api.routers.content as content_router
import memory_lab.api.routers.ask as ask_router
import memory_lab.mcp.tools as mcp_tools

pytestmark = [pytest.mark.unit]

# ─── Workspace constants ──────────────────────────────────────────────────────
WS_A = "00000000-0000-0000-0001-000000000001"
WS_B = "00000000-0000-0000-0001-000000000002"
SUBJECT = "00000000-0000-0000-0000-000000000099"


# ─── FakePersistenceAdapter ───────────────────────────────────────────────────
class FakePersistenceAdapter:
    """In-memory workspace-scoped content store.

    Replaces memory_lab.api.services.api_adapter.ApiAdapter in tests.
    Class-level state is reset by the hermetic_client fixture before each test.
    """

    _store: Dict[str, Dict[str, Any]] = {}  # {workspace_id: {content_id: row}}

    @classmethod
    def reset(cls) -> None:
        cls._store = {}

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def create_content_minimal(
        self,
        content: Optional[str],
        workspace_id: str,
        workspace_source: str = "header",
        created_by_subject: str = SUBJECT,
    ) -> Dict[str, Any]:
        content_id = str(uuid.uuid4())
        row: Dict[str, Any] = {
            "content_id": content_id,
            "workspace_id": workspace_id,
            "persisted": True,
        }
        self.__class__._store.setdefault(workspace_id, {})[content_id] = row
        return {"content_id": content_id, "workspace_id": workspace_id, "persisted": True}

    def get_content_minimal(
        self, content_id: str, workspace_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        if not workspace_id:
            return None
        return self.__class__._store.get(workspace_id, {}).get(content_id)


# ─── FakeQueryService ─────────────────────────────────────────────────────────
class FakeQueryService:
    """Workspace-scoped deterministic answer generator.

    Replaces memory_lab.query.service.QueryService in tests.
    No DB, no provider, no network — answers encode the workspace_id
    so workspace isolation tests can assert divergent responses.
    """

    def __init__(self, database_url: str, **_kwargs: Any) -> None:
        self.database_url = database_url

    @classmethod
    def from_database_url(cls, database_url: str, **kwargs: Any) -> "FakeQueryService":
        return cls(database_url)

    def execute(self, request: AskRequest, workspace_id: str) -> AskResponse:
        query = request.normalized_query()
        # Trigger phrase for graceful no-context test
        if query.startswith("__no_context__"):
            return AskResponse(
                answer="No relevant context found for this query.",
                intent="lookup",
                confidence=0.0,
                confidence_explanation="no evidence available",
                citations=[],
                status="insufficient_evidence",
                mode="deterministic",
                workspace_id=workspace_id,
            )
        # Normal deterministic answer — encodes full workspace_id for isolation assertions
        return AskResponse(
            answer=f"deterministic:ws={workspace_id}:q={query[:40]}",
            intent="lookup",
            confidence=0.85,
            confidence_explanation="fake deterministic path",
            citations=[],
            status="ok",
            mode="deterministic",
            workspace_id=workspace_id,
        )


# ─── MCPHermeticClient ────────────────────────────────────────────────────────
class MCPHermeticClient(MemoryLabApiClient):
    """MemoryLabApiClient backed by a FastAPI TestClient — no real HTTP.

    Routes _request() through TestClient.request() instead of real sockets.
    Workspace IDs are forwarded via X-Workspace-ID header exactly as the
    production client would do.
    """

    def __init__(self, test_client: TestClient) -> None:
        super().__init__(base_url="http://testserver")
        self._tc = test_client

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        headers: Dict[str, str] = {}
        selected = self._selected_workspace_id(workspace_id)
        if selected:
            headers["X-Workspace-ID"] = selected

        resp = self._tc.request(
            method=method,
            url=path,
            params=params,
            json=json_body,
            headers=headers or None,
        )
        if resp.status_code < 200 or resp.status_code >= 300:
            raise MemoryLabApiError(
                f"Non-2xx from {method} {path}: {resp.status_code}",
                method=method,
                url=path,
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json()


# ─── Auth helper ──────────────────────────────────────────────────────────────
def _install_ws_aware_auth(app: Any, permissions: list[str]) -> None:
    """Override require_permission deps to return workspace-aware AuthContext.

    Reads X-Workspace-ID from the request header so that MCPHermeticClient's
    per-call workspace_id propagates correctly through the full tool→client→API stack.
    """

    def _make_override() -> Any:
        async def override(request: Request) -> AuthContext:
            ws = request.headers.get("X-Workspace-ID", WS_A)
            return AuthContext(
                auth_subject_id=SUBJECT,
                subject_type="user",
                workspace_id=ws,
                role="owner",
                auth_method="test",
            )
        return override

    for permission in permissions:
        override_fn = _make_override()
        # Route scan: override the actual closure-based dependency objects
        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if not dependant:
                continue
            for dep in getattr(dependant, "dependencies", []):
                call = getattr(dep, "call", None)
                if (
                    getattr(call, "__name__", "") == "_dependency"
                    and getattr(call, "__closure__", None)
                ):
                    closure_values = [cell.cell_contents for cell in call.__closure__]
                    if permission in closure_values:
                        app.dependency_overrides[call] = override_fn
        # Static key override (belt-and-suspenders)
        app.dependency_overrides[require_permission(permission)] = override_fn


# ─── hermetic_client fixture ──────────────────────────────────────────────────
@pytest.fixture
def hermetic_client(monkeypatch: pytest.MonkeyPatch) -> MCPHermeticClient:
    """Hermetic MCP fixture: MCPHermeticClient wired to a FastAPI TestClient.

    Reusable across MCP-1..N contract slices. Provides:
      - No real HTTP, no real DB, no provider calls
      - Workspace-aware auth via X-Workspace-ID header (WS_A / WS_B)
      - FakePersistenceAdapter: in-memory content store
      - FakeQueryService: deterministic workspace-scoped answers
      - mcp_tools._client monkeypatched to return this client
    """
    FakePersistenceAdapter.reset()

    app = create_app()
    _install_ws_aware_auth(app, ["content.create", "content.read", "retrieval.search"])

    monkeypatch.setattr(content_router, "ApiAdapter", FakePersistenceAdapter)
    monkeypatch.setattr(
        content_router,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"),
    )
    monkeypatch.setattr(ask_router, "QueryService", FakeQueryService)
    monkeypatch.setattr(
        ask_router,
        "get_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://unit/hermetic",
            ask_provider_synthesis_enabled=False,
        ),
    )

    tc = TestClient(app, raise_server_exceptions=True)
    hc = MCPHermeticClient(tc)
    monkeypatch.setattr(mcp_tools, "_client", lambda: hc)

    return hc


# ─── Fail-client helper (for error-shape tests) ───────────────────────────────
def _fail_client(status_code: int = 503, body: str = "service unavailable") -> MCPHermeticClient:
    """Returns a MemoryLabApiClient that always raises MemoryLabApiError."""

    class _FailClient(MemoryLabApiClient):
        def __init__(self) -> None:
            super().__init__(base_url="http://testserver")

        def _request(self, method: str, path: str, **_kw: Any) -> Dict[str, Any]:
            raise MemoryLabApiError(
                f"forced failure: {status_code}",
                method=method,
                url=path,
                status_code=status_code,
                body=body,
            )

    return _FailClient()  # type: ignore[return-value]


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-C1: memory_lab_health — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_health_C1_1_callable_without_exception(hermetic_client: MCPHermeticClient) -> None:
    """C1.1 — health tool is callable and never raises a raw exception."""
    result = mcp_tools.memory_lab_health()
    assert isinstance(result, dict), f"health must return dict, got {type(result)}"


def test_health_C1_2_required_success_shape(hermetic_client: MCPHermeticClient) -> None:
    """C1.2 — health success response contains {status: 'ok', service, version}."""
    result = mcp_tools.memory_lab_health()
    assert result.get("status") == "ok", f"status != 'ok': {result}"
    assert "service" in result, f"'service' missing from health response: {result}"
    assert "version" in result, f"'version' missing from health response: {result}"


def test_health_C1_3_structured_error_shape_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """C1.3 — API failure returns {{ok: False, error: {{type, message, ...}}}}; no raw exception."""
    monkeypatch.setattr(mcp_tools, "_client", lambda: _fail_client(503))
    result = mcp_tools.memory_lab_health()
    assert isinstance(result, dict), "result must be a dict even on failure"
    assert result.get("ok") is False, f"ok must be False on failure, got {result}"
    assert "error" in result, f"'error' key missing from structured error: {result}"
    err = result["error"]
    assert "type" in err, f"'type' missing from error dict: {err}"
    assert "message" in err, f"'message' missing from error dict: {err}"


def test_health_C1_4_structured_error_preserves_status_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """C1.4 — structured error preserves HTTP status_code from the underlying response."""
    monkeypatch.setattr(mcp_tools, "_client", lambda: _fail_client(503, "down"))
    result = mcp_tools.memory_lab_health()
    err = result.get("error", {})
    assert "status_code" in err, f"'status_code' missing from error: {err}"
    assert err["status_code"] == 503


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-C2: memory_lab_content_create_id — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_content_create_C2_1_callable_without_exception(hermetic_client: MCPHermeticClient) -> None:
    """C2.1 — content_create_id tool is callable and never raises a raw exception."""
    result = mcp_tools.memory_lab_content_create_id(
        content="contract test payload", workspace_id=WS_A
    )
    assert isinstance(result, dict)


def test_content_create_C2_2_required_success_shape(hermetic_client: MCPHermeticClient) -> None:
    """C2.2 — success response contains content_id (str) and persisted (bool)."""
    result = mcp_tools.memory_lab_content_create_id(
        content="shape contract test", workspace_id=WS_A
    )
    assert "content_id" in result, f"'content_id' missing: {result}"
    assert "persisted" in result, f"'persisted' missing: {result}"
    assert isinstance(result["content_id"], str)
    assert len(result["content_id"]) > 0


def test_content_create_C2_3_workspace_isolation(hermetic_client: MCPHermeticClient) -> None:
    """C2.3 — content created in WS_A is not retrievable from WS_B (workspace boundary enforced)."""
    res = mcp_tools.memory_lab_content_create_id(
        content="WS_A private content", workspace_id=WS_A
    )
    assert "content_id" in res, f"create failed: {res}"
    cid = res["content_id"]

    # WS_B must not see content that belongs to WS_A
    cross_result = mcp_tools.memory_lab_content_get(content_id=cid, workspace_id=WS_B)
    assert cross_result.get("ok") is False, (
        f"WS_B must not see WS_A content; expected structured error, got {cross_result}"
    )


def test_content_create_C2_4_structured_error_on_adapter_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2.4 — 500 from API (e.g. adapter error) returns {ok: False, error: {...}}; no raw exception.

    Uses raise_server_exceptions=False so TestClient returns HTTP 500 rather than
    re-raising the server-side RuntimeError. MCPHermeticClient converts 5xx to
    MemoryLabApiError; _call_api catches it and returns a structured error dict.
    """
    FakePersistenceAdapter.reset()

    app = create_app()
    _install_ws_aware_auth(app, ["content.create"])

    class _BrokenAdapter:
        def __init__(self, database_url: str) -> None:
            pass

        def create_content_minimal(self, *_a: Any, **_kw: Any) -> None:
            raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(content_router, "ApiAdapter", _BrokenAdapter)
    monkeypatch.setattr(
        content_router,
        "get_settings",
        lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"),
    )

    # raise_server_exceptions=False: TestClient returns 500 instead of re-raising
    tc = TestClient(app, raise_server_exceptions=False)
    hc = MCPHermeticClient(tc)
    monkeypatch.setattr(mcp_tools, "_client", lambda: hc)

    result = mcp_tools.memory_lab_content_create_id(content="fail", workspace_id=WS_A)

    assert isinstance(result, dict), f"must return dict even on 500, got {type(result)}"
    assert result.get("ok") is False, f"ok must be False for 500 response, got {result}"
    assert "error" in result
    err = result["error"]
    assert "type" in err, f"'type' missing from error: {err}"
    assert "message" in err, f"'message' missing from error: {err}"
    assert err.get("status_code") == 500


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-C3: memory_lab_content_get — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_content_get_C3_1_callable_without_exception(hermetic_client: MCPHermeticClient) -> None:
    """C3.1 — content_get tool is callable and never raises a raw exception."""
    res = mcp_tools.memory_lab_content_create_id(content="retrieve me", workspace_id=WS_A)
    cid = res["content_id"]
    result = mcp_tools.memory_lab_content_get(content_id=cid, workspace_id=WS_A)
    assert isinstance(result, dict)


def test_content_get_C3_2_required_success_shape(hermetic_client: MCPHermeticClient) -> None:
    """C3.2 — success response contains content_id matching the requested ID."""
    res = mcp_tools.memory_lab_content_create_id(content="get shape test", workspace_id=WS_A)
    cid = res["content_id"]
    result = mcp_tools.memory_lab_content_get(content_id=cid, workspace_id=WS_A)
    assert "content_id" in result, f"'content_id' missing from get response: {result}"
    assert result["content_id"] == cid, (
        f"returned content_id {result['content_id']!r} != requested {cid!r}"
    )


def test_content_get_C3_3_structured_error_on_not_found(
    hermetic_client: MCPHermeticClient,
) -> None:
    """C3.3 — nonexistent content_id returns {{ok: False, error: {{type, message, status_code}}}}."""
    result = mcp_tools.memory_lab_content_get(
        content_id=str(uuid.uuid4()), workspace_id=WS_A
    )
    assert isinstance(result, dict)
    assert result.get("ok") is False, f"Expected structured error for 404, got {result}"
    assert "error" in result
    err = result["error"]
    assert "type" in err, f"'type' missing from error: {err}"
    assert "message" in err, f"'message' missing from error: {err}"
    assert "status_code" in err, f"'status_code' missing from error: {err}"
    assert err["status_code"] == 404


def test_content_get_C3_4_workspace_isolation(hermetic_client: MCPHermeticClient) -> None:
    """C3.4 — WS_B content not visible from WS_A; WS_B can read its own content."""
    res_b = mcp_tools.memory_lab_content_create_id(
        content="WS_B private content", workspace_id=WS_B
    )
    assert "content_id" in res_b, f"WS_B create failed: {res_b}"
    cid = res_b["content_id"]

    # WS_A must not see WS_B content
    result_cross = mcp_tools.memory_lab_content_get(content_id=cid, workspace_id=WS_A)
    assert result_cross.get("ok") is False, (
        f"WS_A must not see WS_B content; expected structured error, got {result_cross}"
    )

    # WS_B owner can read its own content
    result_own = mcp_tools.memory_lab_content_get(content_id=cid, workspace_id=WS_B)
    assert "content_id" in result_own, f"WS_B get of own content failed: {result_own}"
    assert result_own["content_id"] == cid


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-C4: query_memory — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_query_memory_C4_1_callable_without_exception(
    hermetic_client: MCPHermeticClient,
) -> None:
    """C4.1 — query_memory tool is callable and never raises a raw exception."""
    result = mcp_tools.query_memory(query="What is Context Brain?", workspace_id=WS_A)
    assert isinstance(result, dict)


def test_query_memory_C4_2_required_success_shape(hermetic_client: MCPHermeticClient) -> None:
    """C4.2 — success response contains answer (non-empty str) and status."""
    result = mcp_tools.query_memory(query="retrieval architecture", workspace_id=WS_A)
    assert "answer" in result, f"'answer' missing from query_memory response: {result}"
    assert "status" in result, f"'status' missing from query_memory response: {result}"
    assert isinstance(result["answer"], str)
    assert len(result["answer"]) > 0


def test_query_memory_C4_3_workspace_isolation(hermetic_client: MCPHermeticClient) -> None:
    """C4.3 — query_memory answers are workspace-scoped: WS_A and WS_B return distinct answers."""
    q = "governance policy"
    result_a = mcp_tools.query_memory(query=q, workspace_id=WS_A)
    result_b = mcp_tools.query_memory(query=q, workspace_id=WS_B)

    assert isinstance(result_a, dict)
    assert isinstance(result_b, dict)
    assert "answer" in result_a
    assert "answer" in result_b
    assert result_a["answer"] != result_b["answer"], (
        "WS_A and WS_B must return different answers (workspace isolation violated)"
    )


def test_query_memory_C4_4_no_context_graceful(hermetic_client: MCPHermeticClient) -> None:
    """C4.4 — no-context query returns {{answer, status}} dict; no raw exception, no structured error."""
    result = mcp_tools.query_memory(query="__no_context__trigger", workspace_id=WS_A)
    assert isinstance(result, dict), f"must return dict for no-context, got {type(result)}"
    assert "answer" in result, f"'answer' missing from no-context result: {result}"
    # No-context must NOT be a structured API error
    assert result.get("ok") is not False, (
        f"no-context must not produce a structured error: {result}"
    )
    # Answer must be a non-empty string (graceful degradation)
    assert isinstance(result["answer"], str) and len(result["answer"]) > 0
