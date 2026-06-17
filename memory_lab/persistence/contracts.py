"""B26 persistence backend protocols.

These protocols describe deterministic storage boundaries for future adapters.
They are interface contracts only and intentionally contain no runtime wiring.
"""
from __future__ import annotations

from typing import Any, Protocol

from memory_lab.governance.state import GovernanceState
from memory_lab.governance.state_events import GovernanceStateEventContract
from memory_lab.persistence.results import ContentPersistenceRecord, PersistenceResult

class ContentPersistenceBackend(Protocol):
    def put_content_record(self, record: ContentPersistenceRecord | Any) -> PersistenceResult:
        """Store or replace one caller-supplied content record within its workspace boundary."""

    def get_content_record(self, workspace_id: str, content_id: str) -> PersistenceResult:
        """Return one content record for the explicit workspace, or a structured not-found result."""

    def list_content_records(self, workspace_id: str) -> PersistenceResult:
        """Return content records visible inside the explicit workspace only."""

class GovernanceStatePersistenceBackend(Protocol):
    def put_governance_state(self, state: GovernanceState) -> PersistenceResult:
        """Store or replace one caller-supplied governance state inside its workspace boundary."""

    def get_governance_state(self, workspace_id: str, record_id: str) -> PersistenceResult:
        """Return one governance state for the explicit workspace, or a structured not-found result."""

    def append_governance_event(self, event: GovernanceStateEventContract) -> PersistenceResult:
        """Append one caller-supplied governance event after workspace-boundary validation."""

    def list_governance_events(self, workspace_id: str, record_id: str | None = None) -> PersistenceResult:
        """Return supplied governance events visible inside the explicit workspace only."""

class PersistenceBackend(ContentPersistenceBackend, GovernanceStatePersistenceBackend, Protocol):
    """Combined B26 persistence backend protocol."""
