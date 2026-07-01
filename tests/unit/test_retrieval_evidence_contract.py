"""Unit tests for the retrieval evidence contract.

Validates that normalize_evidence() produces EvidenceItem objects
with all required contract fields, deterministic evidence_id, correct
rank ordering, content-level deduplication, and correct score_kind.
All tests are provider-free and DB-free.
"""
from __future__ import annotations

import pytest

from memory_lab.reasoning.answer_synthesizer import normalize_evidence
from memory_lab.reasoning.models import Citation, EvidenceItem


def _row(
    content_id: str,
    chunk_id: str | None,
    text: str,
    score: float = 0.8,
    retrieval_path: str = "content_chunk_workspace_scoped",
    title: str | None = None,
) -> dict:
    row: dict = {
        "content_id": content_id,
        "chunk_id": chunk_id,
        "text": text,
        "score": score,
        "retrieval_path": retrieval_path,
    }
    if title is not None:
        row["title"] = title
    return row


# ---------------------------------------------------------------------------
# EvidenceItem field contract
# ---------------------------------------------------------------------------

class TestEvidenceItemFields:
    def test_all_required_fields_present(self):
        required = (
            "evidence_id", "rank", "content_id", "chunk_id",
            "snippet", "score", "score_kind", "retrieval_path",
            "source", "title", "metadata",
        )
        fields = EvidenceItem.model_fields
        for f in required:
            assert f in fields, f"EvidenceItem missing contract field: {f}"

    def test_chunk_id_nullable(self):
        e = EvidenceItem(
            evidence_id="ev_x_y", rank=1, content_id="x", snippet="s",
            score_kind="chunk_text_match", retrieval_path="content_chunk_workspace_scoped",
        )
        assert e.chunk_id is None

    def test_source_nullable(self):
        e = EvidenceItem(
            evidence_id="ev_x_y", rank=1, content_id="x", snippet="s",
            score_kind="chunk_text_match", retrieval_path="content_chunk_workspace_scoped",
        )
        assert e.source is None

    def test_title_nullable(self):
        e = EvidenceItem(
            evidence_id="ev_x_y", rank=1, content_id="x", snippet="s",
            score_kind="chunk_text_match", retrieval_path="content_chunk_workspace_scoped",
        )
        assert e.title is None

    def test_metadata_nullable(self):
        e = EvidenceItem(
            evidence_id="ev_x_y", rank=1, content_id="x", snippet="s",
            score_kind="chunk_text_match", retrieval_path="content_chunk_workspace_scoped",
        )
        assert e.metadata is None


# ---------------------------------------------------------------------------
# Deterministic evidence_id
# ---------------------------------------------------------------------------

class TestDeterministicEvidenceId:
    def test_chunk_backed_format(self):
        rows = [_row("cid-001", "chk-001", "some text about memory")]
        evidence = normalize_evidence(rows)
        assert evidence[0].evidence_id == "ev_cid-001_chk-001"

    def test_no_chunk_format(self):
        rows = [_row("cid-002", None, "hub-linked content", retrieval_path="hub_link_workspace_scoped")]
        evidence = normalize_evidence(rows)
        assert evidence[0].evidence_id == "ev_cid-002_hub_link_workspace_scoped_1"

    def test_evidence_id_is_deterministic_across_calls(self):
        rows = [_row("cid-003", "chk-003", "deterministic content")]
        e1 = normalize_evidence(rows)
        e2 = normalize_evidence(rows)
        assert e1[0].evidence_id == e2[0].evidence_id

    def test_no_chunk_rank_embedded_in_id(self):
        rows = [
            _row("cid-a", None, "first no-chunk", retrieval_path="hub_link_workspace_scoped"),
            _row("cid-b", None, "second no-chunk", retrieval_path="hub_link_workspace_scoped"),
        ]
        evidence = normalize_evidence(rows)
        assert evidence[0].evidence_id == "ev_cid-a_hub_link_workspace_scoped_1"
        assert evidence[1].evidence_id == "ev_cid-b_hub_link_workspace_scoped_2"


# ---------------------------------------------------------------------------
# Rank
# ---------------------------------------------------------------------------

class TestRank:
    def test_rank_starts_at_one(self):
        rows = [_row("cid-001", "chk-001", "first item")]
        evidence = normalize_evidence(rows)
        assert evidence[0].rank == 1

    def test_rank_is_sequential(self):
        rows = [
            _row("cid-001", "chk-001", "first item"),
            _row("cid-002", "chk-002", "second item"),
            _row("cid-003", "chk-003", "third item"),
        ]
        evidence = normalize_evidence(rows)
        assert [e.rank for e in evidence] == [1, 2, 3]

    def test_rank_is_int(self):
        rows = [_row("cid-001", "chk-001", "text")]
        evidence = normalize_evidence(rows)
        assert isinstance(evidence[0].rank, int)


