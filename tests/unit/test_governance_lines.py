"""Unit tests — governance lines helper (T8 MCP alignment)."""
import uuid
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


def _gov(data: dict) -> str:
    from memory_lab.api.services import api_adapter
    if hasattr(api_adapter, "_build_governance_lines"):
        lines = api_adapter._build_governance_lines(data)
    elif hasattr(api_adapter, "_governance_lines"):
        lines = api_adapter._governance_lines(data)
    else:
        pytest.skip("_build_governance_lines not exposed as standalone function")
    return "\n".join(lines) if isinstance(lines, list) else str(lines)


class TestT8MCPAlignment:
    def test_exposes_tier(self):
        out = _gov({"tier": "persistent", "content_id": str(uuid.uuid4())})
        assert "persistent" in out

    def test_governance_status_for_duplicate(self):
        out = _gov({"tier": "persistent", "content_id": str(uuid.uuid4()), "governance_status": "duplicate_inherited"})
        assert "duplicate_inherited" in out

    def test_governance_status_absent(self):
        out = _gov({"tier": "transient", "content_id": str(uuid.uuid4())})
        assert "duplicate_inherited" not in out

    def test_exposes_trace_id(self):
        out = _gov({"tier": "persistent", "content_id": str(uuid.uuid4()), "trace_id": "abc123xyz"})
        assert "abc123xyz" in out

    def test_exposes_trace_id_with_timestamp(self):
        out = _gov({
            "tier": "transient", "content_id": str(uuid.uuid4()),
            "trace_id": "trace_abc", "governance_timestamp": "2026-05-23T12:00:00+00:00",
        })
        assert "trace_abc" in out
        assert "2026-05-23" in out

    def test_trace_id_absent_when_not_set(self):
        out = _gov({"tier": "transient", "content_id": str(uuid.uuid4())})
        assert "trace_id" not in out

    def test_conflict_detected_always_shown(self):
        out = _gov({"tier": "transient", "content_id": str(uuid.uuid4())})
        assert "conflict_detected" in out

    def test_conflict_true_when_escalation_present(self):
        esc_id = str(uuid.uuid4())
        out = _gov({"tier": "persistent", "content_id": str(uuid.uuid4()), "escalation_id": esc_id})
        assert "True" in out or esc_id in out

    def test_discarded_shows_conflict_field(self):
        out = _gov({"tier": "discard", "discarded": True, "content_id": "00000000-0000-0000-0000-000000000000"})
        assert "conflict_detected" in out or "conflict_check_skipped" in out
