"""B23 provider-neutral prompt/context package assembly.

The package is compatible with B22 LLMExecutionRequest fields but performs no
live model execution and contains only supplied context-candidate evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from memory_lab.retrieval.context_candidates import ContextCandidatePackage

B23_PROMPT_SCOPE = "public_safe_provider_neutral_prompt_package_only"
B23_PROMPT_NON_CLAIMS: tuple[str, ...] = (
    "no_live_llm_execution", "no_provider_call", "no_private_prompt_copy",
    "no_api_or_wrapper_wiring", "no_private_context_brain_parity",
    "not_production_readiness", "not_full_context_brain_readiness",
)

@dataclass(frozen=True)
class PromptPackageRequest:
    query: str
    purpose: str
    context_package: ContextCandidatePackage
    instructions: str = "Answer only from the supplied evidence. If evidence is insufficient, return no_context."

@dataclass(frozen=True)
class PromptPackage:
    prompt: str
    system: str
    expected_schema: Mapping[str, Any]
    evidence_ids: tuple[int, ...]
    limitations: tuple[str, ...]
    non_claims: tuple[str, ...] = B23_PROMPT_NON_CLAIMS
    scope: str = B23_PROMPT_SCOPE

def build_prompt_package(request: PromptPackageRequest) -> PromptPackage:
    schema = expected_b23_response_schema()
    evidence_ids = tuple(ref.evidence_id for ref in request.context_package.evidence)
    system = _system_text(request.purpose)
    prompt = _prompt_text(request, evidence_ids)
    limitations = tuple(_dedupe(list(request.context_package.limitations) + ["supplied_context_only", "structural_validation_only"]))
    return PromptPackage(prompt, system, schema, evidence_ids, limitations)

def expected_b23_response_schema() -> Mapping[str, Any]:
    return {
        "type": "object",
        "required": ["status", "answer", "confidence", "claims"],
        "properties": {
            "status": {"type": "string", "enum": ["ok", "no_context", "clarify", "degraded", "error"]},
            "answer": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "claims": {"type": "array", "items": {"type": "object"}},
        },
    }

def _system_text(purpose: str) -> str:
    return (
        "You are using a public-safe B23 provider-neutral prompt package. "
        f"Purpose: {purpose}. Use only supplied evidence IDs. "
        "Do not claim private Context Brain parity, live retrieval, provider-backed semantic search, production readiness, or Full Context Brain readiness."
    )

def _prompt_text(request: PromptPackageRequest, evidence_ids: tuple[int, ...]) -> str:
    ids = ", ".join(str(value) for value in evidence_ids) or "none"
    return (
        f"Query: {request.query}\n"
        f"Purpose: {request.purpose}\n"
        f"Instructions: {request.instructions}\n"
        f"Evidence IDs: {ids}\n\n"
        "Supplied evidence context:\n"
        f"{request.context_package.context_text}\n\n"
        "Return an object with status, answer, confidence, and claims. Each factual claim must include evidence_ids."
    )

def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out
