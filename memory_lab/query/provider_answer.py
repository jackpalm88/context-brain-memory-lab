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
    "Do not decide truth. Do not choose a winner. Do not resolve conflicts. No private prompts."
)


def _build_ask_prompt(query: str, deterministic_text: str, evidence: List[EvidenceItem]) -> str:
    citation_ids = [e.evidence_id for e in evidence][:5]
    snippets = "\n".join(f"[{e.evidence_id}] {e.snippet}" for e in evidence[:5])
    return (
        "Answer the user question using ONLY the evidence snippets below. "
        "Do not decide truth. Do not choose a winner. Do not resolve conflicts. "
        "If citing evidence, cite only these evidence_id values exactly: "
        f"{citation_ids}.\n\n"
        f"Question:\n{query}\n\n"
        f"Deterministic candidate:\n{deterministic_text}\n\n"
        f"Evidence:\n{snippets}"
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
