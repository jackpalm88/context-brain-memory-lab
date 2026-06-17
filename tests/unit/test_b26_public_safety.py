from pathlib import Path

B26_FILES = (
    Path("memory_lab/persistence/__init__.py"),
    Path("memory_lab/persistence/contracts.py"),
    Path("memory_lab/persistence/results.py"),
    Path("memory_lab/persistence/memory_backend.py"),
)

FORBIDDEN_RUNTIME_PATTERNS = (
    "os.environ",
    "DATABASE_URL",
    "psycopg2",
    "asyncpg",
    "sqlalchemy",
    "sqlite3",
    "connect(",
    "execute(",
    "requests",
    "httpx",
    "complete_json(",
    "complete_text(",
    "embed_text(",
    "embed_batch(",
    "search_memory(",
    "ask_context_brain(",
    "retrieve_context(",
)

FORBIDDEN_AFFIRMATIVE_CLAIMS = (
    "production persistence ready",
    "production db-backed persistence",
    "db-backed production persistence",
    "full context brain ready",
    "private context brain parity",
    "live memory retrieval",
    "live semantic search",
    "provider-backed reasoning",
    "db-backed retrieval",
    "vector search",
    "embeddings generated",
)


def _text(path):
    return path.read_text(encoding="utf-8")


def test_b26_files_exist_and_no_init_typo_file():
    for path in B26_FILES:
        assert path.exists(), path
    assert not Path("memory_lab/persistence/init.py").exists()


def test_forbidden_runtime_patterns_absent_from_b26_files():
    for path in B26_FILES:
        text = _text(path)
        hits = [pattern for pattern in FORBIDDEN_RUNTIME_PATTERNS if pattern in text]
        assert hits == [], f"{path}: {hits}"


def test_required_private_context_metadata_name_is_only_allowed_private_context_hit():
    for path in B26_FILES:
        text = _text(path)
        reduced = text.replace("requires_private_context_brain", "").replace("not_private_context_brain_parity", "")
        assert "private_context" not in reduced


def test_misleading_affirmative_claims_absent_from_b26_files():
    for path in B26_FILES:
        text = _text(path).lower().replace("not_private_context_brain_parity", "")
        hits = [phrase for phrase in FORBIDDEN_AFFIRMATIVE_CLAIMS if phrase in text]
        assert hits == [], f"{path}: {hits}"


def test_b26_does_not_create_forbidden_namespaces_or_runtime_files():
    assert not Path("memory_lab/storage").exists()
    assert not Path("memory_lab/db").exists()
