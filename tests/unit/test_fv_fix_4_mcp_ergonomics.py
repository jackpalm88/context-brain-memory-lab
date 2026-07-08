"""Unit tests — FV-FIX-4 MCP tool ergonomics.

1. All 32 approved MCP tools carry useful descriptions (docstrings), and the
   FastMCP server actually exposes them via tools/list.
2. query_memory can request the provider-backed ask mode
   (enable_provider_synthesis) and stays wire-compatible when it does not.

Pure-Python; no DB; no provider calls.
"""

import asyncio

import pytest

import memory_lab.mcp.tools as tools_mod
from memory_lab.mcp.client import MemoryLabApiClient
from memory_lab.mcp.tools import APPROVED_TOOLS, query_memory

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

_MIN_DESCRIPTION_LEN = 40


# ---------------------------------------------------------------------------
# 32/32 descriptions
# ---------------------------------------------------------------------------

def test_all_approved_tools_have_useful_docstrings():
    assert len(APPROVED_TOOLS) == 34  # 32 parity + CF-003 anchors + CF-002 decisions-by-content
    missing = {
        name
        for name, fn in APPROVED_TOOLS.items()
        if len((fn.__doc__ or "").strip()) < _MIN_DESCRIPTION_LEN
    }
    assert not missing, f"tools without a useful description: {sorted(missing)}"


def test_fastmcp_server_exposes_all_descriptions():
    from memory_lab.mcp.server import server

    tools = asyncio.run(server.list_tools())
    assert len(tools) == 34  # 32 parity + CF-003 anchors + CF-002 decisions-by-content
    empty = [t.name for t in tools if len((t.description or "").strip()) < _MIN_DESCRIPTION_LEN]
    assert not empty, f"registered tools with empty/short description: {empty}"


def test_descriptions_lead_with_a_summary_line():
    # The first docstring line is what most MCP clients render in tool pickers.
    weak = {
        name
        for name, fn in APPROVED_TOOLS.items()
        if len((fn.__doc__ or "").strip().splitlines()[0].strip()) < 20
    }
    assert not weak, f"tools whose first description line is too thin: {sorted(weak)}"


# ---------------------------------------------------------------------------
# query_memory provider-backed mode threading
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self):
        self.calls = []

    def ask(self, **kwargs):
        self.calls.append(kwargs)
        return {"answer": "a", "status": "ok", "confidence": 0.7,
                "citations": [{"evidence_id": "e1"}]}


def test_query_memory_threads_provider_opt_in(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(tools_mod, "_client", lambda: fake)
    query_memory("q?", enable_provider_synthesis=True)
    assert fake.calls[0].get("enable_provider_synthesis") is True


def test_query_memory_default_stays_wire_compatible(monkeypatch):
    # Default call must not add the new key, so older API deployments and
    # existing stub-based contracts see the exact pre-FV-FIX-4 payload shape.
    fake = _FakeClient()
    monkeypatch.setattr(tools_mod, "_client", lambda: fake)
    query_memory("q?")
    assert "enable_provider_synthesis" not in fake.calls[0]


def test_client_ask_includes_flag_only_when_true():
    captured = {}

    def fake_request(method, path, json_body=None, params=None, workspace_id=None):
        captured["body"] = json_body
        return {"status": "ok"}

    client = MemoryLabApiClient.__new__(MemoryLabApiClient)
    client._request = fake_request
    client.ask("q?", enable_provider_synthesis=True)
    assert captured["body"]["enable_provider_synthesis"] is True
    client.ask("q?")
    assert "enable_provider_synthesis" not in captured["body"]
    client.ask("q?", enable_provider_synthesis=False)
    assert "enable_provider_synthesis" not in captured["body"]


def test_query_memory_docstring_explains_provider_gate():
    doc = query_memory.__doc__ or ""
    assert "enable_provider_synthesis" in doc
    assert "provider_disabled" in doc, (
        "description must explain WHY provider mode may not activate (deployment gate)"
    )
