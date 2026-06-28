"""Unit tests — classify ingest wiring (_run_classify_and_write behavior).

Pure-Python, no DB, no provider calls.
Tests the mapping/guard logic that wraps the classify write path.
"""
import json
import pytest
from unittest.mock import MagicMock, patch, call

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

_WS_ID = "00000000-0000-0000-0000-000000000001"
_CI_ID = "00000000-0000-0000-0000-000000000002"
_DB_URL = "postgresql://fake/fake"


def _make_adapter():
    from memory_lab.api.services.api_adapter import ApiAdapter
    return ApiAdapter(_DB_URL)


# ---------------------------------------------------------------------------
# 1. ClassificationResult fields map correctly to response keys
# ---------------------------------------------------------------------------

class TestClassifyResultMapping:
    def test_classified_response_fields_present(self):
        from memory_lab.ingestion.classify_pipeline import ClassificationResult
        result = ClassificationResult(
            memory_type="milestone",
            memory_sub_type="governance_milestone",
            confidence=0.85,
            signals=["go_classify"],
            project_topic="context_brain_memory_lab",
            domain_hint="governance",
        )
        # Verify to_dict produces expected keys
        d = result.to_dict()
        assert d["memory_type"] == "milestone"
        assert d["memory_sub_type"] == "governance_milestone"
        assert d["confidence"] == 0.85
        assert d["signals"] == ["go_classify"]
        assert d["project_topic"] == "context_brain_memory_lab"
        assert d["domain_hint"] == "governance"

    def test_classify_result_confidence_serialisable(self):
        from memory_lab.ingestion.classify_pipeline import ClassificationResult
        r = ClassificationResult(memory_type="evidence", confidence=0.72)
        assert isinstance(json.dumps(r.to_dict()), str)


# ---------------------------------------------------------------------------
# 2. TIER_DISCARD guard — classify must NOT be called when should_persist=False
# ---------------------------------------------------------------------------

class TestDiscardTierSkip:
    def test_discard_skips_run_classify_and_write(self):
        """create_content_minimal must not call _run_classify_and_write for TIER_DISCARD."""
        adapter = _make_adapter()

        fake_scores_obj = MagicMock()
        fake_scores_obj.composite = 0.2
        fake_scores_obj.quality = 0.1
        fake_scores_obj.relevance = 0.2
        fake_scores_obj.novelty = 0.2
        fake_event = MagicMock()
        fake_event.scores = fake_scores_obj
        fake_event.circuit_open = False
        fake_event.fallback_reason = ""

        from memory_lab.governance.tier_router import TierDecision
        fake_tier = TierDecision(
            tier="discard",
            reason="test_discard",
            rule_id="TEST",
            should_persist=False,
        )

        with patch.object(adapter, "_conn") as mock_conn_ctx, \
             patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
             patch("memory_lab.api.services.api_adapter.tier_route", return_value=fake_tier), \
             patch.object(adapter, "_run_classify_and_write") as mock_classify_write:

            resp = adapter.create_content_minimal(content="low quality content", workspace_id=_WS_ID)

        mock_conn_ctx.assert_not_called()
        mock_classify_write.assert_not_called()
        assert "content_id" not in resp
        assert resp["created"] is False
        assert resp["persisted"] is False
        assert resp["discarded"] is True
        assert resp["mode"] == "governed_discarded"

    def test_discard_response_has_no_classify_fields(self):
        """TIER_DISCARD response must not include memory_type classify fields."""
        adapter = _make_adapter()

        fake_event = MagicMock()
        fake_event.scores.composite = 0.1
        fake_event.scores.quality = 0.1
        fake_event.scores.relevance = 0.1
        fake_event.scores.novelty = 0.1
        fake_event.circuit_open = False
        fake_event.fallback_reason = ""

        from memory_lab.governance.tier_router import TierDecision
        fake_tier = TierDecision(tier="discard", reason="x", rule_id="X", should_persist=False)

        with patch.object(adapter, "_conn") as mock_conn_ctx, \
             patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
             patch("memory_lab.api.services.api_adapter.tier_route", return_value=fake_tier):

            resp = adapter.create_content_minimal(content="discard me", workspace_id=_WS_ID)

        mock_conn_ctx.assert_not_called()
        assert "content_id" not in resp
        assert "memory_type" not in resp
        assert "classify_status" not in resp
        assert resp["created"] is False
        assert resp["persisted"] is False
        assert resp["discarded"] is True