# ---------------------------------------------------------------------------
# Content-level deduplication
# ---------------------------------------------------------------------------

class TestContentLevelDedupe:
    def test_duplicate_content_ids_yield_one_item(self):
        rows = [
            _row("cid-dup", "chk-001", "first chunk of same content"),
            _row("cid-dup", "chk-002", "second chunk of same content"),
        ]
        evidence = normalize_evidence(rows)
        assert len(evidence) == 1

    def test_different_content_ids_not_deduped(self):
        rows = [
            _row("cid-001", "chk-001", "content one"),
            _row("cid-002", "chk-002", "content two"),
        ]
        evidence = normalize_evidence(rows)
        assert len(evidence) == 2

    def test_dedupe_keeps_first_occurrence(self):
        rows = [
            _row("cid-dup", "chk-001", "first chunk text"),
            _row("cid-dup", "chk-002", "second chunk text"),
        ]
        evidence = normalize_evidence(rows)
        assert evidence[0].chunk_id == "chk-001"
        assert evidence[0].snippet == "first chunk text"

    def test_rank_after_dedupe_stays_sequential(self):
        rows = [
            _row("cid-001", "chk-001", "keep this"),
            _row("cid-001", "chk-002", "skip this duplicate"),
            _row("cid-002", "chk-003", "keep this too"),
        ]
        evidence = normalize_evidence(rows)
        assert len(evidence) == 2
        assert [e.rank for e in evidence] == [1, 2]


# ---------------------------------------------------------------------------
# score_kind
# ---------------------------------------------------------------------------

class TestScoreKind:
    def test_chunk_path_gives_chunk_text_match(self):
        rows = [_row("cid-001", "chk-001", "text", retrieval_path="content_chunk_workspace_scoped")]
        evidence = normalize_evidence(rows)
        assert evidence[0].score_kind == "chunk_text_match"

    def test_hub_path_gives_hub_link(self):
        rows = [_row("cid-001", None, "text", retrieval_path="hub_link_workspace_scoped")]
        evidence = normalize_evidence(rows)
        assert evidence[0].score_kind == "hub_link"

    def test_score_kind_is_string(self):
        rows = [_row("cid-001", "chk-001", "text")]
        evidence = normalize_evidence(rows)
        assert isinstance(evidence[0].score_kind, str)


# ---------------------------------------------------------------------------
# Snippet normalization
# ---------------------------------------------------------------------------

class TestSnippetNormalization:
    def test_whitespace_normalized(self):
        rows = [_row("cid-001", "chk-001", "text  with   extra   spaces")]
        evidence = normalize_evidence(rows)
        assert evidence[0].snippet == "text with extra spaces"

    def test_long_snippet_truncated_to_limit(self):
        long_text = "word " * 100
        rows = [_row("cid-001", "chk-001", long_text)]
        evidence = normalize_evidence(rows, limit=50)
        assert len(evidence[0].snippet) <= 50

    def test_truncated_snippet_ends_with_ellipsis(self):
        long_text = "x " * 500
        rows = [_row("cid-001", "chk-001", long_text)]
        evidence = normalize_evidence(rows, limit=50)
        assert evidence[0].snippet.endswith("…")

    def test_short_snippet_not_truncated(self):
        rows = [_row("cid-001", "chk-001", "short text")]
        evidence = normalize_evidence(rows, limit=320)
        assert evidence[0].snippet == "short text"


# ---------------------------------------------------------------------------
# Rows with missing or empty fields
# ---------------------------------------------------------------------------

class TestRowsWithMissingFields:
    def test_row_without_content_id_skipped(self):
        rows = [{"chunk_id": "chk-001", "text": "some text", "score": 0.8,
                 "retrieval_path": "content_chunk_workspace_scoped"}]
        evidence = normalize_evidence(rows)
        assert len(evidence) == 0

    def test_row_without_text_skipped(self):
        rows = [{"content_id": "cid-001", "chunk_id": "chk-001", "score": 0.8,
                 "retrieval_path": "content_chunk_workspace_scoped"}]
        evidence = normalize_evidence(rows)
        assert len(evidence) == 0

    def test_row_with_whitespace_only_text_skipped(self):
        rows = [{"content_id": "cid-001", "chunk_id": "chk-001", "text": "   ",
                 "score": 0.8, "retrieval_path": "content_chunk_workspace_scoped"}]
        evidence = normalize_evidence(rows)
        assert len(evidence) == 0

    def test_empty_results_returns_empty_list(self):
        evidence = normalize_evidence([])
        assert evidence == []

    def test_row_missing_retrieval_path_uses_default(self):
        rows = [{"content_id": "cid-001", "chunk_id": "chk-001", "text": "text", "score": 0.8}]
        evidence = normalize_evidence(rows)
        assert len(evidence) == 1
        assert evidence[0].retrieval_path == "deterministic_db"


