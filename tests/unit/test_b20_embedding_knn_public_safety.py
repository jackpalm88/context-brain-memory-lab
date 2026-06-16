"""B20 public-safety boundary tests for embedding admin and KNN modules."""

import ast
from pathlib import Path

MODULE_PATHS = (
    Path("memory_lab/ingestion/embedding_admin.py"),
    Path("memory_lab/retrieval/__init__.py"),
    Path("memory_lab/retrieval/knn.py"),
)

FORBIDDEN_IMPORT_ROOTS = {
    "openai",
    "anthropic",
    "openrouter",
    "requests",
    "httpx",
    "urllib",
    "socket",
    "sqlalchemy",
    "psycopg",
    "asyncpg",
    "chromadb",
    "pinecone",
    "qdrant_client",
    "weaviate",
    "faiss",
}

FORBIDDEN_TEXT_PATTERNS = {
    "hub_store",
    "match_query",
    "tag_evolution",
    "backfill_embeddings",
    "embed_one",
    "reextract_batch",
    "create_hub",
    "link_content",
    "APIRouter",
    "private_cb",
    "call_provider",
    "fetch_html",
    "complete_json",
    "LLMRequest",
}


def test_b20_modules_exist_and_are_public_safe_scope_only():
    for path in MODULE_PATHS:
        assert path.exists(), f"missing {path}"
        text = path.read_text()
        assert "caller-supplied" in text or "supplied" in text
        assert "no provider" in text.lower() or "provider-free" in text.lower()


def test_no_forbidden_import_roots_in_b20_modules():
    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module.split(".")[0])
        assert not (set(imports) & FORBIDDEN_IMPORT_ROOTS), f"{path} imports forbidden roots: {set(imports) & FORBIDDEN_IMPORT_ROOTS}"


def test_no_forbidden_text_patterns_in_b20_modules():
    for path in MODULE_PATHS:
        text = path.read_text()
        hits = sorted(pattern for pattern in FORBIDDEN_TEXT_PATTERNS if pattern in text)
        assert hits == [], f"{path} contains forbidden public-safety patterns: {hits}"


def test_no_api_router_or_provider_db_callable_shapes_added():
    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name.lower()
                assert "route" not in name
                assert "provider" not in name
                assert "database" not in name
                assert "mutation" not in name
            if isinstance(node, ast.Call):
                called = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                assert called not in {"app.post", "app.get", "router.post", "router.get"}
                assert "connect" not in called.lower()
                assert "request" not in called.lower()
