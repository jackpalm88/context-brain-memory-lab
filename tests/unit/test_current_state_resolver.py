"""Unit tests for B10 current-state resolver helpers.

Provider-free; no network; no production dependencies.
"""

import pytest

from memory_lab.current_state.resolver import (
    derive_current_state_scope,
    resolve_current_state_after_ingest,
)

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]


def test_scope_explicit_current_state_marker_wins():
    scope = derive_current_state_scope(
        content_text="current_state_scope: B10 Candidate Current State Resolver\nbody",
        project_topic="context_brain_memory_lab",
    )
    assert scope == "b10-candidate-current-state-resolver"


def test_scope_falls_back_to_project_topic():
    assert derive_current_state_scope(content_text="no marker", project_topic="Context Brain Memory Lab") == "context-brain-memory-lab"


def test_scope_falls_back_to_domain_then_global():
    assert derive_current_state_scope(domain_hint="Governance") == "governance"
    assert derive_current_state_scope() == "global"


def test_low_confidence_noop_does_not_open_cursor():
    class Conn:
        def cursor(self):  # pragma: no cover - should never be called
            raise AssertionError("resolver must not touch DB for low confidence")

    result = resolve_current_state_after_ingest(
        Conn(), workspace_id="00000000-0000-0000-0000-000000000001",
        content_id="00000000-0000-0000-0000-000000000002", memory_type="anchor",
        classify_confidence=0.69, content_text="current_state_scope: b10",
    )
    assert result.status == "noop"
    assert result.reason == "low_confidence"
    assert result.wrote is False


def test_missing_workspace_noop():
    result = resolve_current_state_after_ingest(
        object(), workspace_id=None, content_id="00000000-0000-0000-0000-000000000002",
        memory_type="anchor", classify_confidence=0.85, content_text="current_state_scope: b10",
    )
    assert result.reason == "missing_workspace"


def test_future_reconcile_job_set_by_is_accepted_for_noop_boundary():
    result = resolve_current_state_after_ingest(
        object(), workspace_id=None, content_id="00000000-0000-0000-0000-000000000002",
        memory_type="anchor", classify_confidence=0.85, set_by="reconcile_job",
    )
    assert result.reason == "missing_workspace"
