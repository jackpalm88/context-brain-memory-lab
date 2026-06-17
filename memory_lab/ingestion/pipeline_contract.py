"""B27 public-safe ingestion pipeline contract.

This module composes existing deterministic B18/B19/B21/B25/B26 public-safe
components over caller-supplied values only. The roadmap label for B27 mentions
"live ingestion pipeline", but this implementation is a contract/orchestration
layer only: no runtime integration, no service access, no storage fallback, and
no private memory behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping, Sequence

from memory_lab.governance.circuit_breaker import CircuitBreakerEvent, evaluate_circuit_state
from memory_lab.governance.tier_routing_plan import TierRoutingPlanInput, plan_tier_route
from memory_lab.governance.workspace import validate_workspace_id
from memory_lab.ingestion.chunk_scoring import score_chunks
from memory_lab.ingestion.chunking import make_deterministic_content_chunker
from memory_lab.ingestion.classifiers import make_deterministic_ingestion_signal_classifiers
from memory_lab.ingestion.extraction import make_deterministic_content_extractor
from memory_lab.ingestion.ingestion_scoring import IngestionSignalInput, score_ingestion_signals
from memory_lab.ingestion.interfaces import IngestionTextInput, SYNTHETIC_DATA_SOURCE
from memory_lab.persistence.results import ContentPersistenceRecord, PersistenceResult

B27_PIPELINE_MODE = "b27_public_safe_ingestion_pipeline_contract_v1"
B27_LIMITATIONS: tuple[str, ...] = (
    "public_safe_ingestion_pipeline_contract_only",
    "caller_supplied_text_only",
    "deterministic_component_composition_only",
    "requires_explicit_workspace_id",
    "source_ref_is_metadata_only_and_not_fetched",
    "persistence_requires_supplied_b26_backend",
    "no_db_fallback",
    "no_provider_call",
    "no_private_context_brain_access",
    "no_api_or_auth_runtime",
    "no_mcp_or_gpt_actions_runtime_wiring",
    "no_embedding_or_vector_retrieval",
    "tier_routing_plan_only",
)
B27_NON_CLAIMS: tuple[str, ...] = (
    "not_production_ingestion_runtime",
    "not_db_backed_production_persistence",
    "not_live_context_brain_ingestion",
    "not_private_context_brain_parity",
    "not_live_memory_retrieval",
    "not_semantic_search",
    "not_provider_backed_reasoning",
    "not_mcp_or_gpt_actions_production_ready",
)


@dataclass(frozen=True)
class IngestionPipelineRequest:
    workspace_id: str
    content_id: str
    text: str
    title: str = ""
    source_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    hub_candidates: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    tag_candidates: Sequence[str] = field(default_factory=tuple)
    circuit_events: Sequence[CircuitBreakerEvent | Mapping[str, Any]] = field(default_factory=tuple)
    circuit_now: float = 0.0
    persist: bool = False


@dataclass(frozen=True)
class IngestionPipelineError:
    code: str
    message: str
    field: str | None = None
    limitations: tuple[str, ...] = B27_LIMITATIONS
    non_claims: tuple[str, ...] = B27_NON_CLAIMS
    mode: str = B27_PIPELINE_MODE


@dataclass(frozen=True)
class IngestionPipelineResult:
    ok: bool
    status: str
    request_id: str
    workspace_id: str
    content_id: str
    extraction: Any = None
    domain: Any = None
    hubs: Any = None
    tags: Any = None
    chunks: Any = None
    chunk_scores: Any = None
    scoring: Any = None
    circuit: Any = None
    tier_plan: Any = None
    persistence: Any = None
    errors: tuple[IngestionPipelineError, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = B27_LIMITATIONS
    non_claims: tuple[str, ...] = B27_NON_CLAIMS
    mode: str = B27_PIPELINE_MODE


class PublicSafeIngestionPipeline:
    """Deterministic B27 orchestrator over explicit caller-supplied inputs."""

    mode: str = B27_PIPELINE_MODE
    limitations: tuple[str, ...] = B27_LIMITATIONS
    non_claims: tuple[str, ...] = B27_NON_CLAIMS

    def run(self, request: IngestionPipelineRequest, backend: Any | None = None) -> IngestionPipelineResult:
        request_id = _request_id(request)
        validation_errors = _validate_request(request)
        if validation_errors:
            return _result(ok=False, status="invalid_request", request=request, request_id=request_id, errors=validation_errors)

        metadata = _metadata_for_components(request)
        item = IngestionTextInput(text=request.text, item_id=request.content_id.strip(), title=request.title or "", metadata=metadata, data_source=SYNTHETIC_DATA_SOURCE)
        extraction = make_deterministic_content_extractor().extract_content(item)
        extracted_item = IngestionTextInput(
            text=extraction.extracted_text,
            item_id=request.content_id.strip(),
            title=str(extraction.fields.get("title_candidate") or request.title or ""),
            metadata={**metadata, "domain": ""},
            data_source=SYNTHETIC_DATA_SOURCE,
        )
        classifiers = make_deterministic_ingestion_signal_classifiers()
        domain = classifiers.domain_classifier.classify_domain(extracted_item)
        signal_item = IngestionTextInput(
            text=extraction.extracted_text,
            item_id=request.content_id.strip(),
            title=extracted_item.title,
            metadata={**metadata, "domain": domain.domain},
            data_source=SYNTHETIC_DATA_SOURCE,
        )
        hubs = classifiers.hub_detector.detect_hubs(signal_item)
        tags = classifiers.tag_classifier.classify_tags(signal_item)
        chunking = make_deterministic_content_chunker().chunk_content(signal_item)
        chunk_score_results = score_chunks(tuple(chunking.chunks))
        chunk_quality = _average(tuple(score.quality for score in chunk_score_results))
        chunk_composite = _average(tuple(score.composite for score in chunk_score_results))
        risk_flags = _dedupe(tuple(flag for score in chunk_score_results for flag in tuple(score.risk_flags)))
        completeness_flags = _completeness_flags(extraction, domain, hubs, tags, chunking, chunk_score_results)
        scoring = score_ingestion_signals(
            IngestionSignalInput(
                extraction_confidence=extraction.confidence,
                domain_confidence=domain.confidence,
                hub_confidence=hubs.confidence,
                tag_confidence=tags.confidence,
                chunk_quality=chunk_quality,
                chunk_composite=chunk_composite,
                embedding_admin_ready=False,
                knn_ready=False,
                risk_flags=risk_flags,
                completeness_flags=completeness_flags,
                signal_metadata={"workspace_id": request.workspace_id.strip(), "content_id": request.content_id.strip()},
            )
        )
        circuit = _evaluate_supplied_circuit(request)
        tier_plan = plan_tier_route(TierRoutingPlanInput(scoring_summary=scoring, circuit_state=circuit.state, safety_flags=()))
        persistence = _persistence_result(request, backend, extraction, domain, hubs, tags, chunking, scoring, tier_plan)
        persistence_error = _persistence_error(persistence)
        errors = (persistence_error,) if persistence_error is not None else ()
        status = "completed" if not errors else ("persistence_backend_required" if persistence_error.code == "persistence_backend_required" else "persistence_error")
        return _result(
            ok=not errors,
            status=status,
            request=request,
            request_id=request_id,
            extraction=extraction,
            domain=domain,
            hubs=hubs,
            tags=tags,
            chunks=tuple(chunking.chunks),
            chunk_scores=chunk_score_results,
            scoring=scoring,
            circuit=circuit,
            tier_plan=tier_plan,
            persistence=persistence,
            errors=errors,
        )


def make_public_safe_ingestion_pipeline() -> PublicSafeIngestionPipeline:
    return PublicSafeIngestionPipeline()


def run_ingestion_pipeline(request: IngestionPipelineRequest, backend: Any | None = None) -> IngestionPipelineResult:
    return make_public_safe_ingestion_pipeline().run(request, backend=backend)


def _validate_request(request: IngestionPipelineRequest) -> tuple[IngestionPipelineError, ...]:
    errors: list[IngestionPipelineError] = []
    workspace_check = validate_workspace_id(request.workspace_id)
    if not workspace_check.valid:
        errors.append(IngestionPipelineError("invalid_workspace_id", "; ".join(workspace_check.errors), "workspace_id"))
    if not isinstance(request.content_id, str) or not request.content_id.strip():
        errors.append(IngestionPipelineError("missing_content_id", "content_id is required", "content_id"))
    if not isinstance(request.text, str) or not request.text.strip():
        errors.append(IngestionPipelineError("missing_text", "text is required and must be caller-supplied non-blank content", "text"))
    return tuple(errors)


def _metadata_for_components(request: IngestionPipelineRequest) -> dict[str, Any]:
    metadata = dict(request.metadata or {})
    metadata["workspace_id"] = request.workspace_id.strip() if isinstance(request.workspace_id, str) else request.workspace_id
    metadata["content_id"] = request.content_id.strip() if isinstance(request.content_id, str) else request.content_id
    if request.source_ref is not None:
        metadata["source_ref"] = request.source_ref
        metadata["source_ref_role"] = "metadata_only_not_fetched"
    if request.hub_candidates:
        metadata["hub_candidates"] = tuple(dict(item) for item in request.hub_candidates)
    if request.tag_candidates:
        metadata["tag_candidates"] = tuple(str(item) for item in request.tag_candidates)
    return metadata


def _evaluate_supplied_circuit(request: IngestionPipelineRequest) -> Any:
    events = tuple(_circuit_event(event) for event in tuple(request.circuit_events or ()))
    now = float(request.circuit_now or 0.0)
    return evaluate_circuit_state(events, now=now, initial_state="closed")


def _circuit_event(event: CircuitBreakerEvent | Mapping[str, Any]) -> CircuitBreakerEvent:
    if isinstance(event, CircuitBreakerEvent):
        return event
    return CircuitBreakerEvent(event_type=str(event.get("event_type", event.get("type", "success"))), timestamp=float(event.get("timestamp", 0.0)), reason=str(event.get("reason", "")))


def _persistence_result(request: IngestionPipelineRequest, backend: Any | None, extraction: Any, domain: Any, hubs: Any, tags: Any, chunking: Any, scoring: Any, tier_plan: Any) -> Mapping[str, Any]:
    if not request.persist:
        return {"attempted": False, "required": False, "backend_required": False, "result": None, "warnings": ("persist_false_no_backend_required_no_mutation",)}
    if backend is None:
        return {"attempted": False, "required": True, "backend_required": True, "result": None, "error_code": "persistence_backend_required", "warnings": ("persist_true_requires_supplied_b26_backend",)}
    record = ContentPersistenceRecord(
        content_id=request.content_id.strip(),
        workspace_id=request.workspace_id.strip(),
        text=extraction.extracted_text,
        title=request.title or None,
        metadata={
            **dict(request.metadata or {}),
            "source_ref": request.source_ref,
            "domain": domain.domain,
            "hubs": tuple(hubs.hub_candidates),
            "tags": tuple(tags.tags),
            "chunk_count": len(tuple(chunking.chunks)),
            "scoring_composite": scoring.score.composite,
            "tier_recommendation": tier_plan.recommended_tier,
            "b27_mode": B27_PIPELINE_MODE,
        },
    )
    result = backend.put_content_record(record)
    return {"attempted": True, "required": True, "backend_required": False, "result": result, "warnings": ("persisted_only_through_supplied_b26_backend",)}


def _persistence_error(persistence: Any) -> IngestionPipelineError | None:
    if isinstance(persistence, Mapping) and persistence.get("error_code") == "persistence_backend_required":
        return IngestionPipelineError("persistence_backend_required", "persist=True requires a caller-supplied B26 backend", "backend")
    result = persistence.get("result") if isinstance(persistence, Mapping) else None
    if isinstance(result, PersistenceResult) and not result.ok:
        code = result.error.code if result.error else "persistence_error"
        message = result.error.message if result.error else "B26 backend returned failure"
        field_name = result.error.field if result.error else None
        return IngestionPipelineError(code, message, field_name)
    return None


def _result(*, ok: bool, status: str, request: IngestionPipelineRequest, request_id: str, extraction: Any = None, domain: Any = None, hubs: Any = None, tags: Any = None, chunks: Any = None, chunk_scores: Any = None, scoring: Any = None, circuit: Any = None, tier_plan: Any = None, persistence: Any = None, errors: Sequence[IngestionPipelineError] = (), warnings: Sequence[str] = ()) -> IngestionPipelineResult:
    return IngestionPipelineResult(ok=ok, status=status, request_id=request_id, workspace_id=request.workspace_id, content_id=request.content_id, extraction=extraction, domain=domain, hubs=hubs, tags=tags, chunks=tuple(chunks or ()), chunk_scores=tuple(chunk_scores or ()), scoring=scoring, circuit=circuit, tier_plan=tier_plan, persistence=persistence, errors=tuple(errors), warnings=tuple(warnings))


def _request_id(request: IngestionPipelineRequest) -> str:
    payload = {"workspace_id": request.workspace_id, "content_id": request.content_id, "text": request.text, "title": request.title, "source_ref": request.source_ref, "metadata": _jsonable(request.metadata), "hub_candidates": _jsonable(request.hub_candidates), "tag_candidates": _jsonable(request.tag_candidates), "persist": request.persist}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "b27-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_jsonable(item) for item in value)
    return value


def _average(values: Sequence[float]) -> float:
    clean = tuple(float(value) for value in values)
    if not clean:
        return 0.0
    return round(sum(clean) / len(clean), 6)


def _completeness_flags(extraction: Any, domain: Any, hubs: Any, tags: Any, chunking: Any, chunk_scores: Any) -> tuple[str, ...]:
    flags: list[str] = []
    if getattr(extraction, "extracted_text", ""):
        flags.append("extraction_present")
    if getattr(domain, "domain", "unknown") not in {"unknown", ""}:
        flags.append("domain_signal_present")
    if tuple(getattr(hubs, "hub_candidates", ())):
        flags.append("hub_signal_present")
    if tuple(getattr(tags, "tags", ())):
        flags.append("tag_signal_present")
    if tuple(getattr(chunking, "chunks", ())):
        flags.append("chunks_present")
    if tuple(chunk_scores or ()): 
        flags.append("chunk_scores_present")
    return tuple(flags)


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)
