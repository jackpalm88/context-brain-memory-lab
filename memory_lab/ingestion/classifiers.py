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

DETERMINISTIC_HUB_SIGNAL_MODE = "deterministic_hub_signal_v1"
DETERMINISTIC_TAG_SIGNAL_MODE = "deterministic_tag_signal_v1"

DETERMINISTIC_HUB_TAG_SIGNAL_LIMITATIONS: Sequence[str] = DEFAULT_LIMITATIONS + (
    "deterministic public-safe signal only",
    "caller-supplied title text and metadata only",
    "small public taxonomy only",
    "no learned private taxonomy",
    "no external service calls",
    "no stored-record access",
    "no vector operation",
    "no mutation methods",
    "no semantic understanding claim",
)

MAX_HUB_CANDIDATES = 3
MAX_TAGS = 10

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


_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def _safe_scalar_text(value: object) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, Mapping):
        return " ".join(_safe_scalar_text(v) for v in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return " ".join(_safe_scalar_text(v) for v in value)
    return ""


def _public_metadata_text(metadata: Mapping[str, object]) -> str:
    return " ".join(_safe_scalar_text(value) for key, value in metadata.items() if key != "hub_candidates")


def _normalize_text(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.lower()))


def _slug(value: str) -> str:
    normalized = _normalize_text(value).replace(" ", "_")
    normalized = _SLUG_RE.sub("_", normalized).strip("_")
    return normalized


def _safe_tokens(value: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(value.lower()) if len(token) >= 4}


def _contains_phrase(scoring_text: str, phrase: str) -> bool:
    normalized = _normalize_text(phrase)
    return bool(normalized and normalized in scoring_text)


def _candidate_rows(metadata: Mapping[str, object]) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...], str], bool]:
    raw = metadata.get("hub_candidates")
    if raw in (None, ""):
        return (), False
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return (), True
    rows: list[tuple[str, tuple[str, ...], tuple[str, ...], str]] = []
    malformed = False
    for entry in raw:
        if not isinstance(entry, Mapping):
            malformed = True
            continue
        title = str(entry.get("title") or entry.get("name") or "").strip()
        if not title:
            malformed = True
            continue
        aliases_raw = entry.get("aliases") or ()
        related_raw = entry.get("related_terms") or entry.get("terms") or ()
        aliases = tuple(str(v).strip() for v in aliases_raw if isinstance(v, (str, int, float, bool)) and str(v).strip()) if isinstance(aliases_raw, Sequence) and not isinstance(aliases_raw, (str, bytes, bytearray)) else ()
        related = tuple(str(v).strip() for v in related_raw if isinstance(v, (str, int, float, bool)) and str(v).strip()) if isinstance(related_raw, Sequence) and not isinstance(related_raw, (str, bytes, bytearray)) else ()
        candidate_slug = _slug(str(entry.get("slug") or title))
        if not candidate_slug:
            malformed = True
            continue
        rows.append((title, aliases, related, candidate_slug))
    return tuple(rows), malformed


def _bounded_signal_confidence(score: float, ambiguous: bool = False) -> float:
    if score <= 0:
        return 0.0
    confidence = max(0.35, min(0.84, 0.31 + (score / 10.0)))
    if ambiguous:
        confidence = min(confidence, 0.55)
    return round(confidence, 2)


TAG_KEYWORDS: Mapping[str, Mapping[str, float]] = {
    "governance": {"governance": 3.0, "gate": 1.8, "approval": 1.4, "policy": 1.4, "evidence": 1.2},
    "planning": {"planning": 3.0, "roadmap": 1.8, "plan": 1.4, "checklist": 1.2, "sprint": 1.0},
    "operations": {"operations": 3.0, "handoff": 1.6, "cadence": 1.4, "workflow": 1.2, "process": 1.0},
    "documentation": {"documentation": 3.0, "readme": 2.0, "docs": 1.7, "guide": 1.4, "section": 1.0},
    "quality": {"quality": 3.0, "test": 1.2, "tests": 1.2, "verify": 1.4, "verified": 1.4},
    "software": {"software": 2.5, "repository": 1.6, "api": 1.6, "version": 1.2, "code": 1.0},
    "knowledge_management": {"knowledge base": 3.0, "knowledge": 1.8, "records": 1.4, "notes": 1.1, "source text": 1.1},
    "public_safe": {"public-safe": 5.0, "public safe": 5.0, "public": 0.8, "safe": 0.8},
    "boundary_check": {"boundary": 4.0, "boundaries": 3.6, "non-claim": 1.4, "non claim": 1.4},
    "scorecard": {"scorecard": 3.0, "score": 1.0},
    "testing": {"testing": 3.0, "tests": 1.8, "pytest": 1.4, "validation": 1.0},
    "release": {"release": 3.0, "version": 1.2, "commit": 1.0, "tag": 0.8},
    "implementation": {"implementation": 3.0, "implement": 1.8, "implemented": 1.8, "scaffold": 1.0},
    "review": {"review": 3.0, "audit": 1.4, "inspect": 1.0},
    "validation": {"validation": 3.0, "verified": 1.6, "evidence": 1.4, "bounded": 0.8},
}

