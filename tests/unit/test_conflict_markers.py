import pytest

from memory_lab.conflicts.markers import extract_markers, is_support_only, normalize_object, normalize_scope, parse_opposing_claims

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


def test_normalize_scope_slugifies():
    assert normalize_scope("B11 Conflict Layer") == "b11-conflict-layer"


def test_extract_counterfinding_marker():
    markers = extract_markers("scope: b11\ncounterfinding: b11")
    assert markers.scope == "b11"
    assert markers.counterfinding[0].name == "counterfinding"


def test_extract_contradiction_marker():
    markers = extract_markers("contradicts: b11")
    assert markers.contradiction[0].name == "contradicts"


def test_support_only_detected():
    markers = extract_markers("supports: b11")
    assert is_support_only(markers) is True


def test_support_plus_contradiction_not_support_only():
    markers = extract_markers("supports: b11\ncontradicts: b11")
    assert is_support_only(markers) is False


def test_opposing_claim_must_pair_object_normalization():
    claims = parse_opposing_claims("must: Use Deterministic Conflicts!\nmust_not: use deterministic conflicts")
    assert {c.polarity for c in claims} == {"positive", "negative"}
    assert {c.obj for c in claims} == {"use deterministic conflicts"}


def test_claim_enabled_disabled_pair():
    claims = parse_opposing_claims("claim: Feature X is enabled\nclaim: feature x is disabled")
    assert {c.polarity for c in claims} == {"positive", "negative"}
    assert {c.obj for c in claims} == {"feature x"}


def test_normalize_object_removes_safe_punctuation():
    assert normalize_object("Use: Deterministic-Conflicts!") == "use deterministic conflicts"
