import pytest

from memory_lab.context_packs.builder import build_context_pack
from memory_lab.context_packs.models import ContextPackBuildRequest
from memory_lab.providers.fake import FakeLLMBackend
from memory_lab.providers.failure import FailureCode
from memory_lab.providers.llm_backend import LLMResponse
from memory_lab.reasoning.answer import answer_context_pack
from memory_lab.reasoning.models import ReasoningRequest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000914"
FORBIDDEN_FIELD_NAMES = {"answer", "verdict", "truth_decision", "resolution", "winner", "canonical_truth"}
REQUIRED = {
    "reasoning_id",
    "mode",
    "answer_candidate",
    "evidence_refs",
    "context_pack_ref",
    "traversal_steps",
    "conflict_warnings",
    "limitations",
    "provider_metadata",
    "degraded_reason",
    "non_claims",
}


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _assert_no_forbidden_fields(body):
    keys = set(_walk_keys(body))
    assert FORBIDDEN_FIELD_NAMES.isdisjoint(keys)
    assert "answer" not in body
    assert "answer_candidate" in body


def _ev(content_id, *, rank=1, text="b14 answer evidence", role=None):
    row = {
        "evidence_id": f"ev_{content_id}",
        "rank": rank,
        "content_id": content_id,
        "snippet": text,
        "score": 0.9,
        "score_kind": "chunk_text_match",
        "memory_type": "decision",
    }
    if role:
        row["role"] = role
    return row


def _pack(*, empty=False):
    conflict = {
        "candidate_id": "cc_b14_answer",
        "conflict_type": "explicit_counterfinding",
        "scope": "b14-answer",
        "status": "unresolved",
        "severity": "high",
        "confidence": 0.9,
        "evidence": [_ev("counter", text="counterfinding evidence is preserved", role="counterfinding")],
        "detection_rule": "explicit_marker",
    }
    return build_context_pack(
        workspace_id=WS,
        request=ContextPackBuildRequest(query="b14 answer", scope="b14-answer"),
        supporting_evidence=[] if empty else [_ev("support", text="B14 endpoint produces answer_candidate from public evidence", rank=1)],
        current_state_rows=[] if empty else [_ev("current", text="current signal for B14 answer", rank=2) | {"is_current": True, "current_state_scope": "b14-answer"}],
        conflict_candidates=[] if empty else [conflict],
    )


def test_deterministic_answer_without_provider_required_shape_and_evidence():
    req = ReasoningRequest(query="b14 answer")
    first = answer_context_pack(context_pack=_pack(), request=req).model_dump()
    second = answer_context_pack(context_pack=_pack(), request=req).model_dump()
    assert first == second
    assert set(first) == REQUIRED
    assert first["mode"] == "deterministic"
    assert first["provider_metadata"]["attempted"] is False
    assert first["provider_metadata"]["provider"] == "none"
    assert first["answer_candidate"]
    assert first["evidence_refs"]
    assert first["traversal_steps"]
    _assert_no_forbidden_fields(first)


def test_answer_surfaces_conflicts_limitations_and_non_claims():
    body = answer_context_pack(context_pack=_pack(), request=ReasoningRequest(query="b14 answer")).model_dump()
    assert body["conflict_warnings"]
    assert any("answer candidate" in item.lower() for item in body["limitations"])
    assert "no_top_level_answer_field" in body["non_claims"]
    assert "no_private_ask_v2_port" in body["non_claims"]
    _assert_no_forbidden_fields(body)


def test_provider_disabled_by_default_and_noop_degrades_only_when_opted_in():
    disabled = answer_context_pack(context_pack=_pack(), request=ReasoningRequest(query="x"))
    assert disabled.mode == "deterministic"
    assert disabled.provider_metadata.attempted is False

    opted = answer_context_pack(context_pack=_pack(), request=ReasoningRequest(query="x", enable_provider_synthesis=True))
    assert opted.mode == "degraded"
    assert opted.provider_metadata.attempted is True
    assert opted.provider_metadata.provider == "none"
    assert opted.provider_metadata.degraded is True
    assert opted.degraded_reason == "not_configured"
    assert opted.evidence_refs


