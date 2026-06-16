"""B21 source-neutral circuit state evaluation over supplied events.

Consumes only caller-supplied events, timestamps, and config. Returns status
recommendations and never invokes a live operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

B21_CIRCUIT_BREAKER_MODE = "b21_provider_neutral_circuit_breaker_v1"
VALID_STATES = ("closed", "degraded", "open", "half_open", "unavailable")
VALID_EVENT_TYPES = ("success", "failure", "timeout", "rate_limited", "unavailable", "manual_reset")
FAILURE_EVENTS = ("failure", "timeout", "rate_limited")
DEFAULT_LIMITATIONS = ("provider-neutral supplied-event state evaluation only", "no live operation wrapping", "no service call", "no durable circuit state", "no live cost or credit check")


@dataclass(frozen=True)
class CircuitBreakerEvent:
    event_type: str
    timestamp: float
    reason: str = ""


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int = 3
    degraded_threshold: int = 2
    unavailable_threshold: int = 1
    window_seconds: float = 60.0
    open_duration_seconds: float = 300.0
    half_open_successes_to_close: int = 1


@dataclass(frozen=True)
class CircuitBreakerStateSnapshot:
    state: str
    allow_request_recommendation: bool
    retry_after_seconds: float | None
    cooldown_remaining_seconds: float
    failure_reason_summary: str
    rationale: str
    limitations: tuple[str, ...]
    mode: str = B21_CIRCUIT_BREAKER_MODE


class ProviderNeutralCircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self.config = config or CircuitBreakerConfig()
        self._validate_config()

    def evaluate_circuit_state(self, events: Sequence[CircuitBreakerEvent], now: float, initial_state: str = "closed") -> CircuitBreakerStateSnapshot:
        state = _normalize_state(initial_state)
        ordered = sorted(events, key=lambda event: event.timestamp)
        opened_at: float | None = None
        half_open_started_at: float | None = None
        recent_failures: list[CircuitBreakerEvent] = []
        reasons: list[str] = []
        for event in ordered:
            if event.timestamp > now:
                continue
            event_type = _normalize_event_type(event.event_type)
            if event.reason:
                reasons.append(event.reason)
            recent_failures = [item for item in recent_failures if event.timestamp - item.timestamp <= self.config.window_seconds]
            if event_type == "manual_reset":
                state = "closed"; opened_at = None; half_open_started_at = None; recent_failures = []
                continue
            if state == "open" and opened_at is not None and event.timestamp - opened_at >= self.config.open_duration_seconds:
                state = "half_open"; half_open_started_at = event.timestamp
            if event_type == "unavailable":
                state = "unavailable"; opened_at = event.timestamp
                continue
            if event_type in FAILURE_EVENTS:
                recent_failures.append(event)
                if state == "half_open":
                    state = "open"; opened_at = event.timestamp
                    continue
                if len(recent_failures) >= self.config.failure_threshold:
                    state = "open"; opened_at = event.timestamp
                    continue
                if len(recent_failures) >= self.config.degraded_threshold and state == "closed":
                    state = "degraded"
                    continue
            if event_type == "success":
                if state == "half_open":
                    successes = _successes_since(ordered, half_open_started_at or event.timestamp, event.timestamp)
                    if successes >= self.config.half_open_successes_to_close:
                        state = "closed"; opened_at = None; recent_failures = []
                elif state == "degraded" and not recent_failures:
                    state = "closed"
        if state in {"open", "unavailable"} and opened_at is not None and max(0.0, now - opened_at) >= self.config.open_duration_seconds:
            state = "half_open"
        cooldown = 0.0; retry_after: float | None = None; allow = state in {"closed", "degraded", "half_open"}
        if state in {"open", "unavailable"} and opened_at is not None:
            cooldown = max(0.0, self.config.open_duration_seconds - max(0.0, now - opened_at))
            retry_after = cooldown; allow = False
        return CircuitBreakerStateSnapshot(
            state=state,
            allow_request_recommendation=allow,
            retry_after_seconds=retry_after,
            cooldown_remaining_seconds=round(cooldown, 6),
            failure_reason_summary="; ".join(_dedupe(reasons)) if reasons else "none supplied",
            rationale="deterministic B21 circuit state evaluated from supplied events/config/timestamps",
            limitations=DEFAULT_LIMITATIONS,
        )

    def _validate_config(self) -> None:
        if self.config.failure_threshold < 1 or self.config.degraded_threshold < 1:
            raise ValueError("thresholds must be positive")
        if self.config.window_seconds <= 0 or self.config.open_duration_seconds <= 0:
            raise ValueError("durations must be positive")


def make_provider_neutral_circuit_breaker(config: CircuitBreakerConfig | None = None) -> ProviderNeutralCircuitBreaker:
    return ProviderNeutralCircuitBreaker(config)


def evaluate_circuit_state(events: Sequence[CircuitBreakerEvent], now: float, config: CircuitBreakerConfig | None = None, initial_state: str = "closed") -> CircuitBreakerStateSnapshot:
    return make_provider_neutral_circuit_breaker(config).evaluate_circuit_state(events, now=now, initial_state=initial_state)


def _normalize_state(state: str) -> str:
    value = (state or "closed").lower()
    if value not in VALID_STATES:
        raise ValueError(f"invalid circuit state: {state}")
    return value


def _normalize_event_type(event_type: str) -> str:
    value = (event_type or "").lower()
    if value not in VALID_EVENT_TYPES:
        raise ValueError(f"invalid circuit event type: {event_type}")
    return value


def _successes_since(events: Sequence[CircuitBreakerEvent], start: float, end: float) -> int:
    return sum(1 for event in events if start <= event.timestamp <= end and _normalize_event_type(event.event_type) == "success")


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set(); out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value); out.append(value)
    return tuple(out)
