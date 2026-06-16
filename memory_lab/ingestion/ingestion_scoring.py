"""B21 deterministic ingestion scoring over caller-supplied signals.

Public-safe planning scaffold: no stored content access, no embedding generation,
no service calls, no durable mutation, and no semantic truth/novelty claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

B21_INGESTION_SCORING_MODE = "b21_deterministic_ingestion_scoring_v1"
DEFAULT_LIMITATIONS = (
    "public-safe deterministic scoring over caller-supplied signals only",
    "no semantic truth claim",
    "no semantic novelty claim",
    "no stored content access",
    "no embedding generation",
    "no durable mutation",
)


@dataclass(frozen=True)
class IngestionSignalInput:
    extraction_confidence: float | None = None
    domain_confidence: float | None = None
    hub_confidence: float | None = None
    tag_confidence: float | None = None
    chunk_quality: float | None = None
    chunk_composite: float | None = None
    embedding_admin_ready: bool | None = None
    knn_ready: bool | None = None
    risk_flags: Sequence[str] = field(default_factory=tuple)
    completeness_flags: Sequence[str] = field(default_factory=tuple)
    signal_metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestionScore:
    quality: float
    risk: float
    completeness: float
    composite: float
    confidence: float


@dataclass(frozen=True)
class IngestionScoringSummary:
    score: IngestionScore
    rationale: str
    rule_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    mode: str = B21_INGESTION_SCORING_MODE
    degraded: bool = False


class DeterministicIngestionScorer:
    """Pure deterministic scorer using only explicit local signals."""

    def score_ingestion_signals(self, signals: IngestionSignalInput) -> IngestionScoringSummary:
        supplied = _supplied_scores(signals)
        rule_ids = ["B21-C1-DETERMINISTIC-SIGNALS"]
        limitations = list(DEFAULT_LIMITATIONS)
        missing_count = 6 - len(supplied)
        degraded = missing_count > 0
        if degraded:
            rule_ids.append("B21-C1-MISSING-SIGNALS-DEGRADE-CONFIDENCE")
            limitations.append("missing signals degrade confidence without failing")

        extraction = _defaulted(signals.extraction_confidence, 0.45)
        domain = _defaulted(signals.domain_confidence, 0.45)
        hub = _defaulted(signals.hub_confidence, 0.45)
        tag = _defaulted(signals.tag_confidence, 0.45)
        chunk_quality = _defaulted(signals.chunk_quality, 0.50)
        chunk_composite = _defaulted(signals.chunk_composite, chunk_quality)

        quality = _clamp((extraction * 0.24) + (domain * 0.16) + (hub * 0.16) + (tag * 0.14) + (chunk_quality * 0.30))
        completeness = _clamp((len(tuple(signals.completeness_flags)) / 4.0) * 0.45 + (len(supplied) / 6.0) * 0.45 + _readiness_bonus(signals) * 0.10)
        risk_flags = tuple(flag for flag in signals.risk_flags if str(flag).strip())
        risk = _clamp((len(risk_flags) * 0.16) + _low_signal_risk((extraction, domain, hub, tag)) + _readiness_risk(signals))
        if risk_flags:
            rule_ids.append("B21-C1-RISK-FLAGS-REDUCE-COMPOSITE")
        if min(extraction, domain, hub, tag) < 0.40:
            rule_ids.append("B21-C1-LOW-CLASSIFICATION-SIGNALS")
        confidence_base = (len(supplied) / 6.0) * 0.72 + min(extraction, domain, hub, tag, chunk_quality, chunk_composite) * 0.28
        confidence = _clamp(confidence_base - min(0.25, len(risk_flags) * 0.04))
        composite = _clamp((quality * 0.48) + (completeness * 0.25) + (chunk_composite * 0.17) + (confidence * 0.10) - (risk * 0.35))
        return IngestionScoringSummary(
            score=IngestionScore(quality=quality, risk=risk, completeness=completeness, composite=composite, confidence=confidence),
            rationale="deterministic B21 ingestion scoring completed from caller-supplied extraction/domain/hub/tag/chunk/readiness/risk/completeness signals",
            rule_ids=tuple(_dedupe(rule_ids)),
            limitations=tuple(_dedupe(limitations)),
            degraded=degraded,
        )


def make_deterministic_ingestion_scorer() -> DeterministicIngestionScorer:
    return DeterministicIngestionScorer()


def score_ingestion_signals(signals: IngestionSignalInput) -> IngestionScoringSummary:
    return make_deterministic_ingestion_scorer().score_ingestion_signals(signals)


def _supplied_scores(signals: IngestionSignalInput) -> tuple[float, ...]:
    values = (signals.extraction_confidence, signals.domain_confidence, signals.hub_confidence, signals.tag_confidence, signals.chunk_quality, signals.chunk_composite)
    return tuple(_clamp(v) for v in values if v is not None)


def _defaulted(value: float | None, default: float) -> float:
    return _clamp(default if value is None else value)


def _readiness_bonus(signals: IngestionSignalInput) -> float:
    known = [value for value in (signals.embedding_admin_ready, signals.knn_ready) if value is not None]
    return 0.0 if not known else sum(1.0 for value in known if value) / len(known)


def _readiness_risk(signals: IngestionSignalInput) -> float:
    return (0.12 if signals.embedding_admin_ready is False else 0.0) + (0.10 if signals.knn_ready is False else 0.0)


def _low_signal_risk(values: Sequence[float]) -> float:
    return _clamp(sum(max(0.0, 0.40 - value) for value in values) * 0.30)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = low
    if numeric < low:
        return low
    if numeric > high:
        return high
    return round(numeric, 6)


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set(); out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value); out.append(value)
    return tuple(out)
