from __future__ import annotations

import pytest

from memory_lab.query.service import QueryService
from memory_lab.reasoning.models import AskRequest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000934"


class FakeRetrievalAdapter:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.rows)


def _row(content_id: str, chunk_id: str, text: str, score: float = 0.9) -> dict:
    return {
        "content_id": content_id,
        "chunk_id": chunk_id,
        "text": text,
        "score": score,
        "retrieval_path": "content_chunk_workspace_scoped",
    }


def test_ask_request_resolves_memory_type_and_memory_types_deduped_in_order():
    req = AskRequest(query="x", memory_type="decision", memory_types=["fact", "note", "decision"])
    assert req.resolved_memory_types() == ["decision", "fact", "note"]


def test_ask_request_resolved_memory_types_none_when_unset():
    assert AskRequest(query="x").resolved_memory_types() is None


def test_ask_request_resolved_memory_types_ignores_blank_values():
    req = AskRequest(query="x", memory_type="  ", memory_types=["", "  ", "fact"])
    assert req.resolved_memory_types() == ["fact"]


def test_query_service_passes_memory_types_to_retrieval_when_set():
    adapter = FakeRetrievalAdapter([_row("cid-1", "chk-1", "decision evidence text")])
    req = AskRequest(query="find decision", memory_type="decision")

    QueryService(retrieval_adapter=adapter).execute(req, workspace_id=WS)

    assert adapter.calls[0]["memory_types"] == ["decision"]


def test_query_service_passes_none_memory_types_by_default():
    adapter = FakeRetrievalAdapter([_row("cid-1", "chk-1", "some evidence text")])
    req = AskRequest(query="find something")

    QueryService(retrieval_adapter=adapter).execute(req, workspace_id=WS)

    assert adapter.calls[0]["memory_types"] is None
