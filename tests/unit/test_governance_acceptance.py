"""
test_governance_acceptance.py — Governance Boundary Acceptance (GOVERNANCE-1)

Engineering Quality Asset. Validates all Constitution invariants across the
full governance kernel:
  - Tier Router (P-II, P-IV, P-V, P-IX + all 4 tier boundaries)
  - Transition Matrix (all allowed + all forbidden paths; terminal/human-gate)
  - Circuit Breaker (full state machine: closed→degraded→open→half_open→closed)
  - Ingestion Policy (constitution load, threshold hierarchy, quality floor)
  - Determinism: pure functions, identical inputs → identical outputs

No DB, no network, no provider calls. 100% pure / hermetic.
"""
from __future__ import annotations

import os
import pytest
from typing import Optional

# ---------------------------------------------------------------------------
# Tier Router
# ---------------------------------------------------------------------------
from memory_lab.governance.tier_router import (
    route, validate_output, TierDecision,
    TIER_DISCARD, TIER_TRANSIENT, TIER_PROBATIONARY, TIER_PERSISTENT,
    _FORBIDDEN_OUTPUTS,
)

# ---------------------------------------------------------------------------
# Transition Matrix
# ---------------------------------------------------------------------------
from memory_lab.governance.transition_matrix import (
    validate_transition, is_upshift, GovernanceTransitionError,
    _TERMINAL_TIERS, _HUMAN_GATE_TIERS, _ALLOWED_SYSTEM, TIER_ORDER,
)

# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------
from memory_lab.governance.circuit_breaker import (
    evaluate_circuit_state, make_provider_neutral_circuit_breaker,
    CircuitBreakerEvent, CircuitBreakerConfig,
    B21_CIRCUIT_BREAKER_MODE, VALID_STATES, VALID_EVENT_TYPES,
)

# ---------------------------------------------------------------------------
# Ingestion Policy
# ---------------------------------------------------------------------------
from memory_lab.governance import ingestion_policy as policy


# ===========================================================================
# SECTION 1 — Tier Router: Constitution Invariants
# ===========================================================================

class TestTierRouterConstitutionInvariants:
    """P-II (Persistence = cost), P-IV (lifecycle states), P-V (human gate),
    P-IX (quality floor) — all four Constitution constraints on tier_router."""

    # P-V: Router NEVER emits decision_artifact or archived/conflicted/decayed
    def test_pv_forbidden_outputs_never_emitted_across_score_range(self):
        """Constitution P-V: human-gate tiers must never come from route()."""
        for score in [0.0, 0.1, 0.25, 0.3, 0.5, 0.7, 0.85, 1.0]:
            d = route(composite_score=score)
            assert d.tier not in _FORBIDDEN_OUTPUTS, (
                f"route({score}) emitted forbidden tier '{d.tier}' — P-V violation"
            )

    def test_pv_forbidden_set_is_correct(self):
        """Invariant set includes all human-gate and lifecycle-reserved tiers."""
        expected = {"decision_artifact", "archived", "conflicted", "superseded", "decayed"}
        assert _FORBIDDEN_OUTPUTS == frozenset(expected)

    # P-II: Default tier is discard/transient unless composite justifies persistence
    def test_pii_low_score_does_not_persist(self):
        """Constitution P-II: persistence is a cost; very low composite → discard."""
        d = route(composite_score=0.05, quality_score=0.9)
        assert d.tier == TIER_DISCARD
        assert d.should_persist is False

    def test_pii_mid_score_is_transient_not_persistent(self):
        """P-II: borderline content → transient, not persistent."""
        d = route(composite_score=0.4, quality_score=0.9)
        assert d.tier == TIER_TRANSIENT
        assert d.should_persist is True

    # P-IX: Quality floor enforced before composite routing
    def test_pix_quality_floor_overrides_high_composite(self):
        """P-IX: high composite + very low quality → discard (quality floor wins)."""
        d = route(composite_score=0.95, quality_score=0.01)
        assert d.tier == TIER_DISCARD
        assert d.should_persist is False
        assert "quality_floor" in d.reason

    def test_pix_epistemic_artifact_lower_quality_floor(self):
        """Epistemic node types (decision, fact, playbook) have a reduced quality floor."""
        # decision type has min_quality=0.25; quality=0.3 must pass floor
        d = route(composite_score=0.8, quality_score=0.3, node_type="decision")
        assert d.tier == TIER_PERSISTENT

    # P-IV: Every tier decision carries tier + reason + rule_id + should_persist
    def test_piv_tier_decision_fields_always_populated(self):
        """P-IV: TierDecision must always have tier, reason, rule_id, should_persist."""
        for score, q in [(0.1, 0.8), (0.35, 0.8), (0.6, 0.8), (0.85, 0.8)]:
            d = route(composite_score=score, quality_score=q)
            assert d.tier, f"score={score}: tier is blank"
            assert d.reason, f"score={score}: reason is blank"
            assert d.rule_id, f"score={score}: rule_id is blank"
            assert isinstance(d.should_persist, bool)

    def test_pv_validate_output_raises_on_forbidden(self):
        """validate_output() raises ValueError on any forbidden tier — Constitution guard."""
        for forbidden in _FORBIDDEN_OUTPUTS:
            bogus = TierDecision(
                tier=forbidden, reason="test", rule_id="TEST", should_persist=True
            )
            with pytest.raises(ValueError, match="INVARIANT VIOLATION"):
                validate_output(bogus)

    def test_pv_validate_output_accepts_valid_tiers(self):
        """validate_output() passes silently on all valid tiers."""
        for tier in (TIER_DISCARD, TIER_TRANSIENT, TIER_PROBATIONARY, TIER_PERSISTENT):
            d = TierDecision(tier=tier, reason="ok", rule_id="T-OK", should_persist=True)
            validate_output(d)  # must not raise


