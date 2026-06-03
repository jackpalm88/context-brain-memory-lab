"""Unit tests — governance event schema (T1). No DB, no provider."""
import uuid
import pytest
from memory_lab.governance.events import (
    build_event, validate_event, GOVERNANCE_EVENT_TYPE,
    TierTransitionEvent, TRIGGER_TYPES, TRIGGER_SOURCES,
)
from memory_lab.governance.transition_matrix import is_upshift

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


def _make_event(**kwargs):
    defaults = dict(
        content_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        previous_tier=None,
        new_tier="persistent",
        transition_reason="composite_persistent_threshold:0.80>=0.70",
        transition_rule="T-PERSISTENT",
        trigger_type="system",
        trigger_source="save",
        trace_id="trace-" + uuid.uuid4().hex[:8],
    )
    defaults.update(kwargs)
    return defaults


class TestT1EventSchema:
    def test_build_valid_event(self):
        ev = build_event(**_make_event())
        assert ev.event_type == GOVERNANCE_EVENT_TYPE
        assert ev.new_tier == "persistent"
        assert ev.event_id  # generated UUID

    def test_missing_required_field_raises(self):
        # validate_event takes a TierTransitionEvent; invalid trigger_type raises
        ev = build_event(**_make_event())
        import dataclasses
        d = dataclasses.asdict(ev)
        d["trigger_type"] = "invalid_trigger"
        # rebuild dataclass with bad trigger_type
        bad = TierTransitionEvent(**d)
        with pytest.raises(ValueError):
            validate_event(bad)

    def test_discard_event_allows_null_content_id(self):
        ev = build_event(**_make_event(content_id=None, new_tier="discard",
                                       transition_reason="below_min_composite",
                                       transition_rule="T-DISCARD"))
        assert ev.new_tier == "discard"

    def test_non_discard_event_requires_content_id(self):
        with pytest.raises(ValueError):
            build_event(**_make_event(content_id=None, new_tier="persistent"))

    def test_wrong_trigger_type_raises(self):
        with pytest.raises(ValueError):
            build_event(**_make_event(trigger_type="auto"))  # not in TRIGGER_TYPES

    def test_wrong_trigger_source_raises(self):
        with pytest.raises(ValueError):
            build_event(**_make_event(trigger_source="ingestion_scorer"))  # not in TRIGGER_SOURCES

    def test_is_upshift_detects_promotion(self):
        assert is_upshift(previous_tier="transient", new_tier="persistent") is True

    def test_is_upshift_false_for_initial_assignment(self):
        assert is_upshift(previous_tier=None, new_tier="persistent") is False

    def test_is_upshift_false_for_downshift(self):
        assert is_upshift(previous_tier="persistent", new_tier="transient") is False
