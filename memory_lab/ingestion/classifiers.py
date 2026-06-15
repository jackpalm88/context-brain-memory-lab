"""Deterministic noop classifiers for the B17 ingestion foundation.

This module intentionally provides no real classification intelligence. It keeps
B17 classifier behavior provider-free, DB-free, embedding-free, mutation-free,
and public-safe while satisfying the existing ingestion interface contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Sequence

from memory_lab.ingestion.interfaces import (
    DEFAULT_LIMITATIONS,
    SYNTHETIC_DATA_SOURCE,
    DomainClassificationResult,
    HubDetectionResult,
    IngestionTextInput,
    TagClassificationResult,
)

NOOP_CLASSIFIER_MODE = "noop_classifier_v1"
NOOP_CLASSIFIER_LIMITATIONS: Sequence[str] = DEFAULT_LIMITATIONS + (
    "noop classifier only",
    "no real domain classification",
    "no real hub detection",
    "no real tag classification",
    "no semantic understanding",
)


@dataclass(frozen=True)
class NoopDomainClassifier:
    """Deterministic noop domain classifier.

    Always returns an unknown domain with zero confidence and explicit degraded
    semantics. It never infers real domains from text, title, metadata, or source
    identifiers.
    """

    mode: str = NOOP_CLASSIFIER_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = NOOP_CLASSIFIER_LIMITATIONS

    def classify_domain(self, item: IngestionTextInput) -> DomainClassificationResult:
        return DomainClassificationResult(
            domain="unknown",
            confidence=0.0,
            rationale="noop classifier does not perform real domain classification",
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            degraded=True,
            limitations=self.limitations,
        )


@dataclass(frozen=True)
class NoopHubDetector:
    """Deterministic noop hub detector.

    Always returns no hub candidates with zero confidence. It performs no graph,
    taxonomy, DB, private Context Brain, embedding, or provider lookup.
    """

    mode: str = NOOP_CLASSIFIER_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = NOOP_CLASSIFIER_LIMITATIONS

    def detect_hubs(self, item: IngestionTextInput) -> HubDetectionResult:
        return HubDetectionResult(
            hub_candidates=(),
            confidence=0.0,
            rationale="noop classifier does not perform real hub detection",
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            degraded=True,
            limitations=self.limitations,
        )


@dataclass(frozen=True)
class NoopTagClassifier:
    """Deterministic noop tag classifier.

    Always returns no tags with zero confidence. It makes no semantic tag,
    language, taxonomy, or external-intelligence claim.
    """

    mode: str = NOOP_CLASSIFIER_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = NOOP_CLASSIFIER_LIMITATIONS

    def classify_tags(self, item: IngestionTextInput) -> TagClassificationResult:
        return TagClassificationResult(
            tags=(),
            confidence=0.0,
            rationale="noop classifier does not perform real tag classification",
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            degraded=True,
            limitations=self.limitations,
        )


class NoopClassifierSet(NamedTuple):
    """Focused bundle of the three noop classifier components."""

    domain_classifier: NoopDomainClassifier
    hub_detector: NoopHubDetector
    tag_classifier: NoopTagClassifier


def make_noop_classifiers(
    *,
    mode: str = NOOP_CLASSIFIER_MODE,
    data_source: str = SYNTHETIC_DATA_SOURCE,
    limitations: Sequence[str] = NOOP_CLASSIFIER_LIMITATIONS,
) -> NoopClassifierSet:
    """Create deterministic noop classifiers with shared boundary defaults."""

    return NoopClassifierSet(
        domain_classifier=NoopDomainClassifier(
            mode=mode,
            data_source=data_source,
            limitations=limitations,
        ),
        hub_detector=NoopHubDetector(
            mode=mode,
            data_source=data_source,
            limitations=limitations,
        ),
        tag_classifier=NoopTagClassifier(
            mode=mode,
            data_source=data_source,
            limitations=limitations,
        ),
    )
