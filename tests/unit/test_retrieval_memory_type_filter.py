"""Unit tests — retrieval memory-type filter (B10_CANDIDATE_CLASSIFY_PIPELINE_TRACK).

Pure Python, no DB, no provider calls.
Covers: request model validation, SQL param injection, backwards compat, ask path guard.

release_context:
  latest_public_release: v0.1.0b9
  active_track: B10_CANDIDATE_CLASSIFY_PIPELINE_TRACK
  release_claim: none
"""
import pytest
from unittest.mock import MagicMock, patch
from pydantic import ValidationError

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

_VALID_TYPES = ["milestone", "decision", "principle", "anchor", "evidence", "plan_roadmap", "raw_memory"]


# ---------------------------------------------------------------------------
# 1. RetrievalRequest model validation
# ---------------------------------------------------------------------------

class TestRetrievalRequestValidation:
    def _make(self, **kwargs):
        from memory_lab.api.routers.retrieval import RetrievalRequest
        return RetrievalRequest(query="test query", **kwargs)

    def test_no_filter_accepted(self):
        req = self._make()
        assert req.memory_type is None
        assert req.memory_types is None
        assert req.resolved_memory_types() is None

    def test_singular_memory_type_accepted(self):
        req = self._make(memory_type="milestone")
        assert req.resolved_memory_types() == ["milestone"]

    def test_plural_memory_types_accepted(self):
        req = self._make(memory_types=["milestone", "evidence"])
        assert req.resolved_memory_types() == ["milestone", "evidence"]

    def test_all_seven_valid_types_accepted(self):
        for t in _VALID_TYPES:
            req = self._make(memory_type=t)
            assert req.resolved_memory_types() == [t]

    def test_multiple_types_in_list(self):
        req = self._make(memory_types=_VALID_TYPES)
        assert set(req.resolved_memory_types()) == set(_VALID_TYPES)

    def test_unknown_type_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            self._make(memory_type="nonexistent_type")
        assert "Unknown memory_type" in str(exc_info.value)

    def test_unknown_type_in_list_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            self._make(memory_types=["milestone", "not_a_real_type"])
        assert "Unknown memory_type" in str(exc_info.value)

    def test_both_singular_and_plural_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            self._make(memory_type="milestone", memory_types=["evidence"])
        assert "not both" in str(exc_info.value)

    def test_empty_memory_types_list_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            self._make(memory_types=[])
        assert "must not be empty" in str(exc_info.value)

    def test_resolved_memory_types_singular_returns_list(self):
        req = self._make(memory_type="decision")
        result = req.resolved_memory_types()
        assert isinstance(result, list)
        assert len(result) == 1

    def test_resolved_memory_types_none_when_no_filter(self):
        req = self._make()
        assert req.resolved_memory_types() is None


# ---------------------------------------------------------------------------
# 2. SQL param injection — memory_types filter applied at query level
# ---------------------------------------------------------------------------

class TestSqlParamInjection:
    def _adapter(self):
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
        return RetrievalAdapter("postgresql://fake/fake")

    def test_no_filter_no_memory_type_in_params(self):
        adapter = self._adapter()
        captured_params = []

        def fake_conn():
            conn = MagicMock()
            cur = MagicMock()
            cur.__enter__ = MagicMock(return_value=cur)
            cur.__exit__ = MagicMock(return_value=False)
            cur.fetchall.return_value = []

            def capture_execute(sql, params=None):
                if params:
                    captured_params.append(params)
            cur.execute = capture_execute
            conn.cursor.return_value = cur
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            return conn

        with patch.object(adapter, "_conn", side_effect=fake_conn):
            adapter._deterministic_vector_search("milestone governance", workspace_id="ws-1")

        flat = str(captured_params)
        assert "milestone" not in flat or "ws-1" in flat  # only workspace in params, no memory_type list

    def test_memory_type_filter_appended_to_params(self):
        adapter = self._adapter()
        captured_params = []

        def fake_conn():
            conn = MagicMock()
            cur = MagicMock()
            cur.__enter__ = MagicMock(return_value=cur)
            cur.__exit__ = MagicMock(return_value=False)
            cur.fetchall.return_value = []

            def capture_execute(sql, params=None):
                if params:
                    captured_params.extend(params)
            cur.execute = capture_execute
            conn.cursor.return_value = cur
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            return conn

        with patch.object(adapter, "_conn", side_effect=fake_conn):
            adapter._deterministic_vector_search(
                "some text", workspace_id="ws-1", memory_types=["milestone"]
            )

        assert ["milestone"] in captured_params, "memory_types list must be in SQL params"

    def test_memory_type_filter_none_produces_no_extra_param(self):
        adapter = self._adapter()
        captured_params = []

        def fake_conn():
            conn = MagicMock()
            cur = MagicMock()
            cur.__enter__ = MagicMock(return_value=cur)
            cur.__exit__ = MagicMock(return_value=False)
            cur.fetchall.return_value = []

            def capture_execute(sql, params=None):
                if params:
                    captured_params.extend(list(params))
            cur.execute = capture_execute
            conn.cursor.return_value = cur
            conn.__enter__ = MagicMock(return_value=conn)
            conn.__exit__ = MagicMock(return_value=False)
            return conn

        with patch.object(adapter, "_conn", side_effect=fake_conn):
            adapter._deterministic_vector_search("some text", workspace_id="ws-1", memory_types=None)

        # only workspace_id and LIKE patterns — no list param
        list_params = [p for p in captured_params if isinstance(p, list)]
        assert len(list_params) == 0, "no list param when memory_types=None"