# ===========================================================================
# SECTION 2 — Tier Router: All 4 Tier Boundaries
# ===========================================================================

class TestTierRouterBoundaries:
    """All four tier boundaries with default thresholds (discard<0.3, transient<0.5,
    probationary<0.7, persistent≥0.7). Also circuit-open override."""

    def test_boundary_discard(self):
        d = route(composite_score=0.1, quality_score=0.9)
        assert d.tier == TIER_DISCARD
        assert d.should_persist is False
        assert "T-DISCARD" == d.rule_id

    def test_boundary_discard_just_below_threshold(self):
        d = route(composite_score=0.299, quality_score=0.9)
        assert d.tier == TIER_DISCARD

    def test_boundary_transient_at_discard_max(self):
        # Default discard_max=0.3; score exactly 0.3 should be transient
        d = route(composite_score=0.3, quality_score=0.9)
        assert d.tier == TIER_TRANSIENT

    def test_boundary_transient_mid(self):
        d = route(composite_score=0.4, quality_score=0.9)
        assert d.tier == TIER_TRANSIENT
        assert d.should_persist is True
        assert "T-TRANSIENT" == d.rule_id

    def test_boundary_probationary_at_transient_max(self):
        d = route(composite_score=0.5, quality_score=0.9)
        assert d.tier == TIER_PROBATIONARY

    def test_boundary_probationary_mid(self):
        d = route(composite_score=0.6, quality_score=0.9)
        assert d.tier == TIER_PROBATIONARY
        assert d.should_persist is True
        assert "T-PROBATIONARY" == d.rule_id

    def test_boundary_persistent_at_probationary_max(self):
        d = route(composite_score=0.7, quality_score=0.9)
        assert d.tier == TIER_PERSISTENT

    def test_boundary_persistent_high(self):
        d = route(composite_score=0.95, quality_score=0.9)
        assert d.tier == TIER_PERSISTENT
        assert d.should_persist is True
        assert "T-PERSISTENT" == d.rule_id

    def test_circuit_open_overrides_to_transient(self):
        """Circuit open → always transient, regardless of composite score."""
        for score in [0.05, 0.4, 0.85]:
            d = route(composite_score=score, circuit_open=True)
            assert d.tier == TIER_TRANSIENT, f"score={score}: circuit open must → transient"
            assert d.should_persist is True
            assert "circuit_open" in d.reason

    def test_env_override_discard_threshold(self, monkeypatch):
        """Env override raises discard ceiling: score below new threshold → discard."""
        monkeypatch.setenv("CB_TIER_DISCARD_MAX", "0.6")
        from memory_lab.governance import tier_router as _tr
        import importlib; importlib.reload(_tr)
        d = _tr.route(composite_score=0.55, quality_score=0.9)
        assert d.tier == TIER_DISCARD
        importlib.reload(_tr)  # restore default thresholds for other tests

    def test_env_override_persistent_threshold(self, monkeypatch):
        monkeypatch.setenv("CB_TIER_PROBATIONARY_MAX", "0.6")
        policy._LOADED = False; policy._RULES = {}
        d = route(composite_score=0.62, quality_score=0.9)
        assert d.tier == TIER_PERSISTENT
        policy._LOADED = False; policy._RULES = {}

    def test_determinism_identical_inputs_identical_outputs(self):
        """Pure function: same inputs must produce identical outputs on repeated calls."""
        for _ in range(5):
            d1 = route(0.65, circuit_open=False, quality_score=0.8, node_type=None)
            d2 = route(0.65, circuit_open=False, quality_score=0.8, node_type=None)
            assert d1.tier == d2.tier
            assert d1.reason == d2.reason
            assert d1.rule_id == d2.rule_id


