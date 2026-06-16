import ast
from pathlib import Path

MODULE_PATHS = (
    Path("memory_lab/ingestion/ingestion_scoring.py"),
    Path("memory_lab/governance/tier_routing_plan.py"),
    Path("memory_lab/governance/circuit_breaker.py"),
)

FORBIDDEN_IMPORT_ROOTS = {"anthropic", "openai", "openrouter", "requests", "httpx", "aiohttp", "psycopg", "psycopg2", "asyncpg", "sqlalchemy", "chromadb", "qdrant", "pinecone", "faiss", "redis"}
FORBIDDEN_PROJECT_IMPORTS = {"memory_lab.api", "memory_lab.providers.anthropic", "memory_lab.providers.openai_embedding"}
FORBIDDEN_TEXT_PATTERNS = {"DATABASE_URL", "os.environ", "connect(", "execute(", "INSERT", "UPDATE", "DELETE", "emit_event(", "call_with_breaker(", "complete_json(", "embed_text(", "embed_batch("}


def imports_for(path):
    tree = ast.parse(path.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def test_b21_modules_exist_and_scope_text_is_public_safe():
    for path in MODULE_PATHS:
        assert path.exists(), f"missing {path}"
        text = path.read_text().lower()
        assert "caller-supplied" in text or "supplied" in text
        assert "no durable" in text


def test_no_forbidden_import_roots_or_project_imports_in_b21_modules():
    for path in MODULE_PATHS:
        imports = imports_for(path)
        roots = {name.split(".")[0] for name in imports}
        assert not (roots & FORBIDDEN_IMPORT_ROOTS), f"{path} imports forbidden roots: {roots & FORBIDDEN_IMPORT_ROOTS}"
        assert not (set(imports) & FORBIDDEN_PROJECT_IMPORTS), f"{path} imports forbidden project modules: {set(imports) & FORBIDDEN_PROJECT_IMPORTS}"


def test_no_forbidden_text_patterns_in_b21_modules():
    for path in MODULE_PATHS:
        text = path.read_text()
        hits = sorted(pattern for pattern in FORBIDDEN_TEXT_PATTERNS if pattern in text)
        assert hits == [], f"{path} contains forbidden public-safety patterns: {hits}"


def test_no_autonomous_governance_mutation_or_live_call_shapes():
    forbidden_name_fragments = ("emit", "mutate", "database", "wrapper")
    for path in MODULE_PATHS:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name.lower()
                assert not any(fragment in name for fragment in forbidden_name_fragments)
            if isinstance(node, ast.Call):
                called = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                assert "request" not in called.lower()
                assert "connect" not in called.lower()
                assert "complete" not in called.lower()
                assert "embed" not in called.lower()
