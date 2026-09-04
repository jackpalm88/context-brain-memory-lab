from typing import Any, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.api.services.retrieval_scope import (
    RetrievalScope,
    resolve_content_types,
    validate_scope_vs_legacy_content_types,
)
from memory_lab.ingestion.classify_pipeline import MEMORY_TYPE_VALUES
from memory_lab.query.evidence import normalize_evidence

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"])


class RetrievalRequest(BaseModel):
    query: str = Field(..., description="Free-text retrieval query.", examples=["What changed in M11C retrieval parity?"])
    limit: int = Field(default=10, ge=1, le=50, description="Maximum normalized evidence results to return.")
    debug: bool = Field(
        default=False,
        description=(
            "When true, include safe debug_metadata with descriptive stage_metrics. "
            "When false, debug_metadata is omitted from the normal response."
        ),
    )
    only_clean: bool = Field(
        default=True,
        description=(
            "Compatibility flag for private search_raw_chunks callers. Public M11C-2 records "
            "the request in debug filters_applied as an accepted no-op; it does not add a "
            "private clean/dirty retrieval filter."
        ),
    )
    max_hops: int = Field(default=1, description="Graph traversal hint used by the retrieval adapter; does not imply private graph expansion parity.")
    min_confidence: float = Field(default=0.7, description="Graph confidence hint forwarded to the retrieval adapter.")
    graph_boost: float = Field(default=0.1, description="Legacy multi-query score multiplier hint forwarded to the retrieval adapter. M12 curation boosts (curated graph neighbor +0.04, manual hub link +0.15) are fixed constants in the composite ranker and are not caller-configurable.")
    memory_type: Optional[str] = Field(default=None, description="Optional single memory type filter. Mutually exclusive with memory_types.")
    memory_types: Optional[List[str]] = Field(default=None, description="Optional list of memory type filters. Mutually exclusive with memory_type.")
    retrieval_scope: Optional[RetrievalScope] = Field(
        default=None,
        description=(
            "Optional first-class scoped-retrieval envelope (docs/DESIGN_SCOPED_RETRIEVAL.md). "
            "allowed_hubs restricts candidates to content linked to those hubs; content_types is "
            "an alias for memory_type/memory_types expressed inside the scope. Absent by default; "
            "omitting it is byte-identical to pre-scoped-retrieval behavior."
        ),
    )

    @model_validator(mode="after")
    def _validate_memory_type_filter(self):
        mt = self.memory_type
        mts = self.memory_types

        if mt is not None and mts is not None:
            raise ValueError(
                "Provide either memory_type or memory_types, not both. "
                "Use memory_types for multi-type filtering."
            )

        effective = [mt] if mt is not None else mts
        if effective is not None:
            if len(effective) == 0:
                raise ValueError("memory_types must not be empty.")
            invalid = [v for v in effective if v not in MEMORY_TYPE_VALUES]
            if invalid:
                raise ValueError(
                    f"Unknown memory_type value(s): {sorted(invalid)!r}. "
                    f"Allowed: {sorted(MEMORY_TYPE_VALUES)!r}"
                )
        return self

    @model_validator(mode="after")
    def _validate_scope_vs_legacy_content_types(self):
        scoped = self.retrieval_scope.content_types if self.retrieval_scope else None
        validate_scope_vs_legacy_content_types(self.resolved_memory_types(), scoped)
        return self

    def resolved_memory_types(self) -> Optional[List[str]]:
        """Return effective memory_types list; None means no filter."""
        if self.memory_type is not None:
            return [self.memory_type]
        return self.memory_types

    def resolved_content_types(self) -> Optional[List[str]]:
        """Effective content-type filter merging legacy memory_type(s) and
        retrieval_scope.content_types (validated equivalent-or-conflicting above).
        None means no filter."""
        scoped = self.retrieval_scope.content_types if self.retrieval_scope else None
        return resolve_content_types(self.resolved_memory_types(), scoped)

    def resolved_allowed_hubs(self) -> Optional[List[str]]:
        return self.retrieval_scope.allowed_hubs if self.retrieval_scope else None


