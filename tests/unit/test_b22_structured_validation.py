import json

from memory_lab.reasoning.structured_validation import (
    StructuredValidationRule,
    validate_structured_response,
)


def valid_payload():
    return {
        "status": "ok",
        "answer": "Evidence-backed answer.",
        "confidence": 0.8,
        "claims": [{"claim": "Claim one", "evidence_ids": [1]}],
    }


def test_valid_structured_json_response_passes():
    result = validate_structured_response(json.dumps(valid_payload()), evidence_count=1)
    assert result.valid is True
    assert result.status == "ok"
    assert "complete" in result.flags
    assert result.quality_score == 1.0
    assert "no_semantic_truth_validation" in result.non_claims


def test_valid_dict_response_passes():
    result = validate_structured_response(valid_payload(), evidence_count=1)
    assert result.valid is True
    assert result.sanitized["status"] == "ok"


def test_malformed_json_fails_with_structural_flag():
    result = validate_structured_response("{not-json", evidence_count=1)
    assert result.valid is False
    assert "malformed" in result.flags
    assert "malformed_json" in result.errors
    assert result.quality_score == 0.0


def test_missing_required_field_fails():
    result = validate_structured_response({"status": "ok", "confidence": 0.7}, evidence_count=1)
    assert result.valid is False
    assert "missing_required_field" in result.flags
    assert "missing_required_field:answer" in result.errors


def test_wrong_type_and_confidence_bounds_fail():
    result = validate_structured_response({"status": "ok", "answer": 7, "confidence": 2.0}, evidence_count=1)
    assert result.valid is False
    assert "wrong_type" in result.flags
    assert "confidence_out_of_bounds" in result.flags


def test_allowed_status_validation_and_degraded_shape():
    degraded = validate_structured_response({"status": "degraded", "answer": "Provider unavailable.", "confidence": 0.0}, evidence_count=0)
    assert degraded.valid is True
    assert degraded.status == "degraded"
    unsupported = validate_structured_response({"status": "done", "answer": "x", "confidence": 0.5}, evidence_count=0)
    assert unsupported.valid is False
    assert "unsupported_status" in unsupported.flags


def test_claims_require_evidence_ids_positive_and_in_bounds():
    result = validate_structured_response(
        {"status": "ok", "answer": "x", "confidence": 0.7, "claims": [{"claim": "c", "evidence_ids": [0, 3]}]},
        evidence_count=2,
    )
    assert result.valid is False
    assert "missing_evidence" in result.flags
    assert "evidence_id_invalid:0" in result.errors
    assert "evidence_id_out_of_bounds:0" in result.errors


def test_unsupported_claim_shape_is_flagged():
    result = validate_structured_response({"status": "ok", "answer": "x", "confidence": 0.7, "claims": "nope"}, evidence_count=1)
    assert result.valid is False
    assert "unsupported_claims" in result.flags


def test_substantive_answer_without_claims_is_warning_not_semantic_judgment():
    result = validate_structured_response(
        {"status": "ok", "answer": "This is a substantive answer with enough length to require structural claim evidence.", "confidence": 0.6},
        evidence_count=0,
    )
    assert result.valid is True
    assert "substantive_answer_without_claims" in result.flags
    assert "substantive_answer_without_claims" in result.warnings
    assert "no_provider_backed_judging" in result.non_claims


def test_custom_rule_is_structural_only_and_deterministic():
    rule = StructuredValidationRule("tier", True, str, allowed_values=("discard", "save"))
    one = validate_structured_response({"tier": "save"}, rules=(rule,))
    two = validate_structured_response({"tier": "save"}, rules=(rule,))
    assert one == two
    assert one.valid is True