UNSAFE_TAG_TERMS = {
    "http", "https", "www", "com", "login", "logout", "cookie", "cookies", "privacy", "terms",
    "subscribe", "click", "share", "navbar", "navigation", "footer", "header", "sign", "tools", "mode",
}


def _safe_tag(value: str) -> str:
    tag = _slug(value.replace("-", "_"))
    if len(tag) < 4 or tag in UNSAFE_TAG_TERMS:
        return ""
    if any(part in UNSAFE_TAG_TERMS for part in tag.split("_")):
        return ""
    if not re.fullmatch(r"[a-z0-9_]+", tag):
        return ""
    return tag


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
class DeterministicHubSignalDetector:
    """Public-safe deterministic hub candidate signal detector."""
    mode: str = DETERMINISTIC_HUB_SIGNAL_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = DETERMINISTIC_HUB_TAG_SIGNAL_LIMITATIONS

    def detect_hubs(self, item: IngestionTextInput) -> HubDetectionResult:
        scoring_text = _normalize_text(" ".join((item.title, item.text, _public_metadata_text(item.metadata))))
        if not scoring_text:
            return HubDetectionResult(hub_candidates=(), confidence=0.0, rationale="deterministic public-safe hub signal found no usable caller-supplied text", mode=self.mode, data_source=item.data_source or self.data_source, degraded=True, limitations=self.limitations)
        rows, malformed = _candidate_rows(item.metadata)
        if malformed:
            return HubDetectionResult(hub_candidates=(), confidence=0.0, rationale="deterministic public-safe hub signal received malformed caller-supplied candidates", mode=self.mode, data_source=item.data_source or self.data_source, degraded=True, limitations=self.limitations)
        if not rows:
            return HubDetectionResult(hub_candidates=(), confidence=0.0, rationale="deterministic public-safe hub signal had no caller-supplied candidate definitions", mode=self.mode, data_source=item.data_source or self.data_source, degraded=False, limitations=self.limitations)
        supplied_domain = str(item.metadata.get("domain") or "").strip().lower()
        scored: list[tuple[float, str]] = []
        scoring_tokens = _safe_tokens(scoring_text)
        for title, aliases, related_terms, candidate_slug in rows:
            score = 0.0
            title_norm = _normalize_text(title)
            if title_norm and title_norm in scoring_text:
                score += 4.0
            for alias in aliases:
                if _contains_phrase(scoring_text, alias):
                    score += 3.0
            for term in related_terms:
                if _contains_phrase(scoring_text, term):
                    score += 2.0
            title_tokens = _safe_tokens(title)
            if title_tokens:
                score += min(1.5, len(title_tokens.intersection(scoring_tokens)) * 0.5)
            if supplied_domain and supplied_domain in title_norm:
                score += 0.75
            if score >= 2.0:
                scored.append((round(score, 4), candidate_slug))
        if not scored:
            return HubDetectionResult(hub_candidates=(), confidence=0.0, rationale="deterministic public-safe hub signal found no bounded candidate match", mode=self.mode, data_source=item.data_source or self.data_source, degraded=False, limitations=self.limitations)
        scored = sorted(scored, key=lambda row: (-row[0], row[1]))
        top_score = scored[0][0]
        ambiguous = len(scored) > 1 and (top_score - scored[1][0]) <= 0.5
        rationale = "deterministic public-safe hub candidate signal matched caller-supplied public definitions"
        if ambiguous:
            rationale = "deterministic public-safe hub candidate signal found close bounded candidate matches"
        return HubDetectionResult(hub_candidates=tuple(slug for _, slug in scored[:MAX_HUB_CANDIDATES]), confidence=_bounded_signal_confidence(top_score, ambiguous), rationale=rationale, mode=self.mode, data_source=item.data_source or self.data_source, degraded=False, limitations=self.limitations)


