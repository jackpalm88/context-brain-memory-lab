from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import Header, HTTPException


DEFAULT_LOCAL_WORKSPACE = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: str
    source: Literal["header", "env", "db_default"]
    is_default: bool
    local_dev_default_used: bool
    slug: Optional[str] = None
    title: Optional[str] = None
    external_auth_subject: Optional[str] = None


def _database_url() -> str:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL required for this operation")
    return database_url


def _parse_workspace_uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid X-Workspace-ID") from exc


def _fetch_workspace(database_url: str, workspace_id: str) -> Optional[dict]:
    with psycopg2.connect(database_url) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT workspace_id::text AS workspace_id, slug, title, is_default
                  FROM cb_workspaces
                 WHERE workspace_id = %s::uuid
                   AND status = 'active'
                """,
                (workspace_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def _fetch_default_workspace(database_url: str) -> Optional[dict]:
    with psycopg2.connect(database_url) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT workspace_id::text AS workspace_id, slug, title, is_default
                  FROM cb_workspaces
                 WHERE is_default = TRUE
                   AND status = 'active'
                 ORDER BY created_at ASC
                 LIMIT 1
                """
            )
            row = cur.fetchone()
            return dict(row) if row else None


def resolve_workspace_context(x_workspace_id: Optional[str] = None) -> WorkspaceContext:
    """Resolve API workspace context for local-dev compatible P3B.

    X-Workspace-ID is a selector, not authentication or authorization.
    No header falls back to MEMORY_LAB_DEFAULT_WORKSPACE_ID, then cb_workspaces default.
    """
    if not os.environ.get("DATABASE_URL", ""):
        return WorkspaceContext(
            workspace_id=DEFAULT_LOCAL_WORKSPACE,
            source="env",
            is_default=True,
            local_dev_default_used=True,
        )

    database_url = _database_url()
    if x_workspace_id:
        workspace_id = _parse_workspace_uuid(x_workspace_id)
        row = _fetch_workspace(database_url, workspace_id)
        if not row:
            raise HTTPException(status_code=404, detail="workspace not found")
        return WorkspaceContext(
            workspace_id=row["workspace_id"],
            source="header",
            is_default=bool(row.get("is_default")),
            local_dev_default_used=False,
            slug=row.get("slug"),
            title=row.get("title"),
        )

    env_workspace_id = os.environ.get("MEMORY_LAB_DEFAULT_WORKSPACE_ID")
    if env_workspace_id:
        workspace_id = _parse_workspace_uuid(env_workspace_id)
        row = _fetch_workspace(database_url, workspace_id)
        if not row:
            raise HTTPException(status_code=404, detail="workspace not found")
        return WorkspaceContext(
            workspace_id=row["workspace_id"],
            source="env",
            is_default=bool(row.get("is_default")),
            local_dev_default_used=bool(row.get("is_default")),
            slug=row.get("slug"),
            title=row.get("title"),
        )

    row = _fetch_default_workspace(database_url)
    if not row:
        raise HTTPException(status_code=500, detail="default workspace not configured")
    return WorkspaceContext(
        workspace_id=row["workspace_id"],
        source="db_default",
        is_default=bool(row.get("is_default")),
        local_dev_default_used=True,
        slug=row.get("slug"),
        title=row.get("title"),
    )


def get_workspace_context(
    x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID"),
) -> WorkspaceContext:
    return resolve_workspace_context(x_workspace_id)
