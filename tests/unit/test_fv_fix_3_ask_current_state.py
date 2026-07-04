"""Unit tests — FV-FIX-3 ask current-state awareness.

/v1/ask evidence is enriched with resolver-owned is_current /
current_state_scope / cs_supersedes_content_id and a stable in-scope
preference is applied: superseded items sink below the current item of
the same scope. Historical questions keep the original order. Retrieval
and ranking are untouched; enrichment is best-effort.

Pure-Python; no DB; no provider calls.
"""

import pytest

import memory_lab.query.current_state_enrichment as cse
from memory_lab.query.current_state_enrichment import (
    enrich_evidence_with_current_state,
    is_historical_query,
)
from memory_lab.query.provider_answer import _build_ask_prompt
from memory_lab.reasoning.models import EvidenceItem

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

DB = "postgresql://unit/test"


def _item(content_id, rank, snippet="snippet text"):
    return EvidenceItem(
        evidence_id=f"ev_{content_id}",
        rank=rank,
        content_id=content_id,
        snippet=snippet,
        score_kind="chunk_text_match",
        retrieval_path="content_chunk_workspace_scoped",
    )


def _state(is_current, scope, supersedes=None):
    return {
        "is_current": is_current,
        "current_state_scope": scope,
        "cs_supersedes_content_id": supersedes,
    }


def _patch_rows(monkeypatch, rows):
    monkeypatch.setattr(cse, "fetch_current_state_rows", lambda db, ids: rows)


# ---------------------------------------------------------------------------
# In-scope preference: current above superseded
# ---------------------------------------------------------------------------

def test_superseded_demoted_below_current_in_same_scope(monkeypatch):
    _patch_rows(monkeypatch, {
        "old-1": _state(False, "message-queue"),
        "new-1": _state(True, "message-queue", supersedes="old-1"),
    })
    evidence = [_item("old-1", 1), _item("new-1", 2)]
    out = enrich_evidence_with_current_state(evidence, database_url=DB, query="what queue do we use?")
    assert [e.content_id for e in out] == ["new-1", "old-1"]
    assert [e.rank for e in out] == [1, 2]
    assert "superseded" in out[1].ranking_reason
    assert out[0].cs_supersedes_content_id == "old-1"


def test_superseded_without_current_in_scope_keeps_order(monkeypatch):
    # No current item in that scope was retrieved → nothing to prefer, no reorder.
    _patch_rows(monkeypatch, {"old-1": _state(False, "message-queue")})
    evidence = [_item("old-1", 1), _item("other", 2)]
    out = enrich_evidence_with_current_state(evidence, database_url=DB, query="queue?")
    assert [e.content_id for e in out] == ["old-1", "other"]
    assert out[0].is_current is False  # still annotated


def test_different_scopes_never_reordered(monkeypatch):
    _patch_rows(monkeypatch, {
        "mq-old": _state(False, "message-queue"),
        "mq-new": _state(True, "message-queue"),
        "design": _state(True, "design-tooling"),
    })
    evidence = [_item("design", 1), _item("mq-old", 2), _item("mq-new", 3)]
    out = enrich_evidence_with_current_state(evidence, database_url=DB, query="decisions?")
    # design keeps first place; only mq-old sinks below mq-new.
    assert [e.content_id for e in out] == ["design", "mq-new", "mq-old"]


def test_items_without_state_untouched(monkeypatch):
    _patch_rows(monkeypatch, {"known": _state(True, "s1")})
    evidence = [_item("unknown-a", 1), _item("known", 2), _item("unknown-b", 3)]
    out = enrich_evidence_with_current_state(evidence, database_url=DB, query="q?")
    assert [e.content_id for e in out] == ["unknown-a", "known", "unknown-b"]
    assert out[0].is_current is None
    assert out[0].metadata is None


# ---------------------------------------------------------------------------
# Historical questions: annotate but never demote
# ---------------------------------------------------------------------------

def test_historical_query_keeps_order_but_annotates(monkeypatch):
    _patch_rows(monkeypatch, {
        "old-1": _state(False, "message-queue"),
        "new-1": _state(True, "message-queue"),
    })
    evidence = [_item("old-1", 1), _item("new-1", 2)]
    out = enrich_evidence_with_current_state(
        evidence, database_url=DB, query="what did we use previously for the queue?"
    )
    assert [e.content_id for e in out] == ["old-1", "new-1"]
    assert out[0].is_current is False
    assert out[1].is_current is True


def test_is_historical_query_terms():
    assert is_historical_query("what did we decide before switching?")
    assert is_historical_query("What was the original choice, historically?")
    assert not is_historical_query("what message queue do we use?")
    assert not is_historical_query("")
    # word-boundary: 'beforehand' must not trigger 'before'
    assert not is_historical_query("prepare the beforehand-checklist")


# ---------------------------------------------------------------------------
# Best-effort guarantees — ask never degrades because of enrichment
# ---------------------------------------------------------------------------

def test_db_error_returns_evidence_unchanged(monkeypatch):
    def boom(db, ids):
        raise RuntimeError("db down")
    monkeypatch.setattr(cse, "fetch_current_state_rows", boom)
    evidence = [_item("a", 1), _item("b", 2)]
    out = enrich_evidence_with_current_state(evidence, database_url=DB, query="q?")
    assert out == evidence


def test_missing_database_url_returns_unchanged():
    evidence = [_item("a", 1)]
    assert enrich_evidence_with_current_state(evidence, database_url=None, query="q?") == evidence


def test_empty_rows_returns_unchanged(monkeypatch):
    _patch_rows(monkeypatch, {})
    evidence = [_item("a", 1), _item("b", 2)]
    out = enrich_evidence_with_current_state(evidence, database_url=DB, query="q?")
    assert out == evidence


# ---------------------------------------------------------------------------
# FV-9 traceability — status visible in metadata
# ---------------------------------------------------------------------------

def test_metadata_carries_current_state_fields(monkeypatch):
    _patch_rows(monkeypatch, {"new-1": _state(True, "message-queue", supersedes="old-1")})
    out = enrich_evidence_with_current_state([_item("new-1", 1)], database_url=DB, query="q?")
    md = out[0].metadata
    assert md["is_current"] is True
    assert md["current_state_scope"] == "message-queue"
    assert md["cs_supersedes_content_id"] == "old-1"


# ---------------------------------------------------------------------------
# Provider prompt — status labels + history rule
# ---------------------------------------------------------------------------

def test_prompt_labels_current_and_superseded():
    current = _item("new-1", 1).model_copy(update={"is_current": True})
    superseded = _item("old-1", 2).model_copy(update={"is_current": False})
    prompt = _build_ask_prompt("q?", "det answer", [current, superseded])
    assert f"[{current.evidence_id}] {current.snippet} [status: current]" in prompt
    assert f"[{superseded.evidence_id}] {superseded.snippet} [status: superseded]" in prompt
    assert "unless the question asks about history" in prompt


def test_prompt_unchanged_when_no_status_known():
    prompt = _build_ask_prompt("q?", "det answer", [_item("a", 1), _item("b", 2)])
    assert "[status:" not in prompt
    assert "asks about history" not in prompt
