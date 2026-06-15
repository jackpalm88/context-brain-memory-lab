"""Deterministic read-only embedding health evaluator for B17.

The evaluator operates only on caller-supplied public-safe or synthetic rows. It
interprets supplied flags, timestamps, chunk metadata, and deterministic
mechanical chunk scores. It does not fetch records, generate vectors, call
external services, rebuild indexes, expose routes, or mutate state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from memory_lab.ingestion.interfaces import (
    ChunkScoringResult,
    ContentChunk,
    SYNTHETIC_DATA_SOURCE,
)

EMBEDDING_HEALTH_MODE = "embedding_ops_read_only_health_v1"

HEALTH_STATES = (
    "embedded",
    "missing_embedding",
    "pending",
    "blocked_empty",
    "blocked_low_quality",
    "blocked_reextract",
    "stale",
    "failed",
    "unknown",
    "unavailable",
)

READY_READ_ONLY = "ready_read_only"
NOT_READY_MISSING = "not_ready_missing_embedding"
NOT_READY_PENDING = "not_ready_pending"
BLOCKED = "blocked"
BLOCKED_REEXTRACT_REQUIRED = "blocked_reextract_required"
NOT_READY_STALE = "not_ready_stale"
NOT_READY_FAILED = "not_ready_failed"
UNKNOWN = "unknown"
UNAVAILABLE = "unavailable"

DEFAULT_NON_CLAIMS = (
    "no embeddings generated",
    "no vector creation implemented",
    "no index mutation",
    "no production embedding health claim",
    "no semantic readiness claim",
    "no semantic scoring",
    "no provider-backed embedding operations",
    "no private Context Brain access",
    "no Full Context Brain claim",
    "no API or admin tooling claim",
    "no release or export claim",
)

DEFAULT_LIMITATIONS = (
    "deterministic read-only embedding health over supplied rows only",
    "synthetic/public-safe input expected",
    "no stored-record access",
    "no external service calls",
    "no vector operation",
    "no mutation methods",
)

_ALLOWED_DATA_SOURCES = {"synthetic_fixture", "public_safe_export", "unavailable", SYNTHETIC_DATA_SOURCE}
_PENDING_STATUSES = {"pending", "queued", "waiting", "scheduled"}
_FAILED_STATUSES = {"failed", "error"}
_PRESENT_STATUSES = {"present", "embedded", "complete", "completed"}
_MISSING_STATUSES = {"missing", "absent", "not_present"}
_EMPTY_RISKS = {"empty_chunk", "whitespace_only_chunk"}
_REEXTRACT_RISKS = {"invalid_char_offsets", "negative_char_offsets", "char_count_mismatch"}


@dataclass(frozen=True)
class EmbeddingHealthInput:
    """Caller-supplied row for deterministic read-only health evaluation."""

    item_id: str = ""
    synthetic_id: str = ""
    chunk_id: str = ""
    chunk_text: str | None = None
    chunk: ContentChunk | None = None
    chunk_score: ChunkScoringResult | Mapping[str, Any] | None = None
    embedding_present: bool | None = None
    embedding_status: str | None = None
    embedding_updated_at: str | datetime | None = None
    source_updated_at: str | datetime | None = None
    requires_reextract: bool = False
    failure_reason: str = ""
    limitations: Sequence[str] = field(default_factory=tuple)
    warnings: Sequence[str] = field(default_factory=tuple)
    data_source: str = "synthetic_fixture"
    source_available: bool = True


@dataclass(frozen=True)
class EmbeddingHealthRecord:
    """JSON-compatible read-only embedding health result."""

    item_id: str
    synthetic_id: str
    chunk_id: str
    embedding_state: str
    reason: str
    readiness: str
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    mode: str
    data_source: str
    degraded: bool
    non_claims: tuple[str, ...]


@dataclass(frozen=True)
class EmbeddingHealthSummary:
    """Aggregate deterministic summary for a batch of health rows."""

    mode: str
    data_source: str
    total_items: int
    total_chunks: int
    state_counts: Mapping[str, int]
    readiness_counts: Mapping[str, int]
    warning_counts: Mapping[str, int]
    degraded_count: int
    limitations: tuple[str, ...]
    non_claims: tuple[str, ...]


class EmbeddingHealthEvaluator:
    """Evaluate supplied rows without side effects or external dependencies."""

    mode: str = EMBEDDING_HEALTH_MODE

    def evaluate_embedding_health(
        self,
        row: EmbeddingHealthInput | Mapping[str, Any] | None,
    ) -> EmbeddingHealthRecord:
        if row is None:
            return self._record(
                item_id="",
                synthetic_id="",
                chunk_id="",
                state="unavailable",
                reason="health_source_unavailable",
                readiness=UNAVAILABLE,
                warnings=("EMBEDDING_HEALTH_SOURCE_UNAVAILABLE",),
                limitations=("no source row supplied",),
                data_source="unavailable",
                degraded=True,
            )

        data = _row_to_mapping(row)
        item_id = str(data.get("item_id") or "")
        synthetic_id = str(data.get("synthetic_id") or data.get("synthetic_item_id") or "")
        chunk = data.get("chunk")
        chunk_id = str(data.get("chunk_id") or _chunk_attr(chunk, "chunk_id") or "")
        data_source = str(data.get("data_source") or _chunk_attr(chunk, "data_source") or "synthetic_fixture")
        limitations = tuple(str(v) for v in data.get("limitations", ()) if str(v))
        warnings = tuple(str(v) for v in data.get("warnings", ()) if str(v))
        source_available = bool(data.get("source_available", True))

        if not source_available or data_source == "unavailable":
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="unavailable",
                reason="health_source_unavailable",
                readiness=UNAVAILABLE,
                warnings=warnings + ("EMBEDDING_HEALTH_SOURCE_UNAVAILABLE",),
                limitations=limitations,
                data_source="unavailable",
                degraded=True,
            )

        if data_source not in _ALLOWED_DATA_SOURCES:
            warnings += ("PUBLIC_SAFE_DATA_SOURCE_NOT_PROVEN",)
            limitations += ("data source is not an approved synthetic/public-safe label",)

        embedding_status = _normal_status(data.get("embedding_status"))
        failure_reason = str(data.get("failure_reason") or "")
        if embedding_status in _FAILED_STATUSES or failure_reason:
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="failed",
                reason="embedding_failure_status_or_reason_supplied",
                readiness=NOT_READY_FAILED,
                warnings=warnings + ("EMBEDDING_FAILED",),
                limitations=limitations + _optional_limitation("sanitized failure reason supplied", bool(failure_reason)),
                data_source=data_source,
                degraded=True,
            )

        if embedding_status in _PENDING_STATUSES:
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="pending",
                reason="embedding_status_pending",
                readiness=NOT_READY_PENDING,
                warnings=warnings + ("EMBEDDING_PENDING",),
                limitations=limitations,
                data_source=data_source,
                degraded=True,
            )

        if bool(data.get("requires_reextract", False)) or _has_reextract_risk(data):
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="blocked_reextract",
                reason="reextract_required_by_supplied_metadata",
                readiness=BLOCKED_REEXTRACT_REQUIRED,
                warnings=warnings + ("BLOCKED_REEXTRACT_REQUIRED",),
                limitations=limitations,
                data_source=data_source,
                degraded=True,
            )

        if _is_empty_chunk(data):
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="blocked_empty",
                reason="empty_or_whitespace_chunk_text",
                readiness=BLOCKED,
                warnings=warnings + ("BLOCKED_EMPTY_TEXT",),
                limitations=limitations,
                data_source=data_source,
                degraded=True,
            )

        if _is_low_mechanical_quality(data):
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="blocked_low_quality",
                reason="mechanical_chunk_score_blocked",
                readiness=BLOCKED,
                warnings=warnings + ("BLOCKED_LOW_MECHANICAL_QUALITY",),
                limitations=limitations,
                data_source=data_source,
                degraded=True,
            )

        embedding_present = _embedding_present(data, embedding_status)
        if embedding_present is True and _is_stale(data):
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="stale",
                reason="source_newer_than_embedding",
                readiness=NOT_READY_STALE,
                warnings=warnings + ("STALE_EMBEDDING",),
                limitations=limitations,
                data_source=data_source,
                degraded=True,
            )

        if embedding_present is True:
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="embedded",
                reason="embedding_present_flag_true",
                readiness=READY_READ_ONLY,
                warnings=warnings + ("SEMANTIC_READINESS_NOT_CLAIMED",),
                limitations=limitations,
                data_source=data_source,
                degraded=bool(warnings or limitations),
            )

        if embedding_present is False:
            return self._record(
                item_id=item_id,
                synthetic_id=synthetic_id,
                chunk_id=chunk_id,
                state="missing_embedding",
                reason="embedding_flag_false",
                readiness=NOT_READY_MISSING,
                warnings=warnings + ("MISSING_EMBEDDING",),
                limitations=limitations,
                data_source=data_source,
                degraded=True,
            )

        return self._record(
            item_id=item_id,
            synthetic_id=synthetic_id,
            chunk_id=chunk_id,
            state="unknown",
            reason="embedding_state_not_proven_by_supplied_row",
            readiness=UNKNOWN,
            warnings=warnings + ("EMBEDDING_STATE_UNKNOWN",),
            limitations=limitations,
            data_source=data_source,
            degraded=True,
        )

    def evaluate_embedding_health_rows(
        self,
        rows: Sequence[EmbeddingHealthInput | Mapping[str, Any] | None] | None,
    ) -> tuple[EmbeddingHealthRecord, ...]:
        if rows is None:
            return (self.evaluate_embedding_health(None),)
        return tuple(self.evaluate_embedding_health(row) for row in rows)

    def summarize(
        self,
        rows: Sequence[EmbeddingHealthInput | Mapping[str, Any] | None] | None,
    ) -> EmbeddingHealthSummary:
        records = self.evaluate_embedding_health_rows(rows)
        state_counts = {state: 0 for state in HEALTH_STATES}
        readiness_counts: dict[str, int] = {}
        warning_counts: dict[str, int] = {}
        for record in records:
            state_counts[record.embedding_state] = state_counts.get(record.embedding_state, 0) + 1
            readiness_counts[record.readiness] = readiness_counts.get(record.readiness, 0) + 1
            for warning in record.warnings:
                warning_counts[warning] = warning_counts.get(warning, 0) + 1
        data_sources = {record.data_source for record in records}
        data_source = records[0].data_source if len(data_sources) == 1 and records else "mixed"
        return EmbeddingHealthSummary(
            mode=self.mode,
            data_source=data_source,
            total_items=len({record.item_id or record.synthetic_id for record in records}),
            total_chunks=len(records),
            state_counts=state_counts,
            readiness_counts=readiness_counts,
            warning_counts=warning_counts,
            degraded_count=sum(1 for record in records if record.degraded),
            limitations=DEFAULT_LIMITATIONS,
            non_claims=DEFAULT_NON_CLAIMS,
        )

    def _record(
        self,
        *,
        item_id: str,
        synthetic_id: str,
        chunk_id: str,
        state: str,
        reason: str,
        readiness: str,
        warnings: Sequence[str],
        limitations: Sequence[str],
        data_source: str,
        degraded: bool,
    ) -> EmbeddingHealthRecord:
        return EmbeddingHealthRecord(
            item_id=item_id,
            synthetic_id=synthetic_id,
            chunk_id=chunk_id,
            embedding_state=state,
            reason=reason,
            readiness=readiness,
            warnings=_dedupe(tuple(warnings)),
            limitations=_dedupe(DEFAULT_LIMITATIONS + tuple(limitations)),
            mode=self.mode,
            data_source=data_source,
            degraded=degraded,
            non_claims=DEFAULT_NON_CLAIMS,
        )


def make_embedding_health_evaluator() -> EmbeddingHealthEvaluator:
    """Factory for the deterministic read-only embedding health evaluator."""

    return EmbeddingHealthEvaluator()


def evaluate_embedding_health(
    row: EmbeddingHealthInput | Mapping[str, Any] | None,
) -> EmbeddingHealthRecord:
    """Convenience wrapper for one supplied row."""

    return make_embedding_health_evaluator().evaluate_embedding_health(row)


def evaluate_embedding_health_rows(
    rows: Sequence[EmbeddingHealthInput | Mapping[str, Any] | None] | None,
) -> tuple[EmbeddingHealthRecord, ...]:
    """Convenience wrapper for supplied row batches."""

    return make_embedding_health_evaluator().evaluate_embedding_health_rows(rows)


def _row_to_mapping(row: EmbeddingHealthInput | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    if is_dataclass(row):
        return row.__dict__
    raise TypeError("embedding health row must be a mapping or EmbeddingHealthInput")


def _chunk_attr(chunk: Any, attr: str) -> Any:
    return getattr(chunk, attr, None) if chunk is not None else None


def _score_mapping(score: Any) -> Mapping[str, Any]:
    if isinstance(score, Mapping):
        return score
    if is_dataclass(score):
        return score.__dict__
    return {}


def _normal_status(value: Any) -> str:
    return str(value or "").strip().lower()


def _embedding_present(data: Mapping[str, Any], embedding_status: str) -> bool | None:
    if "embedding_present" in data and data.get("embedding_present") is not None:
        return bool(data.get("embedding_present"))
    if embedding_status in _PRESENT_STATUSES:
        return True
    if embedding_status in _MISSING_STATUSES:
        return False
    return None


def _is_empty_chunk(data: Mapping[str, Any]) -> bool:
    chunk = data.get("chunk")
    if "chunk_text" in data and data.get("chunk_text") is not None:
        return str(data.get("chunk_text") or "").strip() == ""
    if chunk is not None and getattr(chunk, "text", None) is not None:
        return str(getattr(chunk, "text") or "").strip() == ""
    if int(data.get("text_length") or 0) == 0 and data.get("text_length") is not None:
        return True
    score = _score_mapping(data.get("chunk_score"))
    risks = set(score.get("risk_flags", ()) or ())
    return bool(risks & _EMPTY_RISKS)


def _is_low_mechanical_quality(data: Mapping[str, Any]) -> bool:
    score = _score_mapping(data.get("chunk_score"))
    recommendation = str(score.get("recommendation") or "").lower()
    if recommendation == "block":
        return True
    for field_name in ("quality", "composite", "mechanical_score"):
        value = score.get(field_name, data.get(field_name))
        if value is None:
            continue
        try:
            return float(value) < 0.30
        except (TypeError, ValueError):
            continue
    return False


def _has_reextract_risk(data: Mapping[str, Any]) -> bool:
    score = _score_mapping(data.get("chunk_score"))
    risks = set(score.get("risk_flags", ()) or ())
    return bool(risks & _REEXTRACT_RISKS)


def _is_stale(data: Mapping[str, Any]) -> bool:
    embedding_updated_at = _parse_datetime(data.get("embedding_updated_at"))
    source_updated_at = _parse_datetime(data.get("source_updated_at"))
    if embedding_updated_at is None or source_updated_at is None:
        return False
    return source_updated_at > embedding_updated_at


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _optional_limitation(value: str, include: bool) -> tuple[str, ...]:
    return (value,) if include else ()


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)
