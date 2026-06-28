"""PR1B/P3C minimal MCP tool handlers mapped to API-backed calls."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, List

from .client import MemoryLabApiClient, MemoryLabApiError


def _client() -> MemoryLabApiClient:
    return MemoryLabApiClient.from_env()


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return MemoryLabApiClient.redact_sensitive(value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _structured_api_error(exc: MemoryLabApiError) -> Dict[str, Any]:
    safe_body = _redact(exc.body)
    body_json: Any = None
    if safe_body:
        try:
            body_json = _redact(json.loads(safe_body))
        except ValueError:
            body_json = None
    return {
        "ok": False,
        "error": {
            "type": "memory_lab_api_error",
            "message": _redact(str(exc)),
            "method": exc.method,
            "url": _redact(exc.url),
            "status_code": exc.status_code,
            "body": safe_body,
            "body_json": body_json,
        },
    }


def _call_api(fn, *args, **kwargs) -> Dict[str, Any]:
    try:
        return fn(*args, **kwargs)
    except MemoryLabApiError as exc:
        return _structured_api_error(exc)


def memory_lab_health() -> Dict[str, Any]:
    return _call_api(_client().health)


def memory_lab_content_create_id(content: Optional[str] = None, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().content_create_id, content=content, workspace_id=workspace_id)


def memory_lab_content_get(content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().content_get, content_id=content_id, workspace_id=workspace_id)


def set_quick_summary(content_id: str, quick_summary: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(
        _client().set_quick_summary,
        content_id=content_id,
        quick_summary=quick_summary,
        workspace_id=workspace_id,
    )


def update_node_metadata(content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Read-only node metadata reader (no mutation).

    NOTE: despite the production-parity name, this tool does NOT mutate. It returns the
    content node's metadata and marks the response read_only=true / mutation="none". A
    real metadata update would require a dedicated PATCH endpoint (not implemented).
    """
    result = _call_api(_client().update_node_metadata, content_id=content_id, workspace_id=workspace_id)
    if isinstance(result, dict) and result.get("ok") is not False:
        result.setdefault("read_only", True)
        result.setdefault("mutation", "none")
    return result


