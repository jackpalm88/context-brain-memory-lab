from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.ingestion.classify_pipeline import MEMORY_TYPE_VALUES
from memory_lab.query.evidence import normalize_evidence

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"])


class RetrievalRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)
    debug: bool = False
    only_clean: bool = True
    max_hops: int = 1
    min_confidence: float = 0.7
    graph_boost: float = 0.1
    memory_type: Optional[str] = None
    memory_types: Optional[List[str]] = None

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

    def resolved_memory_types(self) -> Optional[List[str]]:
        """Return effective memory_types list; None means no filter."""
        if self.memory_type is not None:
            return [self.memory_type]
        return self.memory_types


def _debug_metadata(req: RetrievalRequest, *, candidate_count: int, result_count: int) -> dict:
    return {
        "requested": True,
        "stage_metrics": {
            "adapter_search": {
                "attempted": True,
                "status": "ok",
                "candidate_count": candidate_count,
                "output_count": candidate_count,
                "reason": None,
                "duration_ms": None,
            },
            "normalize": {
                "attempted": True,
                "status": "ok",
                "candidate_count": candidate_count,
                "output_count": result_count,
                "reason": None,
                "duration_ms": None,
            },
        },
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
        "degraded_reasons": [],
    }


@router.post("/search")
def retrieval_search(req: RetrievalRequest, auth: AuthContext = Depends(require_permission("retrieval.search"))) -> dict:
    settings = get_settings()
    adapter = RetrievalAdapter(settings.database_url)
    results = adapter.search(
        query=req.query,
        max_hops=req.max_hops,
        min_confidence=req.min_confidence,
        graph_boost=req.graph_boost,
        workspace_id=auth.workspace_id,
        memory_types=req.resolved_memory_types(),
    )
    evidence = normalize_evidence(results)[: req.limit]
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
    }
    if req.debug:
        response["debug_metadata"] = _debug_metadata(
            req,
            candidate_count=len(results),
            result_count=result_count,
        )
    return response
