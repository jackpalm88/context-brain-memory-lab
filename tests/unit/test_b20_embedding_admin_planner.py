"""B20 public-safe embedding admin planner tests."""

from dataclasses import asdict, is_dataclass

from memory_lab.ingestion.embedding_admin import (
    EMBEDDING_ADMIN_PLAN_MODE,
    PLAN_LABELS,
    EmbeddingAdminPlanInput,
    EmbeddingAdminPlanner,
    make_embedding_admin_planner,
    plan_embedding_admin_actions,
)


def row(**overrides):
    data = {
        "item_id": "syn-b20-admin-item-001",
        "synthetic_id": "syn-b20-admin-item-001",
        "chunk_id": "syn-b20-admin-chunk-001",
        "chunk_text": "Synthetic public-safe chunk text for B20 embedding admin planning.",
        "data_source": "synthetic_fixture",
        "source_available": True,
    }
    data.update(overrides)
    return data


def labels(summary):
    return tuple(item.plan_label for item in summary.items)


def test_factory_returns_public_safe_planner():
    planner = make_embedding_admin_planner()
    assert isinstance(planner, EmbeddingAdminPlanner)
    assert planner.mode == EMBEDDING_ADMIN_PLAN_MODE


def test_embedded_rows_produce_noop_embedded():
    summary = plan_embedding_admin_actions([row(embedding_present=True)])
    assert labels(summary) == ("noop_embedded",)
    assert summary.plan_counts["noop_embedded"] == 1
    assert summary.items[0].dry_run is True
    assert "no provider calls" in summary.items[0].non_claims


def test_missing_embedding_rows_produce_dry_run_plan_embed_missing():
    summary = plan_embedding_admin_actions([row(embedding_present=False)])
    assert labels(summary) == ("plan_embed_missing",)
    item = summary.items[0]
    assert item.dry_run is True
    assert item.degraded is True
    assert item.readiness == "not_ready_missing_embedding"


def test_reextract_required_rows_produce_plan_reextract_then_embed():
    summary = plan_embedding_admin_actions([row(requires_reextract=True)])
    assert labels(summary) == ("plan_reextract_then_embed",)
    assert summary.items[0].embedding_state == "blocked_reextract"


def test_empty_and_low_quality_rows_are_blocked():
    summary = plan_embedding_admin_actions([
        row(item_id="empty", synthetic_id="empty", chunk_id="empty-c", chunk_text=""),
        row(
            item_id="low-quality",
            synthetic_id="low-quality",
            chunk_id="low-c",
            chunk_score={"recommendation": "block", "quality": 0.1},
        ),
    ])
    assert labels(summary) == ("blocked_empty", "blocked_low_quality")
    assert summary.plan_counts["blocked_empty"] == 1
    assert summary.plan_counts["blocked_low_quality"] == 1


def test_unavailable_source_returns_degraded_unavailable_summary():
    summary = plan_embedding_admin_actions([row(source_available=False)])
    assert labels(summary) == ("blocked_unavailable",)
    assert summary.degraded_count == 1
    assert "EMBEDDING_HEALTH_SOURCE_UNAVAILABLE" in summary.warnings


def test_unsafe_private_looking_fields_degrade_or_warn():
    summary = plan_embedding_admin_actions([
        row(api_key="sk-public-safety-sentinel", metadata={"dsn": "postgres://example"})
    ])
    item = summary.items[0]
    assert item.degraded is True
    assert "PUBLIC_SAFE_UNSAFE_METADATA_KEY_DEGRADED" in item.warnings
    assert "PUBLIC_SAFE_UNSAFE_METADATA_VALUE_DEGRADED" in item.warnings
    assert "unsafe/private-looking supplied metadata degraded" in item.limitations


def test_plan_contains_no_executable_provider_or_db_handles():
    summary = plan_embedding_admin_actions([row(embedding_present=False)])
    assert is_dataclass(summary)
    data = asdict(summary)
    serialized = repr(data).lower()
    assert "function" not in serialized
    assert "provider_handle" not in serialized
    assert "db_handle" not in serialized
    assert "connection" not in serialized
    assert summary.dry_run is True


def test_deterministic_ordering_and_summary_counts_are_stable():
    rows = [
        row(item_id="b", synthetic_id="b", chunk_id="b-c", embedding_present=False),
        row(item_id="a", synthetic_id="a", chunk_id="a-c", embedding_present=True),
        row(item_id="c", synthetic_id="c", chunk_id="c-c", embedding_status="pending"),
    ]
    first = plan_embedding_admin_actions(rows)
    second = plan_embedding_admin_actions(rows)
    assert first == second
    assert tuple(item.item_id for item in first.items) == ("b", "a", "c")
    assert labels(first) == ("plan_embed_missing", "noop_embedded", "degraded_unknown")
    assert first.total_items == 3
    assert first.total_chunks == 3
    assert set(first.plan_counts) == set(PLAN_LABELS)


def test_dataclass_input_is_supported():
    summary = plan_embedding_admin_actions([
        EmbeddingAdminPlanInput(item_id="dc", synthetic_id="dc", chunk_id="dc-c", embedding_present=True)
    ])
    assert labels(summary) == ("noop_embedded",)
