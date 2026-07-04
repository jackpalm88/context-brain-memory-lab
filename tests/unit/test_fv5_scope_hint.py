"""Unit tests — FV-5 scope_hint threading.

Validates that an explicit scope_hint:
  1. flows through ContentCreateRequest (Pydantic model)
  2. overrides heuristic project_topic in the T4 resolver call  
  3. is correctly absent when not supplied (no regression)
  4. MCP client includes/excludes scope_hint in payload correctly

Pure-Python; no DB; no provider calls.
"""
import pytest
from unittest.mock import MagicMock, patch, call

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

_WS_ID = "00000000-0000-0000-0000-000000000001"
_CI_ID = "00000000-0000-0000-0000-000000000002"
_DB_URL = "postgresql://fake/fake"


def _make_adapter():
    from memory_lab.api.services.api_adapter import ApiAdapter
    return ApiAdapter(_DB_URL)


def _build_fake_conn():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = {"content_id": _CI_ID}  # RealDictCursor returns dicts
    mock_conn.cursor.return_value = mock_cur
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cur


# ---------------------------------------------------------------------------
# 1. ContentCreateRequest Pydantic model accepts scope_hint
# ---------------------------------------------------------------------------

class TestContentCreateRequestModel:
    def test_scope_hint_optional_absent(self):
        from memory_lab.api.routers.content import ContentCreateRequest
        req = ContentCreateRequest(content="hello")
        assert req.scope_hint is None

    def test_scope_hint_present(self):
        from memory_lab.api.routers.content import ContentCreateRequest
        req = ContentCreateRequest(content="hello", scope_hint="my-project-alpha")
        assert req.scope_hint == "my-project-alpha"

    def test_scope_hint_max_length_enforced(self):
        from pydantic import ValidationError
        from memory_lab.api.routers.content import ContentCreateRequest
        with pytest.raises((ValidationError, ValueError)):
            ContentCreateRequest(content="x", scope_hint="a" * 121)


# ---------------------------------------------------------------------------
# 2. create_content_minimal threads scope_hint into resolver as project_topic
# ---------------------------------------------------------------------------

