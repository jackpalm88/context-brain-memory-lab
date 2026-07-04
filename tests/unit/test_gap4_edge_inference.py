"""Gap-4 — deterministic inferred-edge producer (EDGE-INF-1).

Behavioral contracts:
  G4-1  co_membership_v1: hub pairs sharing >= min_shared content propose
        'related' edges; below threshold stays silent
  G4-2  tag_alignment_v1: topic_tags matched against normalized hub terms
        (title + aliases + related_terms); snake_case tags match Title Case
  G4-3  confidence scales with evidence, capped at 0.95
  G4-4  merge: same pair from both rules -> one proposal, higher confidence
        wins, rules unioned; deterministic ordering
  G4-5  persist: status='inferred', origin='ai_suggested', ON CONFLICT
        DO NOTHING — existing/rejected edges are never overwritten
  G4-6  run_edge_inference: workspace required; dry-run writes nothing
  G4-7  proposals are consumable by the existing human gate (type/status/
        origin valid per HubEdgeStore)

All tests are hermetic — no real DB, no providers.
"""
from __future__ import annotations

import pytest

from memory_lab.graph.edge_inference import (
    EdgeProposal,
    PRODUCER_VERSION,
    PROPOSED_EDGE_TYPE,
    merge_proposals,
    normalize_term,
    persist_edge_proposals,
    propose_from_co_membership,
    propose_from_tag_alignment,
    run_edge_inference,
)
from memory_lab.graph.hub_edge_store import ALL_TYPES, VALID_ORIGINS, VALID_STATUSES, _compute_edge_key

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-0000000000a1"
HUB_A = "00000000-0000-0000-0000-00000000aaa1"
HUB_B = "00000000-0000-0000-0000-00000000bbb2"
HUB_C = "00000000-0000-0000-0000-00000000ccc3"


def _memberships(pairs):
    return [(hub, f"content-{i}-{hub[:4]}" if isinstance(i, int) else i) for hub, i in pairs]


# ---------------------------------------------------------------------------
# G4-1 — co-membership producer
# ---------------------------------------------------------------------------

class TestCoMembership:
    def test_g4_1_pair_at_threshold_proposes_related_edge(self):
        rows = [(HUB_A, f"c{i}") for i in range(3)] + [(HUB_B, f"c{i}") for i in range(3)]
        proposals = propose_from_co_membership(rows, min_shared=3)
        assert len(proposals) == 1
        p = proposals[0]
        assert p.edge_type == "related"
        assert {p.source_hub_id, p.target_hub_id} == {HUB_A, HUB_B}
        assert p.detection_rules == ["co_membership_v1"]
        assert p.evidence_count == 3

    def test_g4_1_below_threshold_is_silent(self):
        rows = [(HUB_A, "c1"), (HUB_A, "c2"), (HUB_B, "c1"), (HUB_B, "c2")]
        assert propose_from_co_membership(rows, min_shared=3) == []

    def test_g4_1_source_target_sorted_for_symmetric_key(self):
        rows = [(HUB_B, f"c{i}") for i in range(3)] + [(HUB_A, f"c{i}") for i in range(3)]
        p = propose_from_co_membership(rows, min_shared=3)[0]
        assert p.source_hub_id == min(HUB_A, HUB_B)
        assert p.target_hub_id == max(HUB_A, HUB_B)

    def test_g4_1_three_hubs_produce_only_qualifying_pairs(self):
        rows = (
            [(HUB_A, f"c{i}") for i in range(4)]
            + [(HUB_B, f"c{i}") for i in range(4)]
            + [(HUB_C, "c0")]
        )
        proposals = propose_from_co_membership(rows, min_shared=3)
        assert len(proposals) == 1
        assert {proposals[0].source_hub_id, proposals[0].target_hub_id} == {HUB_A, HUB_B}


# ---------------------------------------------------------------------------
# G4-2 — tag alignment producer
# ---------------------------------------------------------------------------

HUBS = [
    {"hub_id": HUB_A, "title": "Retrieval Augmented Generation", "aliases": ["RAG"], "related_terms": []},
    {"hub_id": HUB_B, "title": "Context Engineering", "aliases": [], "related_terms": ["prompt-engineering"]},
    {"hub_id": HUB_C, "title": "Unrelated Hub", "aliases": [], "related_terms": []},
]


