"""MCP-2 Hub Surface Behavioral Contract Tests.

Engineering Quality Asset. Validates behavioral contracts for 6 hub-surface MCP tools
against the MCP Contract Inventory (OPENCB_MCP_CONTRACT_INVENTORY.md).

Tools under test:
  - memory_lab_hub_create      :: callable; shape {hub_id, title, type, status}; WS isolation
  - memory_lab_hub_get         :: callable; shape {hub_id, title}; 404→structured error; WS isolation
  - memory_lab_hub_link_content:: callable; shape {hub_id, content_id, linked}; 404→structured error
  - list_hubs                  :: callable; shape []; WS-scoped list; no cross-WS leakage
  - update_hub                 :: callable; mutation visible via get; 404→structured error; WS isolation
  - save_and_link_to_hub       :: callable; creates content+link; shape {content_id, linked, hub_id}

Architecture:
  Reuses MCPHermeticClient, FakePersistenceAdapter, _install_ws_aware_auth from MCP-1.
  FakeHubStore — in-memory workspace-scoped hub store (replaces HubStore).
  FakeHubApiAdapter — thin wrapper over FakePersistenceAdapter + FakeHubStore
                      (replaces ApiAdapter in hubs router).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from fastapi import Request
from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.main import create_app
from memory_lab.mcp.client import MemoryLabApiClient, MemoryLabApiError

import memory_lab.api.routers.hubs as hubs_router
import memory_lab.api.routers.content as content_router
import memory_lab.mcp.tools as mcp_tools

pytestmark = [pytest.mark.unit]

# ─── Workspace constants ──────────────────────────────────────────────────────
WS_A = "00000000-0000-0000-0001-000000000001"
WS_B = "00000000-0000-0000-0001-000000000002"
SUBJECT = "00000000-0000-0000-0000-000000000099"


# ─── FakeHubStore ─────────────────────────────────────────────────────────────
class FakeHubStore:
    """In-memory workspace-scoped hub store. Replaces HubStore in hubs router."""

    _hubs: Dict[str, Dict[str, Any]] = {}       # {hub_id: hub_row}
    _links: Dict[str, List[str]] = {}            # {hub_id: [content_id, ...]}

    @classmethod
    def reset(cls) -> None:
        cls._hubs = {}
        cls._links = {}

    def __init__(self, dsn: Optional[str] = None) -> None:
        self.dsn = dsn

    # ---- hub CRUD ----
    def create_hub(
        self,
        title: str,
        type: str = "topic",
        description: Optional[str] = None,
        aliases: Optional[List[str]] = None,
        related_terms: Optional[List[str]] = None,
        workspace_id: Optional[str] = None,
        workspace_uuid: Optional[str] = None,
        owner_defined: bool = True,
        created_by_subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        hub_id = str(uuid.uuid4())
        now = "2025-01-01T00:00:00+00:00"
        row: Dict[str, Any] = {
            "hub_id": hub_id,
            "title": title,
            "type": type,
            "description": description,
            "aliases": aliases or [],
            "related_terms": related_terms or [],
            "status": "active",
            "owner_defined": owner_defined,
            "workspace_id": workspace_id,
            "workspace_uuid": workspace_uuid or workspace_id,
            "created_by_subject": created_by_subject,
            "created_at": now,
            "updated_at": now,
            "linked_content_ids": [],
        }
        self.__class__._hubs[hub_id] = row
        return dict(row)

    def get_hub(
        self, hub_id: str, workspace_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        row = self.__class__._hubs.get(hub_id)
        if not row:
            return None
        if workspace_id and row.get("workspace_uuid") != workspace_id:
            return None
        row = dict(row)
        row["linked_content_ids"] = list(self.__class__._links.get(hub_id, []))
        return row

    def list_hubs(
        self, workspace_id: Optional[str] = None, status: str = "active"
    ) -> List[Dict[str, Any]]:
        result = []
        for row in self.__class__._hubs.values():
            if workspace_id and row.get("workspace_uuid") != workspace_id:
                continue
            if row.get("status") != status:
                continue
            r = dict(row)
            r["linked_content_ids"] = list(self.__class__._links.get(row["hub_id"], []))
            result.append(r)
        return result

    def update_hub(
        self, hub_id: str, updates: Dict[str, Any], workspace_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        row = self.get_hub(hub_id, workspace_id=workspace_id)
        if not row:
            return None
        allowed = {"title", "type", "description", "aliases", "related_terms", "status"}
        for k, v in updates.items():
            if k in allowed:
                self.__class__._hubs[hub_id][k] = v
        return self.get_hub(hub_id, workspace_id=workspace_id)

    def link_content(
        self,
        hub_id: str,
        content_id: str,
        workspace_id: Optional[str] = None,
        created_by_subject: Optional[str] = None,
    ) -> bool:
        if hub_id not in self.__class__._hubs:
            raise KeyError(f"hub not found: {hub_id}")
        row = self.get_hub(hub_id, workspace_id=workspace_id)
        if not row:
            raise KeyError(f"hub not found in workspace: {hub_id}")
        self.__class__._links.setdefault(hub_id, [])
        if content_id in self.__class__._links[hub_id]:
            raise ValueError(f"already linked: {content_id}")
        self.__class__._links[hub_id].append(content_id)
        return True


# ─── FakePersistenceAdapter (same as MCP-1, self-contained) ──────────────────
class FakePersistenceAdapter:
    """In-memory workspace-scoped content store. Replaces ApiAdapter for content routes."""

    _store: Dict[str, Dict[str, Any]] = {}

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


# ─── FakeHubApiAdapter ────────────────────────────────────────────────────────
class FakeHubApiAdapter:
    """Thin adapter bridging hubs router to FakeHubStore + FakePersistenceAdapter.

    Replaces ApiAdapter in hubs router. Mirrors only the methods called by hubs router.
    """

    def __init__(self, database_url: str) -> None:
        self.hub_store = FakeHubStore()
        self._content = FakePersistenceAdapter(database_url)

    @staticmethod
    def _workspace_meta(workspace_id: Optional[str], source: Optional[str] = None) -> Dict[str, Any]:
        if not workspace_id:
            return {}
        return {"workspace_id": workspace_id, "workspace_source": source or "header"}

    def create_hub(
        self,
        payload: Dict[str, Any],
        workspace_id: Optional[str] = None,
        workspace_source: Optional[str] = None,
        created_by_subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        hub = self.hub_store.create_hub(
            title=payload["title"],
            type=payload.get("hub_type", "topic"),
            description=payload.get("description"),
            aliases=payload.get("aliases") or [],
            related_terms=payload.get("related_terms") or [],
            workspace_uuid=workspace_id,
            created_by_subject=created_by_subject,
        )
        hub.update(self._workspace_meta(workspace_id, workspace_source))
        return hub

    def get_hub(self, hub_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.hub_store.get_hub(hub_id, workspace_id=workspace_id)

    def link_content(
        self,
        hub_id: str,
        content_id: str,
        workspace_id: Optional[str] = None,
        created_by_subject: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.hub_store.link_content(hub_id, content_id, workspace_id=workspace_id,
                                    created_by_subject=created_by_subject)
        result: Dict[str, Any] = {"hub_id": hub_id, "content_id": content_id, "linked": True}
        if workspace_id:
            result["workspace_id"] = workspace_id
        return result


# ─── MCPHermeticClient (same pattern as MCP-1, self-contained) ───────────────
class MCPHermeticClient(MemoryLabApiClient):
    """MemoryLabApiClient backed by FastAPI TestClient — no real HTTP."""

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
        app.dependency_overrides[require_permission(permission)] = override_fn


HUB_PERMISSIONS = [
    "hubs.create", "hubs.read", "hubs.update", "hubs.link",
    "content.create", "content.read",
]


# ─── hermetic_client_hubs fixture ────────────────────────────────────────────
@pytest.fixture
def hermetic_client_hubs(monkeypatch: pytest.MonkeyPatch) -> MCPHermeticClient:
    """Hermetic MCP fixture for hub surface tests.

    Wires MCPHermeticClient to FastAPI TestClient with:
      - FakeHubStore (in-memory, WS-scoped)
      - FakeHubApiAdapter (hubs router)
      - FakePersistenceAdapter (content router, for save_and_link)
      - WS-aware auth via X-Workspace-ID
    """
    FakeHubStore.reset()
    FakePersistenceAdapter.reset()

    app = create_app()
    _install_ws_aware_auth(app, HUB_PERMISSIONS)

    monkeypatch.setattr(hubs_router, "ApiAdapter", FakeHubApiAdapter)
    monkeypatch.setattr(hubs_router, "HubStore", FakeHubStore)
    monkeypatch.setattr(
        hubs_router, "get_settings",
        lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"),
    )
    monkeypatch.setattr(content_router, "ApiAdapter", FakePersistenceAdapter)
    monkeypatch.setattr(
        content_router, "get_settings",
        lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"),
    )

    tc = TestClient(app, raise_server_exceptions=True)
    hc = MCPHermeticClient(tc)
    monkeypatch.setattr(mcp_tools, "_client", lambda: hc)
    return hc


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-H1: memory_lab_hub_create — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_hub_create_H1_1_callable_without_exception(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H1.1 — hub_create is callable and never raises a raw exception."""
    result = mcp_tools.memory_lab_hub_create(title="Contract Hub", workspace_id=WS_A)
    assert isinstance(result, dict)