def _clean_mapping(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if v is not None}


def _merge_metric(defaults: dict, override: Any) -> dict:
    merged = dict(defaults)
    merged.update(_clean_mapping(override))
    return merged


def _derive_result_path_metrics(results: list[dict[str, Any]], req: RetrievalRequest) -> dict:
    paths = {str(r.get("retrieval_path") or "") for r in results}
    modes = {str(r.get("retrieval_mode") or "") for r in results}
    embedding_statuses = {str(r.get("embedding_status") or "") for r in results if r.get("embedding_status")}
    deterministic_count = sum(
        1
        for r in results
        if str(r.get("retrieval_path") or "") in {"content_chunk_workspace_scoped", "deterministic_fallback"}
        or str(r.get("retrieval_mode") or "") == "deterministic_fallback"
    )
    pgvector_count = sum(
        1
        for r in results
        if str(r.get("retrieval_path") or "") == "pgvector_knn"
        or str(r.get("retrieval_mode") or "") == "pgvector_knn"
    )
    hub_count = sum(1 for r in results if r.get("hub_match") is not None or "hub" in str(r.get("retrieval_path") or ""))
    graph_count = sum(
        1
        for r in results
        if r.get("_graph_boosted") or bool(r.get("graph_match")) or len(r.get("source_queries") or []) > 1
    )
    pgvector_reason = None
    if pgvector_count == 0:
        pgvector_reason = next((s for s in embedding_statuses if s and s != "ok"), "not_used")
    graph_reason = None if graph_count else "no_expanded_terms"
    return {
        "deterministic_retrieval": {
            "attempted": True,
            "used": deterministic_count > 0,
            "skipped": deterministic_count == 0,
            "output_count": deterministic_count,
            "reason": None if deterministic_count else "no_deterministic_results",
        },
        "pgvector": {
            "attempted": "pgvector_knn" in paths or "pgvector_knn" in modes,
            "used": pgvector_count > 0,
            "skipped": pgvector_count == 0,
            "output_count": pgvector_count,
            "reason": pgvector_reason,
        },
        "hub_inclusion": {
            "attempted": req.max_hops >= 0,
            "used": hub_count > 0,
            "skipped": hub_count == 0,
            "candidate_count": hub_count,
            "output_count": hub_count,
            "reason": None if hub_count else "no_hub_matches",
        },
        "graph_expansion": {
            "attempted": req.max_hops > 0,
            "used": graph_count > 0,
            "skipped": graph_count == 0,
            "expanded_query_count": graph_count,
            "reason": graph_reason,
        },
    }


