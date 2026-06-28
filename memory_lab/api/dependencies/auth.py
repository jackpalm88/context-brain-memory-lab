from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Callable, Dict, Optional, Set
from uuid import UUID

import psycopg2
from fastapi import Header, HTTPException
from psycopg2.extras import Json, RealDictCursor

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import database_required, get_settings
from memory_lab.api.workspace_context import WorkspaceContext, resolve_workspace_context

ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "content.create": {"owner", "admin", "writer", "service_agent"},
    "content.read": {"owner", "admin", "writer", "reader", "service_agent", "auditor"},
    "hubs.create": {"owner", "admin", "writer", "service_agent"},
    "hubs.read": {"owner", "admin", "writer", "reader", "service_agent", "auditor"},
    "hubs.link": {"owner", "admin", "writer", "service_agent"},
    "hubs.update": {"owner", "admin", "writer"},
    "edges.create": {"owner", "admin", "writer", "service_agent"},
    "edges.read": {"owner", "admin", "writer", "reader", "service_agent", "auditor"},
    "edges.update": {"owner", "admin", "writer"},
    "edges.archive": {"owner", "admin"},
    "decisions.create": {"owner", "admin", "writer", "service_agent"},
    "decisions.read": {"owner", "admin", "writer", "reader", "service_agent", "auditor"},
    "decisions.update": {"owner", "admin"},
    "retrieval.search": {"owner", "admin", "writer", "reader", "service_agent"},
    "admin.cleanup": {"owner", "admin"},
    "admin.tier_override": {"owner", "admin"},
    "admin.tier_rollback": {"owner", "admin"},
}

ADMIN_PERMISSIONS = {"admin.cleanup", "admin.tier_override", "admin.tier_rollback"}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_prefix(token: str) -> str:
    if "." in token:
        return token.split(".", 1)[0][:32]
    return token[:12]


def _parse_bearer(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="unauthenticated")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=401, detail="invalid_authorization_header")
    return parts[1].strip()


