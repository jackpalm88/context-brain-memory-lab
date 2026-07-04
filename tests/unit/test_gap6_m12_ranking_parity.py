"""Gap-6 — M12-4 ranking parity closure (curation boosts + ranking surface).

Behavioral contracts:
  G6-1  source_path classification: semantic / hub_linked / mixed / graph_neighbor
  G6-2  curation boosts use production constants and gating:
        graph_neighbor without hub +0.04; hub_linked +0.15; mixed unboosted;
        capped at 1.0; not caller-configurable
  G6-3  per-result ranking surface: confidence == final_score(3dp),
        7-field score_components, result_trust after boost, ranking_reason
        parity strings
  G6-4  build_ranking_signals envelope from ranked rows
  G6-5  boosts participate in ordering (sort by boosted final_score)
  G6-6  evidence normalizer + retrieval envelope carry the surface additively

All tests are hermetic — no DB, no providers.
"""
from __future__ import annotations

import pytest

from memory_lab.ingestion.chunk_scorer_v2 import compute_chunk_score, score_to_trust_level
from memory_lab.retrieval.composite_ranker import (
    CURATED_GRAPH_BOOST,
    MANUAL_LINK_BOOST,
    SCORING_MODEL,
    build_ranking_signals,
    rank_by_composite,
    source_path_for_row,
)
from memory_lab.query.evidence import normalize_evidence

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-0000000000a1"


def _row(**overrides):
    base = {
        "content_id": "c-semantic",
        "chunk_id": "ch1",
        "workspace_id": WS,
        "text": "retrieval ranking notes",
        "score": 0.8,
        "distance": 0.4,
        "retrieval_path": "pgvector_knn",
    }
    base.update(overrides)
    return base


def _hub_row(**overrides):
    row = _row(
        content_id="c-hub",
        chunk_id="ch-hub",
        retrieval_path="hub_link_workspace_scoped",
        hub_match="Ranking Hub",
        distance=None,
        score=0.95,
    )
    row.setdefault("hub_aliases", [])
    row.setdefault("hub_related_terms", [])
    row.update(overrides)
    return row


def _rescue_row(**overrides):
    return _row(
        content_id="c-rescue",
        chunk_id="ch-rescue",
        retrieval_path="graph_rescue_nonzero_workspace_scoped",
        graph_rescue=True,
        graph_match=["ranking"],
        source_queries=["q ranking"],
        **overrides,
    )


# ---------------------------------------------------------------------------
# G6-1 — source_path
# ---------------------------------------------------------------------------

class TestSourcePath:
    def test_semantic(self):
        assert source_path_for_row(_row()) == "semantic"

    def test_hub_linked(self):
        assert source_path_for_row(_hub_row()) == "hub_linked"

    def test_mixed_hub_match_on_non_hub_path(self):
        assert source_path_for_row(_row(hub_match="Hub")) == "mixed"

    def test_graph_neighbor(self):
        assert source_path_for_row(_rescue_row()) == "graph_neighbor"


# ---------------------------------------------------------------------------
# G6-2 / G6-3 — boosts + surface
# ---------------------------------------------------------------------------

