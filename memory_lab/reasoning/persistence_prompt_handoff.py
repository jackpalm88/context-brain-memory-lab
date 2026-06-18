"""B29 public-safe persisted-records-to-prompt-package handoff contract.

This module composes the B28 persistence-to-context handoff with the B23
prompt-package builder over caller-supplied records, or records listed from a
caller-supplied B26-compatible backend. It is deterministic contract glue only:
it does not run model prompts, open storage connections, fetch remote
content, generate embeddings, use vector storage, expose API/MCP runtime wiring,
or access private Context Brain memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Mapping, Sequence

from memory_lab.persistence.results import ContentPersistenceRecord
from memory_lab.reasoning.llm_executor import LLMExecutionRequest
from memory_lab.reasoning.prompt_package import PromptPackage, PromptPackageRequest, build_prompt_package
from memory_lab.retrieval.persistence_handoff import (
    PersistenceRetrievalCandidateRequest,
    PersistenceRetrievalHandoffResult,
    build_context_package_from_persisted_records,
)

B29_PROMPT_HANDOFF_MODE = "b29_public_safe_persisted_records_to_prompt_package_handoff_v1"
B29_LIMITATIONS: tuple[str, ...] = (
    "persisted_record_to_prompt_package_handoff_contract_only",
    "caller_supplied_records_only",
    "optional_supplied_b26_backend_list_only_via_b28",
    "workspace_boundary_validation_over_supplied_values",
    "composes_b28_context_handoff_and_b23_prompt_package",
    "b22_request_shape_only_when_requested",
    "live_mode_disabled",
    "backend_name_none",
    "fake_backend_not_allowed",
    "no_llm_execution",
    "no_live_backend_connection",
    "no_database_access",
    "no_environment_access",
    "no_network_fetch",
    "no_model_service_call",
    "no_private_context_brain_access",
    "no_api_or_mcp_runtime",
    "no_embedding_generation",
    "no_vector_db_access",
    "no_external_state_mutation",
)
B29_NON_CLAIMS: tuple[str, ...] = (
    "not_live_memory_retrieval",
    "not_semantic_search",
    "not_db_backed_retrieval",
    "not_db_backed_production_persistence",
    "not_provider_backed_reasoning",
    "not_llm_execution",
    "not_embedding_or_vector_retrieval",
    "not_private_context_brain_parity",
    "not_full_context_brain_parity",
    "not_api_or_mcp_runtime",
    "not_production_ready",
    "not_prompt_quality_or_truth_claim",
)


@dataclass(frozen=True)
class PersistencePromptCapabilityMetadata:
    capability: str = "b29_persisted_record_to_prompt_package_handoff_contract"
    mode: str = B29_PROMPT_HANDOFF_MODE
    input_scope: str = "caller_supplied_records_or_supplied_b26_backend_list_only"
    live_backend_used: bool = False
    requires_db: bool = False
    requires_provider: bool = False
    requires_private_context_brain: bool = False
    uses_embeddings: bool = False
    uses_vector_db: bool = False
    mutates_external_state: bool = False
    executes_llm: bool = False
    production_runtime: bool = False
    limitations: tuple[str, ...] = B29_LIMITATIONS
    non_claims: tuple[str, ...] = B29_NON_CLAIMS
    degraded_reason: str | None = None


@dataclass(frozen=True)
class PersistencePromptPackageRequest:
    workspace_id: str
    records: Sequence[ContentPersistenceRecord | Mapping[str, Any] | Any] = dataclass_field(default_factory=tuple)
    backend: Any | None = None
    use_backend: bool = False
    query: str = ""
    purpose: str = "answer"
    instructions: str = "Answer only from the supplied evidence. If evidence is insufficient, return no_context."
    limit: int = 10
    max_candidates: int = 8
    max_context_chars: int = 4000
    snippet_chars: int = 600
    max_tokens: int = 512
    temperature: float = 0.0
    circuit_state: str = "unknown"
    include_llm_request: bool = False


@dataclass(frozen=True)
class PersistencePromptPackageError:
    code: str
    message: str
    field: str | None = None
    limitations: tuple[str, ...] = B29_LIMITATIONS
    non_claims: tuple[str, ...] = B29_NON_CLAIMS
    capability_metadata: PersistencePromptCapabilityMetadata = dataclass_field(
        default_factory=lambda: PersistencePromptCapabilityMetadata(degraded_reason="prompt_handoff_error")
    )


@dataclass(frozen=True)
class PersistencePromptPackageResult:
    ok: bool
    status: str
    workspace_id: str
    context_handoff: PersistenceRetrievalHandoffResult | None = None
    prompt_package: PromptPackage | None = None
    llm_request: LLMExecutionRequest | None = None
    errors: tuple[PersistencePromptPackageError, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = B29_LIMITATIONS
    non_claims: tuple[str, ...] = B29_NON_CLAIMS
    capability_metadata: PersistencePromptCapabilityMetadata = dataclass_field(default_factory=PersistencePromptCapabilityMetadata)
    mode: str = B29_PROMPT_HANDOFF_MODE


class PublicSafePersistencePromptPackageHandoff:
    """Deterministic B29 bridge from supplied persisted records to B23 prompts."""

    name = "PublicSafePersistencePromptPackageHandoff"
    mode = B29_PROMPT_HANDOFF_MODE
    limitations = B29_LIMITATIONS
    non_claims = B29_NON_CLAIMS

    def build_prompt_package(self, request: PersistencePromptPackageRequest) -> PersistencePromptPackageResult:
        context_result = _build_context_result(request)
        if not context_result.ok:
            error = _error_from_context_result(context_result)
            return _failure(_status_for_error(error.code), request.workspace_id, context_result, error)
        if context_result.context_package is None:
            error = PersistencePromptPackageError("context_package_failed", "B28 handoff did not return a context package", "context_package")
            return _failure("context_package_failed", request.workspace_id, context_result, error)
        try:
            prompt_package = build_prompt_package(
                PromptPackageRequest(
                    query=request.query,
                    purpose=request.purpose,
                    context_package=context_result.context_package,
                    instructions=request.instructions,
                )
            )
        except Exception as exc:  # pragma: no cover - exercised by monkeypatch in tests
            error = PersistencePromptPackageError("prompt_package_failed", str(exc), "prompt_package")
            return _failure("prompt_package_failed", request.workspace_id, context_result, error)
        llm_request = _llm_request_from_prompt(prompt_package, request) if request.include_llm_request else None
        return PersistencePromptPackageResult(
            ok=True,
            status="completed_with_prompt_package" if llm_request is None else "completed_with_prompt_package_and_llm_request_shape",
            workspace_id=context_result.workspace_id,
            context_handoff=context_result,
            prompt_package=prompt_package,
            llm_request=llm_request,
        )

    def build_llm_execution_request(self, request: PersistencePromptPackageRequest) -> PersistencePromptPackageResult:
        request_with_shape = PersistencePromptPackageRequest(
            workspace_id=request.workspace_id,
            records=request.records,
            backend=request.backend,
            use_backend=request.use_backend,
            query=request.query,
            purpose=request.purpose,
            instructions=request.instructions,
            limit=request.limit,
            max_candidates=request.max_candidates,
            max_context_chars=request.max_context_chars,
            snippet_chars=request.snippet_chars,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            circuit_state=request.circuit_state,
            include_llm_request=True,
        )
        return self.build_prompt_package(request_with_shape)


def build_prompt_package_from_persisted_records(
    request_or_records: PersistencePromptPackageRequest | Sequence[ContentPersistenceRecord | Mapping[str, Any] | Any],
    *,
    workspace_id: str | None = None,
    backend: Any | None = None,
    use_backend: bool = False,
    query: str = "",
    purpose: str = "answer",
    instructions: str = "Answer only from the supplied evidence. If evidence is insufficient, return no_context.",
    limit: int = 10,
    max_candidates: int = 8,
    max_context_chars: int = 4000,
    snippet_chars: int = 600,
) -> PersistencePromptPackageResult:
    request = _coerce_request(
        request_or_records,
        workspace_id=workspace_id,
        backend=backend,
        use_backend=use_backend,
        query=query,
        purpose=purpose,
        instructions=instructions,
        limit=limit,
        max_candidates=max_candidates,
        max_context_chars=max_context_chars,
        snippet_chars=snippet_chars,
        include_llm_request=False,
    )
    return PublicSafePersistencePromptPackageHandoff().build_prompt_package(request)


def build_llm_execution_request_from_persisted_records(
    request_or_records: PersistencePromptPackageRequest | Sequence[ContentPersistenceRecord | Mapping[str, Any] | Any],
    *,
    workspace_id: str | None = None,
    backend: Any | None = None,
    use_backend: bool = False,
    query: str = "",
    purpose: str = "answer",
    instructions: str = "Answer only from the supplied evidence. If evidence is insufficient, return no_context.",
    limit: int = 10,
    max_candidates: int = 8,
    max_context_chars: int = 4000,
    snippet_chars: int = 600,
    max_tokens: int = 512,
    temperature: float = 0.0,
    circuit_state: str = "unknown",
) -> PersistencePromptPackageResult:
    request = _coerce_request(
        request_or_records,
        workspace_id=workspace_id,
        backend=backend,
        use_backend=use_backend,
        query=query,
        purpose=purpose,
        instructions=instructions,
        limit=limit,
        max_candidates=max_candidates,
        max_context_chars=max_context_chars,
        snippet_chars=snippet_chars,
        max_tokens=max_tokens,
        temperature=temperature,
        circuit_state=circuit_state,
        include_llm_request=True,
    )
    return PublicSafePersistencePromptPackageHandoff().build_llm_execution_request(request)


def _coerce_request(
    request_or_records: PersistencePromptPackageRequest | Sequence[ContentPersistenceRecord | Mapping[str, Any] | Any],
    *,
    workspace_id: str | None,
    backend: Any | None,
    use_backend: bool,
    query: str,
    purpose: str,
    instructions: str,
    limit: int,
    max_candidates: int,
    max_context_chars: int,
    snippet_chars: int,
    max_tokens: int = 512,
    temperature: float = 0.0,
    circuit_state: str = "unknown",
    include_llm_request: bool = False,
) -> PersistencePromptPackageRequest:
    if isinstance(request_or_records, PersistencePromptPackageRequest):
        return request_or_records
    return PersistencePromptPackageRequest(
        workspace_id=workspace_id or "",
        records=tuple(request_or_records or ()),
        backend=backend,
        use_backend=use_backend,
        query=query,
        purpose=purpose,
        instructions=instructions,
        limit=limit,
        max_candidates=max_candidates,
        max_context_chars=max_context_chars,
        snippet_chars=snippet_chars,
        max_tokens=max_tokens,
        temperature=temperature,
        circuit_state=circuit_state,
        include_llm_request=include_llm_request,
    )


def _build_context_result(request: PersistencePromptPackageRequest) -> PersistenceRetrievalHandoffResult:
    b28_request = PersistenceRetrievalCandidateRequest(
        workspace_id=request.workspace_id,
        records=request.records,
        backend=request.backend,
        use_backend=request.use_backend,
        query=request.query,
        purpose=request.purpose,
        limit=request.limit,
        max_candidates=request.max_candidates,
        max_context_chars=request.max_context_chars,
        snippet_chars=request.snippet_chars,
    )
    return build_context_package_from_persisted_records(b28_request)


def _llm_request_from_prompt(prompt_package: PromptPackage, request: PersistencePromptPackageRequest) -> LLMExecutionRequest:
    return LLMExecutionRequest(
        prompt=prompt_package.prompt,
        system=prompt_package.system,
        expected_schema=prompt_package.expected_schema,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        live_mode_enabled=False,
        allow_fake_backend=False,
        backend_name="none",
        circuit_state=request.circuit_state,
        evidence_count=len(prompt_package.evidence_ids),
        metadata={
            "b29_mode": B29_PROMPT_HANDOFF_MODE,
            "workspace_id": request.workspace_id.strip() if isinstance(request.workspace_id, str) else request.workspace_id,
            "purpose": request.purpose,
            "non_claims": B29_NON_CLAIMS,
        },
    )


def _error_from_context_result(result: PersistenceRetrievalHandoffResult) -> PersistencePromptPackageError:
    if not result.errors:
        return PersistencePromptPackageError("context_package_failed", "B28 context handoff failed without a structured error", "context_package")
    first = result.errors[0]
    code = _map_context_error_code(first.code, result.status)
    return PersistencePromptPackageError(code, first.message, first.field)


def _map_context_error_code(code: str, status: str) -> str:
    mapping = {
        "invalid_workspace_id": "invalid_workspace",
        "workspace_boundary_violation": "boundary_violation",
        "backend_required": "backend_required",
        "backend_result_failed": "backend_result_failed",
        "no_usable_records": "no_usable_records",
    }
    return mapping.get(code, "context_package_failed" if status == "context_package_failed" else code)


def _status_for_error(code: str) -> str:
    mapping = {
        "invalid_workspace": "invalid_workspace",
        "boundary_violation": "boundary_violation",
        "backend_required": "backend_required",
        "backend_result_failed": "backend_result_failed",
        "no_usable_records": "no_usable_records",
        "prompt_package_failed": "prompt_package_failed",
        "context_package_failed": "context_package_failed",
    }
    return mapping.get(code, "context_package_failed")


def _failure(
    status: str,
    workspace_id: str,
    context_handoff: PersistenceRetrievalHandoffResult | None,
    *errors: PersistencePromptPackageError,
) -> PersistencePromptPackageResult:
    return PersistencePromptPackageResult(
        ok=False,
        status=status,
        workspace_id=workspace_id,
        context_handoff=context_handoff,
        errors=tuple(errors),
        capability_metadata=PersistencePromptCapabilityMetadata(degraded_reason=status),
    )
