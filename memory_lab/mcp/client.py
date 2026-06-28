"""PR1B/P3C MCP API-backed client for local minimal API only.

Scope boundary:
- Local-only HTTP calls to minimal API runtime endpoints.
- No DB direct access.
- No provider/LLM paths.
- No external network calls.

P3C workspace boundary:
- Optional per-call workspace_id is transported as X-Workspace-ID.
- Optional MEMORY_LAB_MCP_DEFAULT_WORKSPACE_ID is a client-side default.
- If neither is set, no workspace header is sent and the API keeps its P3B
  MEMORY_LAB_DEFAULT_WORKSPACE_ID / DB default fallback behavior.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


class MemoryLabApiError(RuntimeError):
    """Raised when API call fails or returns non-2xx response."""

    def __init__(
        self,
        message: str,
        *,
        method: Optional[str] = None,
        url: Optional[str] = None,
        status_code: Optional[int] = None,
        body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body


@dataclass
class MemoryLabApiClient:
    base_url: str
    timeout_s: float = 15.0
    default_workspace_id: Optional[str] = None
    api_token: Optional[str] = None

    @staticmethod
    def from_env() -> "MemoryLabApiClient":
        host = os.getenv("MEMORY_LAB_API_HOST", "127.0.0.1")
        port = os.getenv("MEMORY_LAB_API_PORT", "8000")
        scheme = os.getenv("MEMORY_LAB_API_SCHEME", "http")
        if host not in {"127.0.0.1", "localhost"}:
            raise MemoryLabApiError(f"Unsafe host for local MCP plan: {host}")
        base_url = f"{scheme}://{host}:{port}".rstrip("/")
        default_workspace_id = os.getenv("MEMORY_LAB_MCP_DEFAULT_WORKSPACE_ID") or None
        api_token = os.getenv("MEMORY_LAB_API_TOKEN") or os.getenv("MEMORY_LAB_MCP_API_TOKEN") or None
        return MemoryLabApiClient(base_url=base_url, default_workspace_id=default_workspace_id, api_token=api_token)

    def _selected_workspace_id(self, workspace_id: Optional[str] = None) -> Optional[str]:
        explicit = workspace_id.strip() if isinstance(workspace_id, str) else workspace_id
        if explicit:
            return explicit
        default = self.default_workspace_id.strip() if isinstance(self.default_workspace_id, str) else self.default_workspace_id
        return default or None

    @staticmethod
    def redact_sensitive(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        redacted = value
        patterns = [
            (r"Authorization\s*:\s*Bearer\s+[^\s,;]+", "Authorization: Bearer [REDACTED]"),
            (r"Bearer\s+[^\s,;]+", "Bearer [REDACTED]"),
            (r"(?i)(token|api[_-]?key|key|secret|password)=([^\s&]+)", r"\1=[REDACTED]"),
            (r"(?i)(\"(?:token|api[_-]?key|key|secret|password|authorization)\"\s*:\s*)\"[^\"]+\"", r"\1\"[REDACTED]\""),
        ]
        for pattern, replacement in patterns:
            redacted = re.sub(pattern, replacement, redacted)
        return redacted

    def _headers(self, workspace_id: Optional[str] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        selected = self._selected_workspace_id(workspace_id)
        if selected:
            headers["X-Workspace-ID"] = selected
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._headers(workspace_id)
        try:
            resp = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers or None,
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            safe_exc = self.redact_sensitive(str(exc))
            raise MemoryLabApiError(
                f"Request failed for {method} {url}: {safe_exc}",
                method=method,
                url=url,
            ) from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            safe_body = self.redact_sensitive(resp.text[:2000])
            raise MemoryLabApiError(
                f"Non-2xx from {method} {url}: {resp.status_code} body={safe_body[:500]}",
                method=method,
                url=url,
                status_code=resp.status_code,
                body=safe_body,
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise MemoryLabApiError(
                f"Invalid JSON from {method} {url}",
                method=method,
                url=url,
                status_code=resp.status_code,
                body=self.redact_sensitive(resp.text[:2000]),
            ) from exc

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def content_create_id(self, content: Optional[str] = None, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        return self._request("POST", "/v1/content", json_body=payload, workspace_id=workspace_id)

    def content_get(self, content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", f"/v1/content/{content_id}", workspace_id=workspace_id)

    def set_quick_summary(self, content_id: str, quick_summary: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request(
            "PATCH",
            f"/v1/content/{content_id}/quick-summary",
            json_body={"quick_summary": quick_summary},
            workspace_id=workspace_id,
        )

    def get_content_metadata(self, content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", f"/v1/content/{content_id}/metadata", workspace_id=workspace_id)

    def update_node_metadata(self, content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self.get_content_metadata(content_id=content_id, workspace_id=workspace_id)

    def hub_create(
        self,
        title: str,
        hub_type: Optional[str] = None,
        description: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"title": title}
        if hub_type is not None:
            payload["hub_type"] = hub_type
        if description is not None:
            payload["description"] = description
        return self._request("POST", "/v1/hubs", json_body=payload, workspace_id=workspace_id)

    def hub_get(self, hub_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", f"/v1/hubs/{hub_id}", workspace_id=workspace_id)

    def hub_link_content(self, hub_id: str, content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", f"/v1/hubs/{hub_id}/links", json_body={"content_id": content_id}, workspace_id=workspace_id)

    def edge_create(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/v1/edges",
            json_body={
                "source_hub_id": source_hub_id,
                "target_hub_id": target_hub_id,
                "edge_type": edge_type,
            },
            workspace_id=workspace_id,
        )

    def edge_get(self, edge_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", f"/v1/edges/{edge_id}", workspace_id=workspace_id)

    def edge_list(
        self,
        hub_id: Optional[str] = None,
        include_archived: Optional[bool] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if hub_id is not None:
            params["hub_id"] = hub_id
        if include_archived is not None:
            params["include_archived"] = str(include_archived).lower()
        return self._request("GET", "/v1/edges", params=params, workspace_id=workspace_id)

    def edge_archive(self, edge_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", f"/v1/edges/{edge_id}/archive", workspace_id=workspace_id)

    def retrieval_search(self, query: str, limit: Optional[int] = None, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query}
        if limit is not None:
            payload["limit"] = limit
        return self._request("POST", "/v1/retrieval/search", json_body=payload, workspace_id=workspace_id)


    def ask(self, query: str, top_k: Optional[int] = None, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query}
        if top_k is not None:
            payload["top_k"] = top_k
        return self._request("POST", "/v1/ask", json_body=payload, workspace_id=workspace_id)

    def hub_list(self, status: str = "active", workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", "/v1/hubs", params={"status": status}, workspace_id=workspace_id)

    def hub_update(
        self,
        hub_id: str,
        title: Optional[str] = None,
        hub_type: Optional[str] = None,
        description: Optional[str] = None,
        aliases: Optional[list[str]] = None,
        related_terms: Optional[list[str]] = None,
        status: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if hub_type is not None:
            payload["type"] = hub_type
        if description is not None:
            payload["description"] = description
        if aliases is not None:
            payload["aliases"] = aliases
        if related_terms is not None:
            payload["related_terms"] = related_terms
        if status is not None:
            payload["status"] = status
        return self._request("PATCH", f"/v1/hubs/{hub_id}", json_body=payload, workspace_id=workspace_id)

    def edge_update(
        self,
        edge_id: str,
        edge_type: Optional[str] = None,
        status: Optional[str] = None,
        note: Optional[str] = None,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if edge_type is not None:
            payload["edge_type"] = edge_type
        if status is not None:
            payload["status"] = status
        if note is not None:
            payload["note"] = note
        if reason is not None:
            payload["reason"] = reason
        if confidence is not None:
            payload["confidence"] = confidence
        return self._request("PATCH", f"/v1/edges/{edge_id}", json_body=payload, workspace_id=workspace_id)

    def approve_inferred_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        note: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"source_hub_id": source_hub_id, "target_hub_id": target_hub_id, "edge_type": edge_type}
        if reason is not None:
            payload["reason"] = reason
        if confidence is not None:
            payload["confidence"] = confidence
        if note is not None:
            payload["note"] = note
        return self._request("POST", "/v1/edges/inferred/approve", json_body=payload, workspace_id=workspace_id)

    def reject_inferred_edge(
        self,
        source_hub_id: str,
        target_hub_id: str,
        edge_type: str,
        reason: Optional[str] = None,
        note: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"source_hub_id": source_hub_id, "target_hub_id": target_hub_id, "edge_type": edge_type}
        if reason is not None:
            payload["reason"] = reason
        if note is not None:
            payload["note"] = note
        return self._request("POST", "/v1/edges/inferred/reject", json_body=payload, workspace_id=workspace_id)

    def save_and_link_to_hub(
        self,
        content: str,
        hub_id: str,
        quick_summary: Optional[str] = None,
        save_purpose: Optional[str] = None,
        content_url: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        created = self.content_create_id(content=content, workspace_id=workspace_id)
        unsupported_fields = {
            name: "accepted for production MCP signature parity but not persisted by the public minimal content API"
            for name, value in {"save_purpose": save_purpose, "content_url": content_url}.items()
            if value is not None
        }
        if unsupported_fields:
            created["unsupported_fields"] = unsupported_fields
        if not created.get("persisted") or not created.get("content_id"):
            created["linked"] = False
            created["hub_id"] = hub_id
            return created
        content_id = created["content_id"]
        if quick_summary is not None:
            created["quick_summary_result"] = self.set_quick_summary(
                content_id=content_id, quick_summary=quick_summary, workspace_id=workspace_id
            )
        linked = self.hub_link_content(hub_id=hub_id, content_id=content_id, workspace_id=workspace_id)
        created["linked"] = True
        created["hub_link"] = linked
        created["hub_id"] = hub_id
        return created

    def graph_snapshot(self, include_inferred: bool = True, include_curated: bool = True, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        params = {
            "include_inferred": str(include_inferred).lower(),
            "include_curated": str(include_curated).lower(),
        }
        return self._request("GET", "/v1/graph/snapshot", params=params, workspace_id=workspace_id)

    def graph_node_full(self, content_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", f"/v1/graph/nodes/{content_id}/full", workspace_id=workspace_id)

    def graph_search_preview(
        self,
        query: str,
        node_type: Optional[str] = None,
        hub_id: Optional[str] = None,
        limit: int = 10,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"query": query, "limit": limit}
        if node_type is not None:
            params["node_type"] = node_type
        if hub_id is not None:
            params["hub_id"] = hub_id
        return self._request("GET", "/v1/graph/search-preview", params=params, workspace_id=workspace_id)

    def decision_create(self, payload: Dict[str, Any], workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", "/decisions/", json_body=payload, workspace_id=workspace_id)

    def decision_get(self, decision_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", f"/decisions/{decision_id}", workspace_id=workspace_id)

    def decision_list(
        self,
        status: Optional[str] = None,
        hub_id: Optional[str] = None,
        limit: Optional[int] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if hub_id is not None:
            params["hub_id"] = hub_id
        if limit is not None:
            params["limit"] = limit
        return self._request("GET", "/decisions/", params=params, workspace_id=workspace_id)

    def decision_update_status(self, decision_id: str, decision_status: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request(
            "PATCH",
            f"/decisions/{decision_id}/status",
            json_body={"decision_status": decision_status},
            workspace_id=workspace_id,
        )

    def decision_lineage(self, decision_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", f"/decisions/{decision_id}/lineage", workspace_id=workspace_id)

    def decision_conflicts(self, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        return self._request("GET", "/decisions/conflicts", workspace_id=workspace_id)

    def decision_timeline(
        self,
        hub_id: Optional[str] = None,
        tags: Optional[str] = None,
        limit: Optional[int] = None,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if hub_id is not None:
            params["hub_id"] = hub_id
        if tags is not None:
            params["tags"] = tags
        if limit is not None:
            params["limit"] = limit
        return self._request("GET", "/decisions/timeline", params=params, workspace_id=workspace_id)