class TestBoostsAndSurface:
    def test_g6_2_production_constants(self):
        assert CURATED_GRAPH_BOOST == 0.04
        assert MANUAL_LINK_BOOST == 0.15
        assert SCORING_MODEL == "v2_weighted_components"

    def test_g6_2_hub_linked_gets_manual_link_boost(self):
        ranked = rank_by_composite([_hub_row()], "ranking")
        row = ranked[0]
        unboosted = row["score_components"]["final_score"] - 0  # boosted already applied
        # compute expected unboosted score directly from the formula
        sc = compute_chunk_score(
            distance=2.0, graph_match=[], hub_match=["Ranking Hub"],
            hub_aliases=[], hub_related_terms=[],
            query_tokens={"ranking"}, chunk_text=row["text"], source_query_count=1,
        )
        assert row["final_score"] == round(min(1.0, sc.final_score + MANUAL_LINK_BOOST), 4)
        assert row["source_path"] == "hub_linked"
        assert "manually linked to hub 'Ranking Hub'" in row["ranking_reason"]
        assert f"boost=+{MANUAL_LINK_BOOST}" in row["ranking_reason"]

    def test_g6_2_graph_neighbor_gets_curated_boost_and_prefix(self):
        ranked = rank_by_composite([_rescue_row()], "ranking")
        row = ranked[0]
        sc = compute_chunk_score(
            distance=0.4, graph_match=["ranking"], hub_match=[],
            hub_aliases=[], hub_related_terms=[],
            query_tokens={"ranking"}, chunk_text=row["text"], source_query_count=1,
        )
        assert row["final_score"] == round(min(1.0, sc.final_score + CURATED_GRAPH_BOOST), 4)
        assert row["ranking_reason"].startswith(f"curated graph neighbor (+{CURATED_GRAPH_BOOST:.2f}); ")

    def test_g6_2_mixed_rows_are_not_boosted(self):
        mixed = _row(hub_match="Hub", hub_aliases=[], hub_related_terms=[])
        ranked = rank_by_composite([mixed], "ranking")
        row = ranked[0]
        sc = compute_chunk_score(
            distance=0.4, graph_match=[], hub_match=["Hub"],
            hub_aliases=[], hub_related_terms=[],
            query_tokens={"ranking"}, chunk_text=row["text"], source_query_count=1,
        )
        assert row["final_score"] == round(sc.final_score, 4)
        assert row["source_path"] == "mixed"

    def test_g6_2_semantic_rows_are_not_boosted(self):
        ranked = rank_by_composite([_row()], "ranking")
        row = ranked[0]
        sc = compute_chunk_score(
            distance=0.4, graph_match=[], hub_match=[],
            hub_aliases=[], hub_related_terms=[],
            query_tokens={"ranking"}, chunk_text=row["text"], source_query_count=1,
        )
        assert row["final_score"] == round(sc.final_score, 4)

    def test_g6_2_boost_capped_at_one(self):
        row = _hub_row(text="ranking hub notes", hub_aliases=["ranking", "hub"], distance=0.0)
        row["distance"] = 0.0  # perfect vector signal
        ranked = rank_by_composite([row], "ranking hub notes")
        assert ranked[0]["final_score"] <= 1.0

    def test_g6_3_surface_fields_present_and_consistent(self):
        ranked = rank_by_composite([_row(), _hub_row(), _rescue_row()], "ranking")
        for row in ranked:
            assert set(row["score_components"]) == {
                "vector_score", "graph_score", "hub_score", "keyword_score",
                "trust_score", "penalty", "final_score",
            }
            assert row["confidence"] == round(row["final_score"], 3)
            assert row["score"] == row["final_score"]
            assert row["result_trust"] in {"high", "medium", "low"}
            assert row["source_path"] in {"semantic", "hub_linked", "mixed", "graph_neighbor"}
            assert row["ranking_reason"]

    def test_g6_3_trust_is_computed_after_boost(self):
        # hub_linked row whose unboosted score sits just below a trust boundary
        ranked = rank_by_composite([_hub_row()], "zzz")
        row = ranked[0]
        boosted = row["final_score"]
        expected_trust = "high" if boosted >= 0.70 else ("medium" if boosted >= 0.45 else "low")
        assert row["result_trust"] == expected_trust


# ---------------------------------------------------------------------------
# G6-4 — ranking signals envelope
# ---------------------------------------------------------------------------

class TestRankingSignals:
    def test_g6_4_full_envelope(self):
        ranked = rank_by_composite([_row(), _hub_row(), _rescue_row()], "ranking")
        signals = build_ranking_signals(ranked)
        assert signals["used_scoring_v2"] is True
        assert signals["scoring_model"] == "v2_weighted_components"
        assert signals["hub_linked_in_results"] == 1
        assert signals["used_hub_recall"] is True
        assert signals["hub_recall_results_returned"] == 1
        assert signals["manual_link_boost"] == MANUAL_LINK_BOOST
        assert signals["used_curated_graph"] is True
        assert signals["curated_graph_boost"] == CURATED_GRAPH_BOOST
        assert signals["curated_neighbors_count"] == 1
        assert signals["used_graph_boost"] is True

    def test_g6_4_semantic_only_envelope_is_quiet(self):
        signals = build_ranking_signals(rank_by_composite([_row()], "ranking"))
        assert signals["hub_linked_in_results"] == 0
        assert signals["used_hub_recall"] is False
        assert signals["manual_link_boost"] == 0.0
        assert signals["curated_graph_boost"] == 0.0
        assert signals["used_curated_graph"] is False


