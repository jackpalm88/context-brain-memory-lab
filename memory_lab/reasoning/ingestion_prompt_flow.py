"""B30 public-safe supplied-text to prompt-request flow contract.

This module composes existing deterministic public-safe contracts over caller
supplied values only. It turns supplied text into B27 ingestion output, creates
or uses B26-shaped persistence records, delegates context/prompt packaging to
B29/B28/B23, and can return a B22-compatible request shape with execution
explicitly disabled. It does not add runtime wiring, storage adapters, remote
fetching, model execution, wrapper exposure, or production-readiness behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
import hashlib
import json
from typing import Any, Mapping, Sequence

from memory_lab.ingestion.pipeline_contract import IngestionPipelineRequest, IngestionPipelineResult, run_ingestion_pipeline
from memory_lab.persistence.results import ContentPersistenceRecord
from memory_lab.reasoning.llm_executor import LLMExecutionRequest
from memory_lab.reasoning.persistence_prompt_handoff import (
    PersistencePromptPackageResult,
    build_llm_execution_request_from_persisted_records,
    build_prompt_package_from_persisted_records,
)
from memory_lab.reasoning.prompt_package import PromptPackage

B30_PROMPT_FLOW_MODE = "b30_public_safe_supplied_text_to_prompt_request_flow_contract_v1"
B30_LIMITATIONS: tuple[str, ...] = (
    "supplied_text_to_prompt_request_flow_contract_only",
    "caller_supplied_text_only",
    "requires_explicit_workspace_id",
    "requires_explicit_content_id",
    "composes_b27_ingestion_b26_records_b28_b29_b23_prompt_and_b22_request_shape",
    "direct_record_mode_requires_no_backend",
    "supplied_b26_backend_is_optional_and_explicit",
    "supplied_backend_write_only_when_requested",
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
    "no_private_memory_access",
    "no_api_or_mcp_runtime",
    "no_embedding_generation",
    "no_vector_db_access",
    "no_wrapper_descriptor_update",
    "no_docs_capabilities_alignment",
)
B30_NON_CLAIMS: tuple[str, ...] = (
    "not_production_ready",
    "not_live_memory_retrieval",
    "not_semantic_search",
    "not_db_backed_retrieval",
    "not_db_backed_production_persistence",
    "not_live_ingestion_runtime",
    "not_provider_backed_reasoning",
    "not_llm_execution",
    "not_embedding_or_vector_retrieval",
    "not_private_context_brain_parity",
    "not_full_context_brain_parity",
    "not_api_or_mcp_runtime",
    "not_mcp_or_gpt_actions_production_ready",
    "not_prompt_quality_or_truth_claim",
    "not_wrapper_descriptor_update",
    "not_docs_capabilities_alignment",
)


@dataclass(frozen=True)
class SuppliedTextPromptFlowCapabilityMetadata:
    capability: str = "b30_supplied_text_to_prompt_request_flow_contract"
    mode: str = B30_PROMPT_FLOW_MODE
    input_scope: str = "caller_supplied_text_and_optional_supplied_b26_backend_only"
    live_backend_used: bool = False
    requires_db: bool = False
    requires_provider: bool = False
    requires_private_context_brain: bool = False
    uses_embeddings: bool = False
    uses_vector_db: bool = False
    executes_llm: bool = False
    production_runtime: bool = False
    mutates_external_state: bool = False
    api_runtime: bool = False
    mcp_runtime: bool = False
    supplied_backend_write_possible: bool = True
    external_state_mutation: bool = False
    db_persistence: bool = False
    limitations: tuple[str, ...] = B30_LIMITATIONS
    non_claims: tuple[str, ...] = B30_NON_CLAIMS
    degraded_reason: str | None = None


@dataclass(frozen=True)
class SuppliedTextPromptFlowRequest:
    workspace_id: str
    content_id: str
    text: str
    title: str = ""
    source_ref: str | None = None
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)
    hub_candidates: Sequence[Mapping[str, Any]] = dataclass_field(default_factory=tuple)
    tag_candidates: Sequence[str] = dataclass_field(default_factory=tuple)
    circuit_events: Sequence[Any] = dataclass_field(default_factory=tuple)
    circuit_now: float = 0.0
    backend: Any | None = None
    use_supplied_backend: bool = False
    persist_to_supplied_backend: bool = False
    query: str = ""
    purpose: str = "answer"
    instructions: str = "Answer only from the supplied evidence. If evidence is insufficient, return no_context."
    limit: int = 10
    max_candidates: int = 8
    max_context_chars: int = 4000
    snippet_chars: int = 600
    include_llm_request: bool = False
    max_tokens: int = 512
    temperature: float = 0.0
    circuit_state: str = "unknown"


@dataclass(frozen=True)
class SuppliedTextPromptFlowError:
    code: str
    message: str
    field: str | None = None
    limitations: tuple[str, ...] = B30_LIMITATIONS
    non_claims: tuple[str, ...] = B30_NON_CLAIMS
    capability_metadata: SuppliedTextPromptFlowCapabilityMetadata = dataclass_field(
        default_factory=lambda: SuppliedTextPromptFlowCapabilityMetadata(degraded_reason="prompt_flow_error")
    )


@dataclass(frozen=True)
class SuppliedTextPromptFlowResult:
    ok: bool
    status: str
    request_id: str
    workspace_id: str
    content_id: str
    ingestion_result: IngestionPipelineResult | None = None
    persistence_record: ContentPersistenceRecord | None = None
    prompt_handoff: PersistencePromptPackageResult | None = None
    prompt_package: PromptPackage | None = None
    llm_request: LLMExecutionRequest | None = None
    errors: tuple[SuppliedTextPromptFlowError, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = B30_LIMITATIONS
    non_claims: tuple[str, ...] = B30_NON_CLAIMS
    capability_metadata: SuppliedTextPromptFlowCapabilityMetadata = dataclass_field(default_factory=SuppliedTextPromptFlowCapabilityMetadata)
    mode: str = B30_PROMPT_FLOW_MODE


class PublicSafeSuppliedTextPromptFlow:
    """Deterministic B30 flow over supplied text and optional supplied backend."""

    name = "PublicSafeSuppliedTextPromptFlow"
    mode = B30_PROMPT_FLOW_MODE
    limitations = B30_LIMITATIONS
    non_claims = B30_NON_CLAIMS

    def build_prompt_package(self, request: SuppliedTextPromptFlowRequest) -> SuppliedTextPromptFlowResult:
        request_without_shape = _request_with_llm_shape(request, include_llm_request=False)
        return self._run(request_without_shape)

    def build_prompt_request(self, request: SuppliedTextPromptFlowRequest) -> SuppliedTextPromptFlowResult:
        request_with_shape = _request_with_llm_shape(request, include_llm_request=True)
        return self._run(request_with_shape)

    def _run(self, request: SuppliedTextPromptFlowRequest) -> SuppliedTextPromptFlowResult:
        request_id = _request_id(request)
        ingestion_request = IngestionPipelineRequest(
            workspace_id=request.workspace_id,
            content_id=request.content_id,
            text=request.text,
            title=request.title,
            source_ref=request.source_ref,
            metadata=request.metadata,
            hub_candidates=request.hub_candidates,
            tag_candidates=request.tag_candidates,
            circuit_events=request.circuit_events,
            circuit_now=request.circuit_now,
            persist=request.persist_to_supplied_backend,
        )
        ingestion_result = run_ingestion_pipeline(ingestion_request, backend=request.backend)
        if not ingestion_result.ok:
            error = _error_from_ingestion(ingestion_result)
            return _failure(_status_for_error(error.code), request, request_id, ingestion_result, None, None, error)

        record = _record_from_ingestion(request, ingestion_result)
        if request.use_supplied_backend:
            if request.backend is None:
                error = SuppliedTextPromptFlowError("persistence_backend_required", "supplied backend mode requires a caller-supplied B26-compatible backend", "backend")
                return _failure("persistence_backend_required", request, request_id, ingestion_result, record, None, error)
            records: tuple[ContentPersistenceRecord, ...] = ()
            use_backend = True
            backend = request.backend
        else:
            records = (record,)
            use_backend = False
            backend = None

        try:
            if request.include_llm_request:
                prompt_handoff = build_llm_execution_request_from_persisted_records(
                    records,
                    workspace_id=request.workspace_id,
                    backend=backend,
                    use_backend=use_backend,
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
                )
            else:
                prompt_handoff = build_prompt_package_from_persisted_records(
                    records,
                    workspace_id=request.workspace_id,
                    backend=backend,
                    use_backend=use_backend,
                    query=request.query,
                    purpose=request.purpose,
                    instructions=request.instructions,
                    limit=request.limit,
                    max_candidates=request.max_candidates,
                    max_context_chars=request.max_context_chars,
                    snippet_chars=request.snippet_chars,
                )
        except Exception as exc:  # pragma: no cover - defensive contract boundary
            error = SuppliedTextPromptFlowError("prompt_package_failed", str(exc), "prompt_package")
            return _failure("prompt_package_failed", request, request_id, ingestion_result, record, None, error)

        if not prompt_handoff.ok:
            error = _error_from_prompt_handoff(prompt_handoff)
            return _failure(_status_for_error(error.code), request, request_id, ingestion_result, record, prompt_handoff, error)
        if prompt_handoff.prompt_package is None:
            error = SuppliedTextPromptFlowError("prompt_package_failed", "B29 handoff did not return a prompt package", "prompt_package")
            return _failure("prompt_package_failed", request, request_id, ingestion_result, record, prompt_handoff, error)
        if request.include_llm_request and prompt_handoff.llm_request is None:
            error = SuppliedTextPromptFlowError("llm_request_shape_failed", "B29 handoff did not return a B22-compatible request shape", "llm_request")
            return _failure("llm_request_shape_failed", request, request_id, ingestion_result, record, prompt_handoff, error)

        status = "completed_with_prompt_package_and_llm_request_shape" if request.include_llm_request else "completed_with_prompt_package"
        warnings = _warnings_from(ingestion_result, prompt_handoff)
        return SuppliedTextPromptFlowResult(
            ok=True,
            status=status,
            request_id=request_id,
            workspace_id=request.workspace_id,
            content_id=request.content_id,
            ingestion_result=ingestion_result,
            persistence_record=record,
            prompt_handoff=prompt_handoff,
            prompt_package=prompt_handoff.prompt_package,
            llm_request=prompt_handoff.llm_request,
            warnings=warnings,
        )


def build_prompt_package_from_supplied_text(request: SuppliedTextPromptFlowRequest) -> SuppliedTextPromptFlowResult:
    return PublicSafeSuppliedTextPromptFlow().build_prompt_package(request)


def build_prompt_request_from_supplied_text(request: SuppliedTextPromptFlowRequest) -> SuppliedTextPromptFlowResult:
    return PublicSafeSuppliedTextPromptFlow().build_prompt_request(request)


def _request_with_llm_shape(request: SuppliedTextPromptFlowRequest, *, include_llm_request: bool) -> SuppliedTextPromptFlowRequest:
    return SuppliedTextPromptFlowRequest(
        workspace_id=request.workspace_id,
        content_id=request.content_id,
        text=request.text,
        title=request.title,
        source_ref=request.source_ref,
        metadata=request.metadata,
        hub_candidates=request.hub_candidates,
        tag_candidates=request.tag_candidates,
        circuit_events=request.circuit_events,
        circuit_now=request.circuit_now,
        backend=request.backend,
        use_supplied_backend=request.use_supplied_backend,
        persist_to_supplied_backend=request.persist_to_supplied_backend,
        query=request.query,
        purpose=request.purpose,
        instructions=request.instructions,
        limit=request.limit,
        max_candidates=request.max_candidates,
        max_context_chars=request.max_context_chars,
        snippet_chars=request.snippet_chars,
        include_llm_request=include_llm_request,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        circuit_state=request.circuit_state,
    )


def _record_from_ingestion(request: SuppliedTextPromptFlowRequest, ingestion_result: IngestionPipelineResult) -> ContentPersistenceRecord:
    existing = _record_from_persistence_value(getattr(ingestion_result, "persistence", None))
    if existing is not None:
        return existing
    metadata = {
        **dict(request.metadata or {}),
        "source_ref": request.source_ref,
        "domain": getattr(getattr(ingestion_result, "domain", None), "domain", "unknown"),
        "hubs": tuple(getattr(getattr(ingestion_result, "hubs", None), "hub_candidates", ())),
        "tags": tuple(getattr(getattr(ingestion_result, "tags", None), "tags", ())),
        "chunk_count": len(tuple(getattr(ingestion_result, "chunks", ()) or ())),
        "scoring_composite": _scoring_composite(getattr(ingestion_result, "scoring", None)),
        "tier_recommendation": getattr(getattr(ingestion_result, "tier_plan", None), "recommended_tier", None),
        "b27_mode": getattr(ingestion_result, "mode", None),
        "b30_mode": B30_PROMPT_FLOW_MODE,
    }
    return ContentPersistenceRecord(
        content_id=request.content_id.strip(),
        workspace_id=request.workspace_id.strip(),
        text=getattr(getattr(ingestion_result, "extraction", None), "extracted_text", request.text),
        title=request.title or None,
        metadata=metadata,
    )


def _record_from_persistence_value(persistence: Any) -> ContentPersistenceRecord | None:
    if not isinstance(persistence, Mapping):
        return None
    result = persistence.get("result")
    value = getattr(result, "value", None)
    return value if isinstance(value, ContentPersistenceRecord) else None


def _scoring_composite(scoring: Any) -> float | None:
    score = getattr(scoring, "score", None)
    value = getattr(score, "composite", None)
    return float(value) if value is not None else None


def _error_from_ingestion(result: IngestionPipelineResult) -> SuppliedTextPromptFlowError:
    if not result.errors:
        return SuppliedTextPromptFlowError("ingestion_pipeline_failed", "B27 ingestion pipeline failed without a structured error", None)
    first = result.errors[0]
    mapping = {
        "invalid_workspace_id": "invalid_workspace",
        "missing_text": "missing_text",
        "missing_content_id": "missing_content_id",
        "persistence_backend_required": "persistence_backend_required",
    }
    code = mapping.get(first.code, "persistence_backend_failed" if first.code else "ingestion_pipeline_failed")
    if first.code not in mapping and result.status != "persistence_error":
        code = "ingestion_pipeline_failed"
    return SuppliedTextPromptFlowError(code, first.message, first.field)


def _error_from_prompt_handoff(result: PersistencePromptPackageResult) -> SuppliedTextPromptFlowError:
    if not result.errors:
        return SuppliedTextPromptFlowError("prompt_package_failed", "B29 prompt handoff failed without a structured error", None)
    first = result.errors[0]
    mapping = {
        "invalid_workspace": "invalid_workspace",
        "boundary_violation": "boundary_violation",
        "backend_required": "persistence_backend_required",
        "backend_result_failed": "persistence_backend_failed",
        "context_package_failed": "context_package_failed",
        "prompt_package_failed": "prompt_package_failed",
        "no_usable_records": "context_package_failed",
    }
    return SuppliedTextPromptFlowError(mapping.get(first.code, "prompt_package_failed"), first.message, first.field)


def _status_for_error(code: str) -> str:
    mapping = {
        "invalid_workspace": "invalid_workspace",
        "missing_text": "missing_text",
        "missing_content_id": "missing_content_id",
        "ingestion_pipeline_failed": "ingestion_pipeline_failed",
        "persistence_backend_required": "persistence_backend_required",
        "persistence_backend_failed": "persistence_backend_failed",
        "context_package_failed": "context_package_failed",
        "prompt_package_failed": "prompt_package_failed",
        "llm_request_shape_failed": "llm_request_shape_failed",
        "boundary_violation": "boundary_violation",
    }
    return mapping.get(code, "prompt_package_failed")


def _failure(
    status: str,
    request: SuppliedTextPromptFlowRequest,
    request_id: str,
    ingestion_result: IngestionPipelineResult | None,
    record: ContentPersistenceRecord | None,
    prompt_handoff: PersistencePromptPackageResult | None,
    *errors: SuppliedTextPromptFlowError,
) -> SuppliedTextPromptFlowResult:
    return SuppliedTextPromptFlowResult(
        ok=False,
        status=status,
        request_id=request_id,
        workspace_id=request.workspace_id,
        content_id=request.content_id,
        ingestion_result=ingestion_result,
        persistence_record=record,
        prompt_handoff=prompt_handoff,
        errors=tuple(errors),
        capability_metadata=SuppliedTextPromptFlowCapabilityMetadata(degraded_reason=status),
    )


def _warnings_from(ingestion_result: IngestionPipelineResult, prompt_handoff: PersistencePromptPackageResult) -> tuple[str, ...]:
    return tuple(ingestion_result.warnings or ()) + tuple(prompt_handoff.warnings or ())


def _request_id(request: SuppliedTextPromptFlowRequest) -> str:
    payload = {
        "workspace_id": request.workspace_id,
        "content_id": request.content_id,
        "text": request.text,
        "title": request.title,
        "source_ref": request.source_ref,
        "metadata": _jsonable(request.metadata),
        "hub_candidates": _jsonable(request.hub_candidates),
        "tag_candidates": _jsonable(request.tag_candidates),
        "use_supplied_backend": request.use_supplied_backend,
        "persist_to_supplied_backend": request.persist_to_supplied_backend,
        "query": request.query,
        "purpose": request.purpose,
        "instructions": request.instructions,
        "limit": request.limit,
        "max_candidates": request.max_candidates,
        "max_context_chars": request.max_context_chars,
        "snippet_chars": request.snippet_chars,
        "include_llm_request": request.include_llm_request,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
        "circuit_state": request.circuit_state,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "b30-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_jsonable(item) for item in value)
    return value
