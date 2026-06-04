from fastapi import APIRouter, Depends
from pydantic import BaseModel

from memory_lab.api.config import get_settings
from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.api.workspace_context import WorkspaceContext, get_workspace_context

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"])


class RetrievalRequest(BaseModel):
    query: str
    max_hops: int = 1
    min_confidence: float = 0.7
    graph_boost: float = 0.1


@router.post("/search")
def retrieval_search(req: RetrievalRequest, workspace: WorkspaceContext = Depends(get_workspace_context)) -> dict:
    settings = get_settings()
    adapter = RetrievalAdapter(settings.database_url)
    results = adapter.search(
        query=req.query,
        max_hops=req.max_hops,
        min_confidence=req.min_confidence,
        graph_boost=req.graph_boost,
        workspace_id=workspace.workspace_id,
    )
    return {
        "results": results,
        "count": len(results),
        "mode": "workspace_scoped_deterministic_db",
        "workspace_id": workspace.workspace_id,
        "workspace_source": workspace.source,
    }
