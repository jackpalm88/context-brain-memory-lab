"""M2 opt-in Postgres persistence backend skeleton.

This module defines the real DB-backed persistence adapter surface for M2. It
is intentionally not wired into deterministic paths unless DATABASE_URL is
explicitly supplied through the M2 backend factory. Until the SQL round-trip
implementation lands, operations return structured failures instead of fake
successes or in-memory stand-ins.
"""
from __future__ import annotations

from typing import Any

from memory_lab.governance.state import GovernanceState
from memory_lab.governance.state_events import GovernanceStateEventContract
from memory_lab.persistence.results import ContentPersistenceRecord, PersistenceError, PersistenceOperationMetadata, PersistenceResult


M2_POSTGRES_MODE = "m2_postgres_persistence_backend_skeleton_v1"


def _postgres_metadata() -> PersistenceOperationMetadata:
    return PersistenceOperationMetadata(
        capability="m2_postgres_persistence_backend",
        mode=M2_POSTGRES_MODE,
        input_scope="caller_supplied_values_with_explicit_database_url",
        live_backend_used=False,
        requires_db=True,
        requires_provider=False,
        requires_private_context_brain=False,
        uses_embeddings=False,
        uses_vector_db=False,
        mutates_external_state=False,
        limitations=(
            "explicit_database_url_required",
            "sql_persistence_round_trip_not_implemented_yet",
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
        degraded_reason="m2_sql_persistence_implementation_pending",
    )


class PostgresPersistenceBackend:
    """Explicit DB-required persistence backend placeholder for M2 wiring.

    The class stores the supplied DSN but deliberately does not import psycopg2,
    open a connection, run migrations, or emulate persistence. Full SQL-backed
    save/load behavior belongs to the next M2 implementation step.
    """

    def __init__(self, database_url: str):
        self.database_url = (database_url or "").strip()

    def put_content_record(self, record: ContentPersistenceRecord | Any) -> PersistenceResult:
        return self._unavailable("put_content_record")

    def get_content_record(self, workspace_id: str, content_id: str) -> PersistenceResult:
        return self._unavailable("get_content_record")

    def list_content_records(self, workspace_id: str) -> PersistenceResult:
        return self._unavailable("list_content_records")

    def put_governance_state(self, state: GovernanceState) -> PersistenceResult:
        return self._unavailable("put_governance_state")

    def get_governance_state(self, workspace_id: str, record_id: str) -> PersistenceResult:
        return self._unavailable("get_governance_state")

    def append_governance_event(self, event: GovernanceStateEventContract) -> PersistenceResult:
        return self._unavailable("append_governance_event")

    def list_governance_events(self, workspace_id: str, record_id: str | None = None) -> PersistenceResult:
        return self._unavailable("list_governance_events")

    def _unavailable(self, operation: str) -> PersistenceResult:
        metadata = _postgres_metadata()
        if not self.database_url:
            return PersistenceResult(
                ok=False,
                operation=operation,
                error=PersistenceError(
                    code="database_url_required",
                    message="DATABASE_URL is required for PostgresPersistenceBackend operations.",
                    field="database_url",
                    metadata=metadata,
                ),
                metadata=metadata,
            )
        return PersistenceResult(
            ok=False,
            operation=operation,
            error=PersistenceError(
                code="postgres_sql_persistence_not_implemented",
                message="Postgres persistence SQL round-trip is not implemented yet; no fake/noop persistence was performed.",
                metadata=metadata,
            ),
            metadata=metadata,
        )
