"""Deterministic provider-free KNN retrieval core for B20.

The core ranks caller-supplied synthetic vectors in memory. It does not create
embeddings, fetch records, query databases, call networks, use vector stores, or
expose API routes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any, Mapping, Sequence

KNN_RETRIEVAL_MODE = "deterministic_knn_retrieval_core_v1"

DEFAULT_NON_CLAIMS = (
    "no embeddings generated",
    "no provider-backed semantic retrieval",
    "no database access",
    "no vector store access",
    "no network access",
    "no private content access",
    "no API route wiring",
    "no production vector retrieval claim",
    "no Full Context Brain claim",
)

DEFAULT_LIMITATIONS = (
    "deterministic cosine ranking over caller-supplied vectors only",
    "synthetic/public-safe vectors expected",
    "no embedding generation",
    "no stored-record lookup",
)


@dataclass(frozen=True)
class KnnVectorItem:
    """Caller-supplied vector item for deterministic KNN ranking."""

    item_id: str
    vector: Sequence[float] | None
    text: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    limitations: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class KnnQuery:
    """Caller-supplied query vector and ranking options."""

    vector: Sequence[float] | None
    top_k: int = 5
    query_id: str = "synthetic-query"


@dataclass(frozen=True)
class KnnSearchResult:
    """One deterministic KNN search result."""

    item_id: str
    score: float
    rank: int
    reason: str
    degraded: bool
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    mode: str
    non_claims: tuple[str, ...]


@dataclass(frozen=True)
class KnnSearchSummary:
    """Aggregate deterministic KNN search result shape."""

    query_id: str
    mode: str
    results: tuple[KnnSearchResult, ...]
    total_items: int
    candidate_count: int
    skipped_count: int
    degraded: bool
    unavailable: bool
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    non_claims: tuple[str, ...]


class DeterministicKnnRetriever:
    """Rank supplied vectors by cosine similarity without side effects."""

    mode: str = KNN_RETRIEVAL_MODE

    def rank_by_cosine_similarity(
        self,
        query: KnnQuery | Sequence[float] | None,
        items: Sequence[KnnVectorItem | Mapping[str, Any]] | None,
        *,
        top_k: int | None = None,
    ) -> KnnSearchSummary:
        normalized_query, query_id, query_warnings = _normalize_query(query, top_k=top_k)
        source_items = tuple(items or ())
        requested_top_k = _top_k(query.top_k if isinstance(query, KnnQuery) else top_k)

        if normalized_query is None:
            return self._summary(
                query_id=query_id,
                results=(),
                total_items=len(source_items),
                skipped_count=len(source_items),
                warnings=query_warnings + ("KNN_QUERY_VECTOR_INVALID",),
                unavailable=True,
            )

        if not source_items:
            return self._summary(
                query_id=query_id,
                results=(),
                total_items=0,
                skipped_count=0,
                warnings=query_warnings + ("KNN_CORPUS_EMPTY",),
                unavailable=True,
            )

        ranked: list[tuple[float, str, tuple[str, ...], tuple[str, ...]]] = []
        warnings: list[str] = list(query_warnings)
        skipped_count = 0
        for raw_item in source_items:
            item_id, vector, item_limitations = _normalize_item(raw_item)
            if vector is None:
                skipped_count += 1
                warnings.append("KNN_ITEM_VECTOR_MISSING_OR_INVALID")
                continue
            if len(vector) != len(normalized_query):
                skipped_count += 1
                warnings.append("KNN_DIMENSION_MISMATCH")
                continue
            score, score_warning = _cosine(normalized_query, vector)
            item_warnings = (score_warning,) if score_warning else ()
            warnings.extend(item_warnings)
            ranked.append((score, item_id, item_warnings, item_limitations))

        if not ranked:
            return self._summary(
                query_id=query_id,
                results=(),
                total_items=len(source_items),
                skipped_count=skipped_count,
                warnings=tuple(warnings) + ("KNN_NO_VALID_CANDIDATES",),
                unavailable=True,
            )

        ranked.sort(key=lambda row: (-row[0], row[1]))
        results = tuple(
            KnnSearchResult(
                item_id=item_id,
                score=round(score, 12),
                rank=rank,
                reason="cosine_similarity_over_supplied_vectors",
                degraded=bool(item_warnings or item_limitations),
                warnings=_dedupe(item_warnings),
                limitations=_dedupe(DEFAULT_LIMITATIONS + item_limitations),
                mode=self.mode,
                non_claims=DEFAULT_NON_CLAIMS,
            )
            for rank, (score, item_id, item_warnings, item_limitations) in enumerate(ranked[:requested_top_k], start=1)
        )
        return self._summary(
            query_id=query_id,
            results=results,
            total_items=len(source_items),
            skipped_count=skipped_count,
            warnings=tuple(warnings),
            unavailable=False,
        )

    def _summary(
        self,
        *,
        query_id: str,
        results: Sequence[KnnSearchResult],
        total_items: int,
        skipped_count: int,
        warnings: Sequence[str],
        unavailable: bool,
    ) -> KnnSearchSummary:
        clean_warnings = _dedupe(tuple(warnings))
        return KnnSearchSummary(
            query_id=query_id,
            mode=self.mode,
            results=tuple(results),
            total_items=total_items,
            candidate_count=len(results),
            skipped_count=skipped_count,
            degraded=bool(clean_warnings or unavailable or skipped_count),
            unavailable=unavailable,
            warnings=clean_warnings,
            limitations=DEFAULT_LIMITATIONS,
            non_claims=DEFAULT_NON_CLAIMS,
        )


def make_deterministic_knn_retriever() -> DeterministicKnnRetriever:
    """Factory for the B20 deterministic in-memory KNN retriever."""

    return DeterministicKnnRetriever()


def rank_by_cosine_similarity(
    query: KnnQuery | Sequence[float] | None,
    items: Sequence[KnnVectorItem | Mapping[str, Any]] | None,
    *,
    top_k: int | None = None,
) -> KnnSearchSummary:
    """Convenience wrapper for deterministic cosine KNN ranking."""

    return make_deterministic_knn_retriever().rank_by_cosine_similarity(query, items, top_k=top_k)


def _normalize_query(query: KnnQuery | Sequence[float] | None, *, top_k: int | None) -> tuple[tuple[float, ...] | None, str, tuple[str, ...]]:
    if isinstance(query, KnnQuery):
        return _normalize_vector(query.vector), query.query_id, ()
    return _normalize_vector(query), "synthetic-query", ()


def _normalize_item(raw_item: KnnVectorItem | Mapping[str, Any]) -> tuple[str, tuple[float, ...] | None, tuple[str, ...]]:
    if isinstance(raw_item, KnnVectorItem):
        return raw_item.item_id, _normalize_vector(raw_item.vector), tuple(str(v) for v in raw_item.limitations if str(v))
    item_id = str(raw_item.get("item_id") or raw_item.get("id") or "")
    vector = _normalize_vector(raw_item.get("vector"))
    limitations = tuple(str(v) for v in raw_item.get("limitations", ()) if str(v))
    return item_id, vector, limitations


def _normalize_vector(vector: Sequence[float] | None) -> tuple[float, ...] | None:
    if vector is None or isinstance(vector, (str, bytes)):
        return None
    values: list[float] = []
    try:
        iterator = iter(vector)
    except TypeError:
        return None
    for value in iterator:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number != number or number in (float("inf"), float("-inf")):
            return None
        values.append(number)
    return tuple(values) if values else None


def _cosine(a: Sequence[float], b: Sequence[float]) -> tuple[float, str]:
    norm_a = sqrt(sum(value * value for value in a))
    norm_b = sqrt(sum(value * value for value in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0, "KNN_ZERO_VECTOR_DEGRADED"
    score = sum(left * right for left, right in zip(a, b)) / (norm_a * norm_b)
    return max(-1.0, min(1.0, score)), ""


def _top_k(value: int | None) -> int:
    try:
        parsed = int(value if value is not None else 5)
    except (TypeError, ValueError):
        parsed = 5
    return max(1, min(parsed, 100))


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return tuple(out)
