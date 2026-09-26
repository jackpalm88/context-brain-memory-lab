from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission
from memory_lab.api.services.api_adapter import ApiAdapter

router = APIRouter(prefix="/v1/graph", tags=["graph"])


@router.get("/snapshot")
def graph_snapshot(
    include_inferred: bool = True,
    include_curated: bool = True,
    auth: AuthContext = Depends(require_permission("hubs.read")),
) -> dict:
    adapter = ApiAdapter(get_settings().database_url)
    return adapter.get_graph_snapshot(
        include_inferred=include_inferred,
        include_curated=include_curated,
        workspace_id=auth.workspace_id,
    )


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
    hub_id: Optional[UUID] = None,
    hub_scope: Literal["annotate", "strict"] = "annotate",
    limit: int = 10,
    auth: AuthContext = Depends(require_permission("retrieval.search")),
) -> dict:
    """hub_scope="annotate" (default): hub_id only sets per-row hub_match; the
    candidate set and ranking stay workspace-wide. hub_scope="strict": hub_id is a
    server-side pre-filter applied before ranking/limit on both the content_items
    and the decision branch, fail-closed (unknown / other-workspace hub -> 0 rows)."""
    if hub_scope == "strict" and hub_id is None:
        raise HTTPException(status_code=422, detail="hub_scope=strict requires hub_id")
    adapter = ApiAdapter(get_settings().database_url)
    return adapter.search_graph_preview(
        query=query,
        node_type=node_type,
        hub_id=str(hub_id) if hub_id else None,
        hub_scope=hub_scope,
        limit=limit,
        workspace_id=auth.workspace_id,
    )
