import pytest

from memory_lab.conflicts.detector import ConflictSourceRow, detect_conflict_candidates

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS1 = "00000000-0000-0000-0000-000000000001"
WS2 = "00000000-0000-0000-0000-000000000002"


def row(cid, text, *, ws=WS1, confidence=0.9, scope="b11", is_current=None, supersedes=None):
    return ConflictSourceRow(
        content_id=cid, workspace_id=ws, text=text, memory_type="decision",
        classify_confidence=confidence, current_state_scope=scope,
        is_current=is_current, cs_supersedes_content_id=supersedes,
    )


def test_support_only_returns_no_conflict():
    rows = [row("a", "scope: b11\nsupports: b11"), row("b", "scope: b11\nconfirmed: b11")]
    assert detect_conflict_candidates(rows, workspace_id=WS1) == []


def test_explicit_counterfinding_returns_conflict_candidate():
    rows = [row("a", "scope: b11\nfinding: original"), row("b", "scope: b11\ncounterfinding: b11")]
    c = detect_conflict_candidates(rows, workspace_id=WS1)[0]
    assert c.conflict_type == "explicit_counterfinding"
    assert c.status == "unresolved"
    assert c.supporting_content_ids == ["a"]
    assert c.contradicting_content_ids == ["b"]
    assert "explicit_counterfinding_marker" in c.reason_codes


def test_explicit_contradiction_returns_conflict_candidate():
    rows = [row("a", "scope: b11\nfinding: original"), row("b", "scope: b11\ncontradicts: b11")]
    c = detect_conflict_candidates(rows, workspace_id=WS1)[0]
    assert c.conflict_type == "explicit_contradiction"
    assert c.severity == "high"


def test_stale_current_same_scope_tension_returns_candidate():
    rows = [row("old", "scope: b11\nold state", is_current=False), row("new", "scope: b11\nnew state", is_current=True, supersedes="old")]
    c = detect_conflict_candidates(rows, workspace_id=WS1)[0]
    assert c.conflict_type == "stale_current_tension"
    assert c.status == "resolved"
    assert c.supporting_content_ids == ["new"]
    assert c.contradicting_content_ids == ["old"]


def test_workspace_isolation():
    rows = [row("a", "scope: b11\nfinding"), row("b", "scope: b11\ncontradicts: b11", ws=WS2)]
    assert detect_conflict_candidates(rows, workspace_id=WS1) == []


def test_discard_no_persist_ignored():
    rows = [row("a", "scope: b11\nfinding"), row(None, "scope: b11\ncontradicts: b11")]
    assert detect_conflict_candidates(rows, workspace_id=WS1) == []


def test_low_confidence_edge_case_caps_explicit_marker():
    rows = [row("a", "scope: b11\nfinding", confidence=0.9), row("b", "scope: b11\ncontradicts: b11", confidence=0.4)]
    c = detect_conflict_candidates(rows, workspace_id=WS1)[0]
    assert c.confidence <= 0.60
    assert c.severity == "low"


def test_low_confidence_current_state_ignored():
    rows = [row("old", "scope: b11", is_current=False), row("new", "scope: b11", confidence=0.4, is_current=True, supersedes="old")]
    assert detect_conflict_candidates(rows, workspace_id=WS1) == []


def test_deterministic_candidate_ids_order_independent():
    rows1 = [row("a", "scope: b11\nfinding"), row("b", "scope: b11\ncontradicts: b11")]
    rows2 = list(reversed(rows1))
    assert detect_conflict_candidates(rows1, workspace_id=WS1)[0].candidate_id == detect_conflict_candidates(rows2, workspace_id=WS1)[0].candidate_id


def test_same_scope_opposing_claim_fixture_rules():
    rows = [row("a", "scope: b11\nmust: use deterministic conflicts"), row("b", "scope: b11\nmust_not: use deterministic conflicts")]
    c = detect_conflict_candidates(rows, workspace_id=WS1)[0]
    assert c.conflict_type == "same_scope_opposing_claim"
    assert "exact_normalized_object_match" in c.reason_codes


def test_api_result_shape_model_flags_false():
    c = detect_conflict_candidates([row("a", "scope: b11\nfinding"), row("b", "scope: b11\ncontradicts: b11")], workspace_id=WS1)[0]
    dumped = c.model_dump()
    for key in ["candidate_id", "workspace_id", "conflict_type", "scope", "status", "severity", "confidence", "supporting_content_ids", "contradicting_content_ids", "evidence", "reason_codes"]:
        assert key in dumped