# ---------------------------------------------------------------------------
# Citation contract: evidence_id + rank
# ---------------------------------------------------------------------------

class TestCitationContract:
    def test_citation_has_evidence_id(self):
        fields = Citation.model_fields
        assert "evidence_id" in fields

    def test_citation_has_rank(self):
        fields = Citation.model_fields
        assert "rank" in fields

    def test_citation_rank_matches_evidence_rank(self):
        from memory_lab.reasoning.answer_synthesizer import synthesize_answer
        from memory_lab.reasoning.intent_detector import detect_intent
        from memory_lab.reasoning.models import AskRequest
        from memory_lab.reasoning.policy_generator import policy_for_intent

        rows = [
            _row("cid-001", "chk-001", "some useful workspace evidence about the topic"),
            _row("cid-002", "chk-002", "more workspace evidence related to the question"),
        ]
        evidence = normalize_evidence(rows)
        req = AskRequest(query="what is the topic", top_k=5)
        detection = detect_intent(req.normalized_query())
        policy = policy_for_intent(detection.intent, req.top_k)
        response = synthesize_answer(
            request=req,
            detection=detection,
            policy=policy,
            evidence=evidence,
            workspace_id="test-ws",
        )
        for citation in response.citations:
            matching = [e for e in evidence if e.evidence_id == citation.evidence_id]
            assert len(matching) == 1
            assert citation.rank == matching[0].rank

    def test_citation_evidence_id_matches_evidence(self):
        from memory_lab.reasoning.answer_synthesizer import synthesize_answer
        from memory_lab.reasoning.intent_detector import detect_intent
        from memory_lab.reasoning.models import AskRequest
        from memory_lab.reasoning.policy_generator import policy_for_intent

        rows = [_row("cid-001", "chk-001", "workspace evidence text about the question asked")]
        evidence = normalize_evidence(rows)
        req = AskRequest(query="what is the question", top_k=5)
        detection = detect_intent(req.normalized_query())
        policy = policy_for_intent(detection.intent, req.top_k)
        response = synthesize_answer(
            request=req,
            detection=detection,
            policy=policy,
            evidence=evidence,
            workspace_id="test-ws",
        )
        assert len(response.citations) == 1
        assert response.citations[0].evidence_id == evidence[0].evidence_id


# ---------------------------------------------------------------------------
# Retrieval provenance metadata
# ---------------------------------------------------------------------------

class TestRetrievalProvenanceMetadata:
    def test_normalized_evidence_preserves_retrieval_provenance(self):
        rows = [
            _row(
                "cid-pgv",
                "chk-pgv",
                "pgvector-backed workspace evidence",
                score=0.91,
                retrieval_path="pgvector_knn",
            ) | {
                "retrieval_mode": "pgvector_knn",
                "embedding_status": "ok",
                "distance": 0.123,
                "score_kind": "vector_similarity",
            }
        ]

        evidence = normalize_evidence(rows)

        assert evidence[0].score_kind == "vector_similarity"
        assert evidence[0].retrieval_path == "pgvector_knn"
        assert evidence[0].metadata == {
            "retrieval_mode": "pgvector_knn",
            "retrieval_path": "pgvector_knn",
            "embedding_status": "ok",
            "distance": 0.123,
            "score_kind": "vector_similarity",
        }

    def test_normalized_evidence_preserves_existing_metadata(self):
        rows = [
            _row("cid-fallback", "chk-fallback", "fallback evidence")
            | {
                "retrieval_mode": "deterministic_fallback",
                "embedding_status": "provider_disabled",
                "metadata": {"existing": "kept"},
            }
        ]

        evidence = normalize_evidence(rows)

        assert evidence[0].metadata["existing"] == "kept"
        assert evidence[0].metadata["retrieval_mode"] == "deterministic_fallback"
        assert evidence[0].metadata["retrieval_path"] == "content_chunk_workspace_scoped"
        assert evidence[0].metadata["embedding_status"] == "provider_disabled"
        assert evidence[0].metadata["score_kind"] == "chunk_text_match"

    def test_normalized_evidence_preserves_hub_match_with_existing_metadata(self):
        rows = [
            _row(
                "cid-hub",
                None,
                "hub-linked workspace evidence",
                retrieval_path="hub_link_workspace_scoped",
            )
            | {
                "hub_match": "hub-123",
                "retrieval_mode": "hub_linked",
                "metadata": {"existing": "kept"},
            }
        ]

        evidence = normalize_evidence(rows)

        assert evidence[0].metadata["existing"] == "kept"
        assert evidence[0].metadata["hub_match"] == "hub-123"
        assert evidence[0].metadata["retrieval_mode"] == "hub_linked"
        assert evidence[0].metadata["retrieval_path"] == "hub_link_workspace_scoped"
        assert evidence[0].metadata["score_kind"] == "hub_link"
