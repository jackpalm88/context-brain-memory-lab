"""Deterministic classifiers for the public-safe ingestion foundation.

B17 keeps noop hub and tag components. B18 adds a bounded deterministic domain
signal classifier that uses a small public taxonomy and local text/metadata only.
It is not semantic understanding, not DB-learned classification, and not private
Context Brain parity.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, NamedTuple, Sequence

from memory_lab.ingestion.interfaces import (
    DEFAULT_LIMITATIONS,
    SYNTHETIC_DATA_SOURCE,
    DomainClassificationResult,
    HubDetectionResult,
    IngestionTextInput,
    TagClassificationResult,
)

NOOP_CLASSIFIER_MODE = "noop_classifier_v1"
DETERMINISTIC_DOMAIN_SIGNAL_MODE = "deterministic_domain_signal_v1"

NOOP_CLASSIFIER_LIMITATIONS: Sequence[str] = DEFAULT_LIMITATIONS + (
    "noop classifier only",
    "no real domain classification",
    "no real hub detection",
    "no real tag classification",
    "no semantic understanding",
)

DETERMINISTIC_DOMAIN_SIGNAL_LIMITATIONS: Sequence[str] = DEFAULT_LIMITATIONS + (
    "deterministic domain signal only",
    "small public taxonomy only",
    "caller-supplied text and safe metadata only",
    "no learned private taxonomy",
    "no DB/private Context Brain access",
    "no embeddings or vector operations",
    "no semantic understanding claim",
)

DOMAIN_TAXONOMY: Sequence[str] = (
    "planning",
    "operations",
    "knowledge_management",
    "software",
    "governance",
    "documentation",
    "quality",
    "ambiguous",
    "unknown",
)

DOMAIN_KEYWORDS: Mapping[str, Mapping[str, float]] = {
    "planning": {
        "planning": 3.0,
        "plan": 1.5,
        "meeting": 1.2,
        "roadmap": 2.0,
        "checklist": 1.4,
        "draft": 1.0,
        "follow-up": 1.2,
        "onboarding": 1.5,
        "sprint": 1.0,
    },
    "operations": {
        "operations": 3.0,
        "operational": 2.0,
        "intake": 1.5,
        "handoff": 1.4,
        "cadence": 1.3,
        "review cadence": 2.0,
        "process": 1.0,
        "workflow": 1.0,
    },
    "knowledge_management": {
        "knowledge base": 3.0,
        "knowledge": 1.8,
        "workspace": 1.2,
        "records": 1.2,
        "source text": 1.2,
        "document": 1.0,
        "notes": 1.0,
    },
    "software": {
        "software": 2.5,
        "release": 1.8,
        "api": 1.8,
        "tests": 1.4,
        "repository": 1.4,
        "version": 1.1,
        "implementation": 1.1,
    },
    "governance": {
        "governance": 3.0,
        "gate": 2.0,
        "evidence": 1.8,
        "public-safe": 1.6,
        "boundary": 1.4,
        "policy": 1.4,
        "approval": 1.2,
        "scorecard": 1.2,
    },
    "documentation": {
        "documentation": 3.0,
        "readme": 2.0,
        "docs": 1.8,
        "guide": 1.4,
        "heading": 1.0,
        "section": 1.0,
    },
    "quality": {
        "quality": 3.0,
        "validation": 1.8,
        "verify": 1.4,
        "verified": 1.4,
        "test": 1.2,
        "tests": 1.2,
        "review-needed": 1.1,
        "sample-quality": 1.1,
    },
}

AMBIGUITY_MARKERS = (
    "ambiguous",
    "does not reveal",
    "unclear",
    "whether the topic",
    "could be",
)

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


def _metadata_text(metadata: Mapping[str, object]) -> str:
    safe_values: list[str] = []
    for value in metadata.values():
        if isinstance(value, (str, int, float, bool)):
            safe_values.append(str(value))
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            safe_values.extend(str(item) for item in value if isinstance(item, (str, int, float, bool)))
    return " ".join(safe_values)


def _normalize_for_scoring(item: IngestionTextInput) -> str:
    return " ".join(part for part in (item.title, item.text, _metadata_text(item.metadata)) if part).lower()


def _score_domain(text: str, domain: str) -> float:
    score = 0.0
    for phrase, weight in DOMAIN_KEYWORDS[domain].items():
        if " " in phrase:
            if phrase in text:
                score += weight
        else:
            count = sum(1 for token in _TOKEN_RE.findall(text) if token == phrase)
            score += count * weight
    return round(score, 4)


def _score_all(text: str) -> dict[str, float]:
    return {domain: _score_domain(text, domain) for domain in DOMAIN_KEYWORDS}


def _is_ambiguous(text: str, scores: Mapping[str, float]) -> bool:
    if any(marker in text for marker in AMBIGUITY_MARKERS):
        return True
    ranked = sorted(scores.values(), reverse=True)
    return len(ranked) > 1 and ranked[0] >= 2.0 and (ranked[0] - ranked[1]) <= 0.75


def _confidence_for(score: float, ambiguous: bool) -> float:
    if score <= 0:
        return 0.0
    confidence = min(0.84, 0.25 + (score / 10.0))
    if ambiguous:
        confidence = min(confidence, 0.42)
    return round(confidence, 2)


@dataclass(frozen=True)
class NoopDomainClassifier:
    """Deterministic noop domain classifier retained for B17 regressions."""

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
class DeterministicDomainSignalClassifier:
    """Public-safe deterministic domain signal classifier."""

    mode: str = DETERMINISTIC_DOMAIN_SIGNAL_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = DETERMINISTIC_DOMAIN_SIGNAL_LIMITATIONS

    def classify_domain(self, item: IngestionTextInput) -> DomainClassificationResult:
        scoring_text = _normalize_for_scoring(item)
        if not item.text.strip():
            return DomainClassificationResult(
                domain="unknown",
                confidence=0.0,
                rationale="deterministic domain signal found no usable caller-supplied text",
                mode=self.mode,
                data_source=item.data_source or self.data_source,
                degraded=True,
                limitations=self.limitations,
            )

        scores = _score_all(scoring_text)
        top_domain, top_score = max(scores.items(), key=lambda item: (item[1], item[0]))
        ambiguous = _is_ambiguous(scoring_text, scores)
        if top_score < 2.0:
            domain = "unknown"
            confidence = _confidence_for(top_score, False)
            rationale = "weak deterministic public-taxonomy signal; returning unknown"
        elif ambiguous:
            domain = "ambiguous"
            confidence = _confidence_for(top_score, True)
            rationale = "close or explicitly ambiguous deterministic public-taxonomy signals"
        else:
            domain = top_domain
            confidence = _confidence_for(top_score, False)
            rationale = f"deterministic public-taxonomy signal matched {top_domain}"

        return DomainClassificationResult(
            domain=domain,
            confidence=confidence,
            rationale=rationale,
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            degraded=False,
            limitations=self.limitations,
        )


@dataclass(frozen=True)
class NoopHubDetector:
    """Deterministic noop hub detector.

    Always returns no hub candidates with zero confidence. It performs no graph,
    taxonomy, DB, private Context Brain, embedding, or external-intelligence lookup.
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


class DeterministicDomainSignalClassifierSet(NamedTuple):
    """B18 bundle: deterministic domain signal plus deferred hub/tag noops."""

    domain_classifier: DeterministicDomainSignalClassifier
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
        domain_classifier=NoopDomainClassifier(mode=mode, data_source=data_source, limitations=limitations),
        hub_detector=NoopHubDetector(mode=mode, data_source=data_source, limitations=limitations),
        tag_classifier=NoopTagClassifier(mode=mode, data_source=data_source, limitations=limitations),
    )


def make_deterministic_domain_signal_classifiers(
    *,
    mode: str = DETERMINISTIC_DOMAIN_SIGNAL_MODE,
    data_source: str = SYNTHETIC_DATA_SOURCE,
    limitations: Sequence[str] = DETERMINISTIC_DOMAIN_SIGNAL_LIMITATIONS,
) -> DeterministicDomainSignalClassifierSet:
    """Create the B18 deterministic domain signal classifier bundle."""

    return DeterministicDomainSignalClassifierSet(
        domain_classifier=DeterministicDomainSignalClassifier(mode=mode, data_source=data_source, limitations=limitations),
        hub_detector=NoopHubDetector(),
        tag_classifier=NoopTagClassifier(),
    )
