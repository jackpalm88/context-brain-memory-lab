"""B21 deterministic tier routing plan recommendations.

Recommendation evidence only: no durable tier change, no event emission, and no
autonomous governance authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from memory_lab.ingestion.ingestion_scoring import IngestionScoringSummary

B21_TIER_ROUTING_PLAN_MODE = "b21_deterministic_tier_routing_plan_v1"
ALLOWED_TIERS = ("discard", "transient", "probationary", "persistent")
FORBIDDEN_TIERS = ("decision_artifact", "archived", "conflicted", "superseded", "decayed")
DEFAULT_LIMITATIONS = ("tier routing plan recommendation only", "no durable tier change", "no event emission", "no autonomous governance authority")


@dataclass(frozen=True)
class TierRoutingPlanInput:
    scoring_summary: IngestionScoringSummary
    circuit_state: str = "closed"
    policy_config: Mapping[str, float] = field(default_factory=dict)
    safety_flags: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class TierRoutingPlan:
    recommended_tier: str
    should_persist: bool
    rationale: str
    rule_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    safety_flags: tuple[str, ...]
    mode: str = B21_TIER_ROUTING_PLAN_MODE
    plan_only: bool = True


class DeterministicTierRoutingPlanner:
    def plan_tier_route(self, plan_input: TierRoutingPlanInput) -> TierRoutingPlan:
        score = plan_input.scoring_summary.score
        thresholds = _thresholds(plan_input.policy_config)
        circuit_state = (plan_input.circuit_state or "closed").lower()
        rule_ids = ["B21-C2-PLAN-ONLY"]
        safety_flags = list(plan_input.safety_flags)
        adjusted = score.composite
        if circuit_state in {"open", "unavailable"}:
            adjusted = min(adjusted, thresholds["transient_max"])
            rule_ids.append("B21-C2-CIRCUIT-BLOCKS-PERSISTENCE")
            safety_flags.append("circuit_not_closed")
        elif circuit_state in {"degraded", "half_open"}:
            adjusted = min(adjusted, thresholds["probationary_min"] - 0.000001)
            rule_ids.append("B21-C2-CIRCUIT-DEGRADES-PLAN")
            safety_flags.append("circuit_degraded_or_half_open")
        if score.risk >= thresholds["high_risk"]:
            adjusted = min(adjusted, thresholds["transient_max"])
            rule_ids.append("B21-C2-HIGH-RISK-LIMITS-TIER")
            safety_flags.append("high_risk_score")
        if score.confidence < thresholds["min_confidence"]:
            adjusted = min(adjusted, thresholds["probationary_min"] - 0.000001)
            rule_ids.append("B21-C2-LOW-CONFIDENCE-LIMITS-TIER")
            safety_flags.append("low_confidence")
        tier = _tier_for(adjusted, thresholds)
        if tier not in ALLOWED_TIERS or tier in FORBIDDEN_TIERS:
            raise ValueError(f"forbidden tier recommendation: {tier}")
        should_persist = tier in {"probationary", "persistent"} and not safety_flags
        rule_ids.append({"discard": "B21-C2-DISCARD-BOUNDARY", "transient": "B21-C2-TRANSIENT-BOUNDARY", "probationary": "B21-C2-PROBATIONARY-BOUNDARY", "persistent": "B21-C2-PERSISTENT-BOUNDARY"}[tier])
        return TierRoutingPlan(
            recommended_tier=tier,
            should_persist=should_persist,
            rationale="deterministic B21 tier routing plan generated from scoring summary and supplied circuit status",
            rule_ids=tuple(_dedupe(rule_ids)),
            limitations=DEFAULT_LIMITATIONS,
            safety_flags=tuple(_dedupe(safety_flags)),
        )


def make_deterministic_tier_routing_planner() -> DeterministicTierRoutingPlanner:
    return DeterministicTierRoutingPlanner()


def plan_tier_route(plan_input: TierRoutingPlanInput) -> TierRoutingPlan:
    return make_deterministic_tier_routing_planner().plan_tier_route(plan_input)


def _thresholds(policy_config: Mapping[str, float]) -> dict[str, float]:
    return {"discard_max": _get(policy_config, "discard_max", 0.30), "transient_max": _get(policy_config, "transient_max", 0.55), "probationary_min": _get(policy_config, "probationary_min", 0.55), "persistent_min": _get(policy_config, "persistent_min", 0.78), "high_risk": _get(policy_config, "high_risk", 0.70), "min_confidence": _get(policy_config, "min_confidence", 0.45)}


def _tier_for(score: float, thresholds: Mapping[str, float]) -> str:
    if score <= thresholds["discard_max"]:
        return "discard"
    if score <= thresholds["transient_max"]:
        return "transient"
    if score < thresholds["persistent_min"]:
        return "probationary"
    return "persistent"


def _get(config: Mapping[str, float], key: str, default: float) -> float:
    try:
        return float(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set(); out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value); out.append(value)
    return tuple(out)
