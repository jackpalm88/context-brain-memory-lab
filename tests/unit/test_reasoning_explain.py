import pytest

from memory_lab.context_packs.builder import build_context_pack
from memory_lab.context_packs.models import ContextPackBuildRequest
from memory_lab.reasoning.models import ReasoningRequest
from memory_lab.reasoning.service import explain_context_pack

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000912"
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
        "candidate_id": "cc_b13_explain",
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
        request=ContextPackBuildRequest(query="b13 explain", scope="b13"),
        supporting_evidence=[_ev("support")],
        current_state_rows=[
            _ev("current", rank=2) | {"is_current": True, "current_state_scope": "b13"},
            _ev("stale", rank=3) | {"is_current": False, "current_state_scope": "b13", "cs_supersedes_content_id": "current"},
        ],
        conflict_candidates=[conflict],
    )


def test_explain_from_context_pack_without_provider():
    body = explain_context_pack(context_pack=_pack(), request=ReasoningRequest(query="b13 explain")).model_dump()
    assert body["mode"] == "deterministic_read_only"
    assert body["provider_metadata"]["attempted"] is False
    assert body["explanation"]["summary"].startswith("Reasoning was computed")
    assert body["explanation"]["evidence_inclusion"]["supporting_evidence_count"] == 1
    assert body["evidence_refs"]


def test_explain_current_stale_conflict_limitations_and_non_claims():
    body = explain_context_pack(context_pack=_pack(), request=ReasoningRequest(query="b13 explain")).model_dump()
    assert body["explanation"]["current_and_stale_signals"]
    assert body["explanation"]["conflict_and_counterfinding_warnings"]
    assert body["conflict_warnings"]
    assert any("No truth arbitration" in item for item in body["limitations"])
    assert "no_automatic_conflict_resolution" in body["non_claims"]
    assert "no_private_ask_v2_port" in body["non_claims"]


def test_deterministic_explain_ordering():
    req = ReasoningRequest(query="b13 explain")
    a = explain_context_pack(context_pack=_pack(), request=req).model_dump()
    b = explain_context_pack(context_pack=_pack(), request=req).model_dump()
    assert a == b
    ranks = [ref.get("rank") or 999999 for ref in a["evidence_refs"]]
    assert ranks == sorted(ranks)


def test_forbidden_answer_verdict_truth_decision_resolution_absent():
    body = explain_context_pack(context_pack=_pack(), request=ReasoningRequest(query="b13 explain")).model_dump()
    assert FORBIDDEN.isdisjoint(body.keys())
