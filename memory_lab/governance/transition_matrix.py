"""
Phase 7b T5 — Transition Matrix Enforcement

Defines explicitly allowed and forbidden tier transitions.
Forbidden transitions raise GovernanceTransitionError.
"""
from typing import Optional, Set
import logging

logger = logging.getLogger(__name__)


class GovernanceTransitionError(Exception):
    """Raised when a forbidden tier transition is attempted (T5)."""

    def __init__(self, previous_tier: Optional[str], new_tier: str, reason: str):
        self.previous_tier = previous_tier
        self.new_tier = new_tier
        self.reason = reason
        super().__init__(
            f"[transition_matrix] FORBIDDEN {previous_tier!r} → {new_tier!r}: {reason}"
        )


# Tier ordering for upshift detection (higher = more durable)
TIER_ORDER: dict = {
    "discard": -1,
    "transient": 0,
    "probationary": 1,
    "persistent": 2,
    # Below are not on the main ladder; upshift detection ignores them
    "conflicted": -1,
    "superseded": -1,
    "decayed": -1,
    "archived": -1,
    "decision_artifact": 3,  # human gate only — never via system path
}

# Terminal tiers: once assigned, the system may not transition them further
_TERMINAL_TIERS: frozenset = frozenset({"archived", "decayed", "superseded"})

# Tiers that may only be set by human_override (never by system or policy_engine)
_HUMAN_GATE_TIERS: frozenset = frozenset({"decision_artifact"})

# Explicit system-allowed transitions.
# Key: current tier (None = initial assignment, content not yet in DB).
# Value: set of new tiers reachable by system/policy_engine trigger.
_ALLOWED_SYSTEM: dict = {
    None: {"discard", "transient", "probationary", "persistent"},
    "transient": {"probationary", "persistent", "decayed", "archived", "conflicted"},
    "probationary": {"persistent", "decayed", "archived", "conflicted"},
    "persistent": {"decayed", "archived", "conflicted", "superseded"},
    "conflicted": {"persistent", "transient", "archived"},
    # discard: content was never persisted, no forward transitions
    "discard": set(),
}


def validate_transition(
    previous_tier: Optional[str],
    new_tier: str,
    trigger_type: str = "system",
) -> None:
    """
    Validate a tier transition against the allowed matrix.

    Rules (evaluated in order):
    1. human_gate_only tiers (decision_artifact) → only via human_override.
    2. Terminal tiers (archived, decayed, superseded) → no further transitions, ever.
    3. Discard → no forward transitions (was never persisted).
    4. human_override → allowed to reach any non-human-gate-locked tier.
    5. system / policy_engine → must appear in _ALLOWED_SYSTEM matrix.

    Raises GovernanceTransitionError for forbidden transitions.
    """
    # Rule 1: human-gate-only destinations
    if new_tier in _HUMAN_GATE_TIERS and trigger_type != "human_override":
        raise GovernanceTransitionError(
            previous_tier, new_tier,
            f"tier '{new_tier}' requires trigger_type='human_override', got '{trigger_type}'",
        )

    # Rule 2: terminal source tiers — no exit
    if previous_tier in _TERMINAL_TIERS:
        raise GovernanceTransitionError(
            previous_tier, new_tier,
            f"tier '{previous_tier}' is terminal — no transitions are allowed out of it",
        )

    # Rule 3: discard source — content was never persisted
    if previous_tier == "discard":
        raise GovernanceTransitionError(
            previous_tier, new_tier,
            "discarded content has no content_id; tier transitions are not valid",
        )

    # Rule 4: human_override is broadly permissive (checked rule 1 above already)
    if trigger_type == "human_override":
        return

    # Rule 5: system / policy_engine — check explicit matrix
    allowed: Set[str] = _ALLOWED_SYSTEM.get(previous_tier, set())
    if new_tier not in allowed:
        raise GovernanceTransitionError(
            previous_tier, new_tier,
            f"not in allowed system transitions for '{previous_tier}': {sorted(allowed)}",
        )


def is_upshift(previous_tier: Optional[str], new_tier: str) -> bool:
    """Return True if new_tier is strictly higher on the tier ladder than previous_tier."""
    if previous_tier is None:
        return False
    return TIER_ORDER.get(new_tier, -1) > TIER_ORDER.get(previous_tier, -1)