# ===========================================================================
# SECTION 3 — Transition Matrix: All Allowed Paths
# ===========================================================================

class TestTransitionMatrixAllowed:
    """Every allowed system transition must pass validate_transition silently."""

    @pytest.mark.parametrize("prev,new", [
        (None, "discard"),
        (None, "transient"),
        (None, "probationary"),
        (None, "persistent"),
        ("transient", "probationary"),
        ("transient", "persistent"),
        ("transient", "decayed"),
        ("transient", "archived"),
        ("transient", "conflicted"),
        ("probationary", "persistent"),
        ("probationary", "decayed"),
        ("probationary", "archived"),
        ("probationary", "conflicted"),
        ("persistent", "decayed"),
        ("persistent", "archived"),
        ("persistent", "conflicted"),
        ("persistent", "superseded"),
        ("conflicted", "persistent"),
        ("conflicted", "transient"),
        ("conflicted", "archived"),
    ])
    def test_allowed_system_transition(self, prev, new):
        validate_transition(prev, new, trigger_type="system")  # must not raise

    def test_human_override_reaches_decision_artifact(self):
        """decision_artifact is only reachable via human_override (Constitution P-V)."""
        validate_transition("persistent", "decision_artifact", trigger_type="human_override")

    def test_human_override_broad_permissiveness(self):
        """human_override can reach persistent, transient, probationary from any non-terminal."""
        for prev in [None, "transient", "probationary", "conflicted"]:
            for new in ["persistent", "transient", "probationary"]:
                validate_transition(prev, new, trigger_type="human_override")


# ===========================================================================
# SECTION 4 — Transition Matrix: All Forbidden Paths
# ===========================================================================

