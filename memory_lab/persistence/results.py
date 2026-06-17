"""B26 deterministic persistence result contracts.

The objects in this module are public-safe contract values for supplied data.
They do not open storage connections, read environment variables, call external
services, call providers, or access private memory systems.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Mapping

B26_MODE = "b26_contract_only_in_memory_test_backend_v1"
B26_LIMITATIONS: tuple[str, ...] = (
    "caller_supplied_values_only",
    "deterministic_contract_layer_only",
    "in_memory_backend_for_tests_only",
    "workspace_id_boundary_over_supplied_values",
    "no_live_backend",
    "no_database_access",
    "no_migrations",
    "no_provider_call",
    "no_external_service_call",
    "no_api_or_auth_runtime",
    "no_private_memory_access",
    "no_embedding_or_vector_backend",
)
B26_NON_CLAIMS: tuple[str, ...] = (
    "not_production_ready",
    "not_database_backed_runtime",
    "not_live_persistence_runtime",
    "not_auth_or_rbac_enforcement",
    "not_live_ingestion_pipeline",
    "not_embedding_or_vector_retrieval",
    "not_full_context_brain_parity",
    "not_private_context_brain_parity",
    "not_mcp_or_gpt_actions_readiness",
)

@dataclass(frozen=True)
class PersistenceOperationMetadata:
    capability: str = "b26_persistence_backend_contract"
    mode: str = B26_MODE
    input_scope: str = "caller_supplied_values_only"
    live_backend_used: bool = False
    requires_db: bool = False
    requires_provider: bool = False
    requires_private_context_brain: bool = False
    uses_embeddings: bool = False
    uses_vector_db: bool = False
    mutates_external_state: bool = False
    limitations: tuple[str, ...] = B26_LIMITATIONS
    non_claims: tuple[str, ...] = B26_NON_CLAIMS
    degraded_reason: str | None = "contract_only_in_memory_test_backend"

@dataclass(frozen=True)
class PersistenceError:
    code: str
    message: str
    field: str | None = None
    metadata: PersistenceOperationMetadata = dataclass_field(default_factory=PersistenceOperationMetadata)

@dataclass(frozen=True)
class PersistenceResult:
    ok: bool
    operation: str
    value: Any = None
    error: PersistenceError | None = None
    metadata: PersistenceOperationMetadata = dataclass_field(default_factory=PersistenceOperationMetadata)
    warnings: tuple[str, ...] = ()

    @classmethod
    def success(cls, operation: str, value: Any = None, warnings: tuple[str, ...] = ()) -> "PersistenceResult":
        return cls(ok=True, operation=operation, value=value, warnings=tuple(warnings))

    @classmethod
    def failure(cls, operation: str, code: str, message: str, field: str | None = None) -> "PersistenceResult":
        err = PersistenceError(code=code, message=message, field=field)
        return cls(ok=False, operation=operation, error=err)

@dataclass(frozen=True)
class ContentPersistenceRecord:
    content_id: str
    workspace_id: str
    text: str = ""
    title: str | None = None
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)
    governance_state_id: str | None = None
