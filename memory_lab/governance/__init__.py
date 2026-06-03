"""Governance core for deterministic tier routing and admin governance actions."""

from .tier_router import (
    TIER_DISCARD,
    TIER_TRANSIENT,
    TIER_PROBATIONARY,
    TIER_PERSISTENT,
    TierDecision,
    route,
    validate_output,
)
from .transition_matrix import GovernanceTransitionError, validate_transition, is_upshift
from .events import (
    GOVERNANCE_EVENT_TYPE,
    TRIGGER_TYPES,
    TRIGGER_SOURCES,
    TierTransitionEvent,
    build_event,
    emit_event,
    validate_event,
)

__all__ = [
    "TIER_DISCARD",
    "TIER_TRANSIENT",
    "TIER_PROBATIONARY",
    "TIER_PERSISTENT",
    "TierDecision",
    "route",
    "validate_output",
    "GovernanceTransitionError",
    "validate_transition",
    "is_upshift",
    "GOVERNANCE_EVENT_TYPE",
    "TRIGGER_TYPES",
    "TRIGGER_SOURCES",
    "TierTransitionEvent",
    "build_event",
    "emit_event",
    "validate_event",
]
