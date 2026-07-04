"""FV-FIX-1 — Provider citation format alignment acceptance tests.

Validates that:
1. _build_ask_prompt formats allowed IDs one-per-line (not Python list repr).
2. Prompt contains the ALLOWED IDS block header.
3. Prompt contains the forbidden-terms reminder.
4. system prompt contains the forbidden-terms warning.
5. gate_provider_answer: verbatim ev_ ID → provider_backed.
6. gate_provider_answer: truncated/mutated ev_ ID → rejected.
7. gate_provider_answer default max_tokens >= 400.
8. QueryService path: verbatim ev_ citation → provider_backed.
9. Deterministic fallback unaffected.
"""
from __future__ import annotations

import inspect

import pytest

from memory_lab.providers.answer_gate import gate_provider_answer
from memory_lab.providers.fake import FakeLLMBackend
from memory_lab.providers.llm_backend import LLMResponse
from memory_lab.query.provider_answer import (
    ASK_PROVIDER_SYSTEM,
    _FORBIDDEN_TERMS_REMINDER,
    _build_ask_prompt,
)
from memory_lab.query.service import QueryService
from memory_lab.reasoning.models import AskRequest, EvidenceItem

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000937"

# ── shared helpers (same pattern as test_ask_provider_answer.py) ─────────────

CID_1 = "aabbccdd-1111-0000-0000-000000000001"
CHK_1 = "eeff0011-1111-0000-0000-000000000001"
CID_2 = "aabbccdd-2222-0000-0000-000000000002"
CHK_2 = "eeff0011-2222-0000-0000-000000000002"
EV_ID_1 = f"ev_{CID_1}_{CHK_1}"
EV_ID_2 = f"ev_{CID_2}_{CHK_2}"


def _ev(n: int = 1) -> EvidenceItem:
    """Construct a valid EvidenceItem with all required fields."""
    cid = CID_1 if n == 1 else CID_2
    chk = CHK_1 if n == 1 else CHK_2
    ev_id = EV_ID_1 if n == 1 else EV_ID_2
    return EvidenceItem(
        evidence_id=ev_id,
        rank=n,
        content_id=cid,
        chunk_id=chk,
        snippet=f"Workspace evidence snippet number {n} about the topic.",
        score=0.9,
        score_kind="vector",
        retrieval_path="content_chunk_workspace_scoped",
    )


def _row(n: int = 1) -> dict:
    """Retrieval adapter row dict — QueryService builds EvidenceItem from these."""
    cid = CID_1 if n == 1 else CID_2
    chk = CHK_1 if n == 1 else CHK_2
    return {
        "content_id": cid,
        "chunk_id": chk,
        "text": f"Workspace evidence snippet number {n} about the topic.",
        "score": 0.9,
        "retrieval_path": "content_chunk_workspace_scoped",
    }


class FakeRetrievalAdapter:
    def __init__(self, rows):
        self.rows = rows

    def search(self, **kwargs):
        return list(self.rows)


def _svc(rows, *, backend=None):
    return QueryService(
        retrieval_adapter=FakeRetrievalAdapter(rows),
        provider_synthesis_enabled=True,
        backend=backend,
    )


def _ask(**kw):
    base = dict(query="What does the workspace evidence say?", top_k=5)
    base.update(kw)
    return AskRequest(**base)


# ── 1. _build_ask_prompt: IDs one-per-line, not Python list repr ─────────────

def test_build_ask_prompt_ids_one_per_line():
    ev1, ev2 = _ev(1), _ev(2)
    prompt = _build_ask_prompt("What?", "Deterministic answer.", [ev1, ev2])
    assert EV_ID_1 in prompt, "EV_ID_1 must appear verbatim in prompt"
    assert EV_ID_2 in prompt, "EV_ID_2 must appear verbatim in prompt"
    # Must NOT be formatted as Python list repr
    assert "['" not in prompt, "Prompt must not contain Python list repr ['..."
    assert "', '" not in prompt, "Prompt must not contain Python list separator ', '"


def test_build_ask_prompt_allowed_ids_header_present():
    prompt = _build_ask_prompt("Query?", "Det answer.", [_ev(1)])
    assert "ALLOWED IDS" in prompt


def test_build_ask_prompt_forbidden_terms_reminder_present():
    prompt = _build_ask_prompt("Query?", "Det answer.", [_ev(1)])
    assert "verdict" in prompt.lower()
    assert "resolution" in prompt.lower()


def test_build_ask_prompt_question_and_candidate_sections_present():
    prompt = _build_ask_prompt("My question?", "My det answer.", [_ev(1)])
    assert "QUESTION" in prompt
    assert "My question?" in prompt
    assert "DETERMINISTIC CANDIDATE" in prompt
    assert "My det answer." in prompt


def test_build_ask_prompt_evidence_section_present():
    prompt = _build_ask_prompt("Q?", "Det.", [_ev(1)])
    assert "EVIDENCE" in prompt.upper()
    assert _ev(1).snippet in prompt


# ── 2. System prompt + constant ──────────────────────────────────────────────

def test_system_prompt_warns_about_forbidden_terms():
    assert "verdict" in ASK_PROVIDER_SYSTEM.lower()
    assert "resolution" in ASK_PROVIDER_SYSTEM.lower()


