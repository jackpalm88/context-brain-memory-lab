"""M11C-2-2 raw chunk result diagnostics parity tests.

Focused, provider-free, DB-free tests for per-result diagnostics only.
Diagnostics must describe retrieval; they must not influence retrieval, ranking,
scoring, or graph expansion.
"""
from __future__ import annotations

import pytest

from memory_lab.reasoning.answer_synthesizer import normalize_evidence
from memory_lab.reasoning.models import EvidenceItem

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


DIAGNOSTIC_FIELDS = (
    "retrieval_reason",
    "ranking_reason",
    "hub_match",
    "graph_match",
    "knowledge_path",
    "score_components",
    "distance",
)


def test_evidence_item_exposes_raw_chunk_diagnostics_fields():
    for field in DIAGNOSTIC_FIELDS:
        assert field in EvidenceItem.model_fields, f"EvidenceItem missing M11C-2-2 field: {field}"


def test_normalize_evidence_surfaces_per_result_diagnostics_without_losing_metadata():
    rows = [
        {
            "content_id": "diag-cid-1",
            "chunk_id": "diag-chunk-1",
            "text": "alpha diagnostics chunk text",
            "score": 0.87,
            "distance": 0.13,
            "retrieval_path": "pgvector_knn",
            "retrieval_mode": "pgvector_knn",
            "embedding_status": "ok",
            "hub_match": {"hub_id": "hub-1", "title": "Alpha Hub"},
            "graph_match": {"matched": True, "path_count": 1},
            "knowledge_path": ["query", "chunk:diag-chunk-1"],
            "retrieval_reason": "Matched by pgvector nearest-neighbor search.",
            "ranking_reason": "Rank preserved from existing retrieval adapter order.",
            "score_components": {
                "base_score": 0.87,
                "distance": 0.13,
                "retrieval_path": "pgvector_knn",
            },
            "metadata": {"existing_provenance": "preserved"},
        }
    ]

    evidence = normalize_evidence(rows)
    item = evidence[0]

    assert item.retrieval_reason == "Matched by pgvector nearest-neighbor search."
    assert item.ranking_reason == "Rank preserved from existing retrieval adapter order."
    assert item.hub_match == {"hub_id": "hub-1", "title": "Alpha Hub"}
    assert item.graph_match == {"matched": True, "path_count": 1}
    assert item.knowledge_path == ["query", "chunk:diag-chunk-1"]
    assert item.score_components == {
        "base_score": 0.87,
        "distance": 0.13,
        "retrieval_path": "pgvector_knn",
    }
    assert item.distance == 0.13
    assert item.retrieval_path == "pgvector_knn"
    assert item.metadata["existing_provenance"] == "preserved"
    assert item.metadata["hub_match"] == {"hub_id": "hub-1", "title": "Alpha Hub"}
    assert item.metadata["distance"] == 0.13


def test_normalize_evidence_derives_safe_defaults_for_existing_rows():
    rows = [
        {
            "content_id": "diag-cid-2",
            "chunk_id": "diag-chunk-2",
            "text": "beta deterministic chunk text",
            "score": 0.7,
            "retrieval_path": "content_chunk_workspace_scoped",
        }
    ]

    item = normalize_evidence(rows)[0]

    assert item.retrieval_reason == "Matched chunk text in workspace-scoped deterministic retrieval."
    assert item.ranking_reason == "Rank preserves the existing retrieval adapter order; diagnostics did not rerank."
    assert item.hub_match is None
    assert item.graph_match is None
    assert item.knowledge_path == [
        {"type": "retrieval_path", "value": "content_chunk_workspace_scoped"},
        {"type": "content", "value": "diag-cid-2"},
        {"type": "chunk", "value": "diag-chunk-2"},
    ]
    assert item.score_components == {
        "score": 0.7,
        "score_kind": "chunk_text_match",
        "retrieval_path": "content_chunk_workspace_scoped",
        "diagnostic_only": True,
    }
    assert item.distance is None


def test_diagnostics_do_not_change_dedup_or_rank_order():
    rows = [
        {
            "content_id": "diag-first",
            "chunk_id": "chunk-a",
            "text": "first result remains first",
            "score": 0.1,
            "retrieval_path": "content_chunk_workspace_scoped",
            "ranking_reason": "diagnostic only",
        },
        {
            "content_id": "diag-second",
            "chunk_id": "chunk-b",
            "text": "second result remains second",
            "score": 0.99,
            "retrieval_path": "content_chunk_workspace_scoped",
            "score_components": {"score": 0.99, "diagnostic_only": True},
        },
        {
            "content_id": "diag-first",
            "chunk_id": "chunk-duplicate",
            "text": "duplicate remains deduped",
            "score": 1.0,
            "retrieval_path": "hub_link_workspace_scoped",
        },
    ]

    evidence = normalize_evidence(rows)

    assert [item.content_id for item in evidence] == ["diag-first", "diag-second"]
    assert [item.rank for item in evidence] == [1, 2]
    assert evidence[0].score == 0.1
    assert evidence[1].score == 0.99


def test_model_dump_includes_top_level_diagnostics_for_retrieval_envelope():
    item = normalize_evidence(
        [
            {
                "content_id": "diag-cid-3",
                "chunk_id": "diag-chunk-3",
                "text": "gamma hub-linked chunk",
                "score": 0.95,
                "retrieval_path": "hub_link_workspace_scoped",
                "hub_match": "hub-3",
            }
        ]
    )[0]

    dumped = item.model_dump()
    for field in DIAGNOSTIC_FIELDS:
        assert field in dumped
    assert dumped["hub_match"] == "hub-3"
    assert dumped["retrieval_path"] == "hub_link_workspace_scoped"
