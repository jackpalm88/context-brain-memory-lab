"""M2 opt-in Postgres persistence backend.

This backend is selected only when an explicit database URL is supplied. The
empty-env deterministic path must not import psycopg2 or open a DB connection.
The SQL implementation stores caller-supplied persistence contract objects in
existing Context Brain schema direction: content_items/content_chunks for
content, cb_governance_states for current governance state, and the existing
cb_governance_events append-only stream for governance events.
"""
from __future__ import annotations

import importlib
import json
import uuid
from typing import Any, Mapping

from memory_lab.providers.embedding_backend import EmbeddingBackend
from memory_lab.persistence.body_chunks import persist_body_chunks

from memory_lab.governance.state import (
    GovernanceProvenance,
    GovernanceRecordRef,
    GovernanceState,
    validate_governance_state,
)
from memory_lab.governance.state_events import (
    B25_STATE_EVENT_TYPE,
    GovernanceStateEventContract,
    validate_governance_state_event_contract,
)
from memory_lab.governance.workspace import validate_workspace_boundary, validate_workspace_id
from memory_lab.persistence.results import (
    ContentPersistenceRecord,
    PersistenceError,
    PersistenceOperationMetadata,
    PersistenceResult,
)

M2_POSTGRES_MODE = "m2_postgres_persistence_roundtrip_v1"


def _postgres_metadata(uses_embeddings: bool = False, uses_vector_db: bool = False, degraded_reason: str | None = None) -> PersistenceOperationMetadata:
    return PersistenceOperationMetadata(
        capability="m2_postgres_persistence_backend",
        mode=M2_POSTGRES_MODE,
        input_scope="caller_supplied_values_with_explicit_database_url",
        live_backend_used=True,
        requires_db=True,
        requires_provider=uses_embeddings,
        requires_private_context_brain=False,
        uses_embeddings=uses_embeddings,
        uses_vector_db=uses_vector_db,
        mutates_external_state=True,
        limitations=(
            "explicit_database_url_required",
            "sql_persistence_round_trip_only",
            "no_provider_call",
            "no_embedding_or_vector_backend",
            "no_private_context_brain_access",
        ),
        non_claims=(
            "not_production_ready",
            "not_full_context_brain_parity",
            "not_private_context_brain_parity",
            "not_vector_retrieval",
            "not_llm_reasoning",
        ),
        degraded_reason=degraded_reason,
    )