def _debug_metadata(
    req: RetrievalRequest,
    *,
    results: list[dict[str, Any]],
    normalized_count: int,
    result_count: int,
    adapter_debug_metadata: Any = None,
) -> dict:
    candidate_count = len(results)
    adapter_debug = _clean_mapping(adapter_debug_metadata)
    adapter_stage_metrics = _clean_mapping(adapter_debug.get("stage_metrics"))
    derived = _derive_result_path_metrics(results, req)
    stage_metrics = {
        "adapter_search": _merge_metric(
            {
                "attempted": True,
                "status": "ok",
                "candidate_count": candidate_count,
                "output_count": candidate_count,
                "reason": None,
                "duration_ms": None,
            },
            adapter_stage_metrics.get("adapter_search"),
        ),
        "normalize": _merge_metric(
            {
                "attempted": True,
                "status": "ok",
                "input_count": candidate_count,
                "candidate_count": candidate_count,
                "output_count": normalized_count,
                "result_count_before_limit": normalized_count,
                "result_count_after_limit": result_count,
                "reason": None,
                "duration_ms": None,
            },
            adapter_stage_metrics.get("normalize"),
        ),
        "deterministic_retrieval": _merge_metric(
            derived["deterministic_retrieval"],
            adapter_stage_metrics.get("deterministic_retrieval"),
        ),
        "pgvector": _merge_metric(
            derived["pgvector"],
            adapter_stage_metrics.get("pgvector"),
        ),
        "hub_inclusion": _merge_metric(
            derived["hub_inclusion"],
            adapter_stage_metrics.get("hub_inclusion"),
        ),
        "graph_expansion": _merge_metric(
            derived["graph_expansion"],
            adapter_stage_metrics.get("graph_expansion"),
        ),
        "dedup_filtering": _merge_metric(
            {
                "attempted": True,
                "status": "ok",
                "input_count": candidate_count,
                "output_count": normalized_count,
                "dropped_count": max(candidate_count - normalized_count, 0),
                "reason": None,
            },
            adapter_stage_metrics.get("dedup_filtering"),
        ),
    }
    degraded_reasons = []
    for reason in adapter_debug.get("degraded_reasons") or []:
        if reason and reason not in degraded_reasons:
            degraded_reasons.append(reason)
    for row in results:
        reason = row.get("embedding_status")
        if reason and reason != "ok" and reason not in degraded_reasons:
            degraded_reasons.append(reason)
    return {
        "requested": True,
        "stage_metrics": stage_metrics,
        "filters_applied": {
            "only_clean": {
                "requested": req.only_clean,
                "status": "accepted_noop",
                "reason": "Public raw retrieval has no additional clean/dirty filter in M11C-2-1.",
            },
            "memory_types": {
                "requested": req.resolved_memory_types() is not None,
                "values": req.resolved_memory_types(),
            },
        },
        "degraded_reasons": degraded_reasons,
    }


@router.post("/search", summary="Search raw retrieval evidence")
def retrieval_search(req: RetrievalRequest, auth: AuthContext = Depends(require_permission("retrieval.search"))) -> dict:
    """Return a public M11C retrieval envelope.

    `debug=false` omits debug metadata. `debug=true` adds safe descriptive
    stage_metrics for observability only; it does not change retrieval, ranking,
    scoring, provider behavior, graph expansion, or normalized evidence shape.
    """
    settings = get_settings()
    adapter = RetrievalAdapter(settings.database_url)
    results = adapter.search(
        query=req.query,
        max_hops=req.max_hops,
        min_confidence=req.min_confidence,
        graph_boost=req.graph_boost,
        workspace_id=auth.workspace_id,
        memory_types=req.resolved_content_types(),
        allowed_hubs=req.resolved_allowed_hubs(),
    )
    normalized_evidence = normalize_evidence(results)
    evidence = normalized_evidence[: req.limit]
    result_count = len(evidence)
    response = {
        "query": req.query,
        "results": [e.model_dump() for e in evidence],
        "count": result_count,
        "result_count": result_count,
        "limit": req.limit,
        "debug": req.debug,
        "only_clean": req.only_clean,
        "mode": "workspace_scoped_deterministic_db",
        "source": "retrieval_adapter",
        "status": "ok" if result_count else "no_results",
        "degraded": False,
        "workspace_id": auth.workspace_id,
        "workspace_source": auth.workspace_source,
        # M12-4: RankingSignals envelope (production search_by_text_v2 parity).
        "ranking_signals": getattr(adapter, "last_ranking_signals", None) or None,
    }
    if req.retrieval_scope is not None:
        # Provenance, not debug-only metadata: always present when a scope was
        # supplied, reflecting what was actually enforced (design doc §6.7).
        response["scope_applied"] = {
            "allowed_hubs": req.retrieval_scope.allowed_hubs,
            "content_types": req.resolved_content_types(),
            "enforcement": "pre_filter",
        }
    if req.debug:
        response["debug_metadata"] = _debug_metadata(
            req,
            results=results,
            normalized_count=len(normalized_evidence),
            result_count=result_count,
            adapter_debug_metadata=getattr(adapter, "last_debug_metadata", None),
        )
    return response
