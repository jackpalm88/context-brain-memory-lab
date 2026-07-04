"""Optional provider-backed wording for the public ask/query_memory answer.

This is the ask-path counterpart to the reasoning answer path. It takes the already-built
deterministic AskResponse and, only when both the per-request opt-in and the deployment config
gate allow it, asks a provider to reword the answer using the shared neutral provider gate
(memory_lab.providers.answer_gate). The provider may only reword — it may not introduce
unsupported citations, decide truth, or resolve conflicts. On any non-happy path the
deterministic answer is retained and the response is marked degraded with a typed failure_reason.

Confidence honesty: provider-backed answers keep the deterministic confidence value (the
count-based floor); they never inflate it. Degraded answers also keep the deterministic
confidence, which is already at or below that floor.
"""

from __future__ import annotations

from typing import List, Optional

from memory_lab.providers.answer_gate import gate_provider_answer
from memory_lab.providers.llm_backend import LLMBackend
from memory_lab.reasoning.models import AskRequest, AskResponse, EvidenceItem

ASK_PROVIDER_SYSTEM = (
    "Public OpenCB ask wording only. Answer strictly from the supplied evidence snippets. "
    "Do not decide truth. Do not choose a winner. Do not resolve conflicts. No private prompts. "
    "Do not use the words: verdict, resolution, winner, canonical truth, truth decision."
)

# Forbidden terms mirrored so the prompt warns the model proactively.
_FORBIDDEN_TERMS_REMINDER = "verdict, resolution, winner, canonical truth, truth decision"


def _current_state_label(item: EvidenceItem) -> str:
    """Render the resolver-computed status of one snippet; empty when unknown."""
    if item.is_current is True:
        return " [status: current]"
    if item.is_current is False:
        return " [status: superseded]"
    return ""


def _build_ask_prompt(query: str, deterministic_text: str, evidence: List[EvidenceItem]) -> str:
    top_evidence = evidence[:5]
    # One ID per line so the model can copy them accurately without truncation.
    allowed_ids_block = "\n".join(e.evidence_id for e in top_evidence)
    snippets = "\n".join(
        f"[{e.evidence_id}] {e.snippet}{_current_state_label(e)}" for e in top_evidence
    )
    has_status = any(e.is_current is not None for e in top_evidence)
    status_rule = (
        "- Snippets marked [status: superseded] were replaced by a newer decision; "
        "prefer [status: current] snippets unless the question asks about history, "
        "in which case superseded snippets may be cited as historical context.\n"
        if has_status
        else ""
    )
    return (
        "Reword the deterministic candidate answer using ONLY the evidence snippets below.\n"
        "Rules:\n"
        "- Cite evidence using ONLY the exact evidence_id values from ALLOWED IDS.\n"
        "- Copy each evidence_id character-for-character; do not shorten or alter them.\n"
        "- Do not introduce any evidence_id not listed in ALLOWED IDS.\n"
        "- Do not decide truth. Do not resolve conflicts.\n"
        f"{status_rule}"
        f"- Do not use these words: {_FORBIDDEN_TERMS_REMINDER}.\n\n"
        f"ALLOWED IDS (copy exactly, one per line):\n{allowed_ids_block}\n\n"
        f"QUESTION:\n{query}\n\n"
        f"DETERMINISTIC CANDIDATE:\n{deterministic_text}\n\n"
        f"EVIDENCE SNIPPETS:\n{snippets}"
    )


def apply_provider_answer(
    *,
    response: AskResponse,
    request: AskRequest,
    query: str,
    evidence: List[EvidenceItem],
    provider_synthesis_enabled: bool,
    backend: Optional[LLMBackend] = None,
) -> AskResponse:
    """Optionally upgrade a successful deterministic AskResponse to provider-backed wording.

    Returns the response unchanged when provider synthesis is not opted in. Returns a degraded
    response (deterministic answer retained) when the provider is disabled, unavailable, times
    out, or produces rejected output.
    """
    result = gate_provider_answer(
        enable_provider_synthesis=request.enable_provider_synthesis,
        provider_synthesis_enabled=provider_synthesis_enabled,
        deterministic_text=response.answer,
        allowed_evidence_ids={e.evidence_id for e in evidence},
        prompt=_build_ask_prompt(query, response.answer, evidence),
        system=ASK_PROVIDER_SYSTEM,
        backend=backend,
    )

    if result.mode == "deterministic":
        return response

    if result.mode == "provider_backed":
        return response.model_copy(
            update={
                "answer": result.text,
                "mode": "provider_backed",
                "confidence_explanation": (
                    response.confidence_explanation
                    + f" A configured provider ({result.provider_name}) produced the wording; "
                    "the answer remains bounded to retrieved workspace evidence."
                ),
            }
        )

    # degraded — deterministic answer retained, typed failure_reason recorded.
    return response.model_copy(
        update={
            "mode": "degraded",
            "degraded": True,
            "failure_reason": result.failure_reason,
            "confidence_explanation": (
                response.confidence_explanation
                + f" Provider synthesis was requested but degraded ({result.failure_reason}); "
                "the deterministic evidence-grounded answer was retained."
            ),
        }
    )