def test_provider_opt_in_fake_backend_and_failure_retains_evidence():
    ok = answer_context_pack(
        context_pack=_pack(),
        request=ReasoningRequest(query="x", enable_provider_synthesis=True),
        backend=FakeLLMBackend(),
    )
    assert ok.mode == "provider_backed"
    assert ok.provider_metadata.attempted is True
    assert ok.provider_metadata.provider == "fake"
    assert ok.provider_metadata.degraded is False
    assert ok.answer_candidate == "fake_summary"
    assert ok.evidence_refs

    fail = answer_context_pack(
        context_pack=_pack(),
        request=ReasoningRequest(query="x", enable_provider_synthesis=True),
        backend=FakeLLMBackend(preset_failure=FailureCode.TIMEOUT),
    )
    assert fail.mode == "degraded"
    assert fail.provider_metadata.degraded is True
    assert fail.degraded_reason == "timeout"
    assert fail.evidence_refs
    _assert_no_forbidden_fields(fail.model_dump())


def test_insufficient_evidence_is_degraded_without_provider_call():
    body = answer_context_pack(context_pack=_pack(empty=True), request=ReasoningRequest(query="empty evidence")).model_dump()
    assert body["mode"] == "degraded"
    assert body["degraded_reason"] == "insufficient_evidence"
    assert body["provider_metadata"]["attempted"] is False
    assert body["evidence_refs"] == []
    _assert_no_forbidden_fields(body)


def test_answer_candidate_cites_only_existing_evidence_ids():
    response = answer_context_pack(context_pack=_pack(), request=ReasoningRequest(query="b14 answer"))
    evidence_ids = {str(ref["evidence_id"]) for ref in response.evidence_refs}

    bracketed = {part.split("]", 1)[0][1:] for part in response.answer_candidate.split() if part.startswith("[ev_") and "]" in part}

    assert bracketed
    assert bracketed <= evidence_ids
    assert "[1]" not in response.answer_candidate


def test_global_provider_disabled_returns_deterministic_candidate_without_call():
    backend = FakeLLMBackend()
    body = answer_context_pack(
        context_pack=_pack(),
        request=ReasoningRequest(query="x", enable_provider_synthesis=True),
        backend=backend,
        provider_synthesis_enabled=False,
    )
    assert backend.summarize_calls == 0
    assert body.mode == "degraded"
    assert body.provider_metadata.attempted is False
    assert body.provider_metadata.failure_reason == "provider_disabled"
    assert body.degraded_reason == "provider_disabled"
    assert "fake_summary" not in body.answer_candidate
    assert body.evidence_refs


def test_provider_output_with_invented_citation_is_rejected_to_fallback():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Provider cites ev_missing", provider="fake"))
    body = answer_context_pack(
        context_pack=_pack(),
        request=ReasoningRequest(query="x", enable_provider_synthesis=True),
        backend=backend,
    )
    assert backend.summarize_calls == 1
    assert body.mode == "degraded"
    assert body.provider_metadata.failure_reason == "provider_output_rejected"
    assert body.degraded_reason == "provider_output_rejected"
    assert "ev_missing" not in body.answer_candidate
    assert "[ev_support]" in body.answer_candidate


def test_provider_output_with_forbidden_term_is_rejected_to_fallback():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="The verdict is supported by ev_support", provider="fake"))
    body = answer_context_pack(
        context_pack=_pack(),
        request=ReasoningRequest(query="x", enable_provider_synthesis=True),
        backend=backend,
    )
    assert backend.summarize_calls == 1
    assert body.mode == "degraded"
    assert body.provider_metadata.failure_reason == "provider_output_rejected"
    assert body.degraded_reason == "provider_output_rejected"
    assert "verdict" not in body.answer_candidate.lower()
    _assert_no_forbidden_fields(body.model_dump())


def test_provider_prompt_includes_candidate_evidence_ids_and_constraints():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Provider wording cites ev_support", provider="fake"))
    body = answer_context_pack(
        context_pack=_pack(),
        request=ReasoningRequest(query="x", enable_provider_synthesis=True),
        backend=backend,
    )
    assert body.mode == "provider_backed"
    assert backend.last_request is not None
    prompt = backend.last_request.prompt
    assert "Deterministic candidate" in prompt
    assert "ev_support" in prompt
    assert "Do not decide truth" in prompt
    assert "Do not choose a winner" in prompt
    assert "Do not resolve conflicts" in prompt
