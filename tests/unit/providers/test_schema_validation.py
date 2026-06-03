"""T1-T6: Schema validation and degraded response properties."""
from memory_lab.providers.fake import FakeLLMBackend
from memory_lab.providers.failure import FailureCode
from memory_lab.providers.llm_backend import LLMRequest, LLMResponse


def test_invalid_json_failure_reason():
    b = FakeLLMBackend(invalid_json_text="bad{{")
    r = b.complete_json(LLMRequest(prompt="x"))
    assert r.failure_reason == FailureCode.INVALID_JSON


def test_schema_mismatch_failure_reason():
    b = FakeLLMBackend(schema_mismatch_json={"x": 1})
    r = b.complete_json(LLMRequest(prompt="x"))
    assert r.failure_reason == FailureCode.SCHEMA_VALIDATION_FAILED


def test_valid_preset_json_is_ok():
    b = FakeLLMBackend(preset_json={"q": 0.5})
    r = b.complete_json(LLMRequest(prompt="x"))
    assert r.is_ok is True


def test_circuit_open_failure():
    b = FakeLLMBackend(preset_failure=FailureCode.CIRCUIT_OPEN)
    r = b.complete_json(LLMRequest(prompt="x"))
    assert r.degraded is True
    assert r.failure_reason == FailureCode.CIRCUIT_OPEN


def test_degraded_response_is_not_ok():
    r = LLMResponse(degraded=True)
    assert r.is_ok is False


def test_ok_response_is_ok():
    r = LLMResponse(degraded=False, text="something")
    assert r.is_ok is True