class TestTransitionMatrixForbidden:
    """Every forbidden transition must raise GovernanceTransitionError."""

    # Terminal tiers: no exit
    @pytest.mark.parametrize("terminal", ["archived", "decayed", "superseded"])
    def test_terminal_tiers_no_exit(self, terminal):
        for new in ["transient", "persistent", "probationary", "conflicted"]:
            with pytest.raises(GovernanceTransitionError):
                validate_transition(terminal, new, trigger_type="system")

    # Discard: content was never persisted
    @pytest.mark.parametrize("new", ["transient", "probationary", "persistent", "conflicted"])
    def test_discard_no_forward_transitions(self, new):
        with pytest.raises(GovernanceTransitionError, match="discarded content"):
            validate_transition("discard", new, trigger_type="system")

    # Human-gate tier via non-human_override
    @pytest.mark.parametrize("trigger", ["system", "policy_engine"])
    def test_decision_artifact_requires_human_override(self, trigger):
        with pytest.raises(GovernanceTransitionError, match="human_override"):
            validate_transition("persistent", "decision_artifact", trigger_type=trigger)

    # Not-in-matrix transitions for system
    @pytest.mark.parametrize("prev,new", [
        ("transient", "discard"),         # discard is initial-only
        ("probationary", "transient"),    # no downshift allowed
        ("persistent", "transient"),      # no downshift allowed
        ("persistent", "probationary"),   # no downshift allowed
    ])
    def test_system_forbidden_matrix_transitions(self, prev, new):
        with pytest.raises(GovernanceTransitionError):
            validate_transition(prev, new, trigger_type="system")

    # Error fields are populated correctly
    def test_error_carries_previous_and_new_tier(self):
        try:
            validate_transition("archived", "persistent", trigger_type="system")
        except GovernanceTransitionError as e:
            assert e.previous_tier == "archived"
            assert e.new_tier == "persistent"
            assert e.reason
        else:
            pytest.fail("expected GovernanceTransitionError")


# ===========================================================================
# SECTION 5 — Transition Matrix: Upshift Detection + Terminal Set
# ===========================================================================

class TestTransitionMatrixUpshiftAndTerminal:

    def test_upshift_from_transient_to_persistent(self):
        assert is_upshift("transient", "persistent") is True

    def test_upshift_from_probationary_to_persistent(self):
        assert is_upshift("probationary", "persistent") is True

    def test_no_upshift_from_persistent_to_transient(self):
        assert is_upshift("persistent", "transient") is False

    def test_no_upshift_from_none(self):
        assert is_upshift(None, "persistent") is False

    def test_upshift_same_tier_is_false(self):
        assert is_upshift("persistent", "persistent") is False

    def test_terminal_tiers_set_correctness(self):
        assert _TERMINAL_TIERS == frozenset({"archived", "decayed", "superseded"})

    def test_human_gate_tiers_set_correctness(self):
        assert _HUMAN_GATE_TIERS == frozenset({"decision_artifact"})

    def test_tier_order_decision_artifact_highest(self):
        """decision_artifact must have the highest tier order — human gate only."""
        assert TIER_ORDER["decision_artifact"] > TIER_ORDER["persistent"]

    def test_tier_order_persistent_above_probationary(self):
        assert TIER_ORDER["persistent"] > TIER_ORDER["probationary"]


# ===========================================================================
# SECTION 6 — Circuit Breaker: Full State Machine
# ===========================================================================

