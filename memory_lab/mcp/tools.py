"""PR1B minimal MCP tool handlers mapped to API-backed calls."""

from __future__ import annotations

from typing import Any, Dict, Optional

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
}
