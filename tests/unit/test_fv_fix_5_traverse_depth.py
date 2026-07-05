"""Unit tests — FV-FIX-5 reasoning traverse depth (FV-6).

1. ReasoningRequest.max_hops reaches the M12 retrieval graph expansion instead
   of being discarded by the context-pack builder (which stays at 1 for the
   public /v1/context-packs/build route).
2. Traverse projects retrieval-recorded provenance (hub_match / graph_match /
   source_path) into read-only hop-1 steps.
3. _attach_content_metadata merges content metadata with retrieval provenance
   instead of replacing it (replacement dropped hub_match for anchored content).

Pure-Python; no DB; no provider calls.
"""

import pytest

import memory_lab.context_packs.service as cp_service
import memory_lab.reasoning.service as rsn_service
from memory_lab.context_packs.builder import build_context_pack
from memory_lab.context_packs.models import ContextPackBuildRequest
from memory_lab.reasoning.models import ReasoningRequest
from memory_lab.reasoning.traverse import build_traversal_steps

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000961"
DB = "postgresql://unit/test"


def _ev(content_id, *, rank=1, metadata=None):
    return {
        "evidence_id": f"ev_{content_id}",
        "rank": rank,
        "content_id": content_id,
        "snippet": "evidence text",
        "score": 0.9,
        "score_kind": "chunk_text_match",
        "memory_type": "decision",
        "metadata": metadata,
    }


def _pack(supporting):
    return build_context_pack(
        workspace_id=WS,
        request=ContextPackBuildRequest(query="fv6", scope="fv6"),
        supporting_evidence=supporting,
        current_state_rows=[],
        conflict_candidates=[],
    )


# ---------------------------------------------------------------------------
# max_hops threading: reasoning traverse/explain → context pack → retrieval
# ---------------------------------------------------------------------------

def _capture_pack_builder(monkeypatch, captured):
    def fake_builder(*, database_url, request, workspace_id, workspace_source=None, max_hops=1, consult_hub_graph=False):
        captured["max_hops"] = max_hops
        captured["consult_hub_graph"] = consult_hub_graph
        return _pack([_ev("a")])
    monkeypatch.setattr(rsn_service, "build_context_pack_for_request", fake_builder)


def test_traverse_threads_request_max_hops(monkeypatch):
    captured = {}
    _capture_pack_builder(monkeypatch, captured)
    rsn_service.traverse_for_request(
        database_url=DB, request=ReasoningRequest(query="q", max_hops=3), workspace_id=WS,
    )
    assert captured["max_hops"] == 3
    assert captured["consult_hub_graph"] is True


def test_explain_threads_request_max_hops(monkeypatch):
    captured = {}
    _capture_pack_builder(monkeypatch, captured)
    rsn_service.explain_for_request(
        database_url=DB, request=ReasoningRequest(query="q", max_hops=1), workspace_id=WS,
    )
    assert captured["max_hops"] == 1
    assert captured["consult_hub_graph"] is True


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return []


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, *a, **k):
        return _FakeCursor()


def test_context_pack_builder_forwards_max_hops_to_retrieval(monkeypatch):
    captured = {}

    class FakeAdapter:
        def __init__(self, database_url):
            pass

        def search(self, **kwargs):
            captured.update(kwargs)
            return []

    monkeypatch.setattr(cp_service, "RetrievalAdapter", FakeAdapter)
    monkeypatch.setattr(cp_service.psycopg2, "connect", lambda dsn: _FakeConn())
    request = ContextPackBuildRequest(
        query="q", scope="s",
        include_current_state=False, include_conflicts=False, include_counterfindings=False,
    )
    cp_service.build_context_pack_for_request(
        database_url=DB, request=request, workspace_id=WS, max_hops=3,
    )
    assert captured["max_hops"] == 3
    # default stays 1 → public /v1/context-packs/build route behavior unchanged
    cp_service.build_context_pack_for_request(database_url=DB, request=request, workspace_id=WS)
    assert captured["max_hops"] == 1
    # hard cap mirrors the request model's ceiling
    cp_service.build_context_pack_for_request(database_url=DB, request=request, workspace_id=WS, max_hops=9)
    assert captured["max_hops"] == 3


# ---------------------------------------------------------------------------
# Provenance projection into traversal steps
# ---------------------------------------------------------------------------

def test_hub_provenance_projected_as_step():
    pack = _pack([_ev("a", metadata={"hub_match": "Payments Platform"})])
    steps = build_traversal_steps(pack, ReasoningRequest(query="q", max_hops=2))
    hub_steps = [s for s in steps if s.relation == "included_via_hub_link"]
    assert len(hub_steps) == 1
    assert hub_steps[0].source == "Payments Platform"
    assert hub_steps[0].target == "a"
    assert hub_steps[0].hop == 1


def test_graph_provenance_projected_as_step():
    pack = _pack([
        _ev("g1", rank=1, metadata={"graph_match": "kafka->rabbitmq"}),
        _ev("g2", rank=2, metadata={"source_path": "graph_neighbor"}),
    ])
    steps = build_traversal_steps(pack, ReasoningRequest(query="q", max_hops=2))
    graph_steps = [s for s in steps if s.relation == "included_via_graph_expansion"]
    assert {s.target for s in graph_steps} == {"g1", "g2"}


def test_no_provenance_means_no_extra_steps():
    pack = _pack([_ev("plain")])
    steps = build_traversal_steps(pack, ReasoningRequest(query="q", max_hops=3))
    relations = {s.relation for s in steps}
    assert "included_via_hub_link" not in relations
    assert "included_via_graph_expansion" not in relations


