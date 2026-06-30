from __future__ import annotations

import pytest

from memory_lab.providers.failure import FailureCode
from memory_lab.providers.fake import FakeLLMBackend
from memory_lab.providers.llm_backend import LLMResponse
from memory_lab.query.service import QueryService
from memory_lab.reasoning.models import AskRequest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000936"


class FakeRetrievalAdapter:
    def __init__(self, rows):
        self.rows = rows

    def search(self, **kwargs):
        return list(self.rows)


def _row(content_id="cid-1", chunk_id="chk-1", text="Workspace evidence about the topic.", score=0.9):
    return {
        "content_id": content_id,
        "chunk_id": chunk_id,
        "text": text,
        "score": score,
        "retrieval_path": "content_chunk_workspace_scoped",
    }


def _svc(rows, *, provider_synthesis_enabled=False, backend=None):
    return QueryService(
        retrieval_adapter=FakeRetrievalAdapter(rows),
        provider_synthesis_enabled=provider_synthesis_enabled,
        backend=backend,
    )


def _ask(**kw):
    base = dict(query="What does the workspace evidence say?", top_k=5)
    base.update(kw)
    return AskRequest(**base)


def test_provider_off_by_default_keeps_deterministic_answer():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Provider wording", provider="fake"))
    response = _svc([_row()], provider_synthesis_enabled=True, backend=backend).execute(_ask(), workspace_id=WS)
    assert response.mode == "deterministic"
    assert backend.summarize_calls == 0
    assert response.answer.startswith("Based only on retrieved workspace evidence:")


def test_config_disabled_degrades_when_requested_without_call():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Provider wording", provider="fake"))
    response = _svc([_row()], provider_synthesis_enabled=False, backend=backend).execute(
        _ask(enable_provider_synthesis=True), workspace_id=WS
    )
    assert backend.summarize_calls == 0
    assert response.mode == "degraded"
    assert response.degraded is True
    assert response.failure_reason == "provider_disabled"
    assert response.answer.startswith("Based only on retrieved workspace evidence:")


def test_noop_backend_opted_in_degrades_not_configured():
    response = _svc([_row()], provider_synthesis_enabled=True, backend=None).execute(
        _ask(enable_provider_synthesis=True), workspace_id=WS
    )
    assert response.mode == "degraded"
    assert response.failure_reason == "not_configured"
    assert response.answer.startswith("Based only on retrieved workspace evidence:")


def test_provider_backed_replaces_answer_and_names_provider():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Synthesized grounded answer from workspace evidence.", provider="fake"))
    response = _svc([_row()], provider_synthesis_enabled=True, backend=backend).execute(
        _ask(enable_provider_synthesis=True), workspace_id=WS
    )
    assert backend.summarize_calls == 1
    assert response.mode == "provider_backed"
    assert response.degraded is False
    assert response.answer == "Synthesized grounded answer from workspace evidence."
    assert "provider" in response.confidence_explanation.lower()
    assert response.citations  # citations preserved from evidence


def test_provider_backed_confidence_not_inflated_above_deterministic():
    rows = [_row()]
    deterministic = _svc(rows).execute(_ask(), workspace_id=WS)
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Synthesized grounded answer.", provider="fake"))
    provider_backed = _svc(rows, provider_synthesis_enabled=True, backend=backend).execute(
        _ask(enable_provider_synthesis=True), workspace_id=WS
    )
    assert provider_backed.mode == "provider_backed"
    assert provider_backed.confidence == deterministic.confidence


def test_provider_invented_citation_rejected_to_deterministic():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Answer cites ev_does_not_exist_999", provider="fake"))
    response = _svc([_row()], provider_synthesis_enabled=True, backend=backend).execute(
        _ask(enable_provider_synthesis=True), workspace_id=WS
    )
    assert response.mode == "degraded"
    assert response.failure_reason == "provider_output_rejected"
    assert response.answer.startswith("Based only on retrieved workspace evidence:")


def test_provider_forbidden_term_rejected_to_deterministic():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="The winner is clearly option A", provider="fake"))
    response = _svc([_row()], provider_synthesis_enabled=True, backend=backend).execute(
        _ask(enable_provider_synthesis=True), workspace_id=WS
    )
    assert response.mode == "degraded"
    assert response.failure_reason == "provider_output_rejected"


def test_provider_timeout_degrades_keeping_deterministic_answer():
    backend = FakeLLMBackend(preset_failure=FailureCode.TIMEOUT)
    response = _svc([_row()], provider_synthesis_enabled=True, backend=backend).execute(
        _ask(enable_provider_synthesis=True), workspace_id=WS
    )
    assert response.mode == "degraded"
    assert response.failure_reason == "timeout"
    assert response.answer.startswith("Based only on retrieved workspace evidence:")


def test_insufficient_evidence_never_calls_provider():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Provider wording", provider="fake"))
    response = _svc([], provider_synthesis_enabled=True, backend=backend).execute(
        _ask(enable_provider_synthesis=True), workspace_id=WS
    )
    assert backend.summarize_calls == 0
    assert response.status == "insufficient_evidence"
    assert response.mode == "deterministic"
