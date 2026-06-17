"""B28 public-safe persistence-to-retrieval handoff contract.

This module turns caller-supplied persistence records, or records listed from a
caller-supplied B26 backend, into B23 supplied-input retrieval candidates. It is
contract-only and deterministic: it does not open storage connections, fetch
remote content, call model services, generate embeddings, use vector storage, or
access private Context Brain memory.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Mapping, Sequence

from memory_lab.governance.workspace import validate_workspace_id
from memory_lab.persistence.results import ContentPersistenceRecord, PersistenceResult
from memory_lab.retrieval.context_candidates import ContextCandidateBuildRequest, ContextCandidatePackage, build_context_candidates
from memory_lab.retrieval.search_by_purpose import SearchByPurposeRequest, SearchByPurposeResponse, SuppliedSearchCandidate, rank_context_candidates_by_purpose

B28_HANDOFF_MODE = "b28_public_safe_persistence_to_retrieval_handoff_v1"
B28_LIMITATIONS: tuple[str, ...] = (
    "persistence_to_retrieval_handoff_contract_only",
    "caller_supplied_records_only",
    "optional_supplied_b26_backend_list_only",
    "workspace_boundary_validation_over_supplied_values",
    "deterministic_candidate_mapping_only",
    "metadata_is_public_safe_subset_only",
    "no_live_backend_connection",
    "no_database_access",
    "no_provider_call",
    "no_private_context_brain_access",
    "no_api_or_mcp_runtime",
    "no_embedding_generation",
    "no_vector_db_access",
    "no_external_state_mutation",
)
B28_NON_CLAIMS: tuple[str, ...] = (
    "not_live_memory_retrieval",
    "not_semantic_search",
    "not_db_backed_retrieval",
    "not_db_backed_production_persistence",
    "not_provider_backed_reasoning",
    "not_embedding_or_vector_retrieval",
    "not_private_context_brain_parity",
    "not_full_context_brain_parity",
    "not_api_or_mcp_runtime",
    "not_production_ready",
)

_SAFE_METADATA_KEYS = (
    "domain",
    "tags",
    "hubs",
    "source_ref",
    "source_ref_role",
    "chunk_count",
    "scoring_composite",
    "tier_recommendation",
    "b27_mode",
)


@dataclass(frozen=True)
class PersistenceRetrievalCapabilityMetadata:
    capability: str = "b28_persistence_to_retrieval_handoff_contract"
    mode: str = B28_HANDOFF_MODE
    input_scope: str = "caller_supplied_records_or_supplied_b26_backend_list_only"
    live_backend_used: bool = False
    requires_db: bool = False
    requires_provider: bool = False
    requires_private_context_brain: bool = False
    uses_embeddings: bool = False
    uses_vector_db: bool = False
    mutates_external_state: bool = False
    limitations: tuple[str, ...] = B28_LIMITATIONS
    non_claims: tuple[str, ...] = B28_NON_CLAIMS
    degraded_reason: str | None = None


@dataclass(frozen=True)
class PersistenceRetrievalCandidateRequest:
    workspace_id: str
    records: Sequence[ContentPersistenceRecord | Mapping[str, Any] | Any] = dataclass_field(default_factory=tuple)
    backend: Any | None = None
    use_backend: bool = False
    query: str = ""
    purpose: str = "answer"
    limit: int = 10
    max_candidates: int = 8
    max_context_chars: int = 4000
    snippet_chars: int = 600


@dataclass(frozen=True)
class PersistenceRetrievalCandidate:
    item_id: str
    workspace_id: str
    supplied_candidate: SuppliedSearchCandidate
    limitations: tuple[str, ...] = B28_LIMITATIONS
    non_claims: tuple[str, ...] = B28_NON_CLAIMS
    capability_metadata: PersistenceRetrievalCapabilityMetadata = dataclass_field(default_factory=PersistenceRetrievalCapabilityMetadata)


@dataclass(frozen=True)
class PersistenceRetrievalHandoffError:
    code: str
    message: str
    field: str | None = None
    limitations: tuple[str, ...] = B28_LIMITATIONS
    non_claims: tuple[str, ...] = B28_NON_CLAIMS
    capability_metadata: PersistenceRetrievalCapabilityMetadata = dataclass_field(
        default_factory=lambda: PersistenceRetrievalCapabilityMetadata(degraded_reason="handoff_error")
    )


@dataclass(frozen=True)
class PersistenceRetrievalHandoffResult:
    ok: bool
    status: str
    workspace_id: str
    candidates: tuple[SuppliedSearchCandidate, ...] = ()
    handoff_candidates: tuple[PersistenceRetrievalCandidate, ...] = ()
    ranked: SearchByPurposeResponse | None = None
    context_package: ContextCandidatePackage | None = None
    errors: tuple[PersistenceRetrievalHandoffError, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = B28_LIMITATIONS
    non_claims: tuple[str, ...] = B28_NON_CLAIMS
    capability_metadata: PersistenceRetrievalCapabilityMetadata = dataclass_field(default_factory=PersistenceRetrievalCapabilityMetadata)
    mode: str = B28_HANDOFF_MODE


class PublicSafePersistenceRetrievalHandoff:
    """Deterministic B28 bridge from supplied persistence records to B23 inputs."""

    name = "PublicSafePersistenceRetrievalHandoff"
    mode = B28_HANDOFF_MODE
    limitations = B28_LIMITATIONS
    non_claims = B28_NON_CLAIMS

    def build_candidates(self, request: PersistenceRetrievalCandidateRequest) -> PersistenceRetrievalHandoffResult:
        validation_error = _workspace_error(request.workspace_id)
        if validation_error is not None:
            return _failure("invalid_workspace", request.workspace_id, validation_error)

        records_result = _records_from_request(request)
        if isinstance(records_result, PersistenceRetrievalHandoffError):
            return _failure(_status_for_error(records_result.code), request.workspace_id, records_result)

        candidates: list[PersistenceRetrievalCandidate] = []
        errors: list[PersistenceRetrievalHandoffError] = []
        for record in records_result:
            candidate_or_error = _candidate_from_record(record, request)
            if isinstance(candidate_or_error, PersistenceRetrievalHandoffError):
                errors.append(candidate_or_error)
                continue
            candidates.append(candidate_or_error)

        if errors:
            first = errors[0]
            return _failure(_status_for_error(first.code), request.workspace_id, *errors)
        if not candidates:
            return _failure(
                "no_usable_records",
                request.workspace_id,
                PersistenceRetrievalHandoffError("no_usable_records", "no usable records were supplied for handoff", "records"),
            )

        candidates.sort(key=lambda item: item.item_id)
        supplied = tuple(item.supplied_candidate for item in candidates)
        return PersistenceRetrievalHandoffResult(
            ok=True,
            status="completed",
            workspace_id=request.workspace_id.strip(),
            candidates=supplied,
            handoff_candidates=tuple(candidates),
        )

    def build_context_package(self, request: PersistenceRetrievalCandidateRequest) -> PersistenceRetrievalHandoffResult:
        result = self.build_candidates(request)
        if not result.ok:
            return result
        ranked = rank_context_candidates_by_purpose(
            SearchByPurposeRequest(query=request.query, purpose=request.purpose, candidates=result.candidates, limit=request.limit)
        )
        context_package = build_context_candidates(
            ContextCandidateBuildRequest(
                query=request.query,
                ranked_candidates=ranked.results,
                max_candidates=request.max_candidates,
                max_context_chars=request.max_context_chars,
                snippet_chars=request.snippet_chars,
            )
        )
        return PersistenceRetrievalHandoffResult(
            ok=True,
            status="completed_with_context_package",
            workspace_id=result.workspace_id,
            candidates=result.candidates,
            handoff_candidates=result.handoff_candidates,
            ranked=ranked,
            context_package=context_package,
        )


def build_retrieval_candidates_from_records(
    request_or_records: PersistenceRetrievalCandidateRequest | Sequence[ContentPersistenceRecord | Mapping[str, Any] | Any],
    *,
    workspace_id: str | None = None,
    backend: Any | None = None,
    use_backend: bool = False,
    query: str = "",
    purpose: str = "answer",
    limit: int = 10,
) -> PersistenceRetrievalHandoffResult:
    request = _coerce_request(request_or_records, workspace_id=workspace_id, backend=backend, use_backend=use_backend, query=query, purpose=purpose, limit=limit)
    return PublicSafePersistenceRetrievalHandoff().build_candidates(request)


def build_context_package_from_persisted_records(
    request_or_records: PersistenceRetrievalCandidateRequest | Sequence[ContentPersistenceRecord | Mapping[str, Any] | Any],
    *,
    workspace_id: str | None = None,
    backend: Any | None = None,
    use_backend: bool = False,
    query: str = "",
    purpose: str = "answer",
    limit: int = 10,
    max_candidates: int = 8,
    max_context_chars: int = 4000,
    snippet_chars: int = 600,
) -> PersistenceRetrievalHandoffResult:
    request = _coerce_request(
        request_or_records,
        workspace_id=workspace_id,
        backend=backend,
        use_backend=use_backend,
        query=query,
        purpose=purpose,
        limit=limit,
        max_candidates=max_candidates,
        max_context_chars=max_context_chars,
        snippet_chars=snippet_chars,
    )
    return PublicSafePersistenceRetrievalHandoff().build_context_package(request)


def _coerce_request(
    request_or_records: PersistenceRetrievalCandidateRequest | Sequence[ContentPersistenceRecord | Mapping[str, Any] | Any],
    *,
    workspace_id: str | None,
    backend: Any | None,
    use_backend: bool,
    query: str,
    purpose: str,
    limit: int,
    max_candidates: int = 8,
    max_context_chars: int = 4000,
    snippet_chars: int = 600,
) -> PersistenceRetrievalCandidateRequest:
    if isinstance(request_or_records, PersistenceRetrievalCandidateRequest):
        return request_or_records
    return PersistenceRetrievalCandidateRequest(
        workspace_id=workspace_id or "",
        records=tuple(request_or_records or ()),
        backend=backend,
        use_backend=use_backend,
        query=query,
        purpose=purpose,
        limit=limit,
        max_candidates=max_candidates,
        max_context_chars=max_context_chars,
        snippet_chars=snippet_chars,
    )


def _workspace_error(workspace_id: str) -> PersistenceRetrievalHandoffError | None:
    check = validate_workspace_id(workspace_id)
    if check.valid:
        return None
    return PersistenceRetrievalHandoffError("invalid_workspace_id", "; ".join(check.errors), "workspace_id")


def _records_from_request(request: PersistenceRetrievalCandidateRequest) -> tuple[Any, ...] | PersistenceRetrievalHandoffError:
    direct_records = tuple(request.records or ())
    if direct_records:
        return direct_records
    if not request.use_backend:
        return ()
    if request.backend is None:
        return PersistenceRetrievalHandoffError("backend_required", "use_backend=True requires a caller-supplied B26 backend", "backend")
    list_method = getattr(request.backend, "list_content_records", None)
    if not callable(list_method):
        return PersistenceRetrievalHandoffError("backend_required", "supplied backend must provide list_content_records", "backend")
    result = list_method(request.workspace_id.strip())
    if isinstance(result, PersistenceResult):
        if not result.ok:
            message = result.error.message if result.error else "supplied B26 backend returned failure"
            field_name = result.error.field if result.error else "backend"
            return PersistenceRetrievalHandoffError("backend_result_failed", message, field_name)
        value = result.value
    elif isinstance(result, Mapping) and result.get("ok") is False:
        return PersistenceRetrievalHandoffError("backend_result_failed", str(result.get("error") or "supplied backend returned failure"), "backend")
    else:
        value = result
    return tuple(value or ())


def _candidate_from_record(record: Any, request: PersistenceRetrievalCandidateRequest) -> PersistenceRetrievalCandidate | PersistenceRetrievalHandoffError:
    workspace_id = _record_field(record, "workspace_id")
    content_id = _record_field(record, "content_id") or _record_field(record, "record_id") or _record_field(record, "item_id")
    if not isinstance(workspace_id, str) or workspace_id.strip() != request.workspace_id.strip():
        return PersistenceRetrievalHandoffError("workspace_boundary_violation", "record workspace_id does not match requested workspace_id", "workspace_id")
    if not isinstance(content_id, str) or not content_id.strip():
        return PersistenceRetrievalHandoffError("invalid_record", "record content_id is required", "content_id")
    text = str(_record_field(record, "text") or _record_field(record, "content") or "")
    title = str(_record_field(record, "title") or "")
    metadata = _record_metadata(record)
    snippet = _bounded_snippet(text, request.snippet_chars)
    tags = _tuple_str(metadata.get("tags"))
    domain = _optional_str(metadata.get("domain"))
    supplied = SuppliedSearchCandidate(
        item_id=content_id.strip(),
        text=text,
        snippet=snippet,
        purpose_text=_purpose_text(title, metadata),
        domain=domain,
        tags=tags,
        source_metadata=_safe_metadata(metadata),
        ingestion_score=_optional_float(metadata.get("scoring_composite")),
        tier=_optional_str(metadata.get("tier_recommendation")),
    )
    return PersistenceRetrievalCandidate(item_id=content_id.strip(), workspace_id=workspace_id.strip(), supplied_candidate=supplied)


def _record_field(record: Any, field_name: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(field_name)
    return getattr(record, field_name, None)


def _record_metadata(record: Any) -> Mapping[str, Any]:
    value = _record_field(record, "metadata")
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: metadata[key] for key in _SAFE_METADATA_KEYS if key in metadata}


def _purpose_text(title: str, metadata: Mapping[str, Any]) -> str:
    parts = [title.strip()]
    for key in ("domain", "tier_recommendation", "source_ref_role"):
        value = metadata.get(key)
        if value:
            parts.append(f"{key}:{value}")
    tags = ",".join(_tuple_str(metadata.get("tags")))
    if tags:
        parts.append(f"tags:{tags}")
    return " ".join(part for part in parts if part)


def _bounded_snippet(text: str, snippet_chars: int) -> str:
    try:
        limit = int(snippet_chars)
    except (TypeError, ValueError):
        limit = 600
    return text.strip()[: max(0, min(limit, 4000))]


def _tuple_str(value: Any) -> tuple[str, ...]:
    if value is None or isinstance(value, (str, bytes)):
        return (str(value),) if isinstance(value, str) and value else ()
    try:
        return tuple(str(item) for item in value if str(item))
    except TypeError:
        return ()


def _optional_str(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return max(0.0, min(1.0, number))


def _failure(status: str, workspace_id: str, *errors: PersistenceRetrievalHandoffError) -> PersistenceRetrievalHandoffResult:
    return PersistenceRetrievalHandoffResult(
        ok=False,
        status=status,
        workspace_id=workspace_id,
        errors=tuple(errors),
        capability_metadata=PersistenceRetrievalCapabilityMetadata(degraded_reason=status),
    )


def _status_for_error(code: str) -> str:
    mapping = {
        "backend_required": "backend_required",
        "backend_result_failed": "backend_result_failed",
        "workspace_boundary_violation": "workspace_boundary_violation",
        "no_usable_records": "no_usable_records",
        "invalid_workspace_id": "invalid_workspace",
    }
    return mapping.get(code, "invalid_records")