class TestTagAlignment:
    def test_normalize_folds_snake_kebab_and_case(self):
        assert normalize_term("Retrieval_Augmented-Generation") == "retrieval augmented generation"
        assert normalize_term("  Prompt-Engineering ") == "prompt engineering"

    def test_g4_2_snake_case_tags_match_title_case_hub_terms(self):
        contents = [
            (f"doc{i}", ["retrieval_augmented_generation", "context_engineering"]) for i in range(3)
        ]
        proposals = propose_from_tag_alignment(HUBS, contents, min_cooccur=3)
        assert len(proposals) == 1
        p = proposals[0]
        assert {p.source_hub_id, p.target_hub_id} == {HUB_A, HUB_B}
        assert p.detection_rules == ["tag_alignment_v1"]
        assert p.evidence_count == 3

    def test_g4_2_alias_and_related_terms_participate(self):
        contents = [(f"doc{i}", ["rag", "prompt_engineering"]) for i in range(3)]
        proposals = propose_from_tag_alignment(HUBS, contents, min_cooccur=3)
        assert len(proposals) == 1
        assert {proposals[0].source_hub_id, proposals[0].target_hub_id} == {HUB_A, HUB_B}

    def test_g4_2_below_cooccur_threshold_is_silent(self):
        contents = [("doc1", ["rag", "context_engineering"])]
        assert propose_from_tag_alignment(HUBS, contents, min_cooccur=3) == []

    def test_g4_2_noise_tags_ignored(self):
        contents = [(f"doc{i}", ["placeholder", "rag"]) for i in range(5)]
        assert propose_from_tag_alignment(HUBS, contents, min_cooccur=1) == []

    def test_g4_2_single_hub_mention_never_pairs(self):
        contents = [(f"doc{i}", ["rag"]) for i in range(5)]
        assert propose_from_tag_alignment(HUBS, contents, min_cooccur=1) == []


# ---------------------------------------------------------------------------
# G4-3 — confidence scaling
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_g4_3_confidence_scales_with_evidence(self):
        rows3 = [(h, f"c{i}") for h in (HUB_A, HUB_B) for i in range(3)]
        rows8 = [(h, f"c{i}") for h in (HUB_A, HUB_B) for i in range(8)]
        p3 = propose_from_co_membership(rows3, min_shared=3)[0]
        p8 = propose_from_co_membership(rows8, min_shared=3)[0]
        assert p3.confidence == 0.75
        assert p8.confidence == 0.80

    def test_g4_3_confidence_capped(self):
        rows = [(h, f"c{i}") for h in (HUB_A, HUB_B) for i in range(60)]
        p = propose_from_co_membership(rows, min_shared=3)[0]
        assert p.confidence == 0.95


# ---------------------------------------------------------------------------
# G4-4 — merge semantics
# ---------------------------------------------------------------------------

class TestMerge:
    def test_g4_4_same_pair_from_both_rules_merges_to_one(self):
        a = propose_from_co_membership(
            [(h, f"c{i}") for h in (HUB_A, HUB_B) for i in range(3)], min_shared=3)
        b = propose_from_tag_alignment(
            HUBS, [(f"doc{i}", ["rag", "context_engineering"]) for i in range(10)], min_cooccur=3)
        merged = merge_proposals(a, b)
        assert len(merged) == 1
        p = merged[0]
        assert p.detection_rules == ["co_membership_v1", "tag_alignment_v1"]
        assert p.confidence == max(a[0].confidence, b[0].confidence)
        assert "co_membership" in p.reason and "tag_alignment" in p.reason

    def test_g4_4_ordering_is_confidence_desc_then_key(self):
        low = EdgeProposal(HUB_A, HUB_B, "related", 0.75, "x", ["co_membership_v1"], 3)
        high = EdgeProposal(HUB_A, HUB_C, "related", 0.90, "y", ["tag_alignment_v1"], 18)
        merged = merge_proposals([low], [high])
        assert [p.confidence for p in merged] == [0.90, 0.75]

    def test_g4_4_edge_key_matches_store_convention(self):
        p = EdgeProposal(HUB_B, HUB_A, "related", 0.8, "x", ["co_membership_v1"], 3)
        assert p.edge_key == _compute_edge_key(HUB_B, HUB_A, "related")


