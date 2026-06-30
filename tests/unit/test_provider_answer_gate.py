from __future__ import annotations

import pytest

from memory_lab.providers.answer_gate import (
    ProviderGateResult,
    gate_provider_answer,
    provider_citations_allowed,
    provider_text_allowed,
)
from memory_lab.providers.failure import FailureCode
from memory_lab.providers.fake import FakeLLMBackend
from memory_lab.providers.llm_backend import LLMResponse

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

DET = "Based only on retrieved workspace evidence: [ev_a] alpha [ev_b] beta"
ALLOWED = {"ev_a", "ev_b"}


def _gate(**kw) -> ProviderGateResult:
    base = dict(
        enable_provider_synthesis=True,
        provider_synthesis_enabled=True,
        deterministic_text=DET,
        allowed_evidence_ids=ALLOWED,
        prompt="PROMPT",
        system="SYSTEM",
        backend=None,
    )
    base.update(kw)
    return gate_provider_answer(**base)


def test_flag_off_returns_deterministic_without_attempt():
    result = _gate(enable_provider_synthesis=False, backend=FakeLLMBackend())
    assert result.mode == "deterministic"
    assert result.attempted is False
    assert result.degraded is False
    assert result.failure_reason is None
    assert result.text == DET


def test_config_disabled_degrades_without_provider_call():
    backend = FakeLLMBackend()
    result = _gate(provider_synthesis_enabled=False, backend=backend)
    assert backend.summarize_calls == 0
    assert result.mode == "degraded"
    assert result.attempted is False
    assert result.failure_reason == "provider_disabled"
    assert result.text == DET


def test_noop_backend_opted_in_degrades_not_configured():
    result = _gate(backend=None)
    assert result.mode == "degraded"
    assert result.attempted is True
    assert result.provider_name == "none"
    assert result.degraded is True
    assert result.failure_reason == "not_configured"
    assert result.text == DET


def test_fake_backend_grounded_output_is_provider_backed():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Grounded wording cites [ev_a]", provider="fake"))
    result = _gate(backend=backend)
    assert backend.summarize_calls == 1
    assert result.mode == "provider_backed"
    assert result.attempted is True
    assert result.provider_name == "fake"
    assert result.degraded is False
    assert result.failure_reason is None
    assert result.text == "Grounded wording cites [ev_a]"


def test_invented_citation_rejected_to_deterministic():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Provider cites ev_missing", provider="fake"))
    result = _gate(backend=backend)
    assert backend.summarize_calls == 1
    assert result.mode == "degraded"
    assert result.failure_reason == "provider_output_rejected"
    assert result.text == DET


def test_forbidden_term_rejected_to_deterministic():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="The verdict is supported by ev_a", provider="fake"))
    result = _gate(backend=backend)
    assert backend.summarize_calls == 1
    assert result.mode == "degraded"
    assert result.failure_reason == "provider_output_rejected"
    assert result.text == DET


def test_provider_timeout_degrades_with_reason():
    backend = FakeLLMBackend(preset_failure=FailureCode.TIMEOUT)
    result = _gate(backend=backend)
    assert result.mode == "degraded"
    assert result.degraded is True
    assert result.failure_reason == "timeout"
    assert result.text == DET


def test_prompt_and_system_passed_to_backend():
    backend = FakeLLMBackend(preset_response=LLMResponse(text="ok [ev_a]", provider="fake"))
    _gate(backend=backend, prompt="MY_PROMPT", system="MY_SYSTEM")
    assert backend.last_request is not None
    assert backend.last_request.prompt == "MY_PROMPT"
    assert backend.last_request.system == "MY_SYSTEM"


def test_helpers_directly():
    assert provider_text_allowed("normal grounded text") is True
    assert provider_text_allowed("contains a verdict here") is False
    assert provider_text_allowed("   ") is False
    assert provider_citations_allowed("cites [ev_a] only", {"ev_a", "ev_b"}) is True
    assert provider_citations_allowed("cites ev_c instead", {"ev_a"}) is False
