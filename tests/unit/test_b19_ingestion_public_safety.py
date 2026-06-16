import ast
from pathlib import Path

MODULE_PATHS = [
    Path("memory_lab/ingestion/extraction.py"),
    Path("memory_lab/ingestion/classifiers.py"),
]

FORBIDDEN_IMPORT_ROOTS = {
    "anthropic",
    "openai",
    "openrouter",
    "requests",
    "httpx",
    "sqlalchemy",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "chromadb",
    "pinecone",
    "qdrant_client",
    "weaviate",
    "faiss",
    "redis",
    "boto3",
    "urllib",
    "socket",
    "subprocess",
}

FORBIDDEN_TEXT_PATTERNS = (
    "embed_one",
    "backfill",
    "knn",
    "APIRouter",
    "private_cb",
    "call_provider",
    "fetch_html",
    "AsyncClient",
    "session.get",
    "requests.get",
    "httpx.",
    "psycopg",
    "sqlite3",
    "chromadb",
    "pinecone",
    "weaviate",
    "qdrant",
    "faiss",
    "hub_store",
    "match_query",
    "create_hub",
    "link_content",
    "tag_evolution",
    "complete_json",
    "LLMRequest",
)


def test_b19_modules_have_no_forbidden_import_roots():
    imported_roots = set()
    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
    assert imported_roots.isdisjoint(FORBIDDEN_IMPORT_ROOTS)


def test_b19_modules_have_no_forbidden_behavior_patterns():
    for path in MODULE_PATHS:
        source = path.read_text()
        for pattern in FORBIDDEN_TEXT_PATTERNS:
            assert pattern not in source


def test_b19_modules_do_not_expose_network_db_or_mutation_methods():
    source = "\n".join(path.read_text() for path in MODULE_PATHS)
    assert "def fetch" not in source
    assert "async def" not in source
    assert ".execute(" not in source
    assert ".fetch(" not in source
    assert "def create" not in source
    assert "def update" not in source
    assert "def delete" not in source