def _bool_env(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _conn():
    return psycopg2.connect(database_required())


def _write_audit_event(
    *,
    event_type: str,
    decision: str,
    reason_code: Optional[str],
    required_permission: str,
    workspace_id: Optional[str],
    auth_subject_id: Optional[str] = None,
    role: Optional[str] = None,
    key_prefix: Optional[str] = None,
    status_code: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    if not _bool_env("MEMORY_LAB_AUTH_AUDIT_ENABLED", "true"):
        return
    safe_metadata: Dict[str, Any] = dict(metadata or {})
    if key_prefix:
        safe_metadata["key_prefix"] = key_prefix
    if status_code is not None:
        safe_metadata["status_code"] = status_code
    safe_metadata.pop("token", None)
    safe_metadata.pop("authorization", None)
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cb_audit_events (
                        event_type, auth_subject_id, workspace_id, decision, reason_code,
                        required_permission, role, client_type, metadata
                    ) VALUES (%s, %s::uuid, %s::uuid, %s, %s, %s, %s, 'api', %s::jsonb)
                    """,
                    (
                        event_type,
                        auth_subject_id,
                        workspace_id,
                        decision,
                        reason_code,
                        required_permission,
                        role,
                        Json(safe_metadata),
                    ),
                )
                conn.commit()
    except Exception:
        # Audit failure must not leak secrets. Auth decisions still fail closed before protected work.
        return


def _deny(
    status_code: int,
    reason_code: str,
    *,
    permission: str,
    workspace_id: Optional[str],
    auth_subject_id: Optional[str] = None,
    role: Optional[str] = None,
    key_prefix: Optional[str] = None,
) -> None:
    _write_audit_event(
        event_type="auth.deny",
        decision="deny",
        reason_code=reason_code,
        required_permission=permission,
        workspace_id=workspace_id,
        auth_subject_id=auth_subject_id,
        role=role,
        key_prefix=key_prefix,
        status_code=status_code,
        metadata={"action": permission},
    )
    raise HTTPException(status_code=status_code, detail=reason_code)


def _fetch_subject_and_membership(auth_subject_id: str, workspace_id: str):
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT auth_subject_id::text AS auth_subject_id, subject_type, status
                  FROM auth_subjects
                 WHERE auth_subject_id = %s::uuid
                """,
                (auth_subject_id,),
            )
            subject = cur.fetchone()
            if not subject:
                return None, None
            cur.execute(
                """
                SELECT role, status
                  FROM workspace_memberships
                 WHERE auth_subject_id = %s::uuid
                   AND workspace_id = %s::uuid
                """,
                (auth_subject_id, workspace_id),
            )
            membership = cur.fetchone()
            return dict(subject), dict(membership) if membership else None


def _auth_from_local_dev(permission: str, workspace: WorkspaceContext) -> AuthContext:
    if not _bool_env("MEMORY_LAB_AUTH_ALLOW_LOCAL_DEV_BYPASS", "false"):
        _deny(500, "local_dev_bypass_not_enabled", permission=permission, workspace_id=workspace.workspace_id)
    subject_id = os.environ.get("MEMORY_LAB_DEFAULT_AUTH_SUBJECT_ID", "")
    try:
        subject_id = str(UUID(subject_id))
    except Exception:
        _deny(500, "local_dev_default_subject_not_configured", permission=permission, workspace_id=workspace.workspace_id)
    subject, membership = _fetch_subject_and_membership(subject_id, workspace.workspace_id)
    if not subject or subject.get("status") != "active":
        _deny(403, "auth_subject_inactive", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=subject_id)
    if not membership:
        _deny(403, "workspace_membership_required", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=subject_id)
    if membership.get("status") != "active":
        _deny(403, "workspace_membership_inactive", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=subject_id, role=membership.get("role"))
    return AuthContext(
        auth_subject_id=subject_id,
        subject_type=subject["subject_type"],
        workspace_id=workspace.workspace_id,
        role=membership["role"],
        auth_method="local_dev_bypass",
        is_local_dev_bypass=True,
        workspace=workspace,
    )


def _auth_from_api_key(permission: str, workspace: WorkspaceContext, authorization: Optional[str]) -> AuthContext:
    try:
        token = _parse_bearer(authorization)
    except HTTPException as exc:
        _deny(exc.status_code, str(exc.detail), permission=permission, workspace_id=workspace.workspace_id)
    token_hash = _token_hash(token)
    candidate_hashes = [token_hash, f"sha256:{token_hash}"]
    presented_prefix = _token_prefix(token)
    with _conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT k.key_id::text AS key_id,
                       k.auth_subject_id::text AS auth_subject_id,
                       k.key_hash, k.key_prefix, k.status AS key_status,
                       k.expires_at, k.revoked_at,
                       s.subject_type, s.status AS subject_status
                  FROM api_keys k
                  JOIN auth_subjects s ON s.auth_subject_id = k.auth_subject_id
                 WHERE k.key_hash IN (%s, %s)
                 LIMIT 1
                """,
                tuple(candidate_hashes),
            )
            row = cur.fetchone()
            if not row:
                _deny(401, "invalid_api_key", permission=permission, workspace_id=workspace.workspace_id, key_prefix=presented_prefix)
            row = dict(row)
            if not hmac.compare_digest(str(row["key_hash"]), token_hash) and not hmac.compare_digest(str(row["key_hash"]), f"sha256:{token_hash}"):
                _deny(401, "invalid_api_key", permission=permission, workspace_id=workspace.workspace_id, key_prefix=row.get("key_prefix"))
            if row["key_status"] == "revoked" or row.get("revoked_at") is not None:
                _deny(401, "api_key_revoked", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=row["auth_subject_id"], key_prefix=row.get("key_prefix"))
            if row["key_status"] == "expired":
                _deny(401, "api_key_expired", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=row["auth_subject_id"], key_prefix=row.get("key_prefix"))
            cur.execute("SELECT NOW() > %s AS expired", (row.get("expires_at"),))
            if row.get("expires_at") is not None and cur.fetchone()["expired"]:
                _deny(401, "api_key_expired", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=row["auth_subject_id"], key_prefix=row.get("key_prefix"))
            if row["key_status"] != "active":
                _deny(401, "api_key_disabled", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=row["auth_subject_id"], key_prefix=row.get("key_prefix"))
            if row["subject_status"] != "active":
                _deny(403, "auth_subject_inactive", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=row["auth_subject_id"], key_prefix=row.get("key_prefix"))
            cur.execute(
                """
                SELECT role, status
                  FROM workspace_memberships
                 WHERE auth_subject_id = %s::uuid
                   AND workspace_id = %s::uuid
                """,
                (row["auth_subject_id"], workspace.workspace_id),
            )
            membership = cur.fetchone()
            if not membership:
                _deny(403, "workspace_membership_required", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=row["auth_subject_id"], key_prefix=row.get("key_prefix"))
            membership = dict(membership)
            if membership["status"] != "active":
                _deny(403, "workspace_membership_inactive", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=row["auth_subject_id"], role=membership.get("role"), key_prefix=row.get("key_prefix"))
            cur.execute("UPDATE api_keys SET last_used_at = NOW() WHERE key_id = %s::uuid", (row["key_id"],))
            conn.commit()
    return AuthContext(
        auth_subject_id=row["auth_subject_id"],
        subject_type=row["subject_type"],
        workspace_id=workspace.workspace_id,
        role=membership["role"],
        auth_method="api_key",
        is_local_dev_bypass=False,
        key_prefix=row.get("key_prefix"),
        workspace=workspace,
    )


def resolve_auth_context(permission: str, workspace: WorkspaceContext, authorization: Optional[str]) -> AuthContext:
    if not os.environ.get("DATABASE_URL", ""):
        read_permissions = {perm for perm in ROLE_PERMISSIONS if perm.endswith(".read")}
        if permission in ADMIN_PERMISSIONS or permission not in read_permissions:
            raise HTTPException(status_code=503, detail="DATABASE_URL required for this operation")
        return AuthContext(
            auth_subject_id="00000000-0000-0000-0000-000000000000",
            subject_type="user",
            workspace_id="00000000-0000-0000-0000-000000000000",
            role="reader",
            auth_method="local_dev_deterministic",
            is_local_dev_bypass=True,
            workspace=workspace,
        )

    auth_mode = os.environ.get("MEMORY_LAB_AUTH_MODE", "api_key").strip().lower() or "api_key"
    if auth_mode == "local_dev_bypass":
        ctx = _auth_from_local_dev(permission, workspace)
    elif auth_mode == "api_key":
        ctx = _auth_from_api_key(permission, workspace, authorization)
    else:
        _deny(500, "auth_mode_not_configured", permission=permission, workspace_id=workspace.workspace_id)

    allowed_roles = ROLE_PERMISSIONS.get(permission)
    if not allowed_roles:
        _deny(500, "permission_not_configured", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=ctx.auth_subject_id, role=ctx.role, key_prefix=ctx.key_prefix)
    if ctx.role not in allowed_roles:
        _deny(403, "role_forbidden", permission=permission, workspace_id=workspace.workspace_id, auth_subject_id=ctx.auth_subject_id, role=ctx.role, key_prefix=ctx.key_prefix)

    if permission in ADMIN_PERMISSIONS:
        _write_audit_event(
            event_type="admin.action",
            decision="allow",
            reason_code="allowed",
            required_permission=permission,
            workspace_id=ctx.workspace_id,
            auth_subject_id=ctx.auth_subject_id,
            role=ctx.role,
            key_prefix=ctx.key_prefix,
            status_code=200,
            metadata={"action": permission, "auth_method": ctx.auth_method},
        )
    return ctx


def require_permission(permission: str) -> Callable[..., AuthContext]:
    def _dependency(
        x_workspace_id: Optional[str] = Header(None, alias="X-Workspace-ID"),
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ) -> AuthContext:
        workspace = resolve_workspace_context(x_workspace_id)
        return resolve_auth_context(permission, workspace, authorization)

    return _dependency
