"""PR1B minimal MCP tool handlers mapped to API-backed calls."""

from __future__ import annotations

from typing import Any, Dict, Optional, List

from .client import MemoryLabApiClient


def _client() -> MemoryLabApiClient:
    return MemoryLabApiClient.from_env()


def memory_lab_health() -> Dict[str, Any]:
    return _client().health()


def memory_lab_content_create_id(content: Optional[str] = None) -> Dict[str, Any]:
    return _client().content_create_id(content=content)


def memory_lab_content_get(content_id: str) -> Dict[str, Any]:
    return _client().content_get(content_id=content_id)


def memory_lab_hub_create(title: str, hub_type: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
    return _client().hub_create(title=title, hub_type=hub_type, description=description)


def memory_lab_hub_get(hub_id: str) -> Dict[str, Any]:
    return _client().hub_get(hub_id=hub_id)


def memory_lab_hub_link_content(hub_id: str, content_id: str) -> Dict[str, Any]:
    return _client().hub_link_content(hub_id=hub_id, content_id=content_id)


def memory_lab_edge_create(source_hub_id: str, target_hub_id: str, edge_type: str) -> Dict[str, Any]:
    return _client().edge_create(source_hub_id=source_hub_id, target_hub_id=target_hub_id, edge_type=edge_type)


def memory_lab_edge_get(edge_id: str) -> Dict[str, Any]:
    return _client().edge_get(edge_id=edge_id)


def memory_lab_edge_list(hub_id: Optional[str] = None, include_archived: Optional[bool] = None) -> Dict[str, Any]:
    return _client().edge_list(hub_id=hub_id, include_archived=include_archived)


def memory_lab_edge_archive(edge_id: str) -> Dict[str, Any]:
    return _client().edge_archive(edge_id=edge_id)


def memory_lab_retrieval_search(query: str, limit: Optional[int] = None) -> Dict[str, Any]:
    return _client().retrieval_search(query=query, limit=limit)


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
    return _client().decision_create(payload)


def explain_decision(decision_id: str) -> Dict[str, Any]:
    return _client().decision_get(decision_id)


def list_decisions(status: Optional[str] = None, hub_id: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    return _client().decision_list(status=status, hub_id=hub_id, limit=limit)


def update_decision_status(decision_id: str, decision_status: str) -> Dict[str, Any]:
    return _client().decision_update_status(decision_id=decision_id, decision_status=decision_status)


def get_decision_lineage(decision_id: str) -> Dict[str, Any]:
    return _client().decision_lineage(decision_id)


def list_decision_conflicts() -> Dict[str, Any]:
    return _client().decision_conflicts()


def get_decision_timeline(hub_id: Optional[str] = None, tags: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    return _client().decision_timeline(hub_id=hub_id, tags=tags, limit=limit)


APPROVED_TOOLS = {
    "memory_lab_health": memory_lab_health,
    "memory_lab_content_create_id": memory_lab_content_create_id,
    "memory_lab_content_get": memory_lab_content_get,
    "memory_lab_hub_create": memory_lab_hub_create,
    "memory_lab_hub_get": memory_lab_hub_get,
    "memory_lab_hub_link_content": memory_lab_hub_link_content,
    "memory_lab_edge_create": memory_lab_edge_create,
    "memory_lab_edge_get": memory_lab_edge_get,
    "memory_lab_edge_list": memory_lab_edge_list,
    "memory_lab_edge_archive": memory_lab_edge_archive,
    "memory_lab_retrieval_search": memory_lab_retrieval_search,
    "create_decision_memory": create_decision_memory,
    "explain_decision": explain_decision,
    "list_decisions": list_decisions,
    "update_decision_status": update_decision_status,
    "get_decision_lineage": get_decision_lineage,
    "list_decision_conflicts": list_decision_conflicts,
    "get_decision_timeline": get_decision_timeline,
}