class PostgresPersistenceBackend:
    """Explicit DB-backed persistence backend for M2 save/load round-trips."""

    def __init__(self, database_url: str, embedding_backend: EmbeddingBackend | None = None, vector_embeddings_enabled: bool | None = None):
        self.database_url = (database_url or "").strip()
        self.embedding_backend = embedding_backend
        self.vector_embeddings_enabled = _vector_embeddings_enabled() if vector_embeddings_enabled is None else bool(vector_embeddings_enabled)

    def put_content_record(self, record: ContentPersistenceRecord | Any) -> PersistenceResult:
        operation = "put_content_record"
        normalized = _normalize_content_record(record)
        for field_name, value in (("workspace_id", normalized.workspace_id), ("content_id", normalized.content_id)):
            check = _validate_required_id(value, field_name, operation) or _validate_uuid(value, field_name, operation)
            if check is not None:
                return check

        operation_state: dict[str, Any] = {"uses_embeddings": False, "uses_vector_db": False, "warnings": []}

        def work(conn: Any) -> ContentPersistenceRecord:
            with conn.cursor() as cur:
                _ensure_workspace(cur, normalized.workspace_id)
                cur.execute(
                    """
                    INSERT INTO content_items (
                        content_id, workspace_id, quick_summary,
                        content_title, content_metadata, governance_state_id, updated_at
                    )
                    VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb, %s, NOW())
                    ON CONFLICT (content_id) DO UPDATE
                       SET workspace_id = EXCLUDED.workspace_id,
                           quick_summary = EXCLUDED.quick_summary,
                           content_title = EXCLUDED.content_title,
                           content_metadata = EXCLUDED.content_metadata,
                           governance_state_id = EXCLUDED.governance_state_id,
                           updated_at = NOW()
                    """,
                    (
                        normalized.content_id,
                        normalized.workspace_id,
                        normalized.text[:300] if normalized.text else None,
                        normalized.title,
                        json.dumps(dict(normalized.metadata or {}), sort_keys=True),
                        normalized.governance_state_id,
                    ),
                )
                _chunk_result = persist_body_chunks(
                    cur,
                    normalized.content_id,
                    normalized.workspace_id,
                    normalized.text,
                    embedding_backend=self._embedding_backend(),
                    vector_enabled=self.vector_embeddings_enabled,
                )
                if _chunk_result.uses_embeddings:
                    operation_state["uses_embeddings"] = True
                    operation_state["uses_vector_db"] = True
                operation_state["warnings"].extend(_chunk_result.warnings)
            conn.commit()
            return normalized

        return self._run(
            operation,
            work,
            metadata=lambda: _postgres_metadata(
                uses_embeddings=bool(operation_state["uses_embeddings"]),
                uses_vector_db=bool(operation_state["uses_vector_db"]),
                degraded_reason=(operation_state["warnings"][0] if operation_state["warnings"] else None),
            ),
            warnings=lambda: tuple(operation_state["warnings"]),
        )

    def get_content_record(self, workspace_id: str, content_id: str) -> PersistenceResult:
        operation = "get_content_record"
        for field_name, value in (("workspace_id", workspace_id), ("content_id", content_id)):
            check = _validate_required_id(value, field_name, operation) or _validate_uuid(value, field_name, operation)
            if check is not None:
                return check

        def work(conn: Any) -> ContentPersistenceRecord | None:
            with conn.cursor(cursor_factory=self._real_dict_cursor()) as cur:
                cur.execute(
                    """
                    SELECT ci.content_id::text, ci.workspace_id::text, ci.content_title,
                           ci.content_metadata, ci.governance_state_id,
                           COALESCE(ch.chunk_text, '') AS text
                      FROM content_items ci
                      LEFT JOIN content_chunks ch
                        ON ch.content_id = ci.content_id AND ch.chunk_index = 0
                     WHERE ci.workspace_id = %s::uuid AND ci.content_id = %s::uuid
                    """,
                    (workspace_id, content_id),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return ContentPersistenceRecord(
                content_id=str(row["content_id"]),
                workspace_id=str(row["workspace_id"]),
                text=row.get("text") or "",
                title=row.get("content_title"),
                metadata=dict(row.get("content_metadata") or {}),
                governance_state_id=row.get("governance_state_id"),
            )

        result = self._run(operation, work)
        if result.ok and result.value is None:
            return _failure(operation, "not_found", "content record not found", "content_id")
        return result

    def list_content_records(self, workspace_id: str) -> PersistenceResult:
        operation = "list_content_records"
        check = _validate_workspace_uuid(workspace_id, operation)
        if check is not None:
            return check

        def work(conn: Any) -> tuple[ContentPersistenceRecord, ...]:
            with conn.cursor(cursor_factory=self._real_dict_cursor()) as cur:
                cur.execute(
                    """
                    SELECT ci.content_id::text, ci.workspace_id::text, ci.content_title,
                           ci.content_metadata, ci.governance_state_id,
                           COALESCE(ch.chunk_text, '') AS text
                      FROM content_items ci
                      LEFT JOIN content_chunks ch
                        ON ch.content_id = ci.content_id AND ch.chunk_index = 0
                     WHERE ci.workspace_id = %s::uuid
                     ORDER BY ci.content_id::text
                    """,
                    (workspace_id,),
                )
                rows = cur.fetchall()
            return tuple(
                ContentPersistenceRecord(
                    content_id=str(row["content_id"]),
                    workspace_id=str(row["workspace_id"]),
                    text=row.get("text") or "",
                    title=row.get("content_title"),
                    metadata=dict(row.get("content_metadata") or {}),
                    governance_state_id=row.get("governance_state_id"),
                )
                for row in rows
            )

        return self._run(operation, work)

    def put_governance_state(self, state: GovernanceState) -> PersistenceResult:
        operation = "put_governance_state"
        result = validate_governance_state(state)
        if not result.valid:
            return _failure(operation, "invalid_governance_state", "; ".join(result.errors))
        check = _validate_workspace_uuid(state.record_ref.workspace_id, operation)
        if check is not None:
            return check
        if state.record_ref.content_id:
            check = _validate_uuid(state.record_ref.content_id, "content_id", operation)
            if check is not None:
                return check

        def work(conn: Any) -> GovernanceState:
            with conn.cursor() as cur:
                _ensure_workspace(cur, state.record_ref.workspace_id)
                cur.execute(
                    """
                    INSERT INTO cb_governance_states (
                        workspace_id, record_id, record_type, content_id, status, tier,
                        provenance, supersedes, superseded_by, state_reason,
                        limitations, non_claims, mode, updated_at
                    )
                    VALUES (%s::uuid, %s, %s, %s::uuid, %s, %s, %s::jsonb, %s, %s, %s,
                            %s::jsonb, %s::jsonb, %s, NOW())
                    ON CONFLICT (workspace_id, record_id) DO UPDATE
                       SET record_type = EXCLUDED.record_type,
                           content_id = EXCLUDED.content_id,
                           status = EXCLUDED.status,
                           tier = EXCLUDED.tier,
                           provenance = EXCLUDED.provenance,
                           supersedes = EXCLUDED.supersedes,
                           superseded_by = EXCLUDED.superseded_by,
                           state_reason = EXCLUDED.state_reason,
                           limitations = EXCLUDED.limitations,
                           non_claims = EXCLUDED.non_claims,
                           mode = EXCLUDED.mode,
                           updated_at = NOW()
                    """,
                    (
                        state.record_ref.workspace_id,
                        state.record_ref.record_id,
                        state.record_ref.record_type,
                        state.record_ref.content_id,
                        state.status,
                        state.tier,
                        json.dumps(_provenance_to_dict(state.provenance), sort_keys=True),
                        state.supersedes,
                        state.superseded_by,
                        state.state_reason,
                        json.dumps(list(state.limitations), sort_keys=True),
                        json.dumps(list(state.non_claims), sort_keys=True),
                        state.mode,
                    ),
                )
            conn.commit()
            return state

        return self._run(operation, work)

    def get_governance_state(self, workspace_id: str, record_id: str) -> PersistenceResult:
        operation = "get_governance_state"
        check = _validate_workspace_uuid(workspace_id, operation)
        if check is not None:
            return check
        check = _validate_required_id(record_id, "record_id", operation)
        if check is not None:
            return check

        def work(conn: Any) -> GovernanceState | None:
            with conn.cursor(cursor_factory=self._real_dict_cursor()) as cur:
                cur.execute(
                    """
                    SELECT workspace_id::text, record_id, record_type, content_id::text,
                           status, tier, provenance, supersedes, superseded_by,
                           state_reason, limitations, non_claims, mode
                      FROM cb_governance_states
                     WHERE workspace_id = %s::uuid AND record_id = %s
                    """,
                    (workspace_id, record_id),
                )
                row = cur.fetchone()
            if row is None:
                return None
            return GovernanceState(
                record_ref=GovernanceRecordRef(
                    record_id=row["record_id"],
                    record_type=row["record_type"],
                    workspace_id=str(row["workspace_id"]),
                    content_id=str(row["content_id"]) if row.get("content_id") else None,
                ),
                status=row["status"],
                tier=row["tier"],
                provenance=_provenance_from_mapping(row["provenance"] or {}),
                supersedes=row.get("supersedes"),
                superseded_by=row.get("superseded_by"),
                state_reason=row.get("state_reason"),
                limitations=tuple(row.get("limitations") or ()),
                non_claims=tuple(row.get("non_claims") or ()),
                mode=row.get("mode"),
            )

        result = self._run(operation, work)
        if result.ok and result.value is None:
            return _failure(operation, "not_found", "governance state not found", "record_id")
        return result

    def append_governance_event(self, event: GovernanceStateEventContract) -> PersistenceResult:
        operation = "append_governance_event"
        result = validate_governance_state_event_contract(event)
        if not result.valid:
            return _failure(operation, "invalid_governance_event", "; ".join(result.errors))
        boundary = validate_workspace_boundary((event.record_ref,), event.workspace_id)
        if not boundary.valid:
            return _failure(operation, "workspace_boundary_violation", "; ".join(boundary.errors), "workspace_id")
        check = _validate_workspace_uuid(event.workspace_id, operation)
        if check is not None:
            return check
        if event.record_ref.content_id:
            check = _validate_uuid(event.record_ref.content_id, "content_id", operation)
            if check is not None:
                return check

        def work(conn: Any) -> GovernanceStateEventContract:
            with conn.cursor() as cur:
                _ensure_workspace(cur, event.workspace_id)
                cur.execute(
                    """
                    INSERT INTO cb_governance_events (
                        event_id, event_type, workspace_id, content_id, record_id,
                        previous_tier, new_tier, previous_status, next_status,
                        transition_reason, transition_rule, trigger_type, trigger_source,
                        trace_id, lineage_ref, event_payload
                    )
                    VALUES (%s::uuid, %s, %s::uuid, %s::uuid, %s, %s, %s, %s, %s,
                            %s, %s, 'system', 'mcp', %s, %s, %s::jsonb)
                    """,
                    (
                        str(uuid.uuid4()),
                        B25_STATE_EVENT_TYPE,
                        event.workspace_id,
                        event.record_ref.content_id,
                        event.record_ref.record_id,
                        event.previous_tier,
                        event.next_tier or event.previous_tier or "persistent",
                        event.previous_status,
                        event.next_status,
                        event.event_reason or "governance state contract event",
                        "m2_persistence_roundtrip",
                        event.provenance.trace_id,
                        event.record_ref.source_ref,
                        json.dumps(_governance_event_to_dict(event), sort_keys=True),
                    ),
                )
            conn.commit()
            return event

        return self._run(operation, work)

    def list_governance_events(self, workspace_id: str, record_id: str | None = None) -> PersistenceResult:
        operation = "list_governance_events"
        check = _validate_workspace_uuid(workspace_id, operation)
        if check is not None:
            return check
        if record_id is not None:
            check = _validate_required_id(record_id, "record_id", operation)
            if check is not None:
                return check

        def work(conn: Any) -> tuple[GovernanceStateEventContract, ...]:
            params: list[Any] = [workspace_id, B25_STATE_EVENT_TYPE]
            where = "workspace_id = %s::uuid AND event_type = %s"
            if record_id is not None:
                where += " AND record_id = %s"
                params.append(record_id)
            with conn.cursor(cursor_factory=self._real_dict_cursor()) as cur:
                cur.execute(
                    f"""
                    SELECT event_payload
                      FROM cb_governance_events
                     WHERE {where}
                     ORDER BY created_at ASC, event_id ASC
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
            return tuple(_governance_event_from_mapping(row["event_payload"] or {}) for row in rows)

        return self._run(operation, work)

    def _embedding_backend(self) -> EmbeddingBackend | None:
        if self.embedding_backend is not None:
            return self.embedding_backend
        if not self.vector_embeddings_enabled:
            return None
        from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend

        self.embedding_backend = OpenAIEmbeddingBackend()
        return self.embedding_backend

    def _run(self, operation: str, work: Any, metadata: Any = _postgres_metadata, warnings: Any = tuple) -> PersistenceResult:
        if not self.database_url:
            return _failure(operation, "database_url_required", "DATABASE_URL is required for PostgresPersistenceBackend operations.", "database_url")
        try:
            conn = self._connect()
        except Exception as exc:
            return _failure(operation, "postgres_connection_failed", f"Postgres connection failed: {exc}", "database_url")
        try:
            try:
                value = work(conn)
            except Exception:
                conn.rollback()
                raise
            return PersistenceResult(ok=True, operation=operation, value=value, metadata=metadata(), warnings=warnings())
        except Exception as exc:
            return _failure(operation, "postgres_operation_failed", f"Postgres operation failed: {exc}")
        finally:
            conn.close()

    def _connect(self) -> Any:
        psycopg2 = importlib.import_module("psycopg2")
        return psycopg2.connect(self.database_url)

    def _real_dict_cursor(self) -> Any:
        extras = importlib.import_module("psycopg2.extras")
        return extras.RealDictCursor


def _failure(operation: str, code: str, message: str, field: str | None = None) -> PersistenceResult:
    metadata = _postgres_metadata()
    return PersistenceResult(
        ok=False,
        operation=operation,
        error=PersistenceError(code=code, message=message, field=field, metadata=metadata),
        metadata=metadata,
    )


def _ensure_workspace(cur: Any, workspace_id: str) -> None:
    slug = f"m2-persistence-{workspace_id}"
    cur.execute(
        """
        INSERT INTO cb_workspaces (workspace_id, slug, title, status, is_default, created_by_subject)
        VALUES (%s::uuid, %s, %s, %s, FALSE, %s)
        ON CONFLICT (workspace_id) DO NOTHING
        """,
        (workspace_id, slug, f"M2 Persistence Workspace {workspace_id}", "active", "m2-postgres-persistence-backend"),
    )


def _validate_required_id(value: object, field_name: str, operation: str) -> PersistenceResult | None:
    if not isinstance(value, str) or not value.strip():
        return _failure(operation, f"invalid_{field_name}", f"{field_name} is required", field_name)
    return None


def _validate_uuid(value: str, field_name: str, operation: str) -> PersistenceResult | None:
    try:
        uuid.UUID(str(value).strip())
    except Exception:
        return _failure(operation, f"invalid_{field_name}", f"{field_name} must be a UUID for Postgres persistence", field_name)
    return None


def _validate_workspace_uuid(workspace_id: str, operation: str) -> PersistenceResult | None:
    check = validate_workspace_id(workspace_id)
    if not check.valid:
        return _failure(operation, "invalid_workspace", "; ".join(check.errors), "workspace_id")
    return _validate_uuid(workspace_id, "workspace_id", operation)


def _normalize_content_record(record: ContentPersistenceRecord | Any) -> ContentPersistenceRecord:
    if isinstance(record, ContentPersistenceRecord):
        return ContentPersistenceRecord(
            content_id=record.content_id,
            workspace_id=record.workspace_id,
            text=record.text,
            title=record.title,
            metadata=dict(record.metadata or {}),
            governance_state_id=record.governance_state_id,
        )
    if isinstance(record, Mapping):
        return ContentPersistenceRecord(
            content_id=str(record.get("content_id") or record.get("record_id") or ""),
            workspace_id=str(record.get("workspace_id") or ""),
            text=str(record.get("text") or ""),
            title=record.get("title"),
            metadata=dict(record.get("metadata") or {}),
            governance_state_id=record.get("governance_state_id"),
        )
    return ContentPersistenceRecord(
        content_id=str(getattr(record, "content_id", getattr(record, "record_id", "")) or ""),
        workspace_id=str(getattr(record, "workspace_id", "") or ""),
        text=str(getattr(record, "text", "") or ""),
        title=getattr(record, "title", None),
        metadata=dict(getattr(record, "metadata", {}) or {}),
        governance_state_id=getattr(record, "governance_state_id", None),
    )


def _provenance_to_dict(provenance: GovernanceProvenance) -> dict[str, Any]:
    return {
        "source_type": provenance.source_type,
        "source_id": provenance.source_id,
        "source_label": provenance.source_label,
        "created_by": provenance.created_by,
        "trace_id": provenance.trace_id,
        "created_at": provenance.created_at,
        "metadata": dict(provenance.metadata or {}),
    }


def _provenance_from_mapping(payload: Mapping[str, Any]) -> GovernanceProvenance:
    return GovernanceProvenance(
        source_type=str(payload.get("source_type") or ""),
        source_id=str(payload.get("source_id") or ""),
        source_label=str(payload.get("source_label") or ""),
        created_by=str(payload.get("created_by") or ""),
        trace_id=str(payload.get("trace_id") or ""),
        created_at=str(payload.get("created_at") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def _governance_event_to_dict(event: GovernanceStateEventContract) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "workspace_id": event.workspace_id,
        "record_ref": {
            "record_id": event.record_ref.record_id,
            "record_type": event.record_ref.record_type,
            "workspace_id": event.record_ref.workspace_id,
            "content_id": event.record_ref.content_id,
            "source_ref": event.record_ref.source_ref,
        },
        "provenance": _provenance_to_dict(event.provenance),
        "previous_status": event.previous_status,
        "next_status": event.next_status,
        "previous_tier": event.previous_tier,
        "next_tier": event.next_tier,
        "event_reason": event.event_reason,
        "limitations": list(event.limitations),
        "non_claims": list(event.non_claims),
        "mode": event.mode,
    }


def _governance_event_from_mapping(payload: Mapping[str, Any]) -> GovernanceStateEventContract:
    ref_payload = payload.get("record_ref") or {}
    record_ref = GovernanceRecordRef(
        record_id=str(ref_payload.get("record_id") or ""),
        record_type=str(ref_payload.get("record_type") or ""),
        workspace_id=str(ref_payload.get("workspace_id") or payload.get("workspace_id") or ""),
        content_id=ref_payload.get("content_id"),
        source_ref=ref_payload.get("source_ref"),
    )
    return GovernanceStateEventContract(
        event_type=str(payload.get("event_type") or B25_STATE_EVENT_TYPE),
        workspace_id=str(payload.get("workspace_id") or record_ref.workspace_id),
        record_ref=record_ref,
        provenance=_provenance_from_mapping(payload.get("provenance") or {}),
        previous_status=payload.get("previous_status"),
        next_status=payload.get("next_status"),
        previous_tier=payload.get("previous_tier"),
        next_tier=payload.get("next_tier"),
        event_reason=payload.get("event_reason"),
        limitations=tuple(payload.get("limitations") or ()),
        non_claims=tuple(payload.get("non_claims") or ()),
        mode=str(payload.get("mode") or ""),
    )


def _env_bool(name: str, default: bool = False) -> bool:
    import os

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _vector_embeddings_enabled() -> bool:
    return _env_bool("MEMORY_LAB_VECTOR_EMBEDDINGS_ENABLED", False) or _env_bool("MEMORY_LAB_PROVIDER_EMBEDDINGS_ENABLED", False)


