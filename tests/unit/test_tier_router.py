"""Unit tests — tier router logic. No DB, no API, no network."""
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


def test_router_imports_cleanly():
    from memory_lab.governance import tier_router
    assert hasattr(tier_router, "route")
    assert hasattr(tier_router, "validate_output")
    assert hasattr(tier_router, "TierDecision")


def test_high_composite_routes_to_persistent():
    from memory_lab.governance.tier_router import route, TIER_PERSISTENT
    d = route(composite_score=0.85, circuit_open=False, quality_score=0.8)
    assert d.tier == TIER_PERSISTENT
    assert d.should_persist is True
    assert "T-PERSISTENT" in d.rule_id


def test_mid_composite_routes_to_probationary():
    from memory_lab.governance.tier_router import route, TIER_PROBATIONARY
    d = route(composite_score=0.60, circuit_open=False, quality_score=0.7)
    assert d.tier == TIER_PROBATIONARY
    assert d.should_persist is True


def test_low_composite_routes_to_transient():
    from memory_lab.governance.tier_router import route, TIER_TRANSIENT
    d = route(composite_score=0.40, circuit_open=False, quality_score=0.6)
    assert d.tier == TIER_TRANSIENT
    assert d.should_persist is True


def test_very_low_routes_to_discard():
    from memory_lab.governance.tier_router import route, TIER_DISCARD
    d = route(composite_score=0.15, circuit_open=False, quality_score=0.5)
    assert d.tier == TIER_DISCARD
    assert d.should_persist is False


def test_discard_boundary():
    from memory_lab.governance.tier_router import route, TIER_TRANSIENT, TIER_DISCARD
    assert route(composite_score=0.30, circuit_open=False, quality_score=0.5).tier == TIER_TRANSIENT
    assert route(composite_score=0.299, circuit_open=False, quality_score=0.5).tier == TIER_DISCARD


def test_circuit_open_routes_to_transient():
    from memory_lab.governance.tier_router import route, TIER_TRANSIENT
    d = route(composite_score=0.95, circuit_open=True, quality_score=0.9)
    assert d.tier == TIER_TRANSIENT
    assert "circuit_open" in d.reason


def test_low_quality_triggers_discard():
    from memory_lab.governance.tier_router import route, TIER_DISCARD
    from memory_lab.governance import ingestion_policy as policy
    min_q = policy.min_quality()
    d = route(composite_score=0.80, circuit_open=False, quality_score=min_q - 0.01)
    assert d.tier == TIER_DISCARD
    assert "quality_floor" in d.reason


def test_tier_reason_and_rule_id_populated():
    from memory_lab.governance.tier_router import route
    for score in [0.1, 0.4, 0.6, 0.85]:
        d = route(composite_score=score, circuit_open=False, quality_score=0.6)
        assert d.reason
        assert d.rule_id


FORBIDDEN_TIERS = ["decision_artifact", "archived", "conflicted", "superseded", "decayed"]


@pytest.mark.parametrize("composite", [0.0, 0.3, 0.5, 0.7, 0.9, 1.0])
@pytest.mark.parametrize("circuit_open", [True, False])
def test_never_emits_forbidden_tier(composite, circuit_open):
    from memory_lab.governance.tier_router import route
    d = route(composite_score=composite, circuit_open=circuit_open, quality_score=0.6)
    assert d.tier not in FORBIDDEN_TIERS


def test_validate_raises_on_forbidden():
    from memory_lab.governance.tier_router import TierDecision, validate_output
    bad = TierDecision(tier="decision_artifact", reason="test", rule_id="T-X", should_persist=True)
    with pytest.raises(ValueError, match="INVARIANT VIOLATION"):
        validate_output(bad)


def test_validate_accepts_valid():
    from memory_lab.governance.tier_router import TierDecision, validate_output
    good = TierDecision(tier="persistent", reason="test", rule_id="T-PERSISTENT", should_persist=True)
    validate_output(good)


def test_env_discard_threshold(monkeypatch):
    monkeypatch.setenv("CB_TIER_DISCARD_MAX", "0.6")
    from memory_lab.governance import tier_router
    import importlib; importlib.reload(tier_router)
    t = tier_router._thresholds()
    assert t["discard_max"] == 0.6
    assert tier_router.route(composite_score=0.55, circuit_open=False, quality_score=0.6).tier == "discard"


def test_env_persistent_threshold(monkeypatch):
    monkeypatch.setenv("CB_TIER_PROBATIONARY_MAX", "0.5")
    from memory_lab.governance import tier_router
    import importlib; importlib.reload(tier_router)
    t = tier_router._thresholds()
    assert t["probationary_max"] == 0.5
    assert tier_router.route(composite_score=0.55, circuit_open=False, quality_score=0.6).tier == "persistent"