# ---------------------------------------------------------------------------
# G6-5 — boosts participate in ordering
# ---------------------------------------------------------------------------

class TestOrdering:
    def test_g6_5_manual_link_boost_lifts_hub_row_over_close_semantic(self):
        # semantic row with decent distance vs hub row with no semantic signal:
        # without the boost the semantic row wins comfortably; the +0.15 narrows
        # or flips it. Construct a pair where the boost decides the order.
        semantic = _row(distance=1.2, text="loose match")           # weak vector
        hub = _hub_row(text="ranking evidence hub")                 # hub base 0.30
        order_with = [r["content_id"] for r in rank_by_composite([semantic, hub], "ranking")]
        assert order_with[0] == "c-hub"

        # sanity: strip the hub path (make it 'mixed') and the boost disappears
        unboosted_hub = dict(hub, retrieval_path="pgvector_knn", distance=2.0)
        ranked = rank_by_composite([semantic, unboosted_hub], "ranking")
        hub_row = next(r for r in ranked if r["content_id"] == "c-hub")
        boosted_hub_row = next(
            r for r in rank_by_composite([semantic, hub], "ranking") if r["content_id"] == "c-hub"
        )
        assert boosted_hub_row["final_score"] > hub_row["final_score"]


# ---------------------------------------------------------------------------
# G6-6 — evidence + envelope carry the surface
# ---------------------------------------------------------------------------

class TestEnvelopeIntegration:
    def test_g6_6_normalize_evidence_carries_ranking_surface(self):
        ranked = rank_by_composite([_hub_row()], "ranking")
        items = normalize_evidence(ranked)
        assert len(items) == 1
        item = items[0]
        assert item.confidence == ranked[0]["confidence"]
        assert item.result_trust == ranked[0]["result_trust"]
        assert item.source_path == "hub_linked"
        assert item.score_components["final_score"] == ranked[0]["final_score"]
        assert "manually linked to hub" in item.ranking_reason
        assert item.metadata["result_trust"] == item.result_trust
        assert item.metadata["source_path"] == "hub_linked"

    def test_g6_6_retrieval_response_includes_ranking_signals(self, monkeypatch):
        from types import SimpleNamespace
        from fastapi.testclient import TestClient
        from memory_lab.api.auth_context import AuthContext
        from memory_lab.api.dependencies.auth import require_permission
        from memory_lab.api.main import create_app
        import memory_lab.api.routers.retrieval as retrieval_router

        ranked = rank_by_composite([_hub_row(), _row()], "ranking")
        signals = build_ranking_signals(ranked)

        class FakeAdapter:
            def __init__(self, database_url):
                self.last_ranking_signals = signals
                self.last_debug_metadata = {}

            def search(self, **kwargs):
                return ranked

        app = create_app()

        def override():
            return AuthContext(
                auth_subject_id="00000000-0000-0000-0000-0000000000c3",
                subject_type="user", workspace_id=WS, role="owner", auth_method="test",
            )

        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if not dependant:
                continue
            for dep in getattr(dependant, "dependencies", []):
                call = getattr(dep, "call", None)
                if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                    if "retrieval.search" in [c.cell_contents for c in call.__closure__]:
                        app.dependency_overrides[call] = override

        monkeypatch.setattr(retrieval_router, "RetrievalAdapter", FakeAdapter)
        monkeypatch.setattr(retrieval_router, "get_settings", lambda: SimpleNamespace(database_url="postgresql://unit/test"))

        client = TestClient(app)
        resp = client.post("/v1/retrieval/search", json={"query": "ranking"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["ranking_signals"]["used_scoring_v2"] is True
        assert body["ranking_signals"]["scoring_model"] == "v2_weighted_components"
        assert body["ranking_signals"]["hub_linked_in_results"] == 1
        hub_item = next(r for r in body["results"] if r["source_path"] == "hub_linked")
        assert hub_item["result_trust"] in {"high", "medium", "low"}
        assert hub_item["confidence"] is not None
        assert all(r["result_trust"] for r in body["results"])
