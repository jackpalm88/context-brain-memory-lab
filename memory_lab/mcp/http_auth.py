"""MCP-HTTP-1 Bearer token authentication middleware for streamable-http transport.

Architecture:
- Starlette pure-ASGI middleware — wraps the StreamableHTTP ASGI app.
- Extracts Authorization: Bearer <token> from every incoming request.
- In api_key mode: validates token against api_keys table (SHA-256 hash match),
  resolves workspace_memberships, injects X-Workspace-ID header downstream.
- In none mode (dev/loopback only): injects default workspace from config.
- On rejection: returns HTTP 401 JSON response before the MCP app sees the request.

No tool logic. No DB schema changes. Reuses existing api_keys / workspace_memberships tables.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Callable, Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None
    return parts[1].strip()


def _reject(status: int, detail: str) -> Callable:
    async def _respond(scope: Scope, receive: Receive, send: Send) -> None:
        resp = JSONResponse({"ok": False, "error": detail}, status_code=status)
        await resp(scope, receive, send)

    return _respond


def _resolve_workspace_api_key(token: str) -> Optional[str]:
    """Validate Bearer token against api_keys table; return workspace_id or None.

    Returns workspace_id string on success, None if key not found/invalid.
    Raises on DB connection failure (caller converts to 503).
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return None

    import psycopg2
    from psycopg2.extras import RealDictCursor

    token_hash = _token_hash(token)
    candidate_hashes = [token_hash, f"sha256:{token_hash}"]

    with psycopg2.connect(database_url) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT k.auth_subject_id::text AS auth_subject_id,
                       k.key_hash, k.status AS key_status,
                       k.expires_at, k.revoked_at
                  FROM api_keys k
                  JOIN auth_subjects s ON s.auth_subject_id = k.auth_subject_id
                 WHERE k.key_hash IN (%s, %s)
                   AND k.status = 'active'
                   AND s.status = 'active'
                 LIMIT 1
                """,
                tuple(candidate_hashes),
            )
            row = cur.fetchone()
            if not row:
                return None
            row = dict(row)

            # HMAC-safe compare
            stored = str(row["key_hash"])
            if not (
                hmac.compare_digest(stored, token_hash)
                or hmac.compare_digest(stored, f"sha256:{token_hash}")
            ):
                return None
            if row.get("revoked_at") is not None:
                return None
            if row.get("expires_at") is not None:
                cur.execute("SELECT NOW() > %s AS expired", (row["expires_at"],))
                if cur.fetchone()["expired"]:
                    return None

            auth_subject_id = row["auth_subject_id"]

            # Resolve workspace from membership
            cur.execute(
                """
                SELECT wm.workspace_id::text AS workspace_id
                  FROM workspace_memberships wm
                 WHERE wm.auth_subject_id = %s::uuid
                   AND wm.status = 'active'
                 ORDER BY wm.created_at ASC
                 LIMIT 1
                """,
                (auth_subject_id,),
            )
            membership = cur.fetchone()
            if not membership:
                return None

            # Update last_used_at (best-effort, non-fatal)
            try:
                cur.execute(
                    "UPDATE api_keys SET last_used_at = NOW() WHERE key_hash IN (%s, %s)",
                    tuple(candidate_hashes),
                )
                conn.commit()
            except Exception:
                pass

            return str(membership["workspace_id"])


def _inject_workspace(scope: Scope, workspace_id: str) -> Scope:
    """Return a copy of scope with X-Workspace-ID injected into headers.

    Removes any existing X-Workspace-ID to prevent caller spoofing.
    """
    headers = list(scope.get("headers", []))
    headers = [(k, v) for k, v in headers if k.lower() != b"x-workspace-id"]
    headers.append((b"x-workspace-id", workspace_id.encode("utf-8")))
    return {**scope, "headers": headers}


class MCPBearerAuthMiddleware:
    """ASGI middleware that enforces Bearer token auth before the MCP transport app.

    Injected between the Starlette router and the StreamableHTTP ASGI endpoint.
    Two modes (from http_config.get_mcp_http_auth_mode()):
      'api_key' — token required; workspace resolved from DB.
      'none'    — no token required; default workspace injected from config.

    The resolved workspace_id is injected as X-Workspace-ID so that
    MCP tool calls propagate it to the REST API via MemoryLabApiClient.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        auth_mode: str,
        default_workspace_id: str,
    ) -> None:
        self.app = app
        self.auth_mode = auth_mode
        self.default_workspace_id = default_workspace_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        if self.auth_mode == "none":
            scope = _inject_workspace(scope, self.default_workspace_id)
            await self.app(scope, receive, send)
            return

        # api_key mode — require Authorization: Bearer <token>
        headers = dict(scope.get("headers", []))
        auth_bytes = headers.get(b"authorization", b"")
        auth_header = auth_bytes.decode("utf-8", errors="replace")
        token = _parse_bearer(auth_header)

        if not token:
            await _reject(401, "unauthenticated")(scope, receive, send)
            return

        try:
            workspace_id = _resolve_workspace_api_key(token)
        except Exception:
            await _reject(503, "auth_backend_unavailable")(scope, receive, send)
            return

        if workspace_id is None:
            await _reject(401, "invalid_api_key")(scope, receive, send)
            return

        scope = _inject_workspace(scope, workspace_id)
        await self.app(scope, receive, send)
