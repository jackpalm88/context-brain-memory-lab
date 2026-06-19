from pathlib import Path

from memory_lab.wrappers.bounded_tools import build_supplied_text_prompt_request_shape
from memory_lab.wrappers.examples import sample_payloads


FALSE_FIELDS = (
    "live_backend_used",
    "requires_provider",
    "requires_db",
    "requires_private_context_brain",
    "uses_embeddings",
    "uses_vector_db",
    "mutates_state",
    "executes_llm",
    "production_runtime",
    "api_runtime",
    "mcp_runtime",
)
FORBIDDEN_RUNTIME_MARKERS = (
    "execute_llm_request(",
    "complete_json(",
    "complete_text(",
    "embed_text(",
    "search_memory(",
    "ask_context_brain(",
    "private_cb_search(",
    "DATABASE_URL",
    "FastAPI",
    "APIRouter",
    "FastMCP",
    "requests.",
    "httpx.",
    "psycopg2",
)


def test_b31_capability_metadata_keeps_runtime_false_fields_false():
    result = build_supplied_text_prompt_request_shape(sample_payloads()["build_supplied_text_prompt_request_shape"])
    meta = result["capability_metadata"]

    for field in FALSE_FIELDS:
        assert meta[field] is False
    assert "no_provider_call" in meta["limitations"]
    assert "no_db_access" in meta["limitations"]
    assert "no_private_context_brain_access" in meta["limitations"]
    assert "not_full_context_brain_readiness" in meta["non_claims"]
    assert "not_private_context_brain_parity" in meta["non_claims"]


def test_b31_wrapper_source_has_no_runtime_provider_db_or_private_cb_behavior():
    text = Path("memory_lab/wrappers/bounded_tools.py").read_text()
    for marker in FORBIDDEN_RUNTIME_MARKERS:
        assert marker not in text
    assert "backend=None" in text
    assert "use_supplied_backend=False" in text
    assert "persist_to_supplied_backend=False" in text
