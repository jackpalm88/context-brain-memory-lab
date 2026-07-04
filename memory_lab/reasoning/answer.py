from __future__ import annotations

from typing import Any, Optional

from memory_lab.context_packs.models import ContextPackBuildResponse
from memory_lab.providers.answer_gate import (
    EVIDENCE_ID_PATTERN,
    FORBIDDEN_PROVIDER_TERMS,
    gate_provider_answer,
)
from memory_lab.providers.llm_backend import LLMBackend, LLMRequest
from memory_lab.providers.noop import NoopLLMBackend
from memory_lab.reasoning.explain import BASE_LIMITATIONS, BASE_NON_CLAIMS, build_conflict_warnings
from memory_lab.reasoning.models import ReasoningAnswerResponse, ReasoningProviderMetadata, ReasoningRequest
from memory_lab.reasoning.traverse import build_traversal_steps, collect_evidence_refs

FORBIDDEN_PUBLIC_FIELD_NAMES = {"verdict", "truth_decision", "resolution", "winner", "canonical_truth"}

ANSWER_LIMITATIONS = [
    "B14 returns an evidence-grounded answer candidate only.",
    "The answer candidate is not a truth decision, verdict, or conflict resolution.",
    "Provider wording is disabled unless explicitly requested and configured.",
]

ANSWER_NON_CLAIMS = [
    "no_verdict",
    "no_truth_decision",
    "no_resolution",
    "no_winner",
    "no_canonical_truth",
    "no_private_ask_v2_port",
    "no_private_prompt_copy",
    "no_provider_call_by_default",
    "no_conflict_resolution",
    "no_full_context_brain_claim",
    "no_top_level_answer_field",
]


def _context_pack_ref(context_pack: ContextPackBuildResponse) -> dict[str, Any]:
    return {
        "context_pack_id": context_pack.context_pack_id,
        "workspace_id": context_pack.workspace_id,
        "query": context_pack.query,
        "scope": context_pack.scope,
        "pack_version": context_pack.summary_metadata.pack_version,
    }


def _reasoning_id(context_pack: ContextPackBuildResponse, request: ReasoningRequest, provider_attempted: bool) -> str:
    suffix = "provider" if provider_attempted else "deterministic"
    return f"rsn_answer_{context_pack.context_pack_id}_{request.max_hops}_{suffix}"


def _snippet(ref: dict[str, Any]) -> str:
    text = str(ref.get("snippet") or "").strip()
    text = " ".join(text.split())
    if len(text) > 240:
        return text[:237].rstrip() + "..."
    return text


def _has_usable_evidence(evidence_refs: list[dict[str, Any]]) -> bool:
    return any(_snippet(ref) for ref in evidence_refs)


