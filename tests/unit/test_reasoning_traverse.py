import pytest

from memory_lab.context_packs.builder import build_context_pack
from memory_lab.context_packs.models import ContextPackBuildRequest
from memory_lab.providers.fake import FakeLLMBackend
from memory_lab.providers.failure import FailureCode
from memory_lab.reasoning.models import ReasoningRequest
from memory_lab.reasoning.service import traverse_context_pack

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000911"
FORBIDDEN = {"answer", "verdict", "truth_decision", "resolution"}


def _ev(content_id, *, rank=1, text="b13 evidence"):
    return {
        "evidence_id": f"ev_{content_id}",
        "rank": rank,
        "content_id": content_id,
        "snippet": text,
        "score": 0.9,
        "score_kind": "chunk_text_match",
        "memory_type": "decision",
    }


def _pack():
    conflict = {
        "candidate_id": "cc_b13",
        "conflict_type": "explicit_counterfinding",
        "scope": "b13",
        "status": "unresolved",
        "severity": "high",
        "confidence": 0.9,
        "evidence": [_ev("counter") | {"role": "counterfinding"}],
        "detection_rule": "explicit_marker",
    }
    return build_context_pack(
        workspace_id=WS,
        request=ContextPackBuildRequest(query="b13 reasoning", scope="b13"),
        supporting_evidence=[_ev("b", rank=2), _ev("a", rank=1)],
        current_state_rows=[_ev("current", rank=3) | {"is_current": True, "current_state_scope": "b13"}],
        conflict_candidates=[conflict],
    )


def test_deterministic_traverse_without_provider():
    req = ReasoningRequest(query="b13 reasoning")
    first = traverse_context_pack(context_pack=_pack(), request=req)
    second = traverse_context_pack(context_pack=_pack(), request=req)
    assert first.model_dump() == second.model_dump()
    assert first.mode == "deterministic_read_only"
    assert first.provider_metadata.attempted is False
    assert first.provider_metadata.provider == "none"
    assert first.evidence_refs
    assert first.traversal_steps


def test_max_hops_default_and_hard_cap_enforced():
    assert ReasoningRequest(query="x").max_hops == 2
    with pytest.raises(Exception):
        ReasoningRequest(query="x", max_hops=4)
    body = traverse_context_pack(context_pack=_pack(), request=ReasoningRequest(query="x", max_hops=3)).model_dump()
    assert max(step["hop"] for step in body["traversal_steps"]) <= 3


def test_conflict_warnings_surfaced_and_no_resolution_behavior():
    body = traverse_context_pack(context_pack=_pack(), request=ReasoningRequest(query="x")).model_dump()
    assert body["conflict_warnings"]
    assert any("not automatically resolved" in step["rationale"] or "without choosing" in step["rationale"] for step in body["traversal_steps"])
    assert FORBIDDEN.isdisjoint(body.keys())


def test_provider_disabled_by_default_and_noop_degrades_when_opted_in():
    disabled = traverse_context_pack(context_pack=_pack(), request=ReasoningRequest(query="x"))
    assert disabled.provider_metadata.attempted is False
    opted = traverse_context_pack(context_pack=_pack(), request=ReasoningRequest(query="x", enable_provider_synthesis=True))
    assert opted.provider_metadata.attempted is True
    assert opted.provider_metadata.provider == "none"
    assert opted.provider_metadata.degraded is True
    assert opted.degraded_reason == "not_configured"
    assert opted.evidence_refs


def test_provider_opt_in_with_fake_backend_and_failure_retains_evidence():
    ok = traverse_context_pack(context_pack=_pack(), request=ReasoningRequest(query="x", enable_provider_synthesis=True), backend=FakeLLMBackend())
    assert ok.provider_metadata.attempted is True
    assert ok.provider_metadata.provider == "fake"
    assert ok.provider_metadata.degraded is False
    fail = traverse_context_pack(
        context_pack=_pack(),
        request=ReasoningRequest(query="x", enable_provider_synthesis=True),
        backend=FakeLLMBackend(preset_failure=FailureCode.TIMEOUT),
    )
    assert fail.provider_metadata.degraded is True
    assert fail.degraded_reason == "timeout"
    assert fail.evidence_refs


def test_forbidden_response_fields_absent():
    body = traverse_context_pack(context_pack=_pack(), request=ReasoningRequest(query="x")).model_dump()
    assert FORBIDDEN.isdisjoint(body.keys())