class TestCircuitBreakerStateMachine:
    """Full closed → degraded → open → half_open → closed cycle."""

    def _ev(self, event_type, t, reason=""):
        return CircuitBreakerEvent(event_type=event_type, timestamp=float(t), reason=reason)

    def test_closed_state_allows_requests(self):
        snap = evaluate_circuit_state([], now=100.0)
        assert snap.state == "closed"
        assert snap.allow_request_recommendation is True
        assert snap.mode == B21_CIRCUIT_BREAKER_MODE

    def test_degraded_on_two_failures_within_window(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2, window_seconds=60)
        events = [self._ev("failure", 10), self._ev("failure", 20)]
        snap = evaluate_circuit_state(events, now=50.0, config=cfg)
        assert snap.state == "degraded"
        assert snap.allow_request_recommendation is True

    def test_open_on_failure_threshold_reached(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2, window_seconds=60)
        events = [self._ev("failure", 10), self._ev("failure", 20), self._ev("failure", 30)]
        snap = evaluate_circuit_state(events, now=50.0, config=cfg)
        assert snap.state == "open"
        assert snap.allow_request_recommendation is False
        assert snap.retry_after_seconds is not None
        assert snap.cooldown_remaining_seconds > 0

    def test_half_open_after_cooldown_expires(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2,
                                   window_seconds=60, open_duration_seconds=300)
        events = [self._ev("failure", 10), self._ev("failure", 20), self._ev("failure", 30)]
        # now = 30 + 300 + 1 = 331 → open_duration exceeded → half_open
        snap = evaluate_circuit_state(events, now=331.0, config=cfg)
        assert snap.state == "half_open"
        assert snap.allow_request_recommendation is True

    def test_closed_after_success_in_half_open(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2,
                                   window_seconds=60, open_duration_seconds=300,
                                   half_open_successes_to_close=1)
        events = [
            self._ev("failure", 10), self._ev("failure", 20), self._ev("failure", 30),
            # cooldown elapses → half_open; next success closes
            self._ev("success", 332),
        ]
        snap = evaluate_circuit_state(events, now=400.0, config=cfg)
        assert snap.state == "closed"
        assert snap.allow_request_recommendation is True

    def test_open_again_on_failure_in_half_open(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2,
                                   window_seconds=60, open_duration_seconds=300)
        events = [
            self._ev("failure", 10), self._ev("failure", 20), self._ev("failure", 30),
            # after cooldown → half_open; then fail again
            self._ev("failure", 332),
        ]
        snap = evaluate_circuit_state(events, now=400.0, config=cfg)
        assert snap.state == "open"
        assert snap.allow_request_recommendation is False

    def test_manual_reset_clears_state(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2, window_seconds=60)
        events = [
            self._ev("failure", 10), self._ev("failure", 20), self._ev("failure", 30),
            self._ev("manual_reset", 31),
        ]
        snap = evaluate_circuit_state(events, now=50.0, config=cfg)
        assert snap.state == "closed"

    def test_unavailable_sets_unavailable_state(self):
        events = [self._ev("unavailable", 10)]
        snap = evaluate_circuit_state(events, now=20.0)
        assert snap.state == "unavailable"
        assert snap.allow_request_recommendation is False

    def test_timeout_counts_as_failure(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2, window_seconds=60)
        events = [self._ev("timeout", 10), self._ev("timeout", 20), self._ev("timeout", 30)]
        snap = evaluate_circuit_state(events, now=50.0, config=cfg)
        assert snap.state == "open"

    def test_rate_limited_counts_as_failure(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2, window_seconds=60)
        events = [self._ev("rate_limited", 10), self._ev("rate_limited", 20), self._ev("rate_limited", 30)]
        snap = evaluate_circuit_state(events, now=50.0, config=cfg)
        assert snap.state == "open"

    def test_limitations_always_present(self):
        snap = evaluate_circuit_state([], now=100.0)
        assert len(snap.limitations) > 0
        assert "no live operation wrapping" in snap.limitations

    def test_determinism_same_events_same_snapshot(self):
        events = [self._ev("failure", 10), self._ev("failure", 20)]
        s1 = evaluate_circuit_state(events, now=50.0)
        s2 = evaluate_circuit_state(events, now=50.0)
        assert s1.state == s2.state
        assert s1.allow_request_recommendation == s2.allow_request_recommendation

    def test_invalid_state_raises(self):
        from memory_lab.governance.circuit_breaker import _normalize_state
        with pytest.raises(ValueError, match="invalid circuit state"):
            _normalize_state("totally_bogus")

    def test_invalid_event_type_raises(self):
        events = [CircuitBreakerEvent(event_type="explosion", timestamp=10.0)]
        with pytest.raises(ValueError, match="invalid circuit event type"):
            evaluate_circuit_state(events, now=20.0)

    def test_config_validation_rejects_zero_thresholds(self):
        with pytest.raises(ValueError):
            make_provider_neutral_circuit_breaker(
                CircuitBreakerConfig(failure_threshold=0)
            )


# ===========================================================================
# SECTION 7 — Ingestion Policy: Constitution Load + Thresholds
# ===========================================================================

