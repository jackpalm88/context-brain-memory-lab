"""Unit tests for the canonical evidence normalization ownership move.

normalize_evidence was moved out of memory_lab.reasoning.answer_synthesizer into
the neutral memory_lab.query.evidence module. These tests prove the old import
path and the new import path resolve to the same callable and produce identical
normalized evidence. Provider-free and DB-free.
"""
from __future__ import annotations

from memory_lab.query.evidence import normalize_evidence as normalize_new
from memory_lab.reasoning.answer_synthesizer import normalize_evidence as normalize_old


def _rows() -> list[dict]:
    return [
        {
            "content_id": "cid-001",
            "chunk_id": "chk-001",
            "text": "  first   chunk of   workspace text  ",
            "score": 0.81,
            "retrieval_path": "content_chunk_workspace_scoped",
            "title": "Doc One",
        },
        {
            "content_id": "cid-002",
            "chunk_id": None,
            "text": "hub-linked content body",
            "score": 0.42,
            "retrieval_path": "hub_link_workspace_scoped",
            "metadata": {"embedding_status": "ok", "distance": 0.19},
        },
        # duplicate content_id -> deduped away
        {
            "content_id": "cid-001",
            "chunk_id": "chk-009",
            "text": "second chunk of same content",
            "score": 0.50,
            "retrieval_path": "content_chunk_workspace_scoped",
        },
    ]


def test_old_and_new_import_paths_are_same_callable():
    assert normalize_old is normalize_new


def test_old_and_new_paths_produce_identical_evidence():
    rows = _rows()
    old = normalize_old(rows)
    new = normalize_new(rows)
    assert [e.model_dump() for e in old] == [e.model_dump() for e in new]


def test_limit_argument_behaves_identically():
    rows = _rows()
    old = normalize_old(rows, limit=12)
    new = normalize_new(rows, limit=12)
    assert [e.model_dump() for e in old] == [e.model_dump() for e in new]


def test_empty_input_identical():
    assert normalize_old([]) == normalize_new([])
