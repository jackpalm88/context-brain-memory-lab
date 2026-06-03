"""
Phase 7b — Tier Router

Maps a composite score + metadata flags to a memory tier.

Constitution constraints (PHASE7_BRIEFING.md Section 4):
- P-IV: Memory has lifecycle states — explicit tier per item
- P-II: Persistence is a cost — tier = transient unless justified
- P-V:  Human gate — decision_artifact MUST NOT be auto-assigned here

INVARIANT: This module NEVER emits 'decision_artifact' or 'archived'.
  - 'decision_artifact' is set ONLY by create_decision_memory router (human gate)
  - 'archived' is set ONLY by the decay job (Phase 7d)

DISCARD: When route() returns tier='discard', the caller MUST NOT write to the DB.
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional

from memory_lab.governance import ingestion_policy as policy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier constants — matches the memory_tier ENUM in migration 013
# ---------------------------------------------------------------------------
TIER_DISCARD = "discard"
TIER_TRANSIENT = "transient"
TIER_PROBATIONARY = "probationary"
TIER_PERSISTENT = "persistent"

# Tiers this router will NEVER emit (reserved for other subsystems)
_FORBIDDEN_OUTPUTS = frozenset({"decision_artifact", "archived", "conflicted", "superseded", "decayed"})


@dataclass
class TierDecision:
    tier: str          # One of: discard, transient, probationary, persistent
    reason: str        # Human-readable rationale (stored as tier_reason)
    rule_id: str       # Constitution rule ID (e.g. "T-PERSISTENT")
    should_persist: bool  # False only for 'discard' — caller must check before DB write


def _get_float(env_var: str, default: float) -> float:
    raw = os.environ.get(env_var, "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


def _thresholds() -> dict:
    """Read tier thresholds from policy (YAML + env var overrides)."""
    rules = policy.load()
    tiers = rules.get("tiers", {})

    def _val(tier_name: str, key: str, default: float) -> float:
        node = tiers.get(tier_name, {}).get(key, {})
        if isinstance(node, dict):
            env_var = node.get("env_var")
            yaml_default = node.get("default", default)
            return _get_float(env_var, yaml_default) if env_var else float(yaml_default)
        return default

    return {
        "discard_max":        _val("discard",      "composite_max", 0.3),
        "transient_max":      _val("transient",    "composite_max", 0.5),
        "probationary_max":   _val("probationary", "composite_max", 0.7),
        # persistent: anything >= probationary_max
    }


def route(
    composite_score: float,
    circuit_open: bool = False,
    quality_score: float = 0.5,
    node_type: Optional[str] = None,
) -> TierDecision:
    """
    Map a composite score + flags to a memory tier.

    Args:
        composite_score: Weighted composite from ingestion_scorer (0.0–1.0)
        circuit_open:    True when scoring circuit breaker is open (fallback scores used)
        quality_score:   Raw quality axis score (used for hard quality floor enforcement)
        node_type:       Content node_type (e.g. 'decision') — for future hook, not used here

    Returns:
        TierDecision with tier, reason, rule_id, should_persist

    INVARIANT: Never returns tier='decision_artifact' or any archived/conflicted state.
    """
    t = _thresholds()
    min_quality = policy.min_quality(node_type or "")

    # -----------------------------------------------------------------------
    # Rule 1: Circuit open → transient override (Pitfall #1)
    # -----------------------------------------------------------------------
    if circuit_open:
        return TierDecision(
            tier=TIER_TRANSIENT,
            reason="circuit_open:fallback_scores_used",
            rule_id="T-TRANSIENT",
            should_persist=True,
        )

    # -----------------------------------------------------------------------
    # Rule 2: Hard quality floor — regardless of composite, low quality → discard
    # (Constitution P-IX: Retrieval quality begins at ingestion discipline)
    # -----------------------------------------------------------------------
    if quality_score < min_quality:
        return TierDecision(
            tier=TIER_DISCARD,
            reason=f"quality_floor:quality={quality_score:.3f}<min={min_quality:.3f}",
            rule_id="T-DISCARD",
            should_persist=False,
        )

    # -----------------------------------------------------------------------
    # Rule 3: Composite score routing
    # -----------------------------------------------------------------------
    if composite_score < t["discard_max"]:
        return TierDecision(
            tier=TIER_DISCARD,
            reason=f"composite_below_discard_threshold:{composite_score:.3f}<{t['discard_max']:.3f}",
            rule_id="T-DISCARD",
            should_persist=False,
        )

    if composite_score < t["transient_max"]:
        return TierDecision(
            tier=TIER_TRANSIENT,
            reason=f"composite_transient_range:{t['discard_max']:.3f}<={composite_score:.3f}<{t['transient_max']:.3f}",
            rule_id="T-TRANSIENT",
            should_persist=True,
        )

    if composite_score < t["probationary_max"]:
        return TierDecision(
            tier=TIER_PROBATIONARY,
            reason=f"composite_probationary_range:{t['transient_max']:.3f}<={composite_score:.3f}<{t['probationary_max']:.3f}",
            rule_id="T-PROBATIONARY",
            should_persist=True,
        )

    # composite_score >= probationary_max → persistent
    return TierDecision(
        tier=TIER_PERSISTENT,
        reason=f"composite_persistent_threshold:{composite_score:.3f}>={t['probationary_max']:.3f}",
        rule_id="T-PERSISTENT",
        should_persist=True,
    )


def validate_output(decision: TierDecision) -> None:
    """
    Assert that the router output respects the invariant — never emits
    a forbidden tier. Raises ValueError if violated (should never happen).
    """
    if decision.tier in _FORBIDDEN_OUTPUTS:
        raise ValueError(
            f"[tier_router] INVARIANT VIOLATION: tier_router emitted forbidden tier "
            f"'{decision.tier}'. This tier is reserved for human-gate or decay operations. "
            f"This is a Constitution P-V violation — check tier_router logic immediately."
        )
