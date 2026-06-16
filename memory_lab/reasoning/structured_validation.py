"""Public-safe structured response validation for B22.

The validator only checks caller-supplied JSON/dict/text structure. It does
not judge semantic truth, call providers, inspect private stores, or mutate
state. Scores are deterministic structural completeness signals only.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

ALLOWED_STATUSES: tuple[str, ...] = ("ok", "no_context", "clarify", "degraded", "error")
STRUCTURAL_NON_CLAIMS: tuple[str, ...] = (
    "no_semantic_truth_validation",
    "no_provider_backed_judging",
    "no_private_prompt_or_policy_copy",
    "structural_quality_score_only",
)

@dataclass(frozen=True)
class StructuredValidationRule:
    field: str
    required: bool = True
    expected_type: type | tuple[type, ...] | None = None
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: Sequence[Any] | None = None

@dataclass(frozen=True)
class StructuredResponseQuality:
    complete: bool
    malformed: bool
    missing_evidence: bool
    unsupported_claims: bool
    confidence_in_bounds: bool
    has_required_fields: bool
    score: float

@dataclass(frozen=True)
class StructuredValidationResult:
    valid: bool
    status: str
    flags: tuple[str, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    sanitized: Mapping[str, Any]
    quality_score: float
    mode: str = "structural_only"
    non_claims: tuple[str, ...] = STRUCTURAL_NON_CLAIMS
    quality: StructuredResponseQuality | None = None

class StructuredValidator:
    """Deterministic structural validator for supplied response payloads."""
    def validate(self, response: str | Mapping[str, Any], evidence_count: int = 0, rules: Sequence[StructuredValidationRule] | None = None) -> StructuredValidationResult:
        parsed, malformed_error = _parse_response(response)
        flags: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []
        if malformed_error:
            flags.append("malformed")
            errors.append(malformed_error)
            return _result(False, "error", flags, errors, warnings, {}, 0.0)
        assert parsed is not None
        sanitized = dict(parsed)
        _apply_rules(sanitized, tuple(rules or _default_rules()), flags, errors)
        status = sanitized.get("status")
        if isinstance(status, str) and status not in ALLOWED_STATUSES:
            flags.append("unsupported_status")
            errors.append("status_not_allowed")
        confidence = sanitized.get("confidence")
        confidence_in_bounds = isinstance(confidence, (int, float)) and 0.0 <= float(confidence) <= 1.0
        if "confidence" in sanitized and not confidence_in_bounds:
            flags.append("confidence_out_of_bounds")
            errors.append("confidence_out_of_bounds")
        _validate_claims(sanitized, evidence_count, flags, errors, warnings)
        answer = sanitized.get("answer")
        claims = sanitized.get("claims")
        if isinstance(answer, str) and len(answer.strip()) >= 40 and not claims and status == "ok":
            flags.append("substantive_answer_without_claims")
            warnings.append("substantive_answer_without_claims")
        required_ok = not any(f == "missing_required_field" for f in flags)
        malformed = "malformed" in flags
        unsupported_claims = "unsupported_claims" in flags
        missing_evidence = "missing_evidence" in flags
        valid = not errors and required_ok and not malformed and not unsupported_claims and not missing_evidence
        if valid:
            flags.append("complete")
        score = _quality_score(flags, errors, warnings, required_ok, confidence_in_bounds)
        quality = StructuredResponseQuality(valid, malformed, missing_evidence, unsupported_claims, confidence_in_bounds, required_ok, score)
        return StructuredValidationResult(valid, str(status) if isinstance(status, str) else "error", tuple(_dedupe(flags)), tuple(_dedupe(errors)), tuple(_dedupe(warnings)), sanitized, score, quality=quality)

def make_structured_validator() -> StructuredValidator:
    return StructuredValidator()

def validate_structured_response(response: str | Mapping[str, Any], evidence_count: int = 0, rules: Sequence[StructuredValidationRule] | None = None) -> StructuredValidationResult:
    return make_structured_validator().validate(response, evidence_count, rules)

def _default_rules() -> tuple[StructuredValidationRule, ...]:
    return (
        StructuredValidationRule("status", True, str, allowed_values=ALLOWED_STATUSES),
        StructuredValidationRule("answer", True, str),
        StructuredValidationRule("confidence", True, (int, float), 0.0, 1.0),
    )

def _parse_response(response: str | Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(response, Mapping):
        return dict(response), None
    if not isinstance(response, str) or not response.strip():
        return None, "malformed_response_text"
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None, "malformed_json"
    if not isinstance(parsed, dict):
        return None, "response_not_object"
    return parsed, None

def _apply_rules(sanitized: Mapping[str, Any], rules: Sequence[StructuredValidationRule], flags: list[str], errors: list[str]) -> None:
    for rule in rules:
        if rule.field not in sanitized:
            if rule.required:
                flags.append("missing_required_field")
                errors.append(f"missing_required_field:{rule.field}")
            continue
        value = sanitized[rule.field]
        if rule.expected_type is not None and not isinstance(value, rule.expected_type):
            flags.append("wrong_type")
            errors.append(f"wrong_type:{rule.field}")
            continue
        if rule.allowed_values is not None and value not in rule.allowed_values:
            flags.append("unsupported_value")
            errors.append(f"unsupported_value:{rule.field}")
        if isinstance(value, (int, float)):
            if rule.min_value is not None and value < rule.min_value:
                flags.append("value_below_min")
                errors.append(f"value_below_min:{rule.field}")
            if rule.max_value is not None and value > rule.max_value:
                flags.append("value_above_max")
                errors.append(f"value_above_max:{rule.field}")

def _validate_claims(sanitized: Mapping[str, Any], evidence_count: int, flags: list[str], errors: list[str], warnings: list[str]) -> None:
    claims = sanitized.get("claims")
    if claims is None:
        return
    if not isinstance(claims, list):
        flags.append("unsupported_claims")
        errors.append("claims_not_list")
        return
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            flags.append("unsupported_claims")
            errors.append(f"claim_not_object:{index}")
            continue
        text = claim.get("claim")
        evidence_ids = claim.get("evidence_ids")
        if not isinstance(text, str) or not text.strip():
            flags.append("unsupported_claims")
            errors.append(f"claim_text_missing:{index}")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            flags.append("missing_evidence")
            errors.append(f"missing_evidence:{index}")
            continue
        for evidence_id in evidence_ids:
            if not isinstance(evidence_id, int) or evidence_id <= 0:
                flags.append("missing_evidence")
                errors.append(f"evidence_id_invalid:{index}")
            elif evidence_count and evidence_id > evidence_count:
                flags.append("missing_evidence")
                errors.append(f"evidence_id_out_of_bounds:{index}")
    if sanitized.get("status") in {"no_context", "clarify", "degraded", "error"} and claims:
        warnings.append("claims_present_for_non_ok_status")

def _quality_score(flags: Sequence[str], errors: Sequence[str], warnings: Sequence[str], required_ok: bool, confidence_in_bounds: bool) -> float:
    score = 1.0
    if not required_ok:
        score -= 0.35
    if not confidence_in_bounds:
        score -= 0.15
    score -= 0.15 * len(set(errors))
    score -= 0.05 * len(set(warnings))
    if "malformed" in flags:
        score = 0.0
    return max(0.0, min(1.0, round(score, 3)))

def _result(valid: bool, status: str, flags: Sequence[str], errors: Sequence[str], warnings: Sequence[str], sanitized: Mapping[str, Any], score: float) -> StructuredValidationResult:
    quality = StructuredResponseQuality(valid, "malformed" in flags, "missing_evidence" in flags, "unsupported_claims" in flags, False, False, score)
    return StructuredValidationResult(valid, status, tuple(_dedupe(flags)), tuple(_dedupe(errors)), tuple(_dedupe(warnings)), sanitized, score, quality=quality)

def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
