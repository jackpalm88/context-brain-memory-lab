"""Public-safe deterministic embedding admin planner for B20.

This module converts caller-supplied synthetic/public-safe embedding health rows
into dry-run plan records. It does not fetch content, generate embeddings,
open database handles, call providers, expose routes, or mutate stored state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from typing import Any, Mapping, Sequence

from memory_lab.ingestion.embedding_health import (
    EmbeddingHealthEvaluator,
    EmbeddingHealthRecord,
    make_embedding_health_evaluator,
)

EMBEDDING_ADMIN_PLAN_MODE = "embedding_admin_public_safe_plan_v1"

PLAN_LABELS = (
    "noop_embedded",
    "plan_embed_missing",
    "plan_reextract_then_embed",
    "blocked_empty",
    "blocked_low_quality",
    "blocked_unavailable",
    "degraded_unknown",
)

DEFAULT_NON_CLAIMS = (
    "no embeddings generated",
    "no provider calls",
    "no database access",
    "no vector store access",
    "no live admin operation",
    "no stored-state mutation",
    "no production embedding admin claim",
    "no semantic or vector parity claim",
    "no private Context Brain access",
    "no Full Context Brain claim",
)

DEFAULT_LIMITATIONS = (
    "dry-run plan over caller-supplied rows only",
    "synthetic/public-safe input expected",
    "uses deterministic embedding health signals only",
    "plan labels are not executable operations",
)

_UNSAFE_KEY_FRAGMENTS = (
    "api_key",
    "secret",
    "token",
    "password",
    "dsn",
    "connection",
    "provider_handle",
    "db_handle",
)

_UNSAFE_VALUE_FRAGMENTS = (
    "sk-",
    "postgres://",
    "postgresql://",
    "mysql://",
    "mongodb://",
    "/opt/contentingestor",
)

_STATE_TO_LABEL = {
    "embedded": "noop_embedded",
    "missing_embedding": "plan_embed_missing",
    "stale": "plan_embed_missing",
    "blocked_reextract": "plan_reextract_then_embed",
    "blocked_empty": "blocked_empty",
    "blocked_low_quality": "blocked_low_quality",
    "pending": "degraded_unknown",
    "failed": "degraded_unknown",
    "unknown": "degraded_unknown",
    "unavailable": "blocked_unavailable",
}


@dataclass(frozen=True)
class EmbeddingAdminPlanInput:
    """Caller-supplied row for public-safe embedding admin planning."""

    item_id: str = ""
    synthetic_id: str = ""
    chunk_id: str = ""
    embedding_present: bool | None = None
    embedding_status: str | None = None
    requires_reextract: bool = False
    chunk_text: str | None = None
    chunk_score: Mapping[str, Any] | None = None
    text_length: int | None = None
    data_source: str = "synthetic_fixture"
    source_available: bool = True
    warnings: Sequence[str] = field(default_factory=tuple)
    limitations: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class EmbeddingAdminPlanItem:
    """One deterministic dry-run embedding admin plan item."""

    item_id: str
    synthetic_id: str
    chunk_id: str
    plan_label: str
    embedding_state: str
    readiness: str
    reason: str
    rank: int
    dry_run: bool
    degraded: bool
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    mode: str
    non_claims: tuple[str, ...]


@dataclass(frozen=True)
class EmbeddingAdminPlanSummary:
    """Aggregate deterministic summary for a dry-run embedding admin plan."""

    mode: str
    items: tuple[EmbeddingAdminPlanItem, ...]
    total_items: int
    total_chunks: int
    plan_counts: Mapping[str, int]
    degraded_count: int
    dry_run: bool
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    non_claims: tuple[str, ...]


class EmbeddingAdminPlanner:
    """Build deterministic dry-run plan labels from supplied health rows."""

    mode: str = EMBEDDING_ADMIN_PLAN_MODE

    def __init__(self, evaluator: EmbeddingHealthEvaluator | None = None) -> None:
        self._evaluator = evaluator or make_embedding_health_evaluator()

    def plan_embedding_admin_actions(
        self,
        rows: Sequence[EmbeddingAdminPlanInput | Mapping[str, Any] | None] | None,
    ) -> EmbeddingAdminPlanSummary:
        source_rows: tuple[EmbeddingAdminPlanInput | Mapping[str, Any] | None, ...]
        if rows is None:
            source_rows = (None,)
        else:
            source_rows = tuple(rows)
            if not source_rows:
                source_rows = (None,)

        health_records = self._evaluator.evaluate_embedding_health_rows(source_rows)
        items = tuple(
            self._plan_item(index=index, row=row, health=health)
            for index, (row, health) in enumerate(zip(source_rows, health_records), start=1)
        )
        return self._summary(items)

    def _plan_item(
        self,
        *,
        index: int,
        row: EmbeddingAdminPlanInput | Mapping[str, Any] | None,
        health: EmbeddingHealthRecord,
    ) -> EmbeddingAdminPlanItem:
        unsafe_warnings = _unsafe_warnings(row)
        plan_label = _STATE_TO_LABEL.get(health.embedding_state, "degraded_unknown")
        warnings = _dedupe(health.warnings + unsafe_warnings)
        limitations = _dedupe(
            DEFAULT_LIMITATIONS
            + health.limitations
            + _optional_limitation("unsafe/private-looking supplied metadata degraded", bool(unsafe_warnings))
        )
        degraded = bool(health.degraded or unsafe_warnings or plan_label.startswith("blocked") or plan_label == "degraded_unknown")
        return EmbeddingAdminPlanItem(
            item_id=health.item_id,
            synthetic_id=health.synthetic_id,
            chunk_id=health.chunk_id,
            plan_label=plan_label,
            embedding_state=health.embedding_state,
            readiness=health.readiness,
            reason=health.reason,
            rank=index,
            dry_run=True,
            degraded=degraded,
            warnings=warnings,
            limitations=limitations,
            mode=self.mode,
            non_claims=DEFAULT_NON_CLAIMS,
        )

    def _summary(self, items: Sequence[EmbeddingAdminPlanItem]) -> EmbeddingAdminPlanSummary:
        plan_counts = {label: 0 for label in PLAN_LABELS}
        warning_values: list[str] = []
        for item in items:
            plan_counts[item.plan_label] = plan_counts.get(item.plan_label, 0) + 1
            warning_values.extend(item.warnings)
        total_ids = {item.item_id or item.synthetic_id or item.chunk_id or str(item.rank) for item in items}
        return EmbeddingAdminPlanSummary(
            mode=self.mode,
            items=tuple(items),
            total_items=len(total_ids),
            total_chunks=len(items),
            plan_counts=plan_counts,
            degraded_count=sum(1 for item in items if item.degraded),
            dry_run=True,
            warnings=_dedupe(tuple(warning_values)),
            limitations=DEFAULT_LIMITATIONS,
            non_claims=DEFAULT_NON_CLAIMS,
        )


def make_embedding_admin_planner() -> EmbeddingAdminPlanner:
    """Factory for the B20 public-safe embedding admin planner."""

    return EmbeddingAdminPlanner()


def plan_embedding_admin_actions(
    rows: Sequence[EmbeddingAdminPlanInput | Mapping[str, Any] | None] | None,
) -> EmbeddingAdminPlanSummary:
    """Convenience wrapper for deterministic dry-run embedding admin planning."""

    return make_embedding_admin_planner().plan_embedding_admin_actions(rows)


def _row_to_mapping(row: EmbeddingAdminPlanInput | Mapping[str, Any] | None) -> Mapping[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return row
    if is_dataclass(row):
        return row.__dict__
    return {}


def _unsafe_warnings(row: EmbeddingAdminPlanInput | Mapping[str, Any] | None) -> tuple[str, ...]:
    data = _row_to_mapping(row)
    warnings: list[str] = []
    for key, value in data.items():
        key_text = str(key).lower()
        if any(fragment in key_text for fragment in _UNSAFE_KEY_FRAGMENTS):
            warnings.append("PUBLIC_SAFE_UNSAFE_METADATA_KEY_DEGRADED")
        if _looks_unsafe_value(value):
            warnings.append("PUBLIC_SAFE_UNSAFE_METADATA_VALUE_DEGRADED")
    return _dedupe(tuple(warnings))


def _looks_unsafe_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_looks_unsafe_value(v) or any(fragment in str(k).lower() for fragment in _UNSAFE_KEY_FRAGMENTS) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_looks_unsafe_value(v) for v in value)
    text = str(value or "").lower()
    return any(fragment in text for fragment in _UNSAFE_VALUE_FRAGMENTS)


def _optional_limitation(value: str, include: bool) -> tuple[str, ...]:
    return (value,) if include else ()


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)
