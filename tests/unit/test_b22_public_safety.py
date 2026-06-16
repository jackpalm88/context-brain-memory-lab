import ast
from pathlib import Path

B22_FILES = [
    Path("memory_lab/reasoning/llm_executor.py"),
    Path("memory_lab/reasoning/structured_validation.py"),
]

FORBIDDEN_IMPORTS = {
    "anthropic",
    "openai",
    "httpx",
    "requests",
    "aiohttp",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "sqlalchemy",
    "pgvector",
    "qdrant",
    "pinecone",
    "weaviate",
    "chromadb",
    "app.services",
    "memory_lab.providers.anthropic",
    "memory_lab.providers.openai_embedding",
    "memory_lab.ingestion.scorer",
    "memory_lab.api.routers",
}

FORBIDDEN_PATTERNS = [
    "DATABASE_URL",
    "API_KEY",
    "os.environ",
    "complete_json(",
    "complete_text(",
    "classify(",
    "summarize(",
    "call_with_breaker(",
    "INSERT",
    "UPDATE",
    "DELETE",
    "https://api.",
    "api.anthropic",
    "api.openai",
    "governance_event",
    "tier mutation",
    "vector index mutation",
]

PRIVATE_PROMPT_FRAGMENTS = [
    "EVIDENCE (numbered for citation):",
    "YOUR RESPONSE (valid JSON only",
    "Substantive answer without claims structure",
]


def _source(path):
    return path.read_text(encoding="utf-8")


def test_b22_modules_have_no_forbidden_imports():
    for path in B22_FILES:
        tree = ast.parse(_source(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        lowered = {item.lower() for item in imports}
        assert not (lowered & FORBIDDEN_IMPORTS), (path, lowered & FORBIDDEN_IMPORTS)


def test_b22_modules_have_no_forbidden_behavior_patterns():
    for path in B22_FILES:
        src = _source(path)
        hits = [pattern for pattern in FORBIDDEN_PATTERNS if pattern in src]
        assert hits == [], (path, hits)


def test_b22_modules_do_not_copy_private_prompt_fragments():
    for path in B22_FILES:
        src = _source(path)
        hits = [pattern for pattern in PRIVATE_PROMPT_FRAGMENTS if pattern in src]
        assert hits == [], (path, hits)


def test_b22_modules_keep_public_safe_non_claims():
    llm_src = _source(B22_FILES[0])
    validator_src = _source(B22_FILES[1])
    assert "no_live_provider_call_by_default" in llm_src
    assert "no_runtime_circuit_mutation" in llm_src
    assert "no_semantic_truth_validation" in validator_src
    assert "no_provider_backed_judging" in validator_src