class TestIngestionPolicy:
    """Constitution load is idempotent, thresholds are correctly hierarchical."""

    def test_load_returns_non_empty_dict(self):
        result = policy.load()
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_load_is_idempotent(self):
        r1 = policy.load()
        r2 = policy.load()
        assert r1 is r2  # cached singleton

    def test_default_thresholds_in_expected_range(self):
        assert 0.0 <= policy.min_composite() <= 1.0
        assert 0.0 <= policy.persistent_threshold() <= 1.0
        # persistent_threshold must be > min_composite
        assert policy.persistent_threshold() >= policy.min_composite()

    def test_default_quality_floor_positive(self):
        q = policy.min_quality()
        assert 0.0 < q <= 1.0

    def test_epistemic_type_lower_quality_floor(self):
        """decision/fact/playbook types have a reduced quality floor vs generic."""
        generic_q = policy.min_quality("")
        decision_q = policy.min_quality("decision")
        fact_q = policy.min_quality("fact")
        playbook_q = policy.min_quality("playbook")
        assert decision_q <= generic_q
        assert fact_q <= generic_q
        assert playbook_q <= generic_q

    def test_env_override_min_quality(self, monkeypatch):
        monkeypatch.setenv("CB_SCORE_MIN_QUALITY", "0.55")
        policy._LOADED = False; policy._RULES = {}
        q = policy.min_quality("")
        assert abs(q - 0.55) < 0.001
        policy._LOADED = False; policy._RULES = {}

    def test_env_override_persistent_threshold(self, monkeypatch):
        monkeypatch.setenv("CB_SCORE_PERSISTENT_THRESHOLD", "0.8")
        policy._LOADED = False; policy._RULES = {}
        pt = policy.persistent_threshold()
        assert abs(pt - 0.8) < 0.001
        policy._LOADED = False; policy._RULES = {}

    def test_circuit_config_returns_expected_keys(self):
        cfg = policy.get_circuit_config()
        for key in ("failure_threshold", "window_seconds", "open_duration_seconds",
                    "fallback_composite_score", "fallback_tier"):
            assert key in cfg, f"missing key: {key}"

    def test_get_threshold_missing_path_returns_default(self):
        val = policy.get_threshold("no.such.path", 0.42)
        assert abs(val - 0.42) < 0.001


# ===========================================================================
# SECTION 8 — Cross-cutting: Governance Determinism + No Side-Effects
# ===========================================================================

class TestGovernanceDeterminismAndPurity:
    """Governance functions are pure: no side-effects, identical inputs → identical outputs."""

    def test_route_is_pure_ten_runs(self):
        results = [route(0.72, circuit_open=False, quality_score=0.85) for _ in range(10)]
        tiers = {d.tier for d in results}
        reasons = {d.reason for d in results}
        assert len(tiers) == 1
        assert len(reasons) == 1

    def test_validate_transition_is_pure(self):
        """validate_transition does not mutate state; repeated calls behave identically."""
        for _ in range(5):
            validate_transition("transient", "persistent", trigger_type="system")  # always OK
        for _ in range(5):
            with pytest.raises(GovernanceTransitionError):
                validate_transition("archived", "persistent", trigger_type="system")

    def test_is_upshift_is_pure(self):
        assert all(is_upshift("transient", "persistent") for _ in range(10))
        assert all(not is_upshift("persistent", "transient") for _ in range(10))

    def test_circuit_breaker_is_stateless_across_calls(self):
        """evaluate_circuit_state takes no mutable class state across separate calls."""
        ev = [CircuitBreakerEvent("failure", 10.0)]
        s1 = evaluate_circuit_state(ev, now=20.0)
        s2 = evaluate_circuit_state([], now=20.0)   # clean slate
        assert s1.state != "closed" or s2.state == "closed"
        assert s2.state == "closed"

    def test_no_db_no_network_no_provider_calls(self):
        """All governance functions run with no env vars set — no external calls needed."""
        # If any of these raise connection/import errors, governance has external deps
        route(0.5)
        validate_transition(None, "transient")
        evaluate_circuit_state([], now=100.0)
        policy.load()