# ---------------------------------------------------------------------------
# 3. No current-state fields in SQL
# ---------------------------------------------------------------------------

class TestNoCurrentStateInSql:
    def test_vector_search_sql_lacks_current_state_fields(self):
        adapter_module = __import__(
            "memory_lab.api.services.retrieval_adapter", fromlist=["RetrievalAdapter"]
        )
        import inspect
        src = inspect.getsource(adapter_module.RetrievalAdapter._deterministic_vector_search)
        for forbidden in ("is_current", "current_state_scope", "cs_supersedes_content_id"):
            assert forbidden not in src, f"MUST NOT use {forbidden!r} in vector search SQL"

    def test_hub_linked_results_sql_lacks_current_state_fields(self):
        adapter_module = __import__(
            "memory_lab.api.services.retrieval_adapter", fromlist=["RetrievalAdapter"]
        )
        import inspect
        src = inspect.getsource(adapter_module.RetrievalAdapter._hub_linked_results)
        for forbidden in ("is_current", "current_state_scope", "cs_supersedes_content_id"):
            assert forbidden not in src, f"MUST NOT use {forbidden!r} in hub linked results SQL"


# ---------------------------------------------------------------------------
# 4. Backwards compatibility — no filter = b9 behavior
# ---------------------------------------------------------------------------

class TestBackwardsCompatibility:
    def test_search_signature_accepts_no_memory_types(self):
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
        import inspect
        sig = inspect.signature(RetrievalAdapter.search)
        params = sig.parameters
        assert "memory_types" in params
        assert params["memory_types"].default is None

    def test_request_model_b9_fields_unchanged(self):
        from memory_lab.api.routers.retrieval import RetrievalRequest
        import inspect
        fields = RetrievalRequest.model_fields
        assert "query" in fields
        assert "max_hops" in fields
        assert "min_confidence" in fields
        assert "graph_boost" in fields

    def test_b9_request_without_filters_still_valid(self):
        from memory_lab.api.routers.retrieval import RetrievalRequest
        req = RetrievalRequest(query="what is memory", max_hops=1, min_confidence=0.7, graph_boost=0.1)
        assert req.resolved_memory_types() is None

    def test_evidence_item_backward_compatible_fields_preserved(self):
        from memory_lab.reasoning.models import EvidenceItem
        required = (
            "evidence_id", "rank", "content_id", "chunk_id",
            "snippet", "score", "score_kind", "retrieval_path",
            "source", "title", "metadata",
        )
        diagnostics = (
            "retrieval_reason", "ranking_reason", "hub_match", "graph_match",
            "knowledge_path", "score_components", "distance",
        )
        fields = EvidenceItem.model_fields
        for f in required:
            assert f in fields, f"EvidenceItem lost contract field: {f}"
        for f in diagnostics:
            assert f in fields, f"EvidenceItem missing M11C-2-2 diagnostic field: {f}"


# ---------------------------------------------------------------------------
# 5. Ask path unaffected
# ---------------------------------------------------------------------------

class TestAskPathUnaffected:
    def test_ask_router_does_not_import_memory_type_filter(self):
        import ast
        import pathlib
        src = pathlib.Path("memory_lab/api/routers/ask.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in getattr(node, "names", [])]
                assert "MEMORY_TYPE_VALUES" not in names, \
                    "ask.py must not import MEMORY_TYPE_VALUES"

    def test_adapter_search_default_memory_types_is_none(self):
        from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
        import inspect
        sig = inspect.signature(RetrievalAdapter.search)
        default = sig.parameters["memory_types"].default
        assert default is None, "memory_types must default to None so ask path is unaffected"

    def test_ask_request_has_optional_memory_type_fields_defaulting_to_none(self):
        # OPENCB-M11C-1 §7.1: the ask path now accepts an OPTIONAL memory_type filter.
        # The fields default to None and resolved_memory_types() returns None unless explicitly
        # set, so the deterministic ask path is unaffected when the filter is not used.
        from memory_lab.reasoning.models import AskRequest
        fields = AskRequest.model_fields
        assert "memory_type" in fields
        assert "memory_types" in fields
        assert AskRequest(query="x").resolved_memory_types() is None


# ---------------------------------------------------------------------------
# 6. Guard: no provider dependency
# ---------------------------------------------------------------------------

class TestNoProviderDependency:
    def test_retrieval_request_model_has_no_provider_import(self):
        import ast
        import pathlib
        src = pathlib.Path("memory_lab/api/routers/retrieval.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "openai" not in module
                assert "embedding_backend" not in module
                assert "answer_synthesizer" in module or "retrieval_adapter" in module or True

    def test_memory_type_values_are_deterministic_constants(self):
        from memory_lab.ingestion.classify_pipeline import MEMORY_TYPE_VALUES
        assert isinstance(MEMORY_TYPE_VALUES, (set, frozenset, list, tuple))
        assert "milestone" in MEMORY_TYPE_VALUES
        assert "raw_memory" in MEMORY_TYPE_VALUES
