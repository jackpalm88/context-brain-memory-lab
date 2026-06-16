from memory_lab.governance.tier_routing_plan import FORBIDDEN_TIERS, TierRoutingPlanInput, plan_tier_route
from memory_lab.ingestion.ingestion_scoring import IngestionScore, IngestionScoringSummary


def summary(composite, risk=0.0, confidence=0.9):
    return IngestionScoringSummary(score=IngestionScore(quality=composite, risk=risk, completeness=composite, composite=composite, confidence=confidence), rationale="test", rule_ids=("test",), limitations=("test",))


def plan(composite, **kw):
    return plan_tier_route(TierRoutingPlanInput(scoring_summary=summary(composite, risk=kw.pop("risk", 0.0), confidence=kw.pop("confidence", 0.9)), **kw))


def test_discard_boundary():
    assert plan(0.20).recommended_tier == "discard"


def test_transient_boundary():
    assert plan(0.45).recommended_tier == "transient"


def test_probationary_boundary():
    assert plan(0.65).recommended_tier == "probationary"


def test_persistent_boundary():
    result = plan(0.90)
    assert result.recommended_tier == "persistent"
    assert result.should_persist is True


def test_circuit_open_and_degraded_affect_plan_safely():
    open_plan = plan(0.90, circuit_state="open")
    degraded_plan = plan(0.90, circuit_state="degraded")
    assert open_plan.recommended_tier == "transient"
    assert degraded_plan.recommended_tier == "transient"
    assert open_plan.should_persist is False
    assert degraded_plan.should_persist is False
    assert "circuit_not_closed" in open_plan.safety_flags


def test_high_risk_and_low_confidence_limit_plan():
    risky = plan(0.95, risk=0.9)
    low_conf = plan(0.95, confidence=0.2)
    assert risky.recommended_tier == "transient"
    assert low_conf.recommended_tier == "transient"
    assert risky.should_persist is False
    assert low_conf.should_persist is False


def test_never_emits_forbidden_tiers_and_is_plan_only():
    for value in (0.0, 0.31, 0.56, 0.78, 1.0):
        result = plan(value)
        assert result.recommended_tier not in FORBIDDEN_TIERS
        assert result.plan_only is True
        assert any("recommendation only" in item for item in result.limitations)
        assert any("no durable tier change" in item for item in result.limitations)
        assert any("no event emission" in item for item in result.limitations)
