from __future__ import annotations

from typing import Optional

from memory_lab.context_packs.models import ContextPackBuildRequest, ContextPackBuildResponse
from memory_lab.context_packs.service import build_context_pack_for_request
from memory_lab.providers.llm_backend import LLMBackend, LLMRequest
from memory_lab.providers.noop import NoopLLMBackend
from memory_lab.reasoning.answer import answer_context_pack
from memory_lab.reasoning.explain import BASE_LIMITATIONS, BASE_NON_CLAIMS, build_conflict_warnings, deterministic_explanation
from memory_lab.reasoning.models import ReasoningAnswerResponse, ReasoningProviderMetadata, ReasoningRequest, ReasoningResponse
from memory_lab.reasoning.traverse import build_traversal_steps, collect_evidence_refs


def get_reasoning_llm_backend() -> LLMBackend:
    """Return configured reasoning LLM backend, or Noop without raising."""
    try:
        from memory_lab.providers.anthropic import AnthropicLLMBackend

        backend = AnthropicLLMBackend()
        if backend.is_configured:
            return backend
    except Exception:
        pass
    return NoopLLMBackend()


def _context_pack_request(req: ReasoningRequest) -> ContextPackBuildRequest:
    return ContextPackBuildRequest(
        workspace_id=req.workspace_id,
        query=req.query,
        scope=req.scope,
        memory_type=req.memory_type,
        memory_types=req.memory_types,
        include_supporting_evidence=req.include_supporting_evidence,
        include_current_state=req.include_current_state,
        include_conflicts=req.include_conflicts,
        include_counterfindings=req.include_counterfindings,
        limit=req.limit,
    )


def _reasoning_id(prefix: str, context_pack_id: str, max_hops: int, provider_attempted: bool) -> str:
    mode = "provider" if provider_attempted else "deterministic"
    return f"rsn_{prefix}_{context_pack_id}_{max_hops}_{mode}"


def _provider_metadata(req: ReasoningRequest, backend: Optional[LLMBackend]) -> tuple[ReasoningProviderMetadata, Optional[str]]:
    if not req.enable_provider_synthesis:
        return ReasoningProviderMetadata(provider="none", attempted=False, configured=False, degraded=False), None
    llm = backend or NoopLLMBackend()
    metadata = ReasoningProviderMetadata(
        provider=llm.provider_name,
        attempted=True,
        configured=llm.is_configured,
        degraded=False,
    )
    response = llm.summarize(
        LLMRequest(
            prompt="Summarize evidence path without forbidden public response fields.",
            system="Return only a short process summary. Do not resolve conflicts.",
            max_tokens=128,
            temperature=0.0,
        )
    )
    if response.degraded:
        metadata.degraded = True
        metadata.failure_reason = str(response.failure_reason.value if response.failure_reason else "provider_degraded")
        metadata.model = response.model or None
        return metadata, metadata.failure_reason
    metadata.model = response.model or None
    return metadata, None


def _base_response(
    *,
    prefix: str,
    req: ReasoningRequest,
    context_pack: ContextPackBuildResponse,
    backend: Optional[LLMBackend] = None,
) -> ReasoningResponse:
    provider_metadata, provider_degraded_reason = _provider_metadata(req, backend)
    steps = build_traversal_steps(context_pack, req)
    evidence_refs = collect_evidence_refs(context_pack)
    explanation = deterministic_explanation(
        context_pack=context_pack,
        request=req,
        traversal_steps=steps,
        provider_metadata=provider_metadata,
    )
    degraded_reason = provider_degraded_reason
    if req.enable_provider_synthesis and degraded_reason is None and provider_metadata.attempted:
        explanation["provider_state"]["note"] = "Provider path was explicitly requested; deterministic evidence refs remain authoritative."
    return ReasoningResponse(
        reasoning_id=_reasoning_id(prefix, context_pack.context_pack_id, req.max_hops, provider_metadata.attempted),
        mode="provider_degraded_read_only" if provider_metadata.degraded else ("provider_assisted_read_only" if provider_metadata.attempted else "deterministic_read_only"),
        context_pack_ref={
            "context_pack_id": context_pack.context_pack_id,
            "workspace_id": context_pack.workspace_id,
            "query": context_pack.query,
            "scope": context_pack.scope,
            "pack_version": context_pack.summary_metadata.pack_version,
        },
        traversal_steps=steps,
        evidence_refs=evidence_refs,
        explanation=explanation,
        conflict_warnings=build_conflict_warnings(context_pack),
        limitations=list(BASE_LIMITATIONS),
        provider_metadata=provider_metadata,
        degraded_reason=degraded_reason,
        non_claims=list(dict.fromkeys(list(context_pack.non_claims) + BASE_NON_CLAIMS)),
    )


def traverse_context_pack(
    *,
    context_pack: ContextPackBuildResponse,
    request: ReasoningRequest,
    backend: Optional[LLMBackend] = None,
) -> ReasoningResponse:
    return _base_response(prefix="traverse", req=request, context_pack=context_pack, backend=backend)


def explain_context_pack(
    *,
    context_pack: ContextPackBuildResponse,
    request: ReasoningRequest,
    backend: Optional[LLMBackend] = None,
) -> ReasoningResponse:
    return _base_response(prefix="explain", req=request, context_pack=context_pack, backend=backend)


def traverse_for_request(
    *,
    database_url: str,
    request: ReasoningRequest,
    workspace_id: str,
    workspace_source: Optional[str] = None,
    backend: Optional[LLMBackend] = None,
) -> ReasoningResponse:
    cp_req = _context_pack_request(request)
    context_pack = build_context_pack_for_request(
        database_url=database_url,
        request=cp_req,
        workspace_id=workspace_id,
        workspace_source=workspace_source,
    )
    return traverse_context_pack(context_pack=context_pack, request=request, backend=backend)


def explain_for_request(
    *,
    database_url: str,
    request: ReasoningRequest,
    workspace_id: str,
    workspace_source: Optional[str] = None,
    backend: Optional[LLMBackend] = None,
) -> ReasoningResponse:
    cp_req = _context_pack_request(request)
    context_pack = build_context_pack_for_request(
        database_url=database_url,
        request=cp_req,
        workspace_id=workspace_id,
        workspace_source=workspace_source,
    )
    return explain_context_pack(context_pack=context_pack, request=request, backend=backend)


def answer_for_request(
    *,
    database_url: str,
    request: ReasoningRequest,
    workspace_id: str,
    workspace_source: Optional[str] = None,
    backend: Optional[LLMBackend] = None,
    provider_synthesis_enabled: bool = True,
) -> ReasoningAnswerResponse:
    cp_req = _context_pack_request(request)
    context_pack = build_context_pack_for_request(
        database_url=database_url,
        request=cp_req,
        workspace_id=workspace_id,
        workspace_source=workspace_source,
    )
    resolved_backend = backend
    if resolved_backend is None and request.enable_provider_synthesis and provider_synthesis_enabled:
        resolved_backend = get_reasoning_llm_backend()
    return answer_context_pack(
        context_pack=context_pack,
        request=request,
        backend=resolved_backend,
        provider_synthesis_enabled=provider_synthesis_enabled,
    )
