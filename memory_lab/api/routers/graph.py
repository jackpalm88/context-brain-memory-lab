from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter

router = APIRouter(prefix="/v1/graph", tags=["graph"])


@router.get("/snapshot")
def graph_snapshot(auth: AuthContext = Depends(require_permission("hubs.read"))) -> dict:
    adapter = ApiAdapter(get_settings().database_url)
    return adapter.get_graph_snapshot(workspace_id=auth.workspace_id)


@router.get("/nodes/{content_id}/full")
def load_graph_node_full(content_id: str, auth: AuthContext = Depends(require_permission("content.read"))) -> dict:
    adapter = ApiAdapter(get_settings().database_url)
    node = adapter.load_graph_node_full(content_id, workspace_id=auth.workspace_id)
    if not node:
        raise HTTPException(status_code=404, detail="content not found")
    return node


@router.get("/search-preview")
def search_graph_preview(
    query: str,
    node_type: Optional[str] = None,
    hub_id: Optional[str] = None,
    limit: int = 10,
    auth: AuthContext = Depends(require_permission("retrieval.search")),
) -> dict:
    adapter = ApiAdapter(get_settings().database_url)
    return adapter.search_graph_preview(query=query, node_type=node_type, hub_id=hub_id, limit=limit, workspace_id=auth.workspace_id)
