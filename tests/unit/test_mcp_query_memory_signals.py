from __future__ import annotations

import pytest

from memory_lab.mcp.tools import _enrich_query_memory_result

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000937"

# §5.2 — the six signals an MCP query_memory caller must always be able to obtain.
SIX_SIGNAL_KEYS = {
    "answer",
    "mode",
    "status",
    "confidence",
    "confidence_explanation",
    "has_citations",
    "citations",
    "no_context",
    "failure_reason",
    "fallback",
}


def _ok_response(**over):
    base = {
        "answer": "Based only on retrieved workspace evidence: [ev_1] alpha",
        "intent": "factual",
        "confidence": 0.7,
        "confidence_explanation": "deterministic confidence",
        "citations": [{"evidence_id": "ev_1", "rank": 1, "content_id": "c1", "chunk_id": None, "score": 0.9}],
        "evidence": [],
        "claims": [],
        "degraded": False,
        "insufficient_evidence": False,
        "workspace_id": WS,
        "status": "ok",
        "failure_reason": None,
        "mode": "deterministic",
    }
    base.update(over)
    return base


def test_enrich_exposes_all_six_signals():
    out = _enrich_query_memory_result(_ok_response())
    assert SIX_SIGNAL_KEYS <= set(out)
    assert out["has_citations"] is True
    assert out["no_context"] is False
    assert out["fallback"]["suggested"] is False
    assert out["fallback"]["recommended_tool"]


def test_enrich_marks_no_context_for_insufficient_evidence():
    out = _enrich_query_memory_result(
        _ok_response(
            status="insufficient_evidence",
            citations=[],
            degraded=True,
            confidence=0.0,
            failure_reason="insufficient_workspace_evidence",
        )
    )
    assert out["no_context"] is True
    assert out["has_citations"] is False
    assert out["fallback"]["suggested"] is True


def test_enrich_suggests_fallback_when_confidence_low():
    out = _enrich_query_memory_result(_ok_response(confidence=0.45))
    assert out["fallback"]["suggested"] is True


def test_enrich_no_fallback_suggestion_when_confident_and_grounded():
    out = _enrich_query_memory_result(_ok_response(confidence=0.7))
    assert out["fallback"]["suggested"] is False


def test_enrich_preserves_original_fields():
    out = _enrich_query_memory_result(_ok_response())
    assert out["answer"].startswith("Based only")
    assert out["mode"] == "deterministic"
    assert out["intent"] == "factual"
    assert out["status"] == "ok"


def test_enrich_passes_structured_api_error_through_unchanged():
    err = {"ok": False, "error": {"type": "memory_lab_api_error", "message": "boom"}}
    assert _enrich_query_memory_result(err) == err
