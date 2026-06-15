"""B17 deterministic mechanical chunk scorer tests."""

import re
from dataclasses import asdict
from pathlib import Path

import pytest

from memory_lab.ingestion.chunk_scoring import (
    DETERMINISTIC_CHUNK_SCORER_MODE,
    MECHANICAL_SCORE_KIND,
    DeterministicChunkScorer,
    make_deterministic_chunk_scorer,
)
from memory_lab.ingestion.chunking import make_deterministic_content_chunker
from memory_lab.ingestion.interfaces import ContentChunk

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

SCORER_PATH = Path(__file__).resolve().parents[2] / "memory_lab" / "ingestion" / "chunk_scoring.py"
INTERFACE_PATH = Path(__file__).resolve().parents[2] / "memory_lab" / "ingestion" / "interfaces.py"


def make_chunk(
    text: str,
    *,
    chunk_id: str = "syn-b17-source:det-chunk-v1:0000:000000-000100:abcdef123456",
    index: int = 0,
    char_start: int = 0,
    char_end: int | None = None,
    char_count: int | None = None,
    source_id: str = "syn-b17-source",
    boundary_reason: str = "paragraph_boundary",
    degraded: bool = False,
    limitations: tuple[str, ...] = ("deterministic character chunk",),
) -> ContentChunk:
    end = len(text) if char_end is None else char_end
    count = len(text) if char_count is None else char_count
    return ContentChunk(
        chunk_id=chunk_id,
        text=text,
        order=index,
        index=index,
        char_start=char_start,
        char_end=end,
        char_count=count,
        source_id=source_id,
        source_case_id="synthetic-test-case",
        quality_flags=("quality_not_scored_by_chunker", "duplicate_detection_not_performed"),
        boundary_reason=boundary_reason,
        mode="deterministic_chunker_v1",
        data_source="synthetic_fixture",
        degraded=degraded,
        limitations=limitations,
    )


def test_empty_content_score_is_blocked_non_claim_result():
    result = make_deterministic_chunk_scorer().score_chunk(make_chunk("", char_end=0, char_count=0))

    assert result.quality == 0.0
    assert result.composite == 0.0
    assert result.relevance == 0.0
    assert result.novelty == 0.0
    assert result.recommendation == "block"
    assert result.score_kind == MECHANICAL_SCORE_KIND
    assert "empty_chunk" in result.risk_flags
    assert result.mode == DETERMINISTIC_CHUNK_SCORER_MODE


def test_whitespace_only_score_is_blocked():
    result = make_deterministic_chunk_scorer().score_chunk(make_chunk("   \n\t   "))

    assert result.quality == 0.0
    assert result.recommendation == "block"
    assert "whitespace_only_chunk" in result.risk_flags


def test_short_note_score_is_mechanically_penalized_but_not_semantic():
    chunk = make_chunk("Short operational note.", boundary_reason="short_content_single_chunk")
    result = make_deterministic_chunk_scorer().score_chunk(chunk)

    assert 0.30 <= result.quality < 1.0
    assert result.recommendation in {"use_with_caution", "review"}
    assert "semantic" not in " ".join(result.risk_flags)
    assert result.signals["effective_char_count"] == len(chunk.text)


def test_long_document_chunks_score_deterministically_with_chunker_output():
    chunker = make_deterministic_content_chunker()
    text = "\n\n".join(
        f"Paragraph {i}. This synthetic section has enough plain text for a deterministic mechanical chunk."
        for i in range(80)
    )
    chunks = chunker.chunk_text(text, source_id="syn-b17-long", source_case_id="long document").chunks
    scorer = make_deterministic_chunk_scorer()
    first = scorer.score_chunks(chunks)
    second = scorer.score_chunks(chunks)

    assert len(chunks) > 1
    assert first == second
    assert all(0.0 <= result.quality <= 1.0 for result in first)
    assert all(result.score_kind == MECHANICAL_SCORE_KIND for result in first)
    assert all(result.relevance == 0.0 and result.novelty == 0.0 for result in first)


def test_mixed_language_content_does_not_require_language_understanding():
    text = "Latviešu teksts ar diakritiku. Русский текст. 日本語の短い文。 English sentence for mixed fixture."
    chunk = make_deterministic_content_chunker().chunk_text(
        text,
        source_id="syn-b17-mixed",
        source_case_id="mixed-language content",
    ).chunks[0]
    result = make_deterministic_chunk_scorer().score_chunk(chunk)

    assert result.quality > 0.0
    assert result.relevance == 0.0
    assert result.novelty == 0.0
    assert not any("language" in flag for flag in result.risk_flags)
    assert "no language understanding" in result.limitations


def test_repeated_duplicate_text_gets_mechanical_penalty_only():
    repeated = make_chunk(("alpha beta\n" * 40), boundary_reason="paragraph_boundary")
    normal = make_chunk(
        "This synthetic paragraph contains varied operational words, offsets, boundaries, and enough detail "
        "to avoid exact repeated token or line pattern penalties in the mechanical scorer.",
        boundary_reason="paragraph_boundary",
    )
    scorer = make_deterministic_chunk_scorer()
    repeated_result = scorer.score_chunk(repeated)
    normal_result = scorer.score_chunk(normal)

    assert repeated_result.quality < normal_result.quality
    assert "repeated_line_pattern" in repeated_result.risk_flags
    assert "no semantic duplicate detection" in repeated_result.limitations


