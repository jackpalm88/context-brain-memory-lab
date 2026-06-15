"""B17 synthetic ingestion fixture pack boundary tests.

These tests intentionally load only local JSON fixtures. They do not import
memory_lab ingestion/classifier/chunker/provider modules and do not access DB,
private Context Brain, embeddings, backfill, graph, or admin operations.
"""
import hashlib
import json
import re
from pathlib import Path

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "b17_ingestion" / "synthetic_ingestion_fixtures.json"

REQUIRED_CASES = {
    "short note",
    "long document",
    "mixed-language content",
    "empty content",
    "low-quality content",
    "duplicate or near-duplicate content",
    "ambiguous domain",
    "hub candidate text",
    "tag candidate text",
    "chunking boundary example",
    "extraction candidate example",
}

FORBIDDEN_LITERAL_PARTS = [
    ("/o", "pt/"),
    ("conting", ".superagents", ".solutions"),
    ("api", ".openai", ".com"),
    ("api", ".anthropic", ".com"),
    ("openrouter", ".ai"),
    ("127", ".0", ".0", ".1"),
]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_./+=-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

PRIVATE_ID_PATTERNS = [
    re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I),
    re.compile(r"\b(workspace|hub|content|user)[_-]?(id)?[:=][A-Za-z0-9_-]{6,}\b", re.I),
]

OPERATION_WORDS = {
    "vector index mutation",
    "admin mutation",
    "provider-backed classification",
    "private cb port",
    "database connection",
}


def load_pack():
    return json.loads(FIXTURE_PATH.read_text())


def all_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from all_strings(item)


def joined_literal(parts):
    return "".join(parts)


def fixture_text_blob(pack):
    return "\n".join(fixture.get("text", "") for fixture in pack["fixtures"])


def test_fixture_pack_loads_and_parses():
    pack = load_pack()
    assert pack["pack_id"] == "syn-b17-ingestion-fixture-pack-v1"
    assert pack["version"] == 1
    assert isinstance(pack["fixtures"], list)
    assert len(pack["fixtures"]) >= 11


def test_all_required_fixture_cases_exist():
    cases = {fixture["case"] for fixture in load_pack()["fixtures"]}
    assert REQUIRED_CASES <= cases


def test_fixture_ids_are_synthetic_and_unique():
    ids = [fixture["id"] for fixture in load_pack()["fixtures"]]
    assert len(ids) == len(set(ids))
    assert all(fixture_id.startswith("syn-b17-") for fixture_id in ids)
    assert all("real" not in fixture_id.lower() and "prod" not in fixture_id.lower() for fixture_id in ids)


def test_fixture_text_contains_no_private_identifiers_or_endpoints():
    text = fixture_text_blob(load_pack())
    lowered = text.lower()
    for parts in FORBIDDEN_LITERAL_PARTS:
        assert joined_literal(parts) not in lowered
    for pattern in PRIVATE_ID_PATTERNS:
        assert not pattern.search(text)


def test_fixture_text_contains_no_secret_looking_values():
    text = fixture_text_blob(load_pack())
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(text)


def test_fixture_text_contains_no_private_paths():
    text = fixture_text_blob(load_pack()).lower()
    assert joined_literal(("/o", "pt/")) not in text
    assert "c:\\users\\" not in text


def test_fixture_text_contains_no_provider_api_keys_or_provider_endpoint_values():
    text = fixture_text_blob(load_pack()).lower()
    assert "sk-" not in text
    for parts in FORBIDDEN_LITERAL_PARTS[2:5]:
        assert joined_literal(parts) not in text


def test_fixture_pack_is_deterministic_json():
    raw = FIXTURE_PATH.read_text()
    parsed = json.loads(raw)
    canonical = json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert raw == canonical
    first_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    second_hash = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert first_hash == second_hash


def test_no_provider_imports_or_calls_are_required():
    pack = load_pack()
    blob = fixture_text_blob(pack).lower()
    forbidden = ["anthropic", "openai", "openrouter", "provider endpoint", "provider api key"]
    assert not any(term in blob for term in forbidden)


def test_no_db_private_cb_access_is_required():
    pack = load_pack()
    blob = fixture_text_blob(pack).lower()
    forbidden = ["postgres", "database url", "private context brain", joined_literal(("conting", ".superagents", ".solutions"))]
    assert not any(term in blob for term in forbidden)


def test_no_embedding_backfill_admin_or_mutation_operation_is_present():
    pack = load_pack()
    text_blob = fixture_text_blob(pack).lower()
    assert not any(term in text_blob for term in OPERATION_WORDS)
    assert "embedding" not in text_blob
    assert "backfill" not in text_blob
    assert "graph mutation" not in text_blob
