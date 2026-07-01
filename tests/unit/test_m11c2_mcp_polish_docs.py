"""M11C-2-4 MCP polish and documentation contract tests."""

from fastapi.testclient import TestClient

from memory_lab.api.main import app
from memory_lab.mcp.tools import memory_lab_retrieval_search


def test_mcp_retrieval_search_docstring_documents_debug_and_boundaries():
    doc = memory_lab_retrieval_search.__doc__ or ""

    assert "search_raw_chunks" in doc
    assert "debug_metadata.stage_metrics" in doc
    assert "debug_metadata" in doc
    assert "adapter_search" in doc
    assert "only_clean" in doc
    assert "accepted no-op" in doc
    assert "memory_type" in doc
    assert "does not forward" in doc


def test_retrieval_openapi_documents_safe_debug_and_only_clean_semantics():
    schema = TestClient(app).get("/openapi.json").json()
    retrieval_schema = schema["components"]["schemas"]["RetrievalRequest"]
    props = retrieval_schema["properties"]

    assert "safe debug_metadata" in props["debug"]["description"]
    assert "omitted" in props["debug"]["description"]
    assert "accepted no-op" in props["only_clean"]["description"]
    assert "private clean/dirty" in props["only_clean"]["description"]
    assert "Mutually exclusive" in props["memory_type"]["description"]
    assert "Mutually exclusive" in props["memory_types"]["description"]

    op = schema["paths"]["/v1/retrieval/search"]["post"]
    assert op["summary"] == "Search raw retrieval evidence"
    assert "does not change retrieval, ranking" in op["description"]
