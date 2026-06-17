from pathlib import Path

B25_MODULES = (
    Path("memory_lab/governance/state.py"),
    Path("memory_lab/governance/workspace.py"),
    Path("memory_lab/governance/state_events.py"),
)

FORBIDDEN_PATTERNS = (
    "requests",
    "httpx",
    "openai",
    "anthropic",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "sqlalchemy",
    "pgvector",
    "chromadb",
    "qdrant",
    "pinecone",
    "weaviate",
    "socket",
    "subprocess",
    "FastAPI",
    "APIRouter",
    "FastMCP",
    "DATABASE_URL",
    "os.environ",
    "connect(",
    "execute(",
    "INSERT",
    "UPDATE",
    "DELETE",
    "emit_event(",
    "search_memory",
    "ask_context_brain",
    "retrieve_context",
    "semantic_search",
    "private_context_search",
)


def test_b25_modules_contain_no_forbidden_runtime_imports_or_patterns():
    for module_path in B25_MODULES:
        text = module_path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            assert pattern not in text, f"{pattern!r} found in {module_path}"


def test_b25_non_claims_and_limitations_are_explicit():
    state_text = Path("memory_lab/governance/state.py").read_text(encoding="utf-8")
    required = (
        "caller_supplied_input_only",
        "deterministic_public_safe_validation_only",
        "data_only_governance_state_contract",
        "no_storage_mutation",
        "no_db_access",
        "no_provider_call",
        "no_private_context_brain_access",
        "no_live_tenant_lookup",
        "no_auth_or_rbac_enforcement",
        "not_api_runtime",
        "not_production_governance_runtime",
        "not_production_ready",
        "not_db_backed_persistence",
        "not_live_governance_lifecycle",
        "not_full_context_brain_parity",
        "not_private_context_brain_parity",
        "not_live_memory_retrieval",
        "not_provider_backed_intelligence",
        "not_mcp_or_gpt_actions_production_readiness",
    )
    for token in required:
        assert token in state_text