def test_forbidden_terms_reminder_constant_non_empty():
    assert _FORBIDDEN_TERMS_REMINDER.strip()
    assert "verdict" in _FORBIDDEN_TERMS_REMINDER
    assert "resolution" in _FORBIDDEN_TERMS_REMINDER


# ── 3. gate_provider_answer: verbatim ev_ → provider_backed ─────────────────

def test_gate_verbatim_evidence_id_passes():
    """Backend cites the full evidence_id verbatim → provider_backed."""
    backend = FakeLLMBackend(
        preset_response=LLMResponse(
            text=f"Based on workspace evidence {EV_ID_1}, the answer is confirmed.",
            provider="fake",
        )
    )
    result = gate_provider_answer(
        enable_provider_synthesis=True,
        provider_synthesis_enabled=True,
        deterministic_text="Det answer.",
        allowed_evidence_ids={EV_ID_1},
        prompt="PROMPT",
        system="SYSTEM",
        backend=backend,
        max_tokens=400,
    )
    assert result.mode == "provider_backed", (
        f"expected provider_backed, got {result.mode}: {result.failure_reason}"
    )
    assert result.degraded is False
    assert EV_ID_1 in result.text


def test_gate_no_citation_in_answer_also_passes():
    """Provider answer with zero ev_ references: cited ⊆ allowed = ∅ ⊆ allowed → OK."""
    backend = FakeLLMBackend(
        preset_response=LLMResponse(
            text="The workspace evidence confirms the fact without explicit citation.",
            provider="fake",
        )
    )
    result = gate_provider_answer(
        enable_provider_synthesis=True,
        provider_synthesis_enabled=True,
        deterministic_text="Det answer.",
        allowed_evidence_ids={EV_ID_1},
        prompt="PROMPT",
        system="SYSTEM",
        backend=backend,
        max_tokens=400,
    )
    assert result.mode == "provider_backed"


# ── 4. gate_provider_answer: mutated/invented ev_ → rejected ─────────────────

def test_gate_truncated_evidence_id_rejected():
    """Backend truncates ev_ UUID → gate rejects → degraded/provider_output_rejected."""
    truncated = EV_ID_1[:30]  # clearly truncated
    backend = FakeLLMBackend(
        preset_response=LLMResponse(
            text=f"See evidence {truncated} for details.",
            provider="fake",
        )
    )
    result = gate_provider_answer(
        enable_provider_synthesis=True,
        provider_synthesis_enabled=True,
        deterministic_text="Det answer.",
        allowed_evidence_ids={EV_ID_1},
        prompt="PROMPT",
        system="SYSTEM",
        backend=backend,
        max_tokens=400,
    )
    assert result.mode == "degraded"
    assert result.failure_reason == "provider_output_rejected"


def test_gate_invented_evidence_id_rejected():
    """Backend invents an ev_ ID not in allowed set → rejected."""
    invented = "ev_00000000-dead-beef-0000-000000000000_ffffffff-0000-0000-0000-000000000000"
    backend = FakeLLMBackend(
        preset_response=LLMResponse(
            text=f"Evidence {invented} shows the answer.",
            provider="fake",
        )
    )
    result = gate_provider_answer(
        enable_provider_synthesis=True,
        provider_synthesis_enabled=True,
        deterministic_text="Det answer.",
        allowed_evidence_ids={EV_ID_1},
        prompt="PROMPT",
        system="SYSTEM",
        backend=backend,
        max_tokens=400,
    )
    assert result.mode == "degraded"
    assert result.failure_reason == "provider_output_rejected"


# ── 5. gate_provider_answer default max_tokens >= 400 ────────────────────────

def test_gate_default_max_tokens_is_at_least_400():
    sig = inspect.signature(gate_provider_answer)
    default = sig.parameters["max_tokens"].default
    assert default >= 400, f"gate max_tokens default is {default}, expected >= 400"


# ── 6. QueryService path: verbatim citation → provider_backed ────────────────

def test_query_service_verbatim_citation_provider_backed():
    """Full QueryService path: FakeLLMBackend cites ev_ verbatim → mode=provider_backed."""
    row = _row(1)
    # We need the exact evidence_id that QueryService will assign.
    # QueryService builds ev_id as ev_{content_id}_{chunk_id}
    expected_ev_id = f"ev_{row['content_id']}_{row['chunk_id']}"
    backend = FakeLLMBackend(
        preset_response=LLMResponse(
            text=f"Workspace evidence {expected_ev_id} confirms the fact.",
            provider="fake",
        )
    )
    svc = _svc([row], backend=backend)
    resp = svc.execute(
        _ask(enable_provider_synthesis=True),
        workspace_id=WS,
    )
    assert resp.mode == "provider_backed", (
        f"got mode={resp.mode}, failure={resp.failure_reason}"
    )
    assert expected_ev_id in resp.answer


# ── 7. Deterministic fallback unaffected ─────────────────────────────────────

def test_no_synthesis_flag_still_deterministic():
    """Without enable_provider_synthesis=True, mode stays deterministic."""
    backend = FakeLLMBackend(
        preset_response=LLMResponse(text="Provider text", provider="fake")
    )
    svc = _svc([_row(1)], backend=backend)
    resp = svc.execute(_ask(), workspace_id=WS)  # no enable_provider_synthesis
    assert resp.mode == "deterministic"
    assert backend.summarize_calls == 0