def memory_lab_hub_create(
    title: str,
    hub_type: Optional[str] = None,
    description: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(_client().hub_create, title=title, hub_type=hub_type, description=description, workspace_id=workspace_id)


def memory_lab_hub_get(hub_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().hub_get, hub_id=hub_id, workspace_id=workspace_id)


def memory_lab_hub_link_content(hub_id: str, content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().hub_link_content, hub_id=hub_id, content_id=content_id, workspace_id=workspace_id)


def memory_lab_edge_create(
    source_hub_id: str,
    target_hub_id: str,
    edge_type: str,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(
        _client().edge_create,
        source_hub_id=source_hub_id,
        target_hub_id=target_hub_id,
        edge_type=edge_type,
        workspace_id=workspace_id,
    )


def memory_lab_edge_get(edge_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().edge_get, edge_id=edge_id, workspace_id=workspace_id)


def memory_lab_edge_list(
    hub_id: Optional[str] = None,
    include_archived: Optional[bool] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(_client().edge_list, hub_id=hub_id, include_archived=include_archived, workspace_id=workspace_id)


def memory_lab_edge_archive(edge_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().edge_archive, edge_id=edge_id, workspace_id=workspace_id)


def memory_lab_retrieval_search(query: str, limit: Optional[int] = None, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().retrieval_search, query=query, limit=limit, workspace_id=workspace_id)



def query_memory(query: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().ask, query=query, workspace_id=workspace_id)


def list_hubs(status: str = "active", workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().hub_list, status=status, workspace_id=workspace_id)


def update_hub(
    hub_id: str,
    title: Optional[str] = None,
    hub_type: Optional[str] = None,
    description: Optional[str] = None,
    aliases: Optional[List[str]] = None,
    related_terms: Optional[List[str]] = None,
    status: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(
        _client().hub_update,
        hub_id=hub_id,
        title=title,
        hub_type=hub_type,
        description=description,
        aliases=aliases,
        related_terms=related_terms,
        status=status,
        workspace_id=workspace_id,
    )


def update_hub_edge(
    edge_id: str,
    edge_type: Optional[str] = None,
    status: Optional[str] = None,
    note: Optional[str] = None,
    reason: Optional[str] = None,
    confidence: Optional[float] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(
        _client().edge_update,
        edge_id=edge_id,
        edge_type=edge_type,
        status=status,
        note=note,
        reason=reason,
        confidence=confidence,
        workspace_id=workspace_id,
    )


def approve_inferred_edge(
    source_hub_id: str,
    target_hub_id: str,
    edge_type: str,
    reason: Optional[str] = None,
    confidence: Optional[float] = None,
    note: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(
        _client().approve_inferred_edge,
        source_hub_id=source_hub_id,
        target_hub_id=target_hub_id,
        edge_type=edge_type,
        reason=reason,
        confidence=confidence,
        note=note,
        workspace_id=workspace_id,
    )


def reject_inferred_edge(
    source_hub_id: str,
    target_hub_id: str,
    edge_type: str,
    reason: Optional[str] = None,
    note: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(
        _client().reject_inferred_edge,
        source_hub_id=source_hub_id,
        target_hub_id=target_hub_id,
        edge_type=edge_type,
        reason=reason,
        note=note,
        workspace_id=workspace_id,
    )


def save_and_link_to_hub(
    content: str,
    save_purpose: str,
    hub_id: str,
    content_url: Optional[str] = None,
    quick_summary: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    # save_purpose and content_url have no counterpart in the public minimal API
    # (no classify/governance ingest pipeline), so they are accepted for production
    # tool-signature parity and reported as unsupported when supplied. quick_summary
    # IS persisted via the content quick-summary setter after the content node is saved.
    return _call_api(
        _client().save_and_link_to_hub,
        content=content,
        hub_id=hub_id,
        quick_summary=quick_summary,
        save_purpose=save_purpose,
        content_url=content_url,
        workspace_id=workspace_id,
    )


def get_graph_snapshot(include_inferred: bool = True, include_curated: bool = True, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Full graph snapshot: hub nodes + edges, filterable by origin class.

    PUBLIC IMPROVEMENT over production (where include_inferred is a documented no-op):
    include_inferred toggles machine-suggested edges (origin inferred_approved/ai_suggested),
    include_curated toggles human edges. Both default True; both False yields no edges.
    """
    return _call_api(
        _client().graph_snapshot,
        include_inferred=include_inferred,
        include_curated=include_curated,
        workspace_id=workspace_id,
    )


def list_graph_snapshot(include_inferred: bool = True, include_curated: bool = True, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    """Flag-forwarding alias of get_graph_snapshot (production parity: spec-canonical name)."""
    return get_graph_snapshot(include_inferred=include_inferred, include_curated=include_curated, workspace_id=workspace_id)


def load_graph_node_full(content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().graph_node_full, content_id=content_id, workspace_id=workspace_id)


def search_graph_preview(
    query: str,
    node_type: Optional[str] = None,
    hub_id: Optional[str] = None,
    limit: int = 10,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(
        _client().graph_search_preview,
        query=query,
        node_type=node_type,
        hub_id=hub_id,
        limit=limit,
        workspace_id=workspace_id,
    )


def create_decision_memory(
    title: str,
    decision_reason: str,
    decision_context: Optional[str] = None,
    why_this_matters: Optional[str] = None,
    decision_status: str = "active",
    reversible: bool = True,
    source_content_ids: Optional[List[str]] = None,
    linked_hub_ids: Optional[List[str]] = None,
    supersedes_decision_id: Optional[str] = None,
    alternatives_considered: Optional[List[Dict[str, Any]]] = None,
    contradicting_evidence: Optional[str] = None,
    confidence_level: str = "medium",
    decision_tags: Optional[List[str]] = None,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": title,
        "decision_reason": decision_reason,
        "decision_status": decision_status,
        "reversible": reversible,
        "confidence_level": confidence_level,
    }
    if decision_context is not None:
        payload["decision_context"] = decision_context
    if why_this_matters is not None:
        payload["why_this_matters"] = why_this_matters
    if source_content_ids is not None:
        payload["source_content_ids"] = source_content_ids
    if linked_hub_ids is not None:
        payload["linked_hub_ids"] = linked_hub_ids
    if supersedes_decision_id is not None:
        payload["supersedes_decision_id"] = supersedes_decision_id
    if alternatives_considered is not None:
        payload["alternatives_considered"] = alternatives_considered
    if contradicting_evidence is not None:
        payload["contradicting_evidence"] = contradicting_evidence
    if decision_tags is not None:
        payload["decision_tags"] = decision_tags
    return _call_api(_client().decision_create, payload, workspace_id=workspace_id)


def explain_decision(decision_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().decision_get, decision_id, workspace_id=workspace_id)


def list_decisions(
    status: Optional[str] = None,
    hub_id: Optional[str] = None,
    limit: int = 20,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(_client().decision_list, status=status, hub_id=hub_id, limit=limit, workspace_id=workspace_id)


def update_decision_status(decision_id: str, decision_status: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(
        _client().decision_update_status,
        decision_id=decision_id,
        decision_status=decision_status,
        workspace_id=workspace_id,
    )


def get_decision_lineage(decision_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().decision_lineage, decision_id, workspace_id=workspace_id)


def list_decision_conflicts(workspace_id: Optional[str] = None) -> Dict[str, Any]:
    return _call_api(_client().decision_conflicts, workspace_id=workspace_id)


def get_decision_timeline(
    hub_id: Optional[str] = None,
    tags: Optional[str] = None,
    limit: int = 50,
    workspace_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _call_api(_client().decision_timeline, hub_id=hub_id, tags=tags, limit=limit, workspace_id=workspace_id)


APPROVED_TOOLS = {
    "memory_lab_health": memory_lab_health,
    "memory_lab_content_create_id": memory_lab_content_create_id,
    "memory_lab_content_get": memory_lab_content_get,
    "set_quick_summary": set_quick_summary,
    "update_node_metadata": update_node_metadata,
    "memory_lab_hub_create": memory_lab_hub_create,
    "memory_lab_hub_get": memory_lab_hub_get,
    "memory_lab_hub_link_content": memory_lab_hub_link_content,
    "memory_lab_edge_create": memory_lab_edge_create,
    "memory_lab_edge_get": memory_lab_edge_get,
    "memory_lab_edge_list": memory_lab_edge_list,
    "memory_lab_edge_archive": memory_lab_edge_archive,
    "memory_lab_retrieval_search": memory_lab_retrieval_search,

    "query_memory": query_memory,
    "list_hubs": list_hubs,
    "update_hub": update_hub,
    "update_hub_edge": update_hub_edge,
    "approve_inferred_edge": approve_inferred_edge,
    "reject_inferred_edge": reject_inferred_edge,
    "save_and_link_to_hub": save_and_link_to_hub,
    "get_graph_snapshot": get_graph_snapshot,
    "list_graph_snapshot": list_graph_snapshot,
    "load_graph_node_full": load_graph_node_full,
    "search_graph_preview": search_graph_preview,
    "create_decision_memory": create_decision_memory,
    "explain_decision": explain_decision,
    "list_decisions": list_decisions,
    "update_decision_status": update_decision_status,
    "get_decision_lineage": get_decision_lineage,
    "list_decision_conflicts": list_decision_conflicts,
    "get_decision_timeline": get_decision_timeline,
}