# ---------------------------------------------------------------------------
# G4-5 / G4-6 — persistence against a fake connection
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, fetchone_queue):
        self.executed = []
        self._queue = list(fetchone_queue)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._queue.pop(0) if self._queue else None

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, *a, **k):
        return self.cursor_obj

    def commit(self):
        self.committed = True


def _proposal():
    return EdgeProposal(HUB_A, HUB_B, "related", 0.78, "co_membership: 6 shared content items",
                        ["co_membership_v1"], 6)


class TestPersist:
    def test_g4_5_insert_shape_inferred_ai_suggested(self):
        cur = FakeCursor(fetchone_queue=[("edge-id-1",)])
        conn = FakeConn(cur)

        stats = persist_edge_proposals(conn, [_proposal()], workspace_id=WS)

        sql, params = cur.executed[0]
        assert "INSERT INTO cb_hub_edges" in sql
        assert "'inferred', 'ai_suggested'" in sql
        assert "ON CONFLICT (edge_key) WHERE archived_at IS NULL DO NOTHING" in sql
        assert params[0] == HUB_A and params[1] == HUB_B and params[2] == WS
        assert params[3] == "related"
        assert params[4] == 0.78
        assert "[co_membership_v1]" in params[5]
        assert params[7] == PRODUCER_VERSION
        assert stats == {"inserted": 1, "skipped_existing": 0}
        assert conn.committed

    def test_g4_5_conflict_counts_as_skipped_never_updates(self):
        cur = FakeCursor(fetchone_queue=[None])
        conn = FakeConn(cur)

        stats = persist_edge_proposals(conn, [_proposal()], workspace_id=WS)

        sql_all = " || ".join(s for s, _ in cur.executed)
        assert "UPDATE" not in sql_all
        assert stats == {"inserted": 0, "skipped_existing": 1}

    def test_g4_6_workspace_required(self):
        with pytest.raises(ValueError):
            run_edge_inference(FakeConn(FakeCursor([])), workspace_id="")

    def test_g4_6_dry_run_computes_but_writes_nothing(self):
        class QueryCursor(FakeCursor):
            def __init__(self):
                super().__init__([])
                self._results = [
                    # memberships: A and B share c1..c3
                    [{"hub_id": h, "content_id": f"c{i}"} for h in (HUB_A, HUB_B) for i in range(3)],
                    # hubs
                    [{"hub_id": HUB_A, "title": "Alpha", "aliases": [], "related_terms": []},
                     {"hub_id": HUB_B, "title": "Beta", "aliases": [], "related_terms": []}],
                    # tagged contents
                    [],
                ]

            def fetchall(self):
                return self._results.pop(0) if self._results else []

        cur = QueryCursor()
        conn = FakeConn(cur)
        report = run_edge_inference(conn, workspace_id=WS, min_shared=3, dry_run=True)

        assert report["dry_run"] is True
        assert report["proposals_total"] == 1
        assert report["inserted"] == 0
        assert not conn.committed
        sql_all = " || ".join(s for s, _ in cur.executed)
        assert "INSERT INTO cb_hub_edges" not in sql_all
        assert report["proposals"][0]["detection_rules"] == ["co_membership_v1"]


# ---------------------------------------------------------------------------
# G4-7 — proposals fit the existing human gate
# ---------------------------------------------------------------------------

class TestHumanGateCompatibility:
    def test_g4_7_edge_type_valid_for_store(self):
        assert PROPOSED_EDGE_TYPE in ALL_TYPES

    def test_g4_7_status_and_origin_valid_for_store(self):
        assert "inferred" in VALID_STATUSES
        assert "ai_suggested" in VALID_ORIGINS

    def test_g4_7_approve_reject_consumers_exist(self):
        from memory_lab.graph.hub_edge_store import HubEdgeStore
        assert callable(HubEdgeStore.approve_inferred_edge)
        assert callable(HubEdgeStore.reject_inferred_edge)
