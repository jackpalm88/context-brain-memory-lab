"""T1-T5: FailureCode string serialization and uniqueness."""
import json
from memory_lab.providers.failure import FailureCode


def test_not_configured_value():
    assert FailureCode.NOT_CONFIGURED == "not_configured"


def test_schema_validation_failed_value():
    assert FailureCode.SCHEMA_VALIDATION_FAILED == "schema_validation_failed"


def test_all_codes_unique():
    values = [c.value for c in FailureCode]
    assert len(values) == len(set(values))


def test_json_serializable():
    data = {"reason": FailureCode.TIMEOUT}
    result = json.dumps(data)
    assert "timeout" in result


def test_compare_to_bare_string():
    assert FailureCode.CIRCUIT_OPEN == "circuit_open"
    assert "rate_limited" == FailureCode.RATE_LIMITED