class TestScopeHintThreading:

    def _mock_classify_meta(self, project_topic=None):
        return {
            "classify_confidence": 0.85,
            "memory_type": "evidence",
            "memory_sub_type": None,
            "signals": ["governance"],
            "project_topic": project_topic,
            "domain_hint": "governance",
        }

    def test_scope_hint_overrides_heuristic_project_topic(self):
        """scope_hint must reach the resolver as a first-class param, above heuristics."""
        adapter = _make_adapter()
        mock_conn, mock_cur = _build_fake_conn()
        classify_meta = self._mock_classify_meta(project_topic=None)  # heuristic found nothing
        captured = {}

        def fake_resolver(conn, *, scope_hint=None, project_topic=None, **kwargs):
            captured["scope_hint"] = scope_hint
            captured["project_topic"] = project_topic
            from memory_lab.current_state.resolver import CurrentStateResolution
            return CurrentStateResolution(
                status="active", reason="resolved_current_state",
                content_id=_CI_ID, workspace_id=_WS_ID, memory_type="evidence",
                current_state_scope=scope_hint or project_topic or "global",
                anchor_id="aaaa", wrote=True,
            )

        from memory_lab.governance.tier_router import TierDecision
        fake_event = MagicMock()
        fake_event.scores = MagicMock(composite=0.8, quality=0.8, relevance=0.8, novelty=0.8)
        fake_event.circuit_open = False
        fake_event.fallback_reason = None
        fake_tier = TierDecision(tier="long_term", reason="score_above_threshold",
                                 rule_id="T-PERSISTENT", should_persist=True)

        with patch.object(adapter, "_run_classify_and_write", return_value=classify_meta), \
             patch.object(adapter, "_find_duplicate_content_id", return_value=None), \
             patch.object(adapter, "_conn", return_value=mock_conn), \
             patch("memory_lab.api.services.api_adapter.resolve_current_state_after_ingest",
                   side_effect=fake_resolver), \
             patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
             patch("memory_lab.api.services.api_adapter.tier_route", return_value=fake_tier), \
             patch("memory_lab.api.services.api_adapter.annotate",
                   return_value=MagicMock(topic_tags=[], meta_tags=[])), \
             patch("memory_lab.api.services.api_adapter.persist_body_chunks",
                   return_value=MagicMock(warnings=[])):

            adapter.create_content_minimal(
                content="Some governance text without project keywords",
                workspace_id=_WS_ID,
                scope_hint="my-custom-project-scope",
            )

        assert captured.get("scope_hint") == "my-custom-project-scope", (
            f"scope_hint must reach the resolver; got {captured.get('scope_hint')!r}"
        )
        assert captured.get("project_topic") is None

    def test_no_scope_hint_uses_heuristic(self):
        """Without scope_hint, heuristic project_topic from classify is used unchanged."""
        adapter = _make_adapter()
        mock_conn, mock_cur = _build_fake_conn()
        classify_meta = self._mock_classify_meta(project_topic="context_brain_memory_lab")
        captured = {}

        def fake_resolver(conn, *, scope_hint=None, project_topic=None, **kwargs):
            captured["scope_hint"] = scope_hint
            captured["project_topic"] = project_topic
            from memory_lab.current_state.resolver import CurrentStateResolution
            return CurrentStateResolution(
                status="active", reason="resolved_current_state",
                content_id=_CI_ID, workspace_id=_WS_ID, memory_type="evidence",
                current_state_scope=scope_hint or project_topic or "global",
                anchor_id="bbbb", wrote=True,
            )

        from memory_lab.governance.tier_router import TierDecision
        fake_event = MagicMock()
        fake_event.scores = MagicMock(composite=0.8, quality=0.8, relevance=0.8, novelty=0.8)
        fake_event.circuit_open = False
        fake_event.fallback_reason = None
        fake_tier = TierDecision(tier="long_term", reason="score_above_threshold",
                                 rule_id="T-PERSISTENT", should_persist=True)

        with patch.object(adapter, "_run_classify_and_write", return_value=classify_meta), \
             patch.object(adapter, "_find_duplicate_content_id", return_value=None), \
             patch.object(adapter, "_conn", return_value=mock_conn), \
             patch("memory_lab.api.services.api_adapter.resolve_current_state_after_ingest",
                   side_effect=fake_resolver), \
             patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
             patch("memory_lab.api.services.api_adapter.tier_route", return_value=fake_tier), \
             patch("memory_lab.api.services.api_adapter.annotate",
                   return_value=MagicMock(topic_tags=[], meta_tags=[])), \
             patch("memory_lab.api.services.api_adapter.persist_body_chunks",
                   return_value=MagicMock(warnings=[])):

            adapter.create_content_minimal(
                content="Memory Lab context_brain text",
                workspace_id=_WS_ID,
                # no scope_hint
            )

        assert captured.get("scope_hint") is None
        assert captured.get("project_topic") == "context_brain_memory_lab", (
            f"heuristic project_topic must be preserved when no scope_hint; got {captured.get('project_topic')!r}"
        )


# ---------------------------------------------------------------------------
# 3. MCP client threads scope_hint into POST /v1/content payload
# ---------------------------------------------------------------------------

class TestMcpClientScopeHint:
    def _make_client(self, fake_request_fn):
        from memory_lab.mcp.client import MemoryLabApiClient
        client = MemoryLabApiClient.__new__(MemoryLabApiClient)
        client._base_url = "http://fake"
        client._workspace_id = None
        client._api_key = "fake-key"
        client._request = fake_request_fn
        return client

    def test_scope_hint_included_in_request_payload(self):
        captured = {}

        def fake_request(method, path, json_body=None, params=None, workspace_id=None):
            captured["json_body"] = json_body
            return {"content_id": "xxxx", "persisted": True, "created": True}

        client = self._make_client(fake_request)
        client.content_create_id(content="test content", scope_hint="explicit-scope-v1")
        assert captured["json_body"].get("scope_hint") == "explicit-scope-v1"

    def test_scope_hint_absent_not_in_payload(self):
        captured = {}

        def fake_request(method, path, json_body=None, params=None, workspace_id=None):
            captured["json_body"] = json_body
            return {"content_id": "xxxx", "persisted": True, "created": True}

        client = self._make_client(fake_request)
        client.content_create_id(content="test content")
        assert "scope_hint" not in (captured["json_body"] or {})

    def test_save_and_link_threads_scope_hint(self):
        captured = {}

        def fake_request(method, path, json_body=None, params=None, workspace_id=None):
            if path == "/v1/content":
                captured["content_payload"] = json_body or {}
                return {"content_id": "yyyy", "persisted": True, "created": True}
            if "/hubs/" in path:
                return {"linked": True}
            return {}

        client = self._make_client(fake_request)
        # hub_link_content is a separate call — patch it to avoid needing a real hub
        client.hub_link_content = MagicMock(return_value={"linked": True})
        client.save_and_link_to_hub(
            content="some content", hub_id="hub-abc",
            scope_hint="project-beta", workspace_id=None,
        )
        assert captured["content_payload"].get("scope_hint") == "project-beta"
