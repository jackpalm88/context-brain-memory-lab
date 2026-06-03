"""PR1B MCP API-backed client for local minimal API only.

Scope boundary:
- Local-only HTTP calls to minimal API runtime endpoints.
- No DB direct access.
- No provider/LLM paths.
- No external network calls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


class MemoryLabApiError(RuntimeError):
    """Raised when API call fails or returns non-2xx response."""


@dataclass
class MemoryLabApiClient:
    base_url: str
    timeout_s: float = 15.0

    @staticmethod
    def from_env() -> "MemoryLabApiClient":
        host = os.getenv("MEMORY_LAB_API_HOST", "127.0.0.1")
        port = os.getenv("MEMORY_LAB_API_PORT", "8000")
        scheme = os.getenv("MEMORY_LAB_API_SCHEME", "http")
        if host not in {"127.0.0.1", "localhost"}:
            raise MemoryLabApiError(f"Unsafe host for local MCP plan: {host}")
        base_url = f"{scheme}://{host}:{port}".rstrip("/")
        return MemoryLabApiClient(base_url=base_url)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                timeout=self.timeout_s,
            )
        except requests.RequestException as exc:
            raise MemoryLabApiError(f"Request failed for {method} {url}: {exc}") from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            raise MemoryLabApiError(
                f"Non-2xx from {method} {url}: {resp.status_code} body={resp.text[:500]}"
            )

        try:
            return resp.json()
        except ValueError as exc:
            raise MemoryLabApiError(f"Invalid JSON from {method} {url}") from exc

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health")

    def content_create_id(self, content: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        return self._request("POST", "/v1/content", json_body=payload)

    def content_get(self, content_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/content/{content_id}")

    def hub_create(self, title: str, hub_type: Optional[str] = None, description: Optional[str] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"title": title}
        if hub_type is not None:
            payload["hub_type"] = hub_type
        if description is not None:
            payload["description"] = description
        return self._request("POST", "/v1/hubs", json_body=payload)

    def hub_get(self, hub_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/hubs/{hub_id}")

    def hub_link_content(self, hub_id: str, content_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/v1/hubs/{hub_id}/links", json_body={"content_id": content_id})

    def edge_create(self, source_hub_id: str, target_hub_id: str, edge_type: str) -> Dict[str, Any]:
        return self._request(
            "POST",
            "/v1/edges",
            json_body={
                "source_hub_id": source_hub_id,
                "target_hub_id": target_hub_id,
                "edge_type": edge_type,
            },
        )

    def edge_get(self, edge_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/edges/{edge_id}")

    def edge_list(self, hub_id: Optional[str] = None, include_archived: Optional[bool] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if hub_id is not None:
            params["hub_id"] = hub_id
        if include_archived is not None:
            params["include_archived"] = str(include_archived).lower()
        return self._request("GET", "/v1/edges", params=params)

    def edge_archive(self, edge_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/v1/edges/{edge_id}/archive")

    def retrieval_search(self, query: str, limit: Optional[int] = None) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"query": query}
        if limit is not None:
            payload["limit"] = limit
        return self._request("POST", "/v1/retrieval/search", json_body=payload)

    def decision_create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/decisions/", json_body=payload)

    def decision_get(self, decision_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/decisions/{decision_id}")

    def decision_list(self, status: Optional[str] = None, hub_id: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if status is not None:
            params["status"] = status
        if hub_id is not None:
            params["hub_id"] = hub_id
        if limit is not None:
            params["limit"] = limit
        return self._request("GET", "/decisions/", params=params)

    def decision_update_status(self, decision_id: str, decision_status: str) -> Dict[str, Any]:
        return self._request("PATCH", f"/decisions/{decision_id}/status", json_body={"decision_status": decision_status})

    def decision_lineage(self, decision_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/decisions/{decision_id}/lineage")

    def decision_conflicts(self) -> Dict[str, Any]:
        return self._request("GET", "/decisions/conflicts")

    def decision_timeline(self, hub_id: Optional[str] = None, tags: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if hub_id is not None:
            params["hub_id"] = hub_id
        if tags is not None:
            params["tags"] = tags
        if limit is not None:
            params["limit"] = limit
        return self._request("GET", "/decisions/timeline", params=params)
