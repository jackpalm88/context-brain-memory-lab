#!/usr/bin/env python3
"""
install_smoke_app.py — INSTALL-1 Hermetic Application Smoke.

Validates the full OpenCB application stack (imports → API routes → MCP tool
registry → core operations) without a live database, live uvicorn server, or
provider keys. Uses FastAPI TestClient with the hermetic fake-adapter pattern
proven across MCP-1..6 and Memory Acceptance tests.

Smoke checks:
  SM-1  Module imports (all memory_lab subpackages + mcp + api)
  SM-2  App factory creates without error; routes registered
  SM-3  /health endpoint responds 200 {"status": "ok"}
  SM-4  Content create → persisted=True, governance envelope present
  SM-5  Content get → content_id echoed, workspace-scoped
  SM-6  query_memory → answer + six signals
  SM-7  retrieval_search → list, deterministic, no DB required
  SM-8  MCP tool registry → APPROVED_TOOLS has 32 entries, all callable
  SM-9  Cross-workspace isolation (WS_A content invisible from WS_B)
  SM-10 Governance tier routing: discard→no persist, persistent→persist
  SM-11 save_and_link_to_hub → linked=True, hub_id present

Exits 0 on all-pass, 1 on any failure. Prints PASS / FAIL per check.
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from typing import Any, Dict, Optional

# ── PYTHONPATH sanity ──────────────────────────────────────────────────────────
try:
    from memory_lab.api.main import create_app
    import memory_lab.mcp.tools as mcp_tools
    from memory_lab.mcp.client import MemoryLabApiClient
    from memory_lab.api.auth_context import AuthContext
    from memory_lab.api.workspace_context import WorkspaceContext
    from memory_lab.api.dependencies.auth import require_permission
    from memory_lab.reasoning.models import AskRequest, AskResponse
    import memory_lab.api.routers.ask as ask_router
    import memory_lab.api.routers.content as content_router
    import memory_lab.api.routers.hubs as hubs_router
    import memory_lab.api.routers.retrieval as retrieval_router
    from memory_lab.governance.tier_router import route as tier_route
except ImportError as exc:
    print(f"ABORT: import failed — {exc}")
    print("       Set PYTHONPATH to the repo root: PYTHONPATH=/opt/cbml python3 ...")
    sys.exit(2)

from fastapi import Request
from fastapi.testclient import TestClient

# ── constants ──────────────────────────────────────────────────────────────────
WS_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
WS_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SUBJECT = "00000000-0000-0000-0000-000000000001"
PERMS = [
    "content.create", "content.read", "content.update",
    "hubs.create", "hubs.read", "hubs.link",
    "retrieval.search",
]
EXPECTED_TOOL_COUNT = 32

# ── results accumulator ────────────────────────────────────────────────────────
_checks: list[tuple[str, bool, str]] = []


def check(label: str, passed: bool, detail: str = "") -> bool:
    _checks.append((label, passed, detail))
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {label}" + (f"\n       detail: {detail}" if not passed else ""))
    return passed


# ── fake adapters ──────────────────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


class _FakeMemory:
    _store: Dict[str, Dict[str, Any]] = {}
    _idx: Dict[str, Dict[str, str]] = {}
    _chunks: Dict[str, str] = {}

    @classmethod
    def reset(cls) -> None:
        cls._store = {}; cls._idx = {}; cls._chunks = {}

    def __init__(self, _db: str) -> None:
        pass

    def create_content_minimal(self, content=None, workspace_id=None,
                                workspace_source="header", created_by_subject=SUBJECT):
        ws, text, h = workspace_id or "", content or "", _hash(content or "")
        existing = self.__class__._idx.get(ws, {}).get(h)
        if existing:
            return {"content_id": existing, "workspace_id": ws, "created": False,
                    "persisted": True, "discarded": False, "duplicate": True,
                    "scores": {}, "tier": "duplicate", "tier_reason": "duplicate"}
        n = len(text.strip())
        if n == 0:     q, r, nov, comp = 0.05, 0.1, 0.1, 0.06
        elif n < 20:   q, r, nov, comp = 0.15, 0.2, 0.2, 0.16
        elif n < 80:   q, r, nov, comp = 0.4, 0.45, 0.4, 0.41
        elif n < 200:  q, r, nov, comp = 0.6, 0.65, 0.55, 0.60
        else:          q, r, nov, comp = 0.82, 0.90, 0.75, 0.83
        td = tier_route(composite_score=comp, circuit_open=False, quality_score=q)
        row: Dict[str, Any] = {
            "workspace_id": ws, "created": False,
            "persisted": td.should_persist, "discarded": not td.should_persist,
            "duplicate": False, "mode": "governed",
            "scores": {"quality": q, "relevance": r, "novelty": nov, "composite": comp},
            "tier": td.tier, "tier_reason": td.reason,
        }
        if not td.should_persist:
            return row
        cid = str(uuid.uuid4())
        row["content_id"] = cid; row["created"] = True
        self.__class__._store[f"{ws}:{cid}"] = dict(row)
        self.__class__._idx.setdefault(ws, {})[h] = cid
        self.__class__._chunks[f"{ws}:{cid}"] = text
        return row

    def get_content_minimal(self, content_id, workspace_id=None):
        return self.__class__._store.get(f"{workspace_id or ''}:{content_id}")

    def set_quick_summary(self, content_id, quick_summary, workspace_id=None):
        row = self.__class__._store.get(f"{workspace_id or ''}:{content_id}")
        if row is None:
            return None
        row["quick_summary"] = quick_summary
        return {"content_id": content_id, "quick_summary": quick_summary, "updated": True}

    def get_content_metadata(self, content_id, workspace_id=None):
        row = self.__class__._store.get(f"{workspace_id or ''}:{content_id}")
        if row is None:
            return None
        return {"content_id": content_id, "workspace_id": workspace_id,
                "node_type": row.get("node_type"), "domain": "general",
                "word_count": len(self.__class__._chunks.get(
                    f"{workspace_id or ''}:{content_id}", "").split()),
                "created_at": "2024-01-01T00:00:00+00:00"}

    def set_node_type(self, content_id, node_type, workspace_id=None):
        row = self.__class__._store.get(f"{workspace_id or ''}:{content_id}")
        if row is None:
            return None
        row["node_type"] = node_type
        return {"content_id": content_id, "node_type": node_type, "updated": True}


class _FakeHubStore:
    _hubs: Dict[str, Dict] = {}
    _links: Dict[str, list] = {}

    @classmethod
    def reset(cls) -> None:
        cls._hubs = {}; cls._links = {}

    def __init__(self, _db: str) -> None:
        pass

    def create_hub(self, title, hub_type="topic", workspace_id=None,
                   aliases=None, related_terms=None, description=None,
                   created_by_subject=None, **_):
        hid = str(uuid.uuid4())
        row = {"hub_id": hid, "title": title, "hub_type": hub_type,
               "workspace_id": workspace_id, "status": "active",
               "aliases": aliases or [], "related_terms": related_terms or []}
        self.__class__._hubs[f"{workspace_id}:{hid}"] = row
        return row

    def get_hub(self, hub_id, workspace_id=None):
        return self.__class__._hubs.get(f"{workspace_id}:{hub_id}")

    def link_content(self, hub_id, content_id, workspace_id=None,
                     created_by_subject=None):
        key = f"{workspace_id}:{hub_id}"
        self.__class__._links.setdefault(key, []).append(content_id)
        return {"hub_id": hub_id, "content_id": content_id, "linked": True}

    def list_hubs(self, workspace_id=None, status="active"):
        ws = workspace_id or ""
        return [v for k, v in self.__class__._hubs.items()
                if k.startswith(f"{ws}:") and v.get("status") == status]

    def match_query(self, *_, **__):
        return []

    def update_hub(self, hub_id, workspace_id=None, **kwargs):
        key = f"{workspace_id}:{hub_id}"
        if key not in self.__class__._hubs:
            return None
        self.__class__._hubs[key].update(kwargs)
        return self.__class__._hubs[key]


class _FakeHubApiAdapter(_FakeMemory):
    """Thin adapter bridging hubs router to _FakeHubStore + _FakeMemory."""

    def create_hub(self, payload: Dict[str, Any],
                   workspace_id: Optional[str] = None,
                   workspace_source: Optional[str] = None,
                   created_by_subject: Optional[str] = None) -> Dict[str, Any]:
        hid = str(uuid.uuid4())
        row = {"hub_id": hid,
               "title": payload.get("title", ""),
               "hub_type": payload.get("hub_type", "topic"),
               "status": "active", "workspace_id": workspace_id,
               "aliases": payload.get("aliases") or [],
               "related_terms": payload.get("related_terms") or []}
        _FakeHubStore._hubs[f"{workspace_id}:{hid}"] = row
        return row

    def get_hub(self, hub_id: str, workspace_id: Optional[str] = None):
        return _FakeHubStore._hubs.get(f"{workspace_id}:{hub_id}")

    def link_content(self, hub_id, content_id, workspace_id=None, created_by_subject=None):
        _FakeHubStore._links.setdefault(f"{workspace_id}:{hub_id}", []).append(content_id)
        return {"hub_id": hub_id, "content_id": content_id, "linked": True,
                "workspace_id": workspace_id}


class _FakeRetrievalAdapter:
    def __init__(self, _db: str) -> None:
        pass

    def search(self, query, workspace_id=None, **_):
        if not (query or "").strip():
            return []
        ws = workspace_id or ""
        return [
            {"content_id": str(uuid.uuid5(uuid.UUID("0" * 32), f"{ws}:{query}")),
             "chunk_text": f"smoke:ws={ws}:q={query[:30]}",
             "final_score": 0.80, "retrieval_path": "smoke_deterministic",
             "retrieval_mode": "deterministic_fallback",
             "hub_match": None, "graph_match": None,
             "knowledge_path": None, "retrieval_reason": "smoke",
             "ranking_reason": None, "score_components": {}, "workspace_id": ws}
        ]


class _FakeQueryService:
    def __init__(self, _db: str, **_: Any) -> None:
        pass

    @classmethod
    def from_database_url(cls, database_url: str, **kw: Any) -> "_FakeQueryService":
        return cls(database_url)

    def execute(self, request: AskRequest, workspace_id: str) -> AskResponse:
        q = request.normalized_query()
        if "__no_context__" in q:
            return AskResponse(answer="No context.", intent="lookup", confidence=0.0,
                               confidence_explanation="smoke", citations=[],
                               status="insufficient_evidence",
                               mode="deterministic", workspace_id=workspace_id)
        return AskResponse(answer=f"smoke:ws={workspace_id}:q={q[:40]}",
                           intent="lookup", confidence=0.85,
                           confidence_explanation="smoke",
                           citations=[], status="ok",
                           mode="deterministic", workspace_id=workspace_id)


# ── hermetic wiring ────────────────────────────────────────────────────────────

class _SmokeClient(MemoryLabApiClient):
    def __init__(self, tc: TestClient) -> None:
        super().__init__(base_url="http://testserver")
        self._tc = tc

    def _request(self, method, path, *, params=None, json_body=None,
                 workspace_id=None, timeout=None, **_):
        headers = {"X-Workspace-ID": workspace_id or WS_A}
        resp = self._tc.request(
            method=method,
            url=path,
            params=params,
            json=json_body,
            headers=headers,
        )
        if resp.status_code < 200 or resp.status_code >= 300:
            from memory_lab.mcp.client import MemoryLabApiError
            raise MemoryLabApiError(
                f"Non-2xx from {method} {path}: {resp.status_code}",
                method=method, url=path,
                status_code=resp.status_code, body=resp.text,
            )
        return resp.json()


def _install_auth(app: Any, permissions: list[str]) -> None:
    """Mirror of _install_ws_aware_auth from MCP-1 tests."""

    def _make_override() -> Any:
        async def override(request: Request) -> AuthContext:
            ws = request.headers.get("X-Workspace-ID", WS_A)
            return AuthContext(
                auth_subject_id=SUBJECT,
                subject_type="agent",
                workspace_id=ws,
                role="admin",
                auth_method="smoke_bypass",
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
                if (getattr(call, "__name__", "") == "_dependency"
                        and getattr(call, "__closure__", None)):
                    closure_values = [cell.cell_contents for cell in call.__closure__]
                    if permission in closure_values:
                        app.dependency_overrides[call] = override_fn
        app.dependency_overrides[require_permission(permission)] = override_fn


def _build_client() -> _SmokeClient:
    _FakeMemory.reset()
    _FakeHubStore.reset()

    app = create_app()
    _install_auth(app, PERMS)

    settings_stub = lambda: type("S", (), {  # noqa: E731
        "database_url": "postgresql://smoke/hermetic",
        "ask_provider_synthesis_enabled": False,
    })()

    content_router.ApiAdapter = _FakeMemory          # type: ignore[attr-defined]
    content_router.get_settings = settings_stub       # type: ignore[attr-defined]
    hubs_router.HubStore = _FakeHubStore              # type: ignore[attr-defined]
    hubs_router.ApiAdapter = _FakeHubApiAdapter       # type: ignore[attr-defined]
    hubs_router.get_settings = settings_stub          # type: ignore[attr-defined]
    retrieval_router.RetrievalAdapter = _FakeRetrievalAdapter  # type: ignore[attr-defined]
    retrieval_router.get_settings = settings_stub     # type: ignore[attr-defined]
    ask_router.QueryService = _FakeQueryService       # type: ignore[attr-defined]
    ask_router.get_settings = settings_stub           # type: ignore[attr-defined]

    tc = TestClient(app, raise_server_exceptions=True)
    client = _SmokeClient(tc)
    mcp_tools._client = lambda: client               # type: ignore[attr-defined]
    return client


# ── smoke checks ───────────────────────────────────────────────────────────────

def run_smoke() -> bool:
    print("\n─── OpenCB Hermetic App Smoke (INSTALL-1) ───────────────────────────")
    all_ok = True

    # SM-1: imports
    try:
        import memory_lab.graph, memory_lab.api, memory_lab.mcp, memory_lab.bootstrap
        import memory_lab.decisions, memory_lab.governance, memory_lab.ingestion
        check("SM-1  Module imports (all subpackages)", True)
    except Exception as exc:
        check("SM-1  Module imports", False, str(exc))
        return False

    # SM-2: app factory + routes
    try:
        app = create_app()
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]
        has_health = any("/health" in r for r in routes)
        has_content = any("/v1/content" in r for r in routes)
        has_ask = any("/v1/ask" in r for r in routes)
        ok = has_health and has_content and has_ask
        check("SM-2  App factory + routes registered", ok,
              "" if ok else f"missing routes; found={routes}")
        if not ok:
            all_ok = False
    except Exception as exc:
        check("SM-2  App factory", False, str(exc))
        all_ok = False

    # Build hermetic client
    try:
        _build_client()
    except Exception as exc:
        check("SM-3..SM-11  (hermetic client build failed)", False, str(exc))
        return False

    # SM-3: health
    r = mcp_tools.memory_lab_health()
    ok = r.get("status") == "ok"
    check("SM-3  /health → {status: ok}", ok, "" if ok else str(r))
    if not ok:
        all_ok = False

    # SM-4: content create
    r = mcp_tools.memory_lab_content_create_id(content="A" * 250, workspace_id=WS_A)
    ok = (r.get("persisted") is True and "content_id" in r
          and "scores" in r and "tier" in r)
    check("SM-4  Content create → persisted + governance envelope", ok,
          "" if ok else str(r))
    if not ok:
        all_ok = False
    smoke_cid = r.get("content_id", "")

    # SM-5: content get
    if smoke_cid:
        r = mcp_tools.memory_lab_content_get(content_id=smoke_cid, workspace_id=WS_A)
        ok = r.get("content_id") == smoke_cid
        check("SM-5  Content get → content_id echoed", ok, "" if ok else str(r))
        if not ok:
            all_ok = False
    else:
        check("SM-5  Content get", False, "no content_id from SM-4")
        all_ok = False

    # SM-6: query_memory
    r = mcp_tools.query_memory(query="smoke test", workspace_id=WS_A)
    signals = {"answer", "confidence", "citations", "has_citations", "no_context", "fallback"}
    ok = signals.issubset(r.keys())
    check("SM-6  query_memory → six signals", ok,
          "" if ok else f"missing={signals - r.keys()}")
    if not ok:
        all_ok = False

    # SM-7: retrieval_search
    r = mcp_tools.memory_lab_retrieval_search(query="smoke", workspace_id=WS_A)
    results = r.get("results") if isinstance(r, dict) else r
    ok = isinstance(results, list)
    check("SM-7  retrieval_search → list (deterministic)", ok, "" if ok else str(r))
    if not ok:
        all_ok = False

    # SM-8: MCP tool registry
    from memory_lab.mcp.tools import APPROVED_TOOLS
    count = len(APPROVED_TOOLS)
    all_callable = all(callable(fn) for fn in APPROVED_TOOLS.values())
    ok = (count == EXPECTED_TOOL_COUNT) and all_callable
    check(f"SM-8  MCP APPROVED_TOOLS = {count}/{EXPECTED_TOOL_COUNT}, all callable",
          ok, "" if ok else f"count={count} all_callable={all_callable}")
    if not ok:
        all_ok = False

    # SM-9: cross-WS isolation
    r_a = mcp_tools.memory_lab_content_create_id(content="B" * 250, workspace_id=WS_A)
    cid_a = r_a.get("content_id", "")
    if cid_a:
        r_b = mcp_tools.memory_lab_content_get(content_id=cid_a, workspace_id=WS_B)
        ok = r_b.get("ok") is False
        check("SM-9  Cross-WS isolation (WS_A content not in WS_B)", ok,
              "" if ok else str(r_b))
        if not ok:
            all_ok = False
    else:
        check("SM-9  Cross-WS isolation", False, "no content_id")
        all_ok = False

    # SM-10: governance tier routing
    r_discard = mcp_tools.memory_lab_content_create_id(content="x", workspace_id=WS_A)
    r_persist = mcp_tools.memory_lab_content_create_id(content="C" * 250, workspace_id=WS_A)
    ok = (r_discard.get("discarded") is True
          and r_discard.get("persisted") is not True
          and r_persist.get("persisted") is True)
    check("SM-10 Governance: discard→no persist, long content→persist", ok,
          "" if ok else f"discard={r_discard} persist={r_persist}")
    if not ok:
        all_ok = False

    # SM-11: save_and_link_to_hub
    hub = mcp_tools.memory_lab_hub_create(title="Smoke Hub", hub_type="topic",
                                          workspace_id=WS_A)
    hub_id = hub.get("hub_id", "")
    if hub_id:
        r = mcp_tools.save_and_link_to_hub(
            content="D" * 250, save_purpose="smoke",
            hub_id=hub_id, workspace_id=WS_A
        )
        ok = r.get("linked") is True and r.get("hub_id") == hub_id
        check("SM-11 save_and_link_to_hub → linked=True + hub_id", ok,
              "" if ok else str(r))
        if not ok:
            all_ok = False
    else:
        check("SM-11 save_and_link_to_hub", False, f"hub creation failed: {hub}")
        all_ok = False

    # ── verdict ────────────────────────────────────────────────────────────────
    total = len(_checks)
    passed = sum(1 for _, ok, _ in _checks if ok)
    failed = total - passed
    print(f"\n─── VERDICT: {'PASS' if all_ok else 'FAIL'} ({passed}/{total}) ───────────────────────────")
    if failed:
        print(f"    {failed} check(s) failed — see FAIL lines above")
    return all_ok


if __name__ == "__main__":
    success = run_smoke()
    sys.exit(0 if success else 1)
