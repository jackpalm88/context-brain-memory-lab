"""M8D1 — correct misleading parity surfaces.

Two defects from the M8C functional parity audit:
1. save_and_link_to_hub silently dropped quick_summary (never persisted).
2. update_node_metadata is read-only but its name implies mutation.
"""

import memory_lab.mcp.tools as tools
from memory_lab.api.services.api_adapter import ApiAdapter
from memory_lab.mcp.client import MemoryLabApiClient


WS = "00000000-0000-0000-0000-0000000000a1"
UNSUPPORTED_NOTE = "accepted for production MCP signature parity but not persisted by the public minimal content API"


# ---- save_and_link_to_hub: quick_summary must be persisted ----

class StubClient(MemoryLabApiClient):
    def __init__(self):
        super().__init__(base_url="http://127.0.0.1:8000")
        self.calls = []

    def content_create_id(self, content=None, workspace_id=None):
        self.calls.append(("create", content, workspace_id))
        return {"persisted": True, "content_id": "new-id"}

    def set_quick_summary(self, content_id, quick_summary, workspace_id=None):
        self.calls.append(("quick_summary", content_id, quick_summary, workspace_id))
        return {"content_id": content_id, "quick_summary": quick_summary, "updated": True}

    def hub_link_content(self, hub_id, content_id, workspace_id=None):
        self.calls.append(("link", hub_id, content_id, workspace_id))
        return {"linked": True}


def test_save_and_link_persists_quick_summary_in_order():
    client = StubClient()
    result = client.save_and_link_to_hub(content="text", hub_id="hub-1", quick_summary="qs", workspace_id=WS)
    names = [c[0] for c in client.calls]
    assert names == ["create", "quick_summary", "link"]
    assert ("quick_summary", "new-id", "qs", WS) in client.calls
    assert result["quick_summary_result"]["quick_summary"] == "qs"
    assert result["linked"] is True


def test_save_and_link_skips_quick_summary_when_absent():
    client = StubClient()
    result = client.save_and_link_to_hub(content="text", hub_id="hub-1", workspace_id=WS)
    names = [c[0] for c in client.calls]
    assert names == ["create", "link"]
    assert "quick_summary_result" not in result


def test_save_and_link_reports_unsupported_signature_fields():
    client = StubClient()
    result = client.save_and_link_to_hub(
        content="text",
        hub_id="hub-1",
        save_purpose="why",
        content_url="https://example.test/source",
        workspace_id=WS,
    )

    assert result["unsupported_fields"] == {
        "save_purpose": UNSUPPORTED_NOTE,
        "content_url": UNSUPPORTED_NOTE,
    }


def test_tool_save_and_link_forwards_quick_summary_and_unsupported_fields(monkeypatch):
    captured = {}

    class FakeClient:
        def save_and_link_to_hub(
            self,
            content,
            hub_id,
            quick_summary=None,
            save_purpose=None,
            content_url=None,
            workspace_id=None,
        ):
            captured.update(
                content=content,
                hub_id=hub_id,
                quick_summary=quick_summary,
                save_purpose=save_purpose,
                content_url=content_url,
                workspace_id=workspace_id,
            )
            return {"persisted": True}

    monkeypatch.setattr(tools, "_client", lambda: FakeClient())
    tools.save_and_link_to_hub(
        content="c", save_purpose="why", hub_id="h",
        content_url="u", quick_summary="qs", workspace_id=WS,
    )
    assert captured["quick_summary"] == "qs"
    assert captured["save_purpose"] == "why"
    assert captured["content_url"] == "u"
    assert captured["content"] == "c"
    assert captured["hub_id"] == "h"


class AdapterStub(ApiAdapter):
    def __init__(self):
        self.calls = []

    def create_content_minimal(self, content=None, workspace_id=None, workspace_source=None):
        self.calls.append(("create", content, workspace_id, workspace_source))
        return {"persisted": True, "content_id": "new-id"}

    def set_quick_summary(self, content_id, quick_summary, workspace_id=None):
        self.calls.append(("quick_summary", content_id, quick_summary, workspace_id))
        return {"content_id": content_id, "quick_summary": quick_summary, "updated": True}

    def link_content(self, hub_id, content_id, workspace_id=None):
        self.calls.append(("link", hub_id, content_id, workspace_id))
        return {"linked": True}


def test_api_adapter_save_and_link_persists_quick_summary_before_link():
    adapter = AdapterStub()

    result = adapter.save_and_link_to_hub(
        content="text",
        hub_id="hub-1",
        workspace_id=WS,
        workspace_source="api_key",
        quick_summary="visible summary",
    )

    assert [call[0] for call in adapter.calls] == ["create", "quick_summary", "link"]
    assert ("quick_summary", "new-id", "visible summary", WS) in adapter.calls
    assert result["quick_summary_result"]["quick_summary"] == "visible summary"
    assert result["linked"] is True


def test_api_adapter_save_and_link_documents_unsupported_signature_fields():
    adapter = AdapterStub()

    result = adapter.save_and_link_to_hub(
        content="text",
        hub_id="hub-1",
        workspace_id=WS,
        save_purpose="why",
        content_url="https://example.test/source",
    )

    assert result["unsupported_fields"] == {
        "save_purpose": UNSUPPORTED_NOTE,
        "content_url": UNSUPPORTED_NOTE,
    }


# ---- update_node_metadata: must declare read-only / no mutation ----

def test_update_node_metadata_tool_marks_read_only(monkeypatch):
    class FakeClient:
        def update_node_metadata(self, content_id, workspace_id=None):
            return {"content_id": content_id, "quick_summary": "s", "domain": "x"}

    monkeypatch.setattr(tools, "_client", lambda: FakeClient())
    result = tools.update_node_metadata(content_id="c1", workspace_id=WS)
    assert result["read_only"] is True
    assert result["mutation"] == "none"
    assert result["content_id"] == "c1"


def test_update_node_metadata_tool_does_not_mark_error_responses(monkeypatch):
    from memory_lab.mcp.client import MemoryLabApiError

    class FakeClient:
        def update_node_metadata(self, content_id, workspace_id=None):
            raise MemoryLabApiError("boom", method="GET", url="/x", status_code=404, body="nope")

    monkeypatch.setattr(tools, "_client", lambda: FakeClient())
    result = tools.update_node_metadata(content_id="c1", workspace_id=WS)
    assert result["ok"] is False
    assert "read_only" not in result
