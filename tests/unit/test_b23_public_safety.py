from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
B23_MODULES = [ROOT / "memory_lab/retrieval/search_by_purpose.py", ROOT / "memory_lab/retrieval/context_candidates.py", ROOT / "memory_lab/reasoning/prompt_package.py"]
FORBIDDEN = ["psycopg2", "asyncpg", "requests", "httpx", "openai", "anthropic", "chromadb", "pgvector", "sqlalchemy", "socket", "subprocess", "memory_lab.context_packs.service", "memory_lab.api", "memory_lab.providers.anthropic", "memory_lab.providers.openai_embedding", "memory_lab.ingestion.scorer", "os.environ", "DATABASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "content_items", "SELECT", "INSERT", "UPDATE", "DELETE", "complete_text(", "complete_json(", "embed_text(", "embed_batch(", "call_with_breaker("]

def test_b23_modules_have_no_forbidden_imports_or_runtime_patterns():
    for module in B23_MODULES:
        text = module.read_text(encoding="utf-8")
        for pattern in FORBIDDEN:
            assert pattern not in text, f"{pattern} found in {module}"

def test_b23_modules_do_not_wire_api_or_wrappers():
    for module in B23_MODULES:
        text = module.read_text(encoding="utf-8")
        assert "@app." not in text
        assert "FastAPI" not in text
        assert "MCP" not in text
        assert "GPT Actions" not in text
