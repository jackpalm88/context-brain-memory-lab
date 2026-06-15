"""Provider-neutral B17 ingestion interface scaffold.

This module defines public-safe, deterministic/noop contracts for future B17
intake intelligence work. It intentionally does not implement real domain
classification, hub detection, tag classification, extraction, chunking, chunk
scoring, ingestion scoring, provider-backed intelligence, vector operations,
stored-record access, or mutation behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

NOOP_MODE = "noop_scaffold"
SYNTHETIC_DATA_SOURCE = "synthetic_or_caller_supplied_text"
DEFAULT_LIMITATIONS = (
    "deterministic scaffold only",
    "no real classifier",
    "no real chunker",
    "no external service calls",
    "no stored-record access",
    "no vector operation",
    "no mutation methods",
)


@dataclass(frozen=True)
class IngestionTextInput:
    """Shared text input schema for provider-neutral scaffold contracts."""

    text: str
    item_id: str = "syn-b17-input"
    title: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)
    data_source: str = SYNTHETIC_DATA_SOURCE


@dataclass(frozen=True)
class ScaffoldOutputBase:
    """Common output boundary fields used by every scaffold result."""

    mode: str = NOOP_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    degraded: bool = True
    limitations: Sequence[str] = DEFAULT_LIMITATIONS


@dataclass(frozen=True)
class DomainClassificationResult(ScaffoldOutputBase):
    domain: str = "unknown"
    confidence: float = 0.0
    rationale: str = "noop scaffold does not classify domains"


@dataclass(frozen=True)
class HubDetectionResult(ScaffoldOutputBase):
    hub_candidates: Sequence[str] = field(default_factory=tuple)
    confidence: float = 0.0
    rationale: str = "noop scaffold does not detect hubs"


@dataclass(frozen=True)
class TagClassificationResult(ScaffoldOutputBase):
    tags: Sequence[str] = field(default_factory=tuple)
    confidence: float = 0.0
    rationale: str = "noop scaffold does not classify tags"


@dataclass(frozen=True)
class ContentExtractionResult(ScaffoldOutputBase):
    extracted_text: str = ""
    fields: Mapping[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    rationale: str = "noop scaffold returns caller text only"


@dataclass(frozen=True)
class ContentChunk:
    chunk_id: str
    text: str
    order: int
    index: int = 0
    char_start: int = 0
    char_end: int = 0
    char_count: int = 0
    source_id: str = ""
    source_case_id: str = ""
    quality_flags: Sequence[str] = field(default_factory=tuple)
    boundary_reason: str = ""
    mode: str = NOOP_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    degraded: bool = True
    limitations: Sequence[str] = DEFAULT_LIMITATIONS


@dataclass(frozen=True)
class ContentChunkingResult(ScaffoldOutputBase):
    chunks: Sequence[ContentChunk] = field(default_factory=tuple)
    confidence: float = 0.0
    rationale: str = "noop scaffold preserves input as at most one sample chunk"


@dataclass(frozen=True)
class ChunkScoringResult(ScaffoldOutputBase):
    chunk_id: str = ""
    quality: float = 0.0
    relevance: float = 0.0
    novelty: float = 0.0
    composite: float = 0.0
    confidence: float = 0.0
    rationale: str = "noop scaffold does not score chunks"
    score_kind: str = "not_evaluated"
    signals: Mapping[str, object] = field(default_factory=dict)
    risk_flags: Sequence[str] = field(default_factory=tuple)
    recommendation: str = "not_evaluated"


@dataclass(frozen=True)
class IngestionScoringResult(ScaffoldOutputBase):
    quality: float = 0.0
    relevance: float = 0.0
    novelty: float = 0.0
    composite: float = 0.0
    confidence: float = 0.0
    tier_decision: str = "not_evaluated"
    rationale: str = "noop scaffold does not score ingestion quality"


class DomainClassifier(Protocol):
    def classify_domain(self, item: IngestionTextInput) -> DomainClassificationResult:
        """Return a domain classification result for caller-supplied text."""


class HubDetector(Protocol):
    def detect_hubs(self, item: IngestionTextInput) -> HubDetectionResult:
        """Return hub candidate detection result for caller-supplied text."""


class TagClassifier(Protocol):
    def classify_tags(self, item: IngestionTextInput) -> TagClassificationResult:
        """Return tag classification result for caller-supplied text."""


class ContentExtractor(Protocol):
    def extract_content(self, item: IngestionTextInput) -> ContentExtractionResult:
        """Return extracted content for caller-supplied text."""


class ContentChunker(Protocol):
    def chunk_content(self, item: IngestionTextInput) -> ContentChunkingResult:
        """Return chunking result for caller-supplied text."""


class ChunkScorer(Protocol):
    def score_chunk(self, chunk: ContentChunk) -> ChunkScoringResult:
        """Return chunk score result for a caller-supplied chunk."""


class IngestionScorer(Protocol):
    def score_ingestion(self, item: IngestionTextInput) -> IngestionScoringResult:
        """Return ingestion score result for caller-supplied text."""


@dataclass(frozen=True)
class NoopIngestionInterfaceScaffold:
    """Deterministic provider-neutral implementation of all seven contracts."""

    mode: str = NOOP_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = DEFAULT_LIMITATIONS

    def classify_domain(self, item: IngestionTextInput) -> DomainClassificationResult:
        return DomainClassificationResult(
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            limitations=self.limitations,
        )

    def detect_hubs(self, item: IngestionTextInput) -> HubDetectionResult:
        return HubDetectionResult(
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            limitations=self.limitations,
        )

    def classify_tags(self, item: IngestionTextInput) -> TagClassificationResult:
        return TagClassificationResult(
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            limitations=self.limitations,
        )

    def extract_content(self, item: IngestionTextInput) -> ContentExtractionResult:
        return ContentExtractionResult(
            extracted_text=item.text,
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            limitations=self.limitations,
        )

    def chunk_content(self, item: IngestionTextInput) -> ContentChunkingResult:
        if not item.text:
            chunks: Sequence[ContentChunk] = ()
        else:
            chunks = (
                ContentChunk(
                    chunk_id=f"{item.item_id}:noop-chunk-0001",
                    text=item.text,
                    order=0,
                    mode=self.mode,
                    data_source=item.data_source or self.data_source,
                    limitations=self.limitations,
                ),
            )
        return ContentChunkingResult(
            chunks=chunks,
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            limitations=self.limitations,
        )

    def score_chunk(self, chunk: ContentChunk) -> ChunkScoringResult:
        return ChunkScoringResult(
            chunk_id=chunk.chunk_id,
            mode=self.mode,
            data_source=chunk.data_source or self.data_source,
            limitations=self.limitations,
        )

    def score_ingestion(self, item: IngestionTextInput) -> IngestionScoringResult:
        return IngestionScoringResult(
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            limitations=self.limitations,
        )


def make_noop_ingestion_interface() -> NoopIngestionInterfaceScaffold:
    """Factory for the deterministic provider-neutral scaffold."""

    return NoopIngestionInterfaceScaffold()


def fixture_to_input(fixture: Mapping[str, object]) -> IngestionTextInput:
    """Convert a synthetic fixture mapping into scaffold input.

    The function trusts only caller-supplied in-memory data and performs no I/O.
    """

    return IngestionTextInput(
        text=str(fixture.get("text", "")),
        item_id=str(fixture.get("id", "syn-b17-input")),
        title=str(fixture.get("title", "")),
        metadata={"case": str(fixture.get("case", ""))},
        data_source="synthetic_fixture",
    )
