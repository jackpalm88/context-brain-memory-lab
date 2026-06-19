from memory_lab.wrappers.bounded_tools import build_supplied_text_prompt_package, build_supplied_text_prompt_request_shape
from memory_lab.wrappers.examples import sample_payloads


PAYLOAD = sample_payloads()["build_supplied_text_prompt_request_shape"]


def test_b31_supplied_text_prompt_package_wrapper_is_deterministic():
    first = build_supplied_text_prompt_package(PAYLOAD)
    second = build_supplied_text_prompt_package(PAYLOAD)

    assert first == second
    assert first["tool_name"] == "build_supplied_text_prompt_package"
    assert first["ok"] is True
    assert first["status"] == "completed_with_prompt_package"
    assert first["prompt_package"] is not None
    assert first["llm_request"] is None
    assert first["persistence_record"]["content_id"] == PAYLOAD["content_id"]
    assert first["capability_metadata"]["capability"] == "build_supplied_text_prompt_package"


def test_b31_supplied_text_prompt_request_shape_wrapper_is_deterministic_and_b22_bounded():
    first = build_supplied_text_prompt_request_shape(PAYLOAD)
    second = build_supplied_text_prompt_request_shape(PAYLOAD)

    assert first == second
    assert first["tool_name"] == "build_supplied_text_prompt_request_shape"
    assert first["ok"] is True
    assert first["status"] == "completed_with_prompt_package_and_llm_request_shape"
    request = first["llm_request"]
    assert request is not None
    assert request["live_mode_enabled"] is False
    assert request["backend_name"] == "none"
    assert request["allow_fake_backend"] is False
    assert "not_llm_execution" in first["non_claims"]
    assert "no_llm_execution" in first["limitations"]


def test_b31_missing_required_fields_return_structured_degraded_error():
    result = build_supplied_text_prompt_request_shape({"workspace_id": "", "text": ""})

    assert result["ok"] is False
    assert result["status"] == "missing_required_fields"
    assert result["capability_metadata"]["degraded_reason"] == "missing_required_fields"
    fields = {error["field"] for error in result["errors"]}
    assert fields == {"workspace_id", "content_id", "text"}