# ---------------------------------------------------------------------------
# 3. Classify exception best-effort — content save must succeed
# ---------------------------------------------------------------------------

class TestClassifyExceptionBestEffort:
    def test_classify_exception_does_not_propagate(self):
        adapter = _make_adapter()

        with patch("memory_lab.api.services.api_adapter._classify",
                   side_effect=RuntimeError("unexpected!")):
            result = adapter._run_classify_and_write(
                content="gate pass v0.1.0b9",
                content_id=_CI_ID,
                workspace_id=_WS_ID,
                tier="transient",
                composite_score=0.3,
            )

        assert result is None  # returns None, does not raise

    def test_classify_db_write_failure_returns_none(self):
        adapter = _make_adapter()

        with patch("memory_lab.api.services.api_adapter._classify") as mock_clf, \
             patch.object(adapter, "_conn", side_effect=Exception("DB down")):

            from memory_lab.ingestion.classify_pipeline import ClassificationResult
            mock_clf.return_value = ClassificationResult(
                memory_type="milestone", confidence=0.85, signals=["go_classify"]
            )
            result = adapter._run_classify_and_write(
                content="gate pass",
                content_id=_CI_ID,
                workspace_id=_WS_ID,
                tier="transient",
                composite_score=0.3,
            )

        assert result is None  # DB failure → None, no exception


# ---------------------------------------------------------------------------
# 4. Domain confidence threshold
# ---------------------------------------------------------------------------

