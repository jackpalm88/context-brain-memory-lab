"""Supplied-row repository embedding health adapter for B17.

This module adapts caller-supplied, public-safe, in-memory repository-like rows
into the existing read-only EmbeddingHealthInput shape. It never opens a live
repository, reads stored records, calls providers, creates vectors, rebuilds
indexes, exposes routes, or mutates state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from memory_lab.ingestion.embedding_health import (
    DEFAULT_NON_CLAIMS,
    EmbeddingHealthInput,
    EmbeddingHealthRecord,
    evaluate_embedding_health_rows,
)

REPOSITORY_EMBEDDING_HEALTH_ADAPTER_MODE = "repository_embedding_health_adapter_v1"

ADAPTER_LIMITATIONS = (
    "supplied in-memory rows only",
    "public-safe row-shape adapter only",
    "no live repository provider",
    "no stored-record access",
    "no query execution",
    "no vector operation",
    "no mutation methods",
)

_ALLOWED_SOURCE_TYPES = {
    "synthetic_fixture",
    "public_safe_export",
    "supplied_repository_rows",
    "unavailable",
}

_PRESENT_STATUSES = {"present", "embedded", "complete", "completed"}
_MISSING_STATUSES = {"missing", "absent", "not_present"}
_PENDING_STATUSES = {"pending", "queued", "waiting", "scheduled"}
_FAILED_STATUSES = {"failed", "error"}
_UNAVAILABLE_STATUSES = {"unavailable", "source_unavailable", "provider_unavailable"}
_ALLOWED_STATUSES = _PRESENT_STATUSES | _MISSING_STATUSES | _PENDING_STATUSES | _FAILED_STATUSES | _UNAVAILABLE_STATUSES | {"unknown", ""}

_SAFE_STRING_FIELDS = {
    "item_id",
    "chunk_id",
    "synthetic_id",
    "embedding_status",
    "embedding_model",
    "embedding_updated_at",
    "source_updated_at",
    "status",
    "error",
    "source_type",
}

_VECTOR_FIELD_NAMES = {"embedding", "embedding_vector", "vector", "vector_preview"}
_PRIVATE_ID_FIELD_NAMES = {"content_id", "hub_id", "workspace_id", "tenant_id", "private_cb_id"}
_HANDLE_FIELD_NAMES = {"session", "engine", "cursor", "client", "connection", "repository"}

@dataclass(frozen=True)
class RepositoryEmbeddingHealthAdapterResult:
    """Public-safe result for adapted supplied repository-like rows."""

    rows: tuple[EmbeddingHealthInput, ...]
    records: tuple[EmbeddingHealthRecord, ...]
    mode: str = REPOSITORY_EMBEDDING_HEALTH_ADAPTER_MODE
    data_source: str = "supplied_repository_rows"
    warnings: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = ADAPTER_LIMITATIONS
    degraded: bool = False
    non_claims: tuple[str, ...] = DEFAULT_NON_CLAIMS


@dataclass(frozen=True)
class RepositoryEmbeddingHealthAdapter:
    """Adapt supplied rows without repository, provider, vector, or mutation behavior."""

    mode: str = REPOSITORY_EMBEDDING_HEALTH_ADAPTER_MODE

    def adapt_rows(
        self,
        rows: Sequence[Mapping[str, Any] | object] | None,
    ) -> RepositoryEmbeddingHealthAdapterResult:
        if rows is None:
            adapted = (
                EmbeddingHealthInput(
                    item_id="",
                    synthetic_id="",
                    chunk_id="",
                    data_source="unavailable",
                    source_available=False,
                    warnings=("REPOSITORY_ROWS_UNAVAILABLE",),
                    limitations=("no repository provider configured; supplied-row mode only",),
                ),
            )
            return self._result(adapted, ("REPOSITORY_ROWS_UNAVAILABLE",), "unavailable", True)

        row_tuple = tuple(rows)
        if not row_tuple:
            return self._result(
                (),
                ("EMPTY_SUPPLIED_ROW_SET",),
                "supplied_repository_rows",
                True,
                extra_limitations=("empty supplied row set is not proof of embedding health",),
            )

        seen_ids: set[tuple[str, str]] = set()
        duplicate_ids: set[tuple[str, str]] = set()
        adapted_rows: list[EmbeddingHealthInput] = []
        adapter_warnings: list[str] = []
        data_sources: set[str] = set()

        for row in row_tuple:
            data = _row_to_mapping(row)
            converted = self._adapt_one(data)
            key = (converted.item_id, converted.chunk_id)
            if key != ("", ""):
                if key in seen_ids:
                    duplicate_ids.add(key)
                    converted = _with_warning(converted, "DUPLICATE_ROW_IDENTIFIER")
                seen_ids.add(key)
            adapted_rows.append(converted)
            data_sources.add(converted.data_source)
            adapter_warnings.extend(converted.warnings)

        if duplicate_ids:
            adapter_warnings.append("DUPLICATE_ROW_IDENTIFIER")
        data_source = data_sources.pop() if len(data_sources) == 1 else "mixed"
        degraded = bool(adapter_warnings or duplicate_ids)
        return self._result(tuple(adapted_rows), tuple(adapter_warnings), data_source, degraded)

    def _adapt_one(self, data: Mapping[str, Any]) -> EmbeddingHealthInput:
        unsafe_warnings = _unsafe_warnings(data)
        if unsafe_warnings:
            return EmbeddingHealthInput(
                item_id="unsafe-redacted",
                synthetic_id="unsafe-redacted",
                chunk_id="unsafe-redacted",
                data_source="unavailable",
                source_available=False,
                warnings=tuple(unsafe_warnings) + ("UNSAFE_REPOSITORY_ROW_REDACTED",),
                limitations=("unsafe/private-looking supplied row degraded without preserving unsafe values",),
            )

        warnings: list[str] = []
        limitations: list[str] = []

        item_id = _public_string(data.get("item_id"))
        synthetic_id = _public_string(data.get("synthetic_id")) or item_id
        chunk_id = _public_string(data.get("chunk_id"))
        if not item_id:
            warnings.append("MISSING_ITEM_ID")
            limitations.append("missing required public-safe item_id")
        if not chunk_id:
            warnings.append("MISSING_CHUNK_ID")
            limitations.append("missing required public-safe chunk_id")

        source_type = _normal_status(data.get("source_type") or data.get("data_source") or "supplied_repository_rows")
        if source_type not in _ALLOWED_SOURCE_TYPES:
            warnings.append("PUBLIC_SAFE_SOURCE_TYPE_NOT_PROVEN")
            limitations.append("source_type is not an approved public-safe label")
            source_type = "supplied_repository_rows"

        status = _normal_status(data.get("embedding_status") or data.get("status"))
        if status not in _ALLOWED_STATUSES:
            warnings.append("UNKNOWN_EMBEDDING_STATUS")
            limitations.append("unsupported supplied status treated as unknown")
            status = ""

        source_available = source_type != "unavailable" and status not in _UNAVAILABLE_STATUSES
        if not source_available:
            warnings.append("REPOSITORY_PROVIDER_UNAVAILABLE_SUPPLIED_STATUS_ONLY")
            limitations.append("unavailable repository represented only by supplied row status")
            source_type = "unavailable"

        embedding_present = _bool_or_none(data.get("embedding_present"))
        if embedding_present is None and status in _PRESENT_STATUSES:
            embedding_present = True
        elif embedding_present is None and status in _MISSING_STATUSES:
            embedding_present = False

        if embedding_present is True and status in (_FAILED_STATUSES | _MISSING_STATUSES):
            warnings.append("INCONSISTENT_EMBEDDING_ROW")
            limitations.append("inconsistent supplied state degraded by existing evaluator precedence")
        if embedding_present is False and status in _PRESENT_STATUSES:
            warnings.append("INCONSISTENT_EMBEDDING_ROW")
            limitations.append("inconsistent supplied state degraded by existing evaluator precedence")

        model = _public_string(data.get("embedding_model"))
        dimension = _int_or_none(data.get("embedding_dimension"))
        if "embedding_model" in data and not model:
            warnings.append("UNKNOWN_EMBEDDING_MODEL")
            limitations.append("embedding model unknown or unavailable")
        if "embedding_dimension" in data and dimension is None:
            warnings.append("UNKNOWN_EMBEDDING_DIMENSION")
            limitations.append("embedding dimension unknown or unavailable")
        if dimension is not None and dimension <= 0:
            warnings.append("UNKNOWN_EMBEDDING_DIMENSION")
            limitations.append("non-positive embedding dimension treated as unknown")

        embedding_updated_at = data.get("embedding_updated_at")
        source_updated_at = data.get("source_updated_at")
        if embedding_updated_at and not _timestamp_looks_parseable(embedding_updated_at):
            warnings.append("INVALID_EMBEDDING_TIMESTAMP")
            limitations.append("invalid embedding timestamp treated as unavailable")
            embedding_updated_at = None
        if source_updated_at and not _timestamp_looks_parseable(source_updated_at):
            warnings.append("INVALID_SOURCE_TIMESTAMP")
            limitations.append("invalid source timestamp treated as unavailable")
            source_updated_at = None

        text_length = _int_or_none(data.get("text_length", data.get("chunk_length")))
        if text_length is not None and text_length < 0:
            warnings.append("INVALID_TEXT_LENGTH")
            limitations.append("negative text length treated as unknown")
            text_length = None

        failure_reason = _public_string(data.get("error") or data.get("failure_reason"))
        row_warnings = tuple(_public_string(v) for v in _as_sequence(data.get("warnings")) if _public_string(v))
        row_limitations = tuple(_public_string(v) for v in _as_sequence(data.get("limitations")) if _public_string(v))

        chunk_text = "" if text_length == 0 else None
        return EmbeddingHealthInput(
            item_id=item_id,
            synthetic_id=synthetic_id,
            chunk_id=chunk_id,
            chunk_text=chunk_text,
            embedding_present=embedding_present,
            embedding_status=status,
            embedding_updated_at=embedding_updated_at,
            source_updated_at=source_updated_at,
            failure_reason=failure_reason,
            limitations=tuple(limitations) + row_limitations,
            warnings=tuple(warnings) + row_warnings,
            data_source=source_type,
            source_available=source_available,
        )

    def _result(
        self,
        rows: tuple[EmbeddingHealthInput, ...],
        warnings: Sequence[str],
        data_source: str,
        degraded: bool,
        extra_limitations: Sequence[str] = (),
    ) -> RepositoryEmbeddingHealthAdapterResult:
        records = evaluate_embedding_health_rows(rows)
        return RepositoryEmbeddingHealthAdapterResult(
            rows=rows,
            records=records,
            mode=self.mode,
            data_source=data_source,
            warnings=_dedupe(tuple(warnings)),
            limitations=_dedupe(ADAPTER_LIMITATIONS + tuple(extra_limitations)),
            degraded=degraded or any(record.degraded for record in records),
            non_claims=DEFAULT_NON_CLAIMS,
        )


def make_repository_embedding_health_adapter() -> RepositoryEmbeddingHealthAdapter:
    """Factory for the supplied-row repository embedding health adapter."""

    return RepositoryEmbeddingHealthAdapter()


def adapt_repository_embedding_health_rows(
    rows: Sequence[Mapping[str, Any] | object] | None,
) -> RepositoryEmbeddingHealthAdapterResult:
    """Adapt supplied public-safe rows into existing embedding health rows."""

    return make_repository_embedding_health_adapter().adapt_rows(rows)


def _row_to_mapping(row: Mapping[str, Any] | object) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    if is_dataclass(row):
        return row.__dict__
    public_attrs = {
        name: getattr(row, name)
        for name in _SAFE_STRING_FIELDS | {"embedding_present", "embedding_dimension", "text_length", "chunk_length", "limitations", "warnings"}
        if hasattr(row, name)
    }
    if public_attrs:
        return public_attrs
    return {"item_id": "", "chunk_id": "", "warnings": ("UNSUPPORTED_ROW_OBJECT",)}


def _unsafe_warnings(data: Mapping[str, Any]) -> tuple[str, ...]:
    warnings: list[str] = []
    for key, value in data.items():
        key_text = str(key).lower()
        if key_text in _VECTOR_FIELD_NAMES and value not in (None, ""):
            warnings.append("EMBEDDING_VECTOR_VALUE_BLOCKED")
        if key_text in _PRIVATE_ID_FIELD_NAMES and value not in (None, ""):
            warnings.append("PRIVATE_CONTEXT_BRAIN_IDENTIFIER_BLOCKED")
        if key_text in _HANDLE_FIELD_NAMES and value not in (None, ""):
            warnings.append("LIVE_REPOSITORY_HANDLE_BLOCKED")
        if _unsafe_key_name(key_text) and value not in (None, ""):
            warnings.append("UNSAFE_PRIVATE_VALUE_BLOCKED")
        if _looks_unsafe_value(value):
            warnings.append("UNSAFE_PRIVATE_VALUE_BLOCKED")
    return _dedupe(tuple(warnings))


def _unsafe_key_name(key_text: str) -> bool:
    markers = (
        "api",
        "token",
        "secret",
        "password",
        "dsn",
        "url",
        "endpoint",
        "host",
        "path",
        "sql",
        "query",
    )
    return any(marker in key_text for marker in markers)


def _looks_unsafe_value(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float, datetime)):
        return False
    if isinstance(value, (list, tuple)):
        if len(value) >= 3 and all(isinstance(v, (int, float)) for v in value[:3]):
            return True
        return any(_looks_unsafe_value(v) for v in value)
    if isinstance(value, Mapping):
        return any(_looks_unsafe_value(v) for v in value.values())
    text = str(value).strip().lower()
    if not text:
        return False
    if "production" in text or "private" in text:
        return True
    return False


def _public_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bool, int, float)):
        return str(value)
    if _looks_unsafe_value(value):
        return ""
    return str(value).strip()


def _normal_status(value: Any) -> str:
    return _public_string(value).strip().lower()


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "present"}:
        return True
    if text in {"false", "0", "no", "missing", "absent"}:
        return False
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_looks_parseable(value: Any) -> bool:
    if isinstance(value, datetime):
        return True
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


def _as_sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


def _with_warning(row: EmbeddingHealthInput, warning: str) -> EmbeddingHealthInput:
    return EmbeddingHealthInput(
        item_id=row.item_id,
        synthetic_id=row.synthetic_id,
        chunk_id=row.chunk_id,
        chunk_text=row.chunk_text,
        chunk=row.chunk,
        chunk_score=row.chunk_score,
        embedding_present=row.embedding_present,
        embedding_status=row.embedding_status,
        embedding_updated_at=row.embedding_updated_at,
        source_updated_at=row.source_updated_at,
        requires_reextract=row.requires_reextract,
        failure_reason=row.failure_reason,
        limitations=row.limitations,
        warnings=tuple(row.warnings) + (warning,),
        data_source=row.data_source,
        source_available=row.source_available,
    )


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)