def test_provenance_steps_are_deterministic_and_capped():
    pack = _pack([_ev("a", metadata={"hub_match": "H", "graph_match": "G"})])
    req = ReasoningRequest(query="q", max_hops=3)
    first = [s.model_dump() for s in build_traversal_steps(pack, req)]
    second = [s.model_dump() for s in build_traversal_steps(pack, req)]
    assert first == second
    assert max(s["hop"] for s in first) <= 3
    step_ids = [s["step_id"] for s in first]
    assert step_ids == sorted(step_ids)


# ---------------------------------------------------------------------------
# HubTermGraph — curated hub graph as term adjacency for the existing BFS
# ---------------------------------------------------------------------------

def _hub_graph(monkeypatch, hubs, edges, inner=None):
    from memory_lab.graph.hub_term_graph import HubTermGraph

    graph = HubTermGraph(DB, inner=inner)
    graph._hub_terms = hubs
    graph._edges = edges
    graph._loaded_for = WS
    monkeypatch.setattr(graph, "_load", lambda workspace_id: None)
    return graph


HUBS = {
    "h-pay": {"checkout payments domain", "checkout payments"},
    "h-cache": {"session caching layer", "session cache"},
    "h-backend": {"cache backend selection", "cache backend"},
}
EDGES = [("h-pay", "h-cache", 1.0), ("h-cache", "h-backend", 1.0)]


def test_hub_term_graph_single_word_token_match(monkeypatch):
    graph = _hub_graph(monkeypatch, HUBS, EDGES)
    neighbors = graph.get_neighbors("payments", workspace_id=WS)
    assert neighbors == {"session caching layer", "session cache"}


def test_hub_term_graph_exact_alias_match_walks_one_edge_only(monkeypatch):
    graph = _hub_graph(monkeypatch, HUBS, EDGES)
    # BFS owns the hop loop — a single get_neighbors call is one adjacency step.
    neighbors = graph.get_neighbors("session cache", workspace_id=WS)
    assert "cache backend" in neighbors
    assert "checkout payments" in neighbors
    assert "checkout payments domain" in neighbors


def test_hub_term_graph_two_hops_via_bfs(monkeypatch):
    from memory_lab.graph.expansion import expand_query

    graph = _hub_graph(monkeypatch, HUBS, EDGES)
    one_hop = set(expand_query(["payments"], graph, max_hops=1, workspace_id=WS))
    two_hops = set(expand_query(["payments"], graph, max_hops=2, workspace_id=WS))
    assert "cache backend" not in one_hop, "2-hop hub must be unreachable at max_hops=1"
    assert "cache backend" in two_hops, "2-hop hub must be reachable at max_hops=2"


def test_hub_term_graph_confidence_filter(monkeypatch):
    graph = _hub_graph(monkeypatch, HUBS, [("h-pay", "h-cache", 0.4)])
    assert graph.get_neighbors("payments", min_confidence=0.7, workspace_id=WS) == set()


def test_hub_term_graph_requires_workspace_and_never_raises(monkeypatch):
    from memory_lab.graph.hub_term_graph import HubTermGraph

    graph = HubTermGraph(DB)  # real _load would hit DB → exception is swallowed
    assert graph.get_neighbors("payments", workspace_id=None) == set()
    assert graph.get_neighbors("payments", workspace_id=WS) == set()


def test_hub_term_graph_unions_inner_term_graph(monkeypatch):
    class InnerStore:
        def get_neighbors(self, node, min_confidence=0.7, workspace_id=None):
            return {"legacy-term"}

    graph = _hub_graph(monkeypatch, HUBS, EDGES, inner=InnerStore())
    neighbors = graph.get_neighbors("payments", workspace_id=WS)
    assert "legacy-term" in neighbors
    assert "session cache" in neighbors


# ---------------------------------------------------------------------------
# consult_hub_graph opt-in isolation — default retrieval byte-identical
# ---------------------------------------------------------------------------

def test_retrieval_adapter_defaults_to_plain_term_graph(monkeypatch):
    from memory_lab.api.services.retrieval_adapter import RetrievalAdapter

    adapter = RetrievalAdapter(DB, pgvector_retrieval_enabled=False)
    called = {}

    class FakeSearch:
        def __init__(self, name):
            self.name = name

        def search(self, **kwargs):
            called["adapter"] = self.name
            return []

    monkeypatch.setattr(adapter, "adapter", FakeSearch("plain"))
    monkeypatch.setattr(adapter, "hub_term_adapter", FakeSearch("hub"))
    monkeypatch.setattr(adapter, "_query_embedding", lambda q: (None, None))
    monkeypatch.setattr(adapter, "_hub_linked_results", lambda *a, **k: [])

    adapter.search(query="q", workspace_id=WS)
    assert called["adapter"] == "plain"
    adapter.search(query="q", workspace_id=WS, consult_hub_graph=True)
    assert called["adapter"] == "hub"


# ---------------------------------------------------------------------------
# Metadata merge fix
# ---------------------------------------------------------------------------

def test_attach_content_metadata_merges_provenance_with_anchor_meta():
    evidence = [_ev("a", metadata={"hub_match": "H", "source_path": "hub_linked"})]
    content_meta = {"a": {
        "content_id": "a", "memory_type": "decision",
        "anchor_scope": "s1", "state_status": "active",
    }}
    rows = cp_service._attach_content_metadata(evidence, content_meta)
    md = rows[0]["metadata"]
    assert md["hub_match"] == "H", "retrieval provenance must survive anchored-content merge"
    assert md["anchor_scope"] == "s1"
