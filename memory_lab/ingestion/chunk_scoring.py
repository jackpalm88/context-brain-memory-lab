"""Deterministic mechanical chunk scoring for B17 ingestion scaffolds.

This module scores only local, caller-supplied ``ContentChunk`` objects. Scores
are deterministic mechanical quality/readiness checks, not semantic relevance,
semantic quality, novelty, embedding readiness, domain correctness, classifier
behavior, or production ingestion quality.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from memory_lab.ingestion.chunking import (
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_MIN_CHUNK_CHARS,
    DEFAULT_OVERLAP_CHARS,
)
from memory_lab.ingestion.interfaces import (
    ChunkScoringResult,
    ContentChunk,
    SYNTHETIC_DATA_SOURCE,
)

DETERMINISTIC_CHUNK_SCORER_MODE = "deterministic_chunk_scorer_v1"
MECHANICAL_SCORE_KIND = "mechanical_chunk_quality"

GOOD_THRESHOLD = 0.80
ACCEPTABLE_THRESHOLD = 0.60
WEAK_THRESHOLD = 0.30

STRONG_BOUNDARIES = {
    "paragraph_boundary",
    "sentence_boundary",
    "final_chunk",
    "single_chunk_within_max",
}
ACCEPTABLE_BOUNDARIES = {
    "newline_boundary",
    "list_boundary",
    "whitespace_boundary",
    "short_content_single_chunk",
}
WEAK_BOUNDARIES = {"hard_character_boundary"}
BLOCKING_BOUNDARIES = {"hard_boundary_guard"}

DEFAULT_SCORER_LIMITATIONS = (
    "deterministic mechanical chunk scoring only",
    "no semantic scoring",
    "no semantic relevance",
    "no semantic novelty",
    "no semantic duplicate detection",
    "no language understanding",
    "no provider-backed intelligence",
    "no embedding operation",
    "no stored-record access",
    "no mutation methods",
)


@dataclass(frozen=True)
class ChunkScorerConfig:
    """Deterministic mechanical scorer thresholds."""

    min_chunk_chars: int = DEFAULT_MIN_CHUNK_CHARS
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS
    expected_overlap_chars: int = DEFAULT_OVERLAP_CHARS

    def validate(self) -> None:
        if self.min_chunk_chars < 1:
            raise ValueError("min_chunk_chars must be positive")
        if self.max_chunk_chars < self.min_chunk_chars:
            raise ValueError("max_chunk_chars must be >= min_chunk_chars")
        if self.expected_overlap_chars < 0:
            raise ValueError("expected_overlap_chars must be non-negative")


class DeterministicChunkScorer:
    """Provider-free deterministic mechanical scorer for ``ContentChunk``."""

    def __init__(self, config: ChunkScorerConfig | None = None) -> None:
        self.config = config or ChunkScorerConfig()
        self.config.validate()

    def score_chunk(self, chunk: ContentChunk) -> ChunkScoringResult:
        """Score one chunk using only local mechanical signals."""

        signals = self._signals(chunk)
        risk_flags: list[str] = []
        penalties: list[float] = []

        text = chunk.text or ""
        if text == "":
            risk_flags.append("empty_chunk")
            return self._result(
                chunk=chunk,
                score=0.0,
                signals=signals,
                risk_flags=tuple(risk_flags),
                rationale="blocked: empty chunk text",
            )

        if text.strip() == "":
            risk_flags.append("whitespace_only_chunk")
            return self._result(
                chunk=chunk,
                score=0.0,
                signals=signals,
                risk_flags=tuple(risk_flags),
                rationale="blocked: whitespace-only chunk text",
            )

        char_count = _effective_char_count(chunk)
        if char_count < 20:
            penalties.append(0.50)
            risk_flags.append("very_short_chunk")
        elif char_count < self.config.min_chunk_chars:
            penalties.append(0.22)
            risk_flags.append("below_min_chunk_chars")
        elif char_count > self.config.max_chunk_chars:
            penalties.append(0.40)
            risk_flags.append("chunk_exceeds_max_chars")

        whitespace_ratio = float(signals["whitespace_ratio"])
        if whitespace_ratio > 0.70:
            penalties.append(0.35)
            risk_flags.append("high_whitespace_ratio")
        elif whitespace_ratio > 0.45:
            penalties.append(0.15)
            risk_flags.append("elevated_whitespace_ratio")

        alnum_ratio = float(signals["alnum_ratio"])
        if alnum_ratio < 0.20:
            penalties.append(0.30)
            risk_flags.append("low_information_density")
        elif alnum_ratio < 0.35:
            penalties.append(0.15)
            risk_flags.append("low_alnum_ratio")

        unique_token_ratio = float(signals["unique_token_ratio"])
        token_count = int(signals["token_count"])
        if token_count >= 8 and unique_token_ratio < 0.30:
            penalties.append(0.20)
            risk_flags.append("repeated_token_pattern")

        if bool(signals["has_repeated_line_pattern"]):
            penalties.append(0.20)
            risk_flags.append("repeated_line_pattern")
        if bool(signals["has_repeated_character_run"]):
            penalties.append(0.12)
            risk_flags.append("repeated_character_run")

        boundary_reason = chunk.boundary_reason or ""
        signals["boundary_quality"] = _boundary_quality(boundary_reason)
        if boundary_reason in WEAK_BOUNDARIES:
            penalties.append(0.16)
            risk_flags.append("weak_boundary_reason")
        elif boundary_reason in BLOCKING_BOUNDARIES:
            penalties.append(0.32)
            risk_flags.append("boundary_guard_used")
        elif not boundary_reason:
            penalties.append(0.18)
            risk_flags.append("missing_boundary_reason")
        elif boundary_reason not in STRONG_BOUNDARIES and boundary_reason not in ACCEPTABLE_BOUNDARIES:
            penalties.append(0.12)
            risk_flags.append("unknown_boundary_reason")

        risk_flags.extend(self._metadata_risks(chunk, signals))
        penalties.extend(_metadata_penalties(risk_flags))

        if chunk.degraded:
            penalties.append(0.12)
            risk_flags.append("chunk_degraded")

        non_default_limitations = tuple(
            limitation for limitation in chunk.limitations if limitation and limitation != "deterministic character chunk"
        )
        if non_default_limitations:
            penalties.append(min(0.18, 0.06 * len(non_default_limitations)))
            risk_flags.append("chunk_limitations_present")
            signals["chunk_limitation_count"] = len(non_default_limitations)
        else:
            signals["chunk_limitation_count"] = 0

        score = _clamp(1.0 - sum(penalties))
        if "invalid_char_offsets" in risk_flags or "missing_chunk_id" in risk_flags:
            score = min(score, 0.29)

        return self._result(
            chunk=chunk,
            score=score,
            signals=signals,
            risk_flags=tuple(_dedupe(risk_flags)),
            rationale="deterministic mechanical chunk scoring completed",
        )

    def score_chunks(self, chunks: Sequence[ContentChunk]) -> tuple[ChunkScoringResult, ...]:
        """Score chunks and apply local batch order/overlap penalties.

        Batch checks are mechanical only: index/order monotonicity and adjacent
        offset overlap shape. They do not detect semantic duplicates.
        """

        base_results = [self.score_chunk(chunk) for chunk in chunks]
        batch_risks = self._batch_risks(chunks)
        if not batch_risks:
            return tuple(base_results)

        adjusted: list[ChunkScoringResult] = []
        for result in base_results:
            risk_flags = tuple(_dedupe(tuple(result.risk_flags) + batch_risks))
            signals = dict(result.signals)
            signals["batch_risk_count"] = len(batch_risks)
            score = _clamp(result.quality - min(0.16, 0.08 * len(batch_risks)))
            adjusted.append(
                ChunkScoringResult(
                    chunk_id=result.chunk_id,
                    quality=score,
                    relevance=0.0,
                    novelty=0.0,
                    composite=score,
                    confidence=result.confidence,
                    rationale="deterministic mechanical chunk scoring completed with batch checks",
                    score_kind=MECHANICAL_SCORE_KIND,
                    signals=signals,
                    risk_flags=risk_flags,
                    recommendation=_recommendation(score),
                    mode=DETERMINISTIC_CHUNK_SCORER_MODE,
                    data_source=result.data_source,
                    degraded=result.degraded or score < WEAK_THRESHOLD,
                    limitations=result.limitations,
                )
            )
        return tuple(adjusted)

    def _signals(self, chunk: ContentChunk) -> dict[str, object]:
        text = chunk.text or ""
        length = len(text)
        stripped = text.strip()
        token_matches = re.findall(r"\w+", stripped.lower(), flags=re.UNICODE)
        unique_tokens = set(token_matches)
        line_values = [line.strip() for line in text.splitlines() if line.strip()]
        repeated_lines = len(line_values) >= 3 and len(set(line_values)) < len(line_values)

        return {
            "text_length": length,
            "char_count": chunk.char_count,
            "effective_char_count": _effective_char_count(chunk),
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "whitespace_ratio": _ratio(sum(1 for ch in text if ch.isspace()), length),
            "alnum_ratio": _ratio(sum(1 for ch in text if ch.isalnum()), length),
            "token_count": len(token_matches),
            "unique_token_ratio": _ratio(len(unique_tokens), len(token_matches)),
            "has_repeated_line_pattern": repeated_lines,
            "has_repeated_character_run": bool(re.search(r"(.)\1{9,}", text, flags=re.DOTALL)),
            "boundary_reason": chunk.boundary_reason,
            "quality_flag_count": len(tuple(chunk.quality_flags)),
            "metadata_complete": bool(chunk.chunk_id and chunk.source_id and chunk.boundary_reason),
        }

    def _metadata_risks(self, chunk: ContentChunk, signals: dict[str, object]) -> list[str]:
        risks: list[str] = []
        text_length = int(signals["text_length"])
        if not chunk.chunk_id:
            risks.append("missing_chunk_id")
        if not chunk.source_id:
            risks.append("missing_source_id")
        if not chunk.mode:
            risks.append("missing_mode")
        if not chunk.data_source:
            risks.append("missing_data_source")
        if chunk.char_count != text_length:
            risks.append("char_count_mismatch")
        if text_length > 0 and chunk.char_end <= chunk.char_start:
            risks.append("invalid_char_offsets")
        if chunk.char_start < 0 or chunk.char_end < 0:
            risks.append("negative_char_offsets")
        return risks

    def _batch_risks(self, chunks: Sequence[ContentChunk]) -> tuple[str, ...]:
        risks: list[str] = []
        previous: ContentChunk | None = None
        for expected_index, chunk in enumerate(chunks):
            if chunk.index != expected_index or chunk.order != expected_index:
                risks.append("non_monotonic_chunk_order")
            if previous is not None:
                if chunk.char_start < previous.char_start:
                    risks.append("non_monotonic_char_offsets")
                overlap = previous.char_end - chunk.char_start
                if overlap < 0:
                    risks.append("gap_between_adjacent_chunks")
                elif overlap > self.config.expected_overlap_chars + 1:
                    risks.append("excessive_chunk_overlap")
            previous = chunk
        return tuple(_dedupe(risks))

    def _result(
        self,
        *,
        chunk: ContentChunk,
        score: float,
        signals: dict[str, object],
        risk_flags: Sequence[str],
        rationale: str,
    ) -> ChunkScoringResult:
        recommendation = _recommendation(score)
        limitations = tuple(_dedupe(DEFAULT_SCORER_LIMITATIONS + tuple(chunk.limitations)))
        confidence = 1.0 if not any(flag.startswith("missing_") for flag in risk_flags) else 0.80
        return ChunkScoringResult(
            chunk_id=chunk.chunk_id,
            quality=score,
            relevance=0.0,
            novelty=0.0,
            composite=score,
            confidence=confidence,
            rationale=rationale,
            score_kind=MECHANICAL_SCORE_KIND,
            signals=dict(signals),
            risk_flags=tuple(_dedupe(risk_flags)),
            recommendation=recommendation,
            mode=DETERMINISTIC_CHUNK_SCORER_MODE,
            data_source=chunk.data_source or SYNTHETIC_DATA_SOURCE,
            degraded=score < WEAK_THRESHOLD or bool(risk_flags and recommendation == "block"),
            limitations=limitations,
        )


def make_deterministic_chunk_scorer(
    config: ChunkScorerConfig | None = None,
) -> DeterministicChunkScorer:
    """Factory for the deterministic mechanical chunk scorer."""

    return DeterministicChunkScorer(config=config)


def score_chunk(chunk: ContentChunk) -> ChunkScoringResult:
    """Convenience wrapper for scoring one chunk."""

    return make_deterministic_chunk_scorer().score_chunk(chunk)


def score_chunks(chunks: Sequence[ContentChunk]) -> tuple[ChunkScoringResult, ...]:
    """Convenience wrapper for scoring a sequence of chunks."""

    return make_deterministic_chunk_scorer().score_chunks(chunks)


def _effective_char_count(chunk: ContentChunk) -> int:
    return chunk.char_count if chunk.char_count else len(chunk.text or "")


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 6)


def _recommendation(score: float) -> str:
    if score >= GOOD_THRESHOLD:
        return "use"
    if score >= ACCEPTABLE_THRESHOLD:
        return "use_with_caution"
    if score >= WEAK_THRESHOLD:
        return "review"
    return "block"


def _boundary_quality(boundary_reason: str) -> str:
    if boundary_reason in STRONG_BOUNDARIES:
        return "strong"
    if boundary_reason in ACCEPTABLE_BOUNDARIES:
        return "acceptable"
    if boundary_reason in WEAK_BOUNDARIES:
        return "weak"
    if boundary_reason in BLOCKING_BOUNDARIES:
        return "blocked"
    return "missing_or_unknown"


def _metadata_penalties(risk_flags: Sequence[str]) -> list[float]:
    penalties: list[float] = []
    for flag in risk_flags:
        if flag in {"missing_chunk_id", "invalid_char_offsets", "negative_char_offsets"}:
            penalties.append(0.40)
        elif flag == "char_count_mismatch":
            penalties.append(0.24)
        elif flag in {"missing_source_id", "missing_mode", "missing_data_source"}:
            penalties.append(0.08)
    return penalties


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)
