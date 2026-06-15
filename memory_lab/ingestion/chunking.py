"""Deterministic provider-free content chunking for B17 ingestion scaffolds.

The chunker in this module is intentionally local and mechanical. It does not
call providers, embeddings, stores, graph indexes, admin tools, or private
Context Brain services. It only splits caller-supplied text into stable
character-based chunks.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Sequence

from memory_lab.ingestion.interfaces import (
    ContentChunk,
    ContentChunkingResult,
    IngestionTextInput,
    SYNTHETIC_DATA_SOURCE,
)

DETERMINISTIC_CHUNKER_MODE = "deterministic_chunker_v1"
DEFAULT_TARGET_CHUNK_CHARS = 640
DEFAULT_MAX_CHUNK_CHARS = 900
DEFAULT_MIN_CHUNK_CHARS = 80
DEFAULT_OVERLAP_CHARS = 80
DEFAULT_MAX_CHUNKS_PER_ITEM = 1000


@dataclass(frozen=True)
class ChunkerConfig:
    """Deterministic character-based chunker settings."""

    target_chunk_chars: int = DEFAULT_TARGET_CHUNK_CHARS
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS
    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS
    overlap_chars: int = DEFAULT_OVERLAP_CHARS
    max_chunks_per_item: int = DEFAULT_MAX_CHUNKS_PER_ITEM

    def validate(self) -> None:
        if self.min_chunk_chars < 1:
            raise ValueError("min_chunk_chars must be positive")
        if self.target_chunk_chars < self.min_chunk_chars:
            raise ValueError("target_chunk_chars must be >= min_chunk_chars")
        if self.max_chunk_chars < self.target_chunk_chars:
            raise ValueError("max_chunk_chars must be >= target_chunk_chars")
        if self.overlap_chars < 0:
            raise ValueError("overlap_chars must be non-negative")
        if self.overlap_chars >= self.max_chunk_chars:
            raise ValueError("overlap_chars must be smaller than max_chunk_chars")
        if self.max_chunks_per_item < 1:
            raise ValueError("max_chunks_per_item must be positive")


@dataclass(frozen=True)
class _Boundary:
    position: int
    reason: str
    priority: int


class DeterministicContentChunker:
    """Provider-free deterministic content chunker.

    Boundary preference order:
    1. paragraph boundary
    2. single newline
    3. sentence punctuation
    4. list boundary
    5. whitespace boundary
    6. hard character boundary
    """

    def __init__(self, config: ChunkerConfig | None = None) -> None:
        self.config = config or ChunkerConfig()
        self.config.validate()

    def chunk_text(
        self,
        text: str,
        *,
        source_id: str = "syn-b17-input",
        source_case_id: str = "",
        data_source: str = SYNTHETIC_DATA_SOURCE,
    ) -> ContentChunkingResult:
        item = IngestionTextInput(
            text=text,
            item_id=source_id,
            metadata={"source_case_id": source_case_id} if source_case_id else {},
            data_source=data_source,
        )
        return self.chunk_content(item)

    def chunk_content(self, item: IngestionTextInput) -> ContentChunkingResult:
        text = _normalize_line_endings(item.text)
        data_source = item.data_source or SYNTHETIC_DATA_SOURCE
        source_case_id = str(item.metadata.get("source_case_id", ""))
        limitations = [
            "deterministic character chunker",
            "no provider calls",
            "no stored-record access",
            "no vector operation",
            "no mutation methods",
        ]

        if text == "":
            return self._result(
                chunks=(),
                data_source=data_source,
                degraded=True,
                limitations=tuple(limitations + ["empty_content"]),
                rationale="empty content produced zero chunks",
            )

        if text.strip() == "":
            return self._result(
                chunks=(),
                data_source=data_source,
                degraded=True,
                limitations=tuple(limitations + ["whitespace_only_content"]),
                rationale="whitespace-only content produced zero chunks",
            )

        chunks: list[ContentChunk] = []
        start = 0
        text_length = len(text)
        guard_hit = False

        while start < text_length:
            if len(chunks) >= self.config.max_chunks_per_item:
                guard_hit = True
                break

            end, boundary_reason = self._choose_end(text, start)
            if end <= start:
                end = min(text_length, start + self.config.max_chunk_chars)
                boundary_reason = "hard_boundary_guard"

            chunk_text = text[start:end]
            flags = self._quality_flags(chunk_text, text_length)
            if text_length <= self.config.max_chunk_chars:
                boundary_reason = "short_content_single_chunk" if len(chunk_text) < self.config.min_chunk_chars else "single_chunk_within_max"

            chunks.append(
                self._make_chunk(
                    source_id=item.item_id,
                    source_case_id=source_case_id,
                    index=len(chunks),
                    text=chunk_text,
                    char_start=start,
                    char_end=end,
                    data_source=data_source,
                    quality_flags=flags,
                    boundary_reason=boundary_reason,
                )
            )

            if end >= text_length:
                break

            next_start = max(0, end - self.config.overlap_chars)
            if next_start <= start:
                next_start = end
            start = next_start

        result_limitations = tuple(limitations + (["max_chunk_count_reached"] if guard_hit else []))
        return self._result(
            chunks=tuple(chunks),
            data_source=data_source,
            degraded=guard_hit,
            limitations=result_limitations,
            rationale="deterministic character chunking completed",
        )

    def _choose_end(self, text: str, start: int) -> tuple[int, str]:
        text_length = len(text)
        remaining = text_length - start
        if remaining <= self.config.max_chunk_chars:
            return text_length, "final_chunk"

        min_pos = min(text_length, start + self.config.min_chunk_chars)
        target_pos = min(text_length, start + self.config.target_chunk_chars)
        max_pos = min(text_length, start + self.config.max_chunk_chars)
        candidates = [
            boundary
            for boundary in _boundary_candidates(text, start, max_pos)
            if min_pos <= boundary.position <= max_pos
        ]

        for priority in range(1, 6):
            priority_candidates = [c for c in candidates if c.priority == priority]
            before_or_at = [c for c in priority_candidates if c.position <= target_pos]
            if before_or_at:
                chosen = max(before_or_at, key=lambda c: c.position)
                return chosen.position, chosen.reason
            after = [c for c in priority_candidates if c.position > target_pos]
            if after:
                chosen = min(after, key=lambda c: c.position)
                return chosen.position, chosen.reason

        return max_pos, "hard_character_boundary"

    def _make_chunk(
        self,
        *,
        source_id: str,
        source_case_id: str,
        index: int,
        text: str,
        char_start: int,
        char_end: int,
        data_source: str,
        quality_flags: Sequence[str],
        boundary_reason: str,
    ) -> ContentChunk:
        chunk_id = _chunk_id(source_id, index, char_start, char_end, text)
        return ContentChunk(
            chunk_id=chunk_id,
            text=text,
            order=index,
            index=index,
            char_start=char_start,
            char_end=char_end,
            char_count=len(text),
            source_id=source_id,
            source_case_id=source_case_id,
            quality_flags=tuple(quality_flags),
            boundary_reason=boundary_reason,
            mode=DETERMINISTIC_CHUNKER_MODE,
            data_source=data_source,
            degraded=False,
            limitations=("deterministic character chunk",),
        )

    def _quality_flags(self, chunk_text: str, source_length: int) -> tuple[str, ...]:
        flags: list[str] = []
        stripped = chunk_text.strip()
        if len(stripped) < self.config.min_chunk_chars:
            flags.append("short_content")
        alnum_count = sum(1 for ch in stripped if ch.isalnum())
        if stripped and alnum_count < max(12, len(stripped) // 5):
            flags.append("low_information_density_candidate")
        if source_length > self.config.max_chunk_chars:
            flags.append("split_from_long_content")
        flags.append("quality_not_scored_by_chunker")
        flags.append("duplicate_detection_not_performed")
        return tuple(flags)

    def _result(
        self,
        *,
        chunks: Sequence[ContentChunk],
        data_source: str,
        degraded: bool,
        limitations: Sequence[str],
        rationale: str,
    ) -> ContentChunkingResult:
        return ContentChunkingResult(
            chunks=tuple(chunks),
            confidence=1.0 if chunks and not degraded else 0.0,
            rationale=rationale,
            mode=DETERMINISTIC_CHUNKER_MODE,
            data_source=data_source,
            degraded=degraded,
            limitations=tuple(limitations),
        )


def make_deterministic_content_chunker(
    config: ChunkerConfig | None = None,
) -> DeterministicContentChunker:
    return DeterministicContentChunker(config=config)


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _boundary_candidates(text: str, start: int, max_pos: int) -> list[_Boundary]:
    window = text[start:max_pos]
    candidates: list[_Boundary] = []

    for match in re.finditer(r"\n\s*\n+", window):
        candidates.append(_Boundary(start + match.end(), "paragraph_boundary", 1))

    for match in re.finditer(r"\n", window):
        candidates.append(_Boundary(start + match.end(), "newline_boundary", 2))

    for match in re.finditer(r"(?:[.!?]\s+|[。！？])", window):
        candidates.append(_Boundary(start + match.end(), "sentence_boundary", 3))

    for match in re.finditer(r"\n\s*(?:[-*]|\d+[.])\s+", window):
        candidates.append(_Boundary(start + match.start(), "list_boundary", 4))

    for match in re.finditer(r"\s+", window):
        candidates.append(_Boundary(start + match.end(), "whitespace_boundary", 5))

    return candidates


def _chunk_id(source_id: str, index: int, char_start: int, char_end: int, text: str) -> str:
    digest_source = "\u241f".join(
        [source_id, str(len(text)), str(index), str(char_start), str(char_end), text]
    )
    digest12 = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
    return f"{source_id}:det-chunk-v1:{index:04d}:{char_start:06d}-{char_end:06d}:{digest12}"