def _usable_refs(evidence_refs: list[dict[str, Any]], roles: set[str | None] | None = None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for ref in evidence_refs:
        if roles is not None and ref.get("role") not in roles:
            continue
        if _snippet(ref):
            refs.append(ref)
    return refs


def _cited_snippet(ref: dict[str, Any]) -> str:
    evidence_id = str(ref.get("evidence_id") or "").strip()
    if not evidence_id:
        return _snippet(ref)
    return f"[{evidence_id}] {_snippet(ref)}"


def build_answer_candidate(
    *,
    context_pack: ContextPackBuildResponse,
    evidence_refs: list[dict[str, Any]],
    conflict_warnings: list[str],
) -> tuple[str, Optional[str]]:
    """Build a deterministic public answer candidate from evidence refs only."""
    if not _has_usable_evidence(evidence_refs):
        return (
            "Insufficient public evidence to produce an evidence-grounded answer candidate for this query or scope.",
            "insufficient_evidence",
        )

    support = _usable_refs(evidence_refs, {"support", None})
    current = _usable_refs(evidence_refs, {"current_state"})
    counter = _usable_refs(evidence_refs, {"counterfinding", "contradicting"})
    stale = [ref for ref in evidence_refs if (ref.get("is_current") is False or ref.get("cs_supersedes_content_id")) and _snippet(ref)]

    parts: list[str] = ["Based on the public evidence refs in this context pack, the answer candidate is:"]
    selected = (support or current or counter or stale)[:3]
    parts.append(" ".join(_cited_snippet(ref) for ref in selected))
    if current:
        parts.append("Current-state signals are included as evidence signals, not as automatic proof that other evidence is false.")
    if counter or stale or conflict_warnings:
        parts.append("Conflict, counterfinding, or stale signals require human review and are not resolved by this endpoint.")
    parts.append("This candidate is bounded by the supplied evidence refs and limitations.")
    return " ".join(parts), None


def _provider_metadata_without_call() -> ReasoningProviderMetadata:
    return ReasoningProviderMetadata(provider="none", attempted=False, configured=False, degraded=False)


def _provider_failure_reason(response) -> str:
    if getattr(response, "failure_reason", None):
        return str(response.failure_reason.value)
    return "provider_degraded"


def _provider_text_allowed(text: str) -> bool:
    lowered = text.lower()
    return bool(text.strip()) and not any(term in lowered for term in FORBIDDEN_PROVIDER_TERMS)


def _evidence_id(ref: dict[str, Any]) -> str:
    return str(ref.get("evidence_id") or "").strip()


def _provider_citations_allowed(text: str, evidence_refs: list[dict[str, Any]]) -> bool:
    allowed = {_evidence_id(ref) for ref in evidence_refs if _evidence_id(ref)}
    cited = set(EVIDENCE_ID_PATTERN.findall(text))
    return cited <= allowed


def provider_synthesize_answer_candidate(
    *,
    request: ReasoningRequest,
    deterministic_candidate: str,
    evidence_refs: list[dict[str, Any]],
    conflict_warnings: list[str],
    backend: Optional[LLMBackend] = None,
    provider_synthesis_enabled: bool = True,
) -> tuple[str, ReasoningProviderMetadata, Optional[str], str]:
    """Try explicitly opted-in provider wording through the shared neutral provider gate.

    The decision flow (dual gate, forbidden-term rejection, citation allow-list, typed degraded
    fallback) lives in memory_lab.providers.answer_gate so the ask/query path shares one
    implementation. This function only builds the reasoning-specific prompt and maps the neutral
    ProviderGateResult onto ReasoningProviderMetadata.
    """
    citation_ids = [_evidence_id(ref) for ref in evidence_refs if _evidence_id(ref)]
    top_ids = citation_ids[:5]
    # One ID per line so the model can copy them accurately without truncation.
    allowed_ids_block = "\n".join(top_ids)
    snippets_block = "\n".join(
        f"[{_evidence_id(ref)}] {_snippet(ref)}"
        for ref in evidence_refs[:5]
        if _evidence_id(ref)
    )
    _forbidden = "verdict, resolution, winner, canonical truth, truth decision"
    prompt = (
        "Reword the deterministic candidate answer using ONLY the evidence snippets below.\n"
        "Rules:\n"
        "- Cite evidence using ONLY the exact evidence_id values from ALLOWED IDS.\n"
        "- Copy each evidence_id character-for-character; do not shorten or alter them.\n"
        "- Do not introduce any evidence_id not listed in ALLOWED IDS.\n"
        "- Do not decide truth. Do not resolve conflicts.\n"
        f"- Do not use these words: {_forbidden}.\n\n"
        f"ALLOWED IDS (copy exactly, one per line):\n{allowed_ids_block}\n\n"
        f"DETERMINISTIC CANDIDATE:\n{deterministic_candidate}\n\n"
        f"EVIDENCE SNIPPETS:\n{snippets_block}\n\n"
        f"WARNINGS:\n{conflict_warnings}"
    )
    result = gate_provider_answer(
        enable_provider_synthesis=request.enable_provider_synthesis,
        provider_synthesis_enabled=provider_synthesis_enabled,
        deterministic_text=deterministic_candidate,
        allowed_evidence_ids=set(citation_ids),
        prompt=prompt,
        system="Public B14 answer-candidate wording only. No private prompts. No conflict decision.",
        backend=backend,
        max_tokens=400,
    )
    metadata = ReasoningProviderMetadata(
        provider=result.provider_name,
        attempted=result.attempted,
        configured=result.configured,
        degraded=result.degraded,
        failure_reason=result.failure_reason,
        model=result.model,
    )
    degraded_reason = result.failure_reason if result.mode == "degraded" else None
    return result.text, metadata, degraded_reason, result.mode


def answer_context_pack(
    *,
    context_pack: ContextPackBuildResponse,
    request: ReasoningRequest,
    backend: Optional[LLMBackend] = None,
    provider_synthesis_enabled: bool = True,
) -> ReasoningAnswerResponse:
    steps = build_traversal_steps(context_pack, request)
    evidence_refs = collect_evidence_refs(context_pack)
    conflict_warnings = build_conflict_warnings(context_pack)
    deterministic_candidate, deterministic_degraded_reason = build_answer_candidate(
        context_pack=context_pack,
        evidence_refs=evidence_refs,
        conflict_warnings=conflict_warnings,
    )

    if deterministic_degraded_reason:
        provider_metadata = _provider_metadata_without_call()
        mode = "degraded"
        answer_candidate = deterministic_candidate
        degraded_reason = deterministic_degraded_reason
    else:
        answer_candidate, provider_metadata, provider_degraded_reason, mode = provider_synthesize_answer_candidate(
            request=request,
            deterministic_candidate=deterministic_candidate,
            evidence_refs=evidence_refs,
            conflict_warnings=conflict_warnings,
            backend=backend,
            provider_synthesis_enabled=provider_synthesis_enabled,
        )
        degraded_reason = provider_degraded_reason

    limitations = list(dict.fromkeys(BASE_LIMITATIONS + ANSWER_LIMITATIONS))
    non_claims = list(dict.fromkeys(list(context_pack.non_claims) + BASE_NON_CLAIMS + ANSWER_NON_CLAIMS))
    return ReasoningAnswerResponse(
        reasoning_id=_reasoning_id(context_pack, request, provider_metadata.attempted),
        mode=mode,
        answer_candidate=answer_candidate,
        evidence_refs=evidence_refs,
        context_pack_ref=_context_pack_ref(context_pack),
        traversal_steps=steps,
        conflict_warnings=conflict_warnings,
        limitations=limitations,
        provider_metadata=provider_metadata,
        degraded_reason=degraded_reason,
        non_claims=non_claims,
    )