def test_boundary_quality_scoring_prefers_stronger_boundaries():
    text = "This is a deterministic test chunk with enough length to avoid short-content penalties. " * 2
    strong = make_chunk(text, boundary_reason="paragraph_boundary")
    hard = make_chunk(text, boundary_reason="hard_character_boundary")
    unknown = make_chunk(text, boundary_reason="unknown_boundary")
    scorer = make_deterministic_chunk_scorer()

    strong_result = scorer.score_chunk(strong)
    hard_result = scorer.score_chunk(hard)
    unknown_result = scorer.score_chunk(unknown)

    assert strong_result.quality > hard_result.quality
    assert strong_result.quality > unknown_result.quality
    assert "weak_boundary_reason" in hard_result.risk_flags
    assert "unknown_boundary_reason" in unknown_result.risk_flags


def test_max_min_size_scoring_flags_too_short_and_over_max():
    scorer = make_deterministic_chunk_scorer()
    too_short = scorer.score_chunk(make_chunk("tiny", boundary_reason="short_content_single_chunk"))
    over_max_text = "word " * 190
    over_max = scorer.score_chunk(make_chunk(over_max_text, char_count=len(over_max_text)))

    assert too_short.quality < 0.60
    assert "very_short_chunk" in too_short.risk_flags
    assert over_max.quality < 0.80
    assert "chunk_exceeds_max_chars" in over_max.risk_flags


def test_deterministic_repeatability_for_same_chunk():
    chunk = make_chunk("Deterministic repeatability chunk with stable metadata and mechanical scoring only. " * 3)
    scorer = DeterministicChunkScorer()

    assert scorer.score_chunk(chunk) == scorer.score_chunk(chunk)


def test_batch_overlap_order_check_is_mechanical_only():
    first = make_chunk("First deterministic chunk with valid enough content. " * 3, index=0, char_start=0, char_end=150)
    second = make_chunk(
        "Second deterministic chunk with intentionally repeated index metadata. " * 3,
        index=0,
        char_start=10,
        char_end=180,
        chunk_id="syn-b17-source:det-chunk-v1:0001:000010-000180:abcdef123456",
    )

    results = make_deterministic_chunk_scorer().score_chunks((first, second))

    assert len(results) == 2
    assert all("non_monotonic_chunk_order" in result.risk_flags for result in results)
    assert all("excessive_chunk_overlap" in result.risk_flags for result in results)
    assert all(result.relevance == 0.0 and result.novelty == 0.0 for result in results)


def test_relevance_and_novelty_remain_non_claim_placeholders():
    result = make_deterministic_chunk_scorer().score_chunk(
        make_chunk("Mechanical scoring checks text shape and metadata only. " * 3)
    )
    data = asdict(result)

    assert data["relevance"] == 0.0
    assert data["novelty"] == 0.0
    assert "no semantic relevance" in data["limitations"]
    assert "no semantic novelty" in data["limitations"]


def test_source_has_no_provider_imports_or_calls():
    source = SCORER_PATH.read_text()
    forbidden_import_patterns = [
        r"^\s*import\s+(anthropic|openai|openrouter|requests|httpx)\b",
        r"^\s*from\s+(anthropic|openai|openrouter|requests|httpx)\b",
        r"^\s*from\s+memory_lab\.(providers|api|retrieval)\b",
        r"^\s*import\s+memory_lab\.(providers|api|retrieval)\b",
    ]
    for pattern in forbidden_import_patterns:
        assert not re.search(pattern, source, re.MULTILINE)


def test_source_has_no_db_private_cb_access():
    source = SCORER_PATH.read_text().lower()
    forbidden_patterns = [
        r"^\s*import\s+(psycopg|psycopg2|sqlalchemy)\b",
        r"^\s*from\s+(psycopg|psycopg2|sqlalchemy)\b",
        r"^\s*from\s+memory_lab\.(db|database)\b",
        r"^\s*import\s+memory_lab\.(db|database)\b",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, source, re.MULTILINE)
    forbidden_literals = ["postgres://", "postgresql://", "conting.superagents.solutions", "/opt/"]
    for literal in forbidden_literals:
        assert literal not in source


def test_source_has_no_embedding_backfill_knn_admin_methods():
    source = SCORER_PATH.read_text().lower()
    forbidden_runtime_terms = [
        "embedding_client",
        "embed_text",
        "backfill_embeddings",
        "knn_search",
        "create_index",
        "drop_index",
        "admin_client",
        "search_v2",
        "search-by-purpose",
    ]
    for term in forbidden_runtime_terms:
        assert term not in source


def test_interface_extension_is_narrow_for_score_metadata_only():
    source = INTERFACE_PATH.read_text()
    start = source.index("class ChunkScoringResult")
    end = source.index("class IngestionScoringResult")
    chunk_score_block = source[start:end]
    assert "score_kind: str" in chunk_score_block
    assert "signals: Mapping[str, object]" in chunk_score_block
    assert "risk_flags: Sequence[str]" in chunk_score_block
    assert "recommendation: str" in chunk_score_block
    forbidden_model_fields = ["domain_label", "hub_candidates", "embedding_id", "provider_metadata", "database_id"]
    for field in forbidden_model_fields:
        assert field not in chunk_score_block
