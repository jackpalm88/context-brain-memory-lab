"""Unit tests — ingestion policy YAML binding. No DB, no provider."""
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


def test_policy_loads():
    from memory_lab.governance import ingestion_policy as policy
    rules = policy.load()
    assert isinstance(rules, dict)
    assert "scoring" in rules
    assert "circuit_breaker" in rules


def test_policy_thresholds():
    from memory_lab.governance import ingestion_policy as policy
    q = policy.min_quality()
    c = policy.min_composite()
    p = policy.persistent_threshold()
    assert 0.0 <= q <= 1.0
    assert 0.0 <= c <= 1.0
    assert c <= p <= 1.0


def test_policy_env_override(monkeypatch):
    from memory_lab.governance import ingestion_policy as policy
    monkeypatch.setenv("CB_SCORE_MIN_QUALITY", "0.99")
    result = policy._apply_env_override("CB_SCORE_MIN_QUALITY", 0.4)
    assert result == 0.99
