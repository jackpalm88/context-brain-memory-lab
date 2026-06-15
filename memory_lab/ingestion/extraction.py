"""Deterministic noop content extractor for the B17 ingestion foundation.

This module intentionally provides no real content extraction intelligence. It is
provider-free, DB-free, embedding-free, mutation-free, and public-safe. The
extractor only establishes a local supplied-text boundary for future ingestion
flows that need a ``ContentExtractionResult`` before deterministic chunking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from memory_lab.ingestion.interfaces import (
    DEFAULT_LIMITATIONS,
    SYNTHETIC_DATA_SOURCE,
    ContentExtractionResult,
    IngestionTextInput,
)

NOOP_EXTRACTOR_MODE = "noop_extractor_v1"
NOOP_EXTRACTOR_LIMITATIONS: Sequence[str] = DEFAULT_LIMITATIONS + (
    "noop content extractor only",
    "no real content extraction",
    "no semantic extraction",
    "no entity extraction",
    "no fact extraction",
    "no summarization",
    "no document parsing beyond supplied text",
    "no provider calls",
    "no DB/private Context Brain access",
    "no embeddings or vector operations",
)


@dataclass(frozen=True)
class NoopContentExtractor:
    """Deterministic noop/identity content extractor.

    Non-whitespace caller-supplied text is preserved unchanged. Empty or
    whitespace-only text returns an explicit empty extracted text result. The
    component does not inspect title, metadata, source identifiers, stored
    records, providers, embeddings, chunkers, or graph state to infer content.
    """

    mode: str = NOOP_EXTRACTOR_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = NOOP_EXTRACTOR_LIMITATIONS

    def extract_content(self, item: IngestionTextInput) -> ContentExtractionResult:
        """Return a degraded noop extraction result for supplied in-memory text."""

        extracted_text = "" if item.text.strip() == "" else item.text
        return ContentExtractionResult(
            extracted_text=extracted_text,
            fields={},
            confidence=0.0,
            rationale="noop extractor preserves caller-supplied text only",
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            degraded=True,
            limitations=self.limitations,
        )


def make_noop_content_extractor(
    *,
    mode: str = NOOP_EXTRACTOR_MODE,
    data_source: str = SYNTHETIC_DATA_SOURCE,
    limitations: Sequence[str] = NOOP_EXTRACTOR_LIMITATIONS,
) -> NoopContentExtractor:
    """Create a deterministic noop content extractor with boundary defaults."""

    return NoopContentExtractor(
        mode=mode,
        data_source=data_source,
        limitations=limitations,
    )