def test_hub_create_H1_2_required_success_shape(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H1.2 — success response contains hub_id (str), title, type, status."""
    result = mcp_tools.memory_lab_hub_create(
        title="Shape Hub", hub_type="topic", workspace_id=WS_A
    )
    assert "hub_id" in result, f"'hub_id' missing: {result}"
    assert "title" in result, f"'title' missing: {result}"
    assert "type" in result, f"'type' missing: {result}"
    assert "status" in result, f"'status' missing: {result}"
    assert isinstance(result["hub_id"], str) and len(result["hub_id"]) > 0
    assert result["title"] == "Shape Hub"
    assert result["status"] == "active"


def test_hub_create_H1_3_workspace_isolation(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H1.3 — hub created in WS_A is not retrievable from WS_B."""
    res = mcp_tools.memory_lab_hub_create(title="WS_A Hub", workspace_id=WS_A)
    hub_id = res["hub_id"]

    cross = mcp_tools.memory_lab_hub_get(hub_id=hub_id, workspace_id=WS_B)
    assert cross.get("ok") is False, (
        f"WS_B must not see WS_A hub; expected structured error, got {cross}"
    )


def test_hub_create_H1_4_structured_error_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H1.4 — API failure returns {ok: False, error: {type, message, status_code}}."""
    FakeHubStore.reset()
    FakePersistenceAdapter.reset()

    app = create_app()
    _install_ws_aware_auth(app, HUB_PERMISSIONS)

    class _BrokenHubAdapter:
        def __init__(self, database_url: str) -> None:
            pass
        def create_hub(self, *_a: Any, **_kw: Any) -> None:
            raise RuntimeError("simulated hub store failure")

    monkeypatch.setattr(hubs_router, "ApiAdapter", _BrokenHubAdapter)
    monkeypatch.setattr(
        hubs_router, "get_settings",
        lambda: SimpleNamespace(database_url="postgresql://unit/hermetic"),
    )

    tc = TestClient(app, raise_server_exceptions=False)
    hc = MCPHermeticClient(tc)
    monkeypatch.setattr(mcp_tools, "_client", lambda: hc)

    result = mcp_tools.memory_lab_hub_create(title="fail", workspace_id=WS_A)
    assert isinstance(result, dict)
    assert result.get("ok") is False, f"ok must be False for 500, got {result}"
    assert "error" in result
    err = result["error"]
    assert "type" in err
    assert "message" in err
    assert err.get("status_code") == 500


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-H2: memory_lab_hub_get — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_hub_get_H2_1_callable_without_exception(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H2.1 — hub_get is callable and never raises a raw exception."""
    res = mcp_tools.memory_lab_hub_create(title="Gettable Hub", workspace_id=WS_A)
    result = mcp_tools.memory_lab_hub_get(hub_id=res["hub_id"], workspace_id=WS_A)
    assert isinstance(result, dict)


def test_hub_get_H2_2_required_success_shape(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H2.2 — success response contains hub_id matching request, plus title."""
    res = mcp_tools.memory_lab_hub_create(title="Get Shape Hub", workspace_id=WS_A)
    hub_id = res["hub_id"]
    result = mcp_tools.memory_lab_hub_get(hub_id=hub_id, workspace_id=WS_A)
    assert "hub_id" in result, f"'hub_id' missing: {result}"
    assert "title" in result, f"'title' missing: {result}"
    assert result["hub_id"] == hub_id
    assert result["title"] == "Get Shape Hub"


def test_hub_get_H2_3_structured_error_on_not_found(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H2.3 — nonexistent hub_id returns {ok: False, error: {type, message, status_code: 404}}."""
    result = mcp_tools.memory_lab_hub_get(
        hub_id=str(uuid.uuid4()), workspace_id=WS_A
    )
    assert isinstance(result, dict)
    assert result.get("ok") is False, f"Expected structured 404 error, got {result}"
    assert "error" in result
    err = result["error"]
    assert "type" in err
    assert "message" in err
    assert err.get("status_code") == 404


def test_hub_get_H2_4_workspace_isolation(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H2.4 — WS_B hub not visible from WS_A; WS_B can read its own hub."""
    res_b = mcp_tools.memory_lab_hub_create(title="WS_B Hub", workspace_id=WS_B)
    hub_id = res_b["hub_id"]

    cross = mcp_tools.memory_lab_hub_get(hub_id=hub_id, workspace_id=WS_A)
    assert cross.get("ok") is False, (
        f"WS_A must not see WS_B hub; expected structured error, got {cross}"
    )

    own = mcp_tools.memory_lab_hub_get(hub_id=hub_id, workspace_id=WS_B)
    assert "hub_id" in own, f"WS_B get of own hub failed: {own}"
    assert own["hub_id"] == hub_id


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-H3: memory_lab_hub_link_content — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_hub_link_H3_1_callable_without_exception(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H3.1 — hub_link_content is callable and never raises a raw exception."""
    hub = mcp_tools.memory_lab_hub_create(title="Link Hub", workspace_id=WS_A)
    content = mcp_tools.memory_lab_content_create_id(content="linkable", workspace_id=WS_A)
    result = mcp_tools.memory_lab_hub_link_content(
        hub_id=hub["hub_id"], content_id=content["content_id"], workspace_id=WS_A
    )
    assert isinstance(result, dict)


def test_hub_link_H3_2_required_success_shape(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H3.2 — success response contains hub_id, content_id, linked=True."""
    hub = mcp_tools.memory_lab_hub_create(title="Link Shape Hub", workspace_id=WS_A)
    content = mcp_tools.memory_lab_content_create_id(content="shaped content", workspace_id=WS_A)
    result = mcp_tools.memory_lab_hub_link_content(
        hub_id=hub["hub_id"], content_id=content["content_id"], workspace_id=WS_A
    )
    assert "hub_id" in result, f"'hub_id' missing: {result}"
    assert "content_id" in result, f"'content_id' missing: {result}"
    assert "linked" in result, f"'linked' missing: {result}"
    assert result["linked"] is True
    assert result["hub_id"] == hub["hub_id"]
    assert result["content_id"] == content["content_id"]


def test_hub_link_H3_3_structured_error_on_not_found(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H3.3 — linking to nonexistent hub returns {ok: False, error: {status_code: 404}}."""
    content = mcp_tools.memory_lab_content_create_id(content="orphan content", workspace_id=WS_A)
    result = mcp_tools.memory_lab_hub_link_content(
        hub_id=str(uuid.uuid4()),
        content_id=content["content_id"],
        workspace_id=WS_A,
    )
    assert isinstance(result, dict)
    assert result.get("ok") is False, f"Expected structured 404 error, got {result}"
    assert "error" in result
    err = result["error"]
    assert "type" in err
    assert "message" in err
    assert err.get("status_code") == 404


def test_hub_link_H3_4_link_visible_in_hub_get(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H3.4 — after linking, hub_get reflects the content_id in linked_content_ids."""
    hub = mcp_tools.memory_lab_hub_create(title="Inspect Link Hub", workspace_id=WS_A)
    content = mcp_tools.memory_lab_content_create_id(
        content="content to inspect", workspace_id=WS_A
    )
    mcp_tools.memory_lab_hub_link_content(
        hub_id=hub["hub_id"], content_id=content["content_id"], workspace_id=WS_A
    )
    refreshed = mcp_tools.memory_lab_hub_get(hub_id=hub["hub_id"], workspace_id=WS_A)
    linked_ids = refreshed.get("linked_content_ids", [])
    assert content["content_id"] in linked_ids, (
        f"content_id not in linked_content_ids after link: {linked_ids}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-H4: list_hubs — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_list_hubs_H4_1_callable_without_exception(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H4.1 — list_hubs is callable and never raises a raw exception."""
    result = mcp_tools.list_hubs(workspace_id=WS_A)
    assert isinstance(result, (dict, list))


def test_list_hubs_H4_2_returns_created_hub(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H4.2 — created hub appears in list_hubs for same workspace."""
    created = mcp_tools.memory_lab_hub_create(title="Listed Hub", workspace_id=WS_A)
    result = mcp_tools.list_hubs(workspace_id=WS_A)
    # list_hubs may return a list directly or wrap in {hubs: [...]}
    hubs = result if isinstance(result, list) else result.get("hubs", [])
    hub_ids = [h.get("hub_id") for h in hubs]
    assert created["hub_id"] in hub_ids, (
        f"created hub_id {created['hub_id']} not in list: {hub_ids}"
    )


def test_list_hubs_H4_3_workspace_isolation(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H4.3 — WS_A list does not contain WS_B hubs (and vice versa)."""
    hub_a = mcp_tools.memory_lab_hub_create(title="A Only Hub", workspace_id=WS_A)
    hub_b = mcp_tools.memory_lab_hub_create(title="B Only Hub", workspace_id=WS_B)

    list_a = mcp_tools.list_hubs(workspace_id=WS_A)
    list_b = mcp_tools.list_hubs(workspace_id=WS_B)

    ids_a = {h["hub_id"] for h in (list_a if isinstance(list_a, list) else list_a.get("hubs", []))}
    ids_b = {h["hub_id"] for h in (list_b if isinstance(list_b, list) else list_b.get("hubs", []))}

    assert hub_a["hub_id"] in ids_a, "WS_A hub missing from WS_A list"
    assert hub_b["hub_id"] not in ids_a, "WS_B hub leaked into WS_A list"
    assert hub_b["hub_id"] in ids_b, "WS_B hub missing from WS_B list"
    assert hub_a["hub_id"] not in ids_b, "WS_A hub leaked into WS_B list"


def test_list_hubs_H4_4_empty_list_for_new_workspace(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H4.4 — freshly-isolated workspace returns empty hub list without error."""
    fresh_ws = "00000000-0000-0000-0001-000000000099"
    result = mcp_tools.list_hubs(workspace_id=fresh_ws)
    hubs = result if isinstance(result, list) else result.get("hubs", [])
    assert isinstance(hubs, list), f"list_hubs must return a list, got {type(hubs)}"
    assert len(hubs) == 0, f"Expected empty list for fresh workspace, got {hubs}"


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-H5: update_hub — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_update_hub_H5_1_callable_without_exception(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H5.1 — update_hub is callable and never raises a raw exception."""
    hub = mcp_tools.memory_lab_hub_create(title="Update Target", workspace_id=WS_A)
    result = mcp_tools.update_hub(
        hub_id=hub["hub_id"], title="Updated Title", workspace_id=WS_A
    )
    assert isinstance(result, dict)


def test_update_hub_H5_2_mutation_visible_via_get(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H5.2 — title updated via update_hub is visible via hub_get."""
    hub = mcp_tools.memory_lab_hub_create(title="Before Update", workspace_id=WS_A)
    mcp_tools.update_hub(
        hub_id=hub["hub_id"], title="After Update", workspace_id=WS_A
    )
    refreshed = mcp_tools.memory_lab_hub_get(hub_id=hub["hub_id"], workspace_id=WS_A)
    assert refreshed.get("title") == "After Update", (
        f"Expected 'After Update', got {refreshed.get('title')!r}: {refreshed}"
    )


def test_update_hub_H5_3_structured_error_on_not_found(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H5.3 — update on nonexistent hub returns {ok: False, error: {status_code: 404}}."""
    result = mcp_tools.update_hub(
        hub_id=str(uuid.uuid4()), title="Ghost", workspace_id=WS_A
    )
    assert isinstance(result, dict)
    assert result.get("ok") is False, f"Expected structured 404 error, got {result}"
    assert "error" in result
    err = result["error"]
    assert err.get("status_code") == 404


def test_update_hub_H5_4_workspace_isolation(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H5.4 — WS_A cannot update a hub that belongs to WS_B."""
    hub_b = mcp_tools.memory_lab_hub_create(title="WS_B Protected Hub", workspace_id=WS_B)
    result = mcp_tools.update_hub(
        hub_id=hub_b["hub_id"], title="Hijacked", workspace_id=WS_A
    )
    assert result.get("ok") is False, (
        f"WS_A must not update WS_B hub; expected structured error, got {result}"
    )
    # Confirm original title unchanged
    original = mcp_tools.memory_lab_hub_get(hub_id=hub_b["hub_id"], workspace_id=WS_B)
    assert original.get("title") == "WS_B Protected Hub", (
        f"WS_B hub title was mutated by WS_A update: {original}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MCP-H6: save_and_link_to_hub — behavioral contract
# ═══════════════════════════════════════════════════════════════════════════════

def test_save_and_link_H6_1_callable_without_exception(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H6.1 — save_and_link_to_hub is callable and never raises a raw exception."""
    hub = mcp_tools.memory_lab_hub_create(title="Save+Link Hub", workspace_id=WS_A)
    result = mcp_tools.save_and_link_to_hub(
        content="content for save and link",
        save_purpose="contract test",
        hub_id=hub["hub_id"],
        workspace_id=WS_A,
    )
    assert isinstance(result, dict)


def test_save_and_link_H6_2_required_success_shape(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H6.2 — success response contains content_id, linked=True, hub_id."""
    hub = mcp_tools.memory_lab_hub_create(title="Shape S+L Hub", workspace_id=WS_A)
    result = mcp_tools.save_and_link_to_hub(
        content="shape test content",
        save_purpose="shape test",
        hub_id=hub["hub_id"],
        workspace_id=WS_A,
    )
    assert "content_id" in result, f"'content_id' missing: {result}"
    assert "linked" in result, f"'linked' missing: {result}"
    assert "hub_id" in result, f"'hub_id' missing: {result}"
    assert result["linked"] is True
    assert result["hub_id"] == hub["hub_id"]
    assert isinstance(result["content_id"], str) and len(result["content_id"]) > 0


def test_save_and_link_H6_3_content_appears_in_hub_get(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H6.3 — after save_and_link, hub_get reflects content_id in linked_content_ids."""
    hub = mcp_tools.memory_lab_hub_create(title="Inspect S+L Hub", workspace_id=WS_A)
    res = mcp_tools.save_and_link_to_hub(
        content="content to inspect after link",
        save_purpose="inspect test",
        hub_id=hub["hub_id"],
        workspace_id=WS_A,
    )
    refreshed = mcp_tools.memory_lab_hub_get(hub_id=hub["hub_id"], workspace_id=WS_A)
    linked_ids = refreshed.get("linked_content_ids", [])
    assert res["content_id"] in linked_ids, (
        f"content_id not in linked_content_ids after save_and_link: {linked_ids}"
    )


def test_save_and_link_H6_4_workspace_isolation(
    hermetic_client_hubs: MCPHermeticClient,
) -> None:
    """H6.4 — WS_A cannot save_and_link into a WS_B hub; result carries linked=False or structured error."""
    hub_b = mcp_tools.memory_lab_hub_create(title="WS_B Private Hub", workspace_id=WS_B)
    result = mcp_tools.save_and_link_to_hub(
        content="cross-workspace content",
        save_purpose="isolation test",
        hub_id=hub_b["hub_id"],
        workspace_id=WS_A,
    )
    assert isinstance(result, dict)
    # Either linked=False (hub not found → graceful) or ok=False (structured error)
    linked_ok = result.get("linked") is True
    assert not linked_ok, (
        f"WS_A must not successfully link into WS_B hub; got {result}"
    )
