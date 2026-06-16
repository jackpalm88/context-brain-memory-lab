from memory_lab.governance.circuit_breaker import CircuitBreakerConfig, CircuitBreakerEvent, evaluate_circuit_state


def ev(event_type, timestamp, reason=""):
    return CircuitBreakerEvent(event_type=event_type, timestamp=timestamp, reason=reason)


def test_closed_to_degraded():
    config = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2, window_seconds=60)
    result = evaluate_circuit_state([ev("failure", 1), ev("timeout", 2)], now=3, config=config)
    assert result.state == "degraded"
    assert result.allow_request_recommendation is True


def test_closed_or_degraded_to_open():
    config = CircuitBreakerConfig(failure_threshold=3, degraded_threshold=2, window_seconds=60)
    result = evaluate_circuit_state([ev("failure", 1), ev("timeout", 2), ev("rate_limited", 3)], now=4, config=config)
    assert result.state == "open"
    assert result.allow_request_recommendation is False
    assert result.retry_after_seconds is not None


def test_open_to_half_open_after_cooldown():
    config = CircuitBreakerConfig(failure_threshold=1, open_duration_seconds=10)
    result = evaluate_circuit_state([ev("failure", 0)], now=11, config=config)
    assert result.state == "half_open"
    assert result.allow_request_recommendation is True


def test_half_open_to_closed_on_supplied_success():
    config = CircuitBreakerConfig(failure_threshold=1, open_duration_seconds=10)
    result = evaluate_circuit_state([ev("failure", 0), ev("success", 11)], now=12, config=config)
    assert result.state == "closed"
    assert result.cooldown_remaining_seconds == 0.0


def test_half_open_to_open_on_supplied_failure():
    config = CircuitBreakerConfig(failure_threshold=1, open_duration_seconds=10)
    result = evaluate_circuit_state([ev("failure", 0), ev("failure", 11, "trial failed")], now=12, config=config)
    assert result.state == "open"
    assert result.allow_request_recommendation is False
    assert "trial failed" in result.failure_reason_summary


def test_unavailable_behavior_from_supplied_events():
    config = CircuitBreakerConfig(open_duration_seconds=30)
    result = evaluate_circuit_state([ev("unavailable", 5, "maintenance")], now=10, config=config)
    assert result.state == "unavailable"
    assert result.allow_request_recommendation is False
    assert result.cooldown_remaining_seconds == 25


def test_cooldown_uses_supplied_timestamps_and_config_only():
    config = CircuitBreakerConfig(failure_threshold=1, open_duration_seconds=100)
    result = evaluate_circuit_state([ev("failure", 40)], now=65, config=config)
    assert result.state == "open"
    assert result.cooldown_remaining_seconds == 75
    assert any("supplied-event" in item for item in result.limitations)
    assert any("no live operation" in item for item in result.limitations)