@dataclass(frozen=True)
class DeterministicTagSignalClassifier:
    """Public-safe deterministic sanitized tag signal classifier."""
    mode: str = DETERMINISTIC_TAG_SIGNAL_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = DETERMINISTIC_HUB_TAG_SIGNAL_LIMITATIONS

    def classify_tags(self, item: IngestionTextInput) -> TagClassificationResult:
        scoring_text = _normalize_text(" ".join((item.title, item.text, _public_metadata_text(item.metadata))))
        if not scoring_text:
            return TagClassificationResult(tags=(), confidence=0.0, rationale="deterministic public-safe tag signal found no usable caller-supplied text", mode=self.mode, data_source=item.data_source or self.data_source, degraded=True, limitations=self.limitations)
        scores: dict[str, float] = {}
        tokens = _TOKEN_RE.findall(scoring_text)
        for tag, keywords in TAG_KEYWORDS.items():
            score = 0.0
            for phrase, weight in keywords.items():
                phrase_norm = _normalize_text(phrase)
                if " " in phrase_norm:
                    if phrase_norm in scoring_text:
                        score += weight
                else:
                    score += tokens.count(phrase_norm) * weight
            if score > 0:
                safe = _safe_tag(tag)
                if safe:
                    scores[safe] = scores.get(safe, 0.0) + score
        supplied_domain = _safe_tag(str(item.metadata.get("domain") or ""))
        if supplied_domain in TAG_KEYWORDS:
            scores[supplied_domain] = scores.get(supplied_domain, 0.0) + 1.25
        for token in _safe_tokens(scoring_text):
            safe = _safe_tag(token)
            if safe in TAG_KEYWORDS:
                scores[safe] = scores.get(safe, 0.0) + 0.5
        ranked = sorted(scores.items(), key=lambda row: (-row[1], row[0]))
        tags = tuple(tag for tag, score in ranked if score >= 1.2)[:MAX_TAGS]
        if not tags:
            return TagClassificationResult(tags=(), confidence=0.0, rationale="deterministic public-safe tag signal found no bounded sanitized tags", mode=self.mode, data_source=item.data_source or self.data_source, degraded=False, limitations=self.limitations)
        top_score = ranked[0][1]
        ambiguous = len(ranked) > 1 and (ranked[0][1] - ranked[1][1]) <= 0.5
        return TagClassificationResult(tags=tags, confidence=_bounded_signal_confidence(top_score, ambiguous), rationale="deterministic public-safe sanitized tag signal from public taxonomy and caller-supplied text", mode=self.mode, data_source=item.data_source or self.data_source, degraded=False, limitations=self.limitations)


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


class DeterministicIngestionSignalClassifierSet(NamedTuple):
    """B19 bundle: deterministic domain, hub candidate, and tag signals."""

    domain_classifier: DeterministicDomainSignalClassifier
    hub_detector: DeterministicHubSignalDetector
    tag_classifier: DeterministicTagSignalClassifier


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


def make_deterministic_ingestion_signal_classifiers(
    *,
    domain_mode: str = DETERMINISTIC_DOMAIN_SIGNAL_MODE,
    hub_mode: str = DETERMINISTIC_HUB_SIGNAL_MODE,
    tag_mode: str = DETERMINISTIC_TAG_SIGNAL_MODE,
    data_source: str = SYNTHETIC_DATA_SOURCE,
    domain_limitations: Sequence[str] = DETERMINISTIC_DOMAIN_SIGNAL_LIMITATIONS,
    signal_limitations: Sequence[str] = DETERMINISTIC_HUB_TAG_SIGNAL_LIMITATIONS,
) -> DeterministicIngestionSignalClassifierSet:
    """Create the B19 deterministic public-safe ingestion signal bundle."""

    return DeterministicIngestionSignalClassifierSet(
        domain_classifier=DeterministicDomainSignalClassifier(mode=domain_mode, data_source=data_source, limitations=domain_limitations),
        hub_detector=DeterministicHubSignalDetector(mode=hub_mode, data_source=data_source, limitations=signal_limitations),
        tag_classifier=DeterministicTagSignalClassifier(mode=tag_mode, data_source=data_source, limitations=signal_limitations),
    )
