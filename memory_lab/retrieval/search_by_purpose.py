"""B23 public-safe search-by-purpose over caller-supplied records.

This module performs deterministic local ranking only. It accepts records and
signals supplied by the caller, emits transparent scoring components, and makes
no live retrieval, provider, vector-store, or private Context Brain claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

B23_SEARCH_SCOPE = "public_safe_supplied_records_deterministic_ranking_only"
B23_SEARCH_NON_CLAIMS: tuple[str, ...] = (
    "no_live_search", "no_private_memory_retrieval", "no_embedding_generation",
    "no_vector_store_integration", "no_provider_backed_semantic_search",
    "no_private_context_brain_parity", "not_production_readiness",
    "not_full_context_brain_readiness",
)

class SearchPurpose(str, Enum):
    ANSWER = "answer"
    CITE = "cite"
    SUMMARIZE = "summarize"
    COMPARE = "compare"
    RECALL = "recall"
    DECIDE = "decide"

@dataclass(frozen=True)
class SuppliedSearchCandidate:
    """Caller-supplied record used by B23 ranking."""
    item_id: str
    text: str = ""
    snippet: str = ""
    purpose_text: str = ""
    domain: str | None = None
    tags: tuple[str, ...] = ()
    source_metadata: Mapping[str, Any] = field(default_factory=dict)
    extraction_confidence: float | None = None
    domain_confidence: float | None = None
    hub_signal: float | None = None
    tag_signal: float | None = None
    knn_score: float | None = None
    knn_ready: bool | None = None
    ingestion_score: float | None = None
    tier: str | None = None
    circuit_state: str | None = None
    executor_limitations: tuple[str, ...] = ()
    validator_limitations: tuple[str, ...] = ()
    risk_level: str | None = None
    recency_rank: float | None = None

@dataclass(frozen=True)
class SearchByPurposeRequest:
    query: str
    purpose: SearchPurpose | str
    candidates: tuple[SuppliedSearchCandidate, ...]
    limit: int = 10

@dataclass(frozen=True)
class RankedContextCandidate:
    item_id: str
    rank: int
    score: float
    score_components: Mapping[str, float]
    reason: str
    limitations: tuple[str, ...]
    matched_terms: tuple[str, ...]
    candidate: SuppliedSearchCandidate
    purpose: str

@dataclass(frozen=True)
class SearchByPurposeResponse:
    query: str
    purpose: str
    results: tuple[RankedContextCandidate, ...]
    warnings: tuple[str, ...]
    non_claims: tuple[str, ...] = B23_SEARCH_NON_CLAIMS
    scope: str = B23_SEARCH_SCOPE

def rank_context_candidates_by_purpose(request: SearchByPurposeRequest) -> SearchByPurposeResponse:
    purpose, warnings = _normalize_purpose(request.purpose)
    query_terms = _terms(request.query)
    ranked: list[tuple[float, str, RankedContextCandidate]] = []
    for candidate in request.candidates:
        components, limitations, matches = _score_candidate(candidate, purpose, query_terms)
        score = round(max(0.0, min(1.0, sum(components.values()))), 4)
        reason = _reason(purpose, components, limitations, matches)
        ranked.append((score, candidate.item_id, RankedContextCandidate(candidate.item_id, 0, score, components, reason, limitations, matches, candidate, purpose)))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    limited = ranked[: max(0, request.limit)]
    results = tuple(_with_rank(item, index + 1) for index, (_, _, item) in enumerate(limited))
    return SearchByPurposeResponse(request.query, purpose, results, tuple(warnings))

def _with_rank(candidate: RankedContextCandidate, rank: int) -> RankedContextCandidate:
    return RankedContextCandidate(candidate.item_id, rank, candidate.score, candidate.score_components, candidate.reason, candidate.limitations, candidate.matched_terms, candidate.candidate, candidate.purpose)

def _normalize_purpose(value: SearchPurpose | str) -> tuple[str, list[str]]:
    raw = value.value if isinstance(value, SearchPurpose) else str(value).strip().lower()
    allowed = {p.value for p in SearchPurpose}
    if raw in allowed:
        return raw, []
    fallback = raw or "custom"
    return fallback, [f"unknown_purpose_degraded:{fallback}"]

def _score_candidate(candidate: SuppliedSearchCandidate, purpose: str, query_terms: tuple[str, ...]) -> tuple[dict[str, float], tuple[str, ...], tuple[str, ...]]:
    limitations: list[str] = []
    text_blob = " ".join(part for part in (candidate.snippet, candidate.text, candidate.purpose_text, candidate.domain or "", " ".join(candidate.tags)) if part)
    matches = tuple(term for term in query_terms if term in text_blob.lower())
    components: dict[str, float] = {
        "text_available": 0.08 if (candidate.snippet or candidate.text) else 0.0,
        "lexical_match": min(0.18, 0.04 * len(matches)),
        "extraction_confidence": 0.10 * _bounded(candidate.extraction_confidence),
        "domain_confidence": 0.06 * _bounded(candidate.domain_confidence),
        "hub_signal": 0.06 * _bounded(candidate.hub_signal),
        "tag_signal": 0.06 * _bounded(candidate.tag_signal),
        "knn_signal": 0.16 * _bounded(candidate.knn_score) if candidate.knn_score is not None and candidate.knn_ready is not False else 0.0,
        "ingestion_signal": 0.14 * _bounded(candidate.ingestion_score),
        "recency_signal": 0.05 * _bounded(candidate.recency_rank),
        "source_metadata": 0.05 if candidate.source_metadata else 0.0,
        "purpose_fit": _purpose_fit(candidate, purpose, matches),
        "penalty": _penalty(candidate, limitations),
    }
    return components, tuple(_dedupe(limitations + list(candidate.executor_limitations) + list(candidate.validator_limitations))), matches

def _purpose_fit(candidate: SuppliedSearchCandidate, purpose: str, matches: tuple[str, ...]) -> float:
    text_len = len((candidate.snippet or candidate.text).strip())
    has_meta = bool(candidate.source_metadata)
    has_multi = bool(candidate.domain) and bool(candidate.tags)
    safe_circuit = (candidate.circuit_state or "closed").lower() in {"closed", "healthy", "safe", "ok", "unknown"}
    if purpose == SearchPurpose.ANSWER.value:
        return 0.17 * max(_bounded(candidate.knn_score), _bounded(candidate.ingestion_score), len(matches) / 5 if matches else 0.0)
    if purpose == SearchPurpose.CITE.value:
        return (0.25 if has_meta else 0.0) + (0.08 if text_len else 0.0)
    if purpose == SearchPurpose.SUMMARIZE.value:
        return (0.12 if 80 <= text_len <= 4000 else 0.04 if text_len else 0.0) + 0.04 * _bounded(candidate.extraction_confidence)
    if purpose == SearchPurpose.COMPARE.value:
        return (0.08 if has_multi else 0.0) + 0.05 * _bounded(candidate.tag_signal) + 0.04 * _bounded(candidate.domain_confidence)
    if purpose == SearchPurpose.RECALL.value:
        return min(0.16, 0.05 * len(matches)) + 0.04 * _bounded(candidate.recency_rank)
    if purpose == SearchPurpose.DECIDE.value:
        return (0.08 if safe_circuit else 0.0) + 0.06 * _bounded(candidate.ingestion_score) + 0.04 * _bounded(candidate.domain_confidence)
    return 0.05 if matches else 0.0

def _penalty(candidate: SuppliedSearchCandidate, limitations: list[str]) -> float:
    penalty = 0.0
    if not (candidate.snippet or candidate.text):
        limitations.append("missing_snippet_or_text")
        penalty -= 0.18
    state = (candidate.circuit_state or "closed").lower()
    if state in {"open", "degraded", "tripped"}:
        limitations.append(f"circuit_state_{state}")
        penalty -= 0.16 if state == "open" else 0.10
    if candidate.knn_ready is False:
        limitations.append("knn_not_ready")
        penalty -= 0.04
    low_conf = [v for v in (candidate.extraction_confidence, candidate.domain_confidence) if v is not None and v < 0.35]
    if low_conf:
        limitations.append("low_confidence_signal")
        penalty -= 0.06
    if (candidate.risk_level or "").lower() in {"high", "blocked", "unsafe"}:
        limitations.append("high_risk_supplied_signal")
        penalty -= 0.18
    suspicious = " ".join(str(v).lower() for v in candidate.source_metadata.values())
    if any(marker in suspicious for marker in ("private", "secret", "credential")):
        limitations.append("source_metadata_private_looking")
        penalty -= 0.12
    return penalty

def _reason(purpose: str, components: Mapping[str, float], limitations: Sequence[str], matches: Sequence[str]) -> str:
    positive = [name for name, value in components.items() if name != "penalty" and value > 0]
    bits = [f"purpose={purpose}", f"positive={','.join(positive) or 'none'}"]
    if matches:
        bits.append("matched_terms=" + ",".join(matches))
    if limitations:
        bits.append("limitations=" + ",".join(limitations))
    if components.get("penalty", 0.0) < 0:
        bits.append(f"penalty={components['penalty']:.2f}")
    return " | ".join(bits)

def _terms(text: str) -> tuple[str, ...]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return tuple(_dedupe([part for part in cleaned.split() if len(part) >= 3]))

def _bounded(value: float | int | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(1.0, float(value)))

def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out