class TestDomainConfidenceThreshold:
    def _build_fake_conn(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = None  # no dedup match
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        return mock_conn, mock_cur

    def test_low_confidence_skips_domain_upsert(self):
        adapter = _make_adapter()
        mock_conn, mock_cur = self._build_fake_conn()

        from memory_lab.ingestion.classify_pipeline import ClassificationResult
        low_conf = ClassificationResult(
            memory_type="evidence", confidence=0.62,
            signals=["smoke_001"], domain_hint="schema"
        )

        with patch("memory_lab.api.services.api_adapter._classify", return_value=low_conf), \
             patch.object(adapter, "_conn", return_value=mock_conn):
            adapter._run_classify_and_write(
                content="smoke_001 pass",
                content_id=_CI_ID,
                workspace_id=_WS_ID,
                tier="transient",
                composite_score=0.3,
            )

        sql_calls = [str(c) for c in mock_cur.execute.call_args_list]
        domain_upserts = [s for s in sql_calls if "cb_discovered_domains" in s]
        assert len(domain_upserts) == 0, "domain upsert must NOT run when confidence < 0.70"

    def test_high_confidence_triggers_domain_upsert(self):
        adapter = _make_adapter()
        mock_conn, mock_cur = self._build_fake_conn()

        from memory_lab.ingestion.classify_pipeline import ClassificationResult
        high_conf = ClassificationResult(
            memory_type="milestone", confidence=0.85,
            signals=["go_classify", "_schema_apply_pass"], domain_hint="governance"
        )

        with patch("memory_lab.api.services.api_adapter._classify", return_value=high_conf), \
             patch.object(adapter, "_conn", return_value=mock_conn):
            adapter._run_classify_and_write(
                content="go_classify schema_apply_pass",
                content_id=_CI_ID,
                workspace_id=_WS_ID,
                tier="transient",
                composite_score=0.3,
            )

        sql_calls = [str(c) for c in mock_cur.execute.call_args_list]
        domain_upserts = [s for s in sql_calls if "cb_discovered_domains" in s]
        assert len(domain_upserts) >= 1, "domain upsert must run when confidence >= 0.70"


# ---------------------------------------------------------------------------
# 5. No current-state fields written
# ---------------------------------------------------------------------------

class TestNoCurrentStateFieldsWritten:
    def test_classify_write_sql_lacks_is_current(self):
        adapter = _make_adapter()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        from memory_lab.ingestion.classify_pipeline import ClassificationResult
        r = ClassificationResult(memory_type="principle", confidence=0.85, signals=["principle:"])

        with patch("memory_lab.api.services.api_adapter._classify", return_value=r), \
             patch.object(adapter, "_conn", return_value=mock_conn):
            adapter._run_classify_and_write(
                content="principle: invariant",
                content_id=_CI_ID,
                workspace_id=_WS_ID,
                tier="persistent",
                composite_score=0.8,
            )

        forbidden = {"is_current", "current_state_scope", "cs_supersedes_content_id"}
        all_sql = " ".join(str(c) for c in mock_cur.execute.call_args_list)
        for field in forbidden:
            assert field not in all_sql, f"MUST NOT write {field!r} in classify write path"


# ---------------------------------------------------------------------------
# 6. Current-state resolver ingest boundary
# ---------------------------------------------------------------------------

def _mock_conn_with_cursor(fetchone_value=None):
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = fetchone_value
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cur


class TestCurrentStateResolverBoundary:
    def _persist_event_and_tier(self):
        fake_event = MagicMock()
        fake_event.scores.composite = 0.85
        fake_event.scores.quality = 0.85
        fake_event.scores.relevance = 0.85
        fake_event.scores.novelty = 0.85
        fake_event.circuit_open = False
        fake_event.fallback_reason = ""
        from memory_lab.governance.tier_router import TierDecision
        fake_tier = TierDecision(tier="long_term", reason="test", rule_id="X", should_persist=True)
        return fake_event, fake_tier

    def test_high_confidence_persisted_content_calls_resolver_after_classify(self):
        adapter = _make_adapter()
        fake_event, fake_tier = self._persist_event_and_tier()
        conn_insert, _ = _mock_conn_with_cursor({"content_id": _CI_ID})
        conn_score, _ = _mock_conn_with_cursor(None)
        conn_body, _ = _mock_conn_with_cursor(None)
        conn_resolver, _ = _mock_conn_with_cursor(None)
        classify_meta = {
            "memory_type": "anchor",
            "memory_sub_type": "current_state_anchor",
            "classify_confidence": 0.85,
            "signals": ["current state"],
            "project_topic": "context_brain_memory_lab",
            "domain_hint": "governance",
            "classify_mode": "heuristic_v1",
            "classify_status": "classified",
        }
        fake_resolution = MagicMock()
        fake_resolution.to_dict.return_value = {
            "status": "active",
            "reason": "resolved_current_state",
            "current_state_scope": "b10",
            "supersedes_content_id": None,
        }

        with patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
             patch("memory_lab.api.services.api_adapter.tier_route", return_value=fake_tier), \
             patch.object(adapter, "_run_classify_and_write", return_value=classify_meta) as mock_classify, \
             patch.object(adapter, "_conn", side_effect=[conn_insert, conn_score, conn_body, conn_resolver]), \
             patch("memory_lab.api.services.api_adapter.resolve_current_state_after_ingest", return_value=fake_resolution) as mock_resolver:
            resp = adapter.create_content_minimal(
                content="current_state_scope: b10\nCurrent state active anchor.", workspace_id=_WS_ID
            )

        mock_classify.assert_called_once()
        mock_resolver.assert_called_once()
        _, kwargs = mock_resolver.call_args
        assert kwargs["content_id"] == _CI_ID
        assert kwargs["workspace_id"] == _WS_ID
        assert kwargs["memory_type"] == "anchor"
        assert kwargs["classify_confidence"] == 0.85
        assert resp["current_state_status"] == "active"
        assert resp["current_state_scope"] == "b10"

    def test_low_confidence_persisted_content_does_not_call_resolver(self):
        adapter = _make_adapter()
        fake_event, fake_tier = self._persist_event_and_tier()
        conn_insert, _ = _mock_conn_with_cursor({"content_id": _CI_ID})
        conn_score, _ = _mock_conn_with_cursor(None)
        conn_body, _ = _mock_conn_with_cursor(None)
        classify_meta = {
            "memory_type": "evidence",
            "memory_sub_type": "implementation_evidence",
            "classify_confidence": 0.62,
            "classify_mode": "heuristic_v1",
            "classify_status": "classified",
        }

        with patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
             patch("memory_lab.api.services.api_adapter.tier_route", return_value=fake_tier), \
             patch.object(adapter, "_run_classify_and_write", return_value=classify_meta), \
             patch.object(adapter, "_conn", side_effect=[conn_insert, conn_score, conn_body]), \
             patch("memory_lab.api.services.api_adapter.resolve_current_state_after_ingest") as mock_resolver:
            resp = adapter.create_content_minimal(content="weak evidence", workspace_id=_WS_ID)

        mock_resolver.assert_not_called()
        assert "current_state_status" not in resp
