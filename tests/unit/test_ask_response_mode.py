from __future__ import annotations

import pytest

from memory_lab.query.ask_projection import (
    insufficient_evidence_response,
    successful_ask_response,
    unsupported_intent_response,
)
from memory_lab.reasoning.models import AskResponse, EvidenceItem

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000935"


def _ev(evidence_id: str = "ev_1") -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        rank=1,
        content_id="c1",
        snippet="snippet text",
        score_kind="chunk_text_match",
        retrieval_path="deterministic_db",
    )


def test_askresponse_has_mode_field_default_deterministic():
    response = AskResponse(
        answer="a",
        intent="factual",
        confidence=0.0,
        confidence_explanation="x",
        workspace_id=WS,
        status="ok",
    )
    assert response.mode == "deterministic"


def test_successful_response_mode_is_deterministic():
    response = successful_ask_response(intent="factual", evidence=[_ev()], include_evidence=True, workspace_id=WS)
    assert response.mode == "deterministic"
    assert response.degraded is False


def test_insufficient_response_mode_is_deterministic():
    response = insufficient_evidence_response(intent="factual", evidence=[], include_evidence=True, workspace_id=WS)
    assert response.mode == "deterministic"
    assert response.degraded is True
    assert response.status == "insufficient_evidence"


def test_unsupported_response_mode_is_deterministic():
    response = unsupported_intent_response(intent="unknown", workspace_id=WS)
    assert response.mode == "deterministic"
    assert response.degraded is True
    assert response.status == "unsupported_intent"
