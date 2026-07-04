"""OAS-1 schema smoke tests — validate public OpenAPI schema without a live server.

Gate: OAS-1
Scope: tests/smoke/test_oas1_schema_smoke.py

What is tested (import/parse smoke — no live API, no DB, no network):
  OAS-1  Schema file exists at expected path
  OAS-2  Schema is valid YAML (parseable)
  OAS-3  Schema is OpenAPI 3.x (openapi key present)
  OAS-4  Required top-level keys present (info, paths, components)
  OAS-5  All required public operationIds present
  OAS-6  No admin/internal paths present
  OAS-7  No hardcoded secrets (no literal token/password values)
  OAS-8  All paths have at least one response defined
  OAS-9  SecuritySchemes defined (BearerAuth)
  OAS-10 GPT_ACTIONS.md exists and references demo seed path
  OAS-11 GPT_ACTIONS.md references MCP alternative
  OAS-12 All $ref targets resolve within the document
  OAS-13 Health endpoint marked security: [] (no auth required)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

# ── Paths ──────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parent.parent.parent
_SCHEMA_PATH = _REPO_ROOT / "openapi" / "context-brain-actions.public.openapi.yaml"
_GPT_ACTIONS_PATH = _REPO_ROOT / "docs" / "GPT_ACTIONS.md"

# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def schema_doc() -> Dict[str, Any]:
    """Load and parse the OpenAPI YAML once per module."""
    assert _SCHEMA_PATH.exists(), f"Schema file not found: {_SCHEMA_PATH}"
    with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def schema_text() -> str:
    with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def gpt_actions_text() -> str:
    assert _GPT_ACTIONS_PATH.exists(), f"GPT_ACTIONS.md not found: {_GPT_ACTIONS_PATH}"
    return _GPT_ACTIONS_PATH.read_text(encoding="utf-8")


# ── Required operationIds ──────────────────────────────────────────────────

_REQUIRED_OPERATION_IDS = {
    # health
    "health_check",
    # content
    "create_content",
    "get_content",
    "get_content_metadata",
    "set_quick_summary",
    "classify_content_node",
    # hubs
    "create_hub",
    "list_hubs",
    "get_hub",
    "update_hub",
    "link_content_to_hub",
    # edges
    "create_hub_edge",
    "list_hub_edges",
    "get_hub_edge",
    "archive_hub_edge",
    # retrieval
    "search_raw_chunks",
    # ask
    "query_memory",
    # decisions
    "create_decision_memory",
    "list_decisions",
    "explain_decision",
    "get_decision_lineage",
    "update_decision_status",
    "list_decision_conflicts",
    "get_decision_timeline",
    # graph
    "get_graph_snapshot",
    "load_graph_node_full",
    "search_graph_preview",
}

# ── Excluded path prefixes ─────────────────────────────────────────────────

_EXCLUDED_PREFIXES = [
    "/admin",
    "/v1/reasoning",
    "/v1/context-packs",
    "/v1/graph/health",
    "/v1/graph/alias-candidates",
]

# Partial match for hub recall-health
_EXCLUDED_PATTERNS = [
    re.compile(r"/v1/hubs/[^/]+/recall-health"),
    re.compile(r"/admin/"),
]

# ── Secret patterns (no literal secrets in schema) ────────────────────────

_SECRET_PATTERNS = [
    re.compile(r'(?i)(bearer|token)\s*:\s*[a-zA-Z0-9_\-]{20,}'),
    re.compile(r'(?i)password\s*=\s*["\'][^"\']{6,}'),
    re.compile(r'(?i)api[_-]?key\s*=\s*["\'][a-zA-Z0-9]{16,}'),
]

# ── Helper ────────────────────────────────────────────────────────────────

def _collect_operation_ids(paths: dict) -> set[str]:
    """Walk paths → methods → operationId."""
    ids = set()
    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method in {"get", "post", "put", "patch", "delete", "options", "head"} and isinstance(op, dict):
                oid = op.get("operationId")
                if oid:
                    ids.add(oid)
    return ids


def _collect_refs(obj: Any, found: set[str] | None = None) -> set[str]:
    """Recursively collect all $ref values in a document."""
    if found is None:
        found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "$ref" and isinstance(v, str):
                found.add(v)
            else:
                _collect_refs(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_refs(item, found)
    return found


def _resolve_local_ref(ref: str, doc: dict) -> bool:
    """Return True if a local $ref (#/...) resolves within doc."""
    if not ref.startswith("#/"):
        return True  # external refs not validated
    parts = ref.lstrip("#/").split("/")
    node: Any = doc
    for part in parts:
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


# ── Tests ──────────────────────────────────────────────────────────────────

def test_oas1_schema_file_exists():
    """OAS-1: schema file exists at expected path."""
    assert _SCHEMA_PATH.exists(), f"Missing: {_SCHEMA_PATH}"


def test_oas2_schema_valid_yaml(schema_doc):
    """OAS-2: schema is valid YAML."""
    assert isinstance(schema_doc, dict), "Parsed schema must be a dict"


def test_oas3_openapi_version_present(schema_doc):
    """OAS-3: openapi key indicates OpenAPI 3.x."""
    version = schema_doc.get("openapi", "")
    assert isinstance(version, str), "openapi key must be a string"
    assert version.startswith("3."), f"Expected OpenAPI 3.x, got: {version!r}"


def test_oas4_required_top_level_keys(schema_doc):
    """OAS-4: required top-level keys present."""
    for key in ("info", "paths", "components"):
        assert key in schema_doc, f"Missing top-level key: {key!r}"


def test_oas5_required_operation_ids_present(schema_doc):
    """OAS-5: all required public operationIds present."""
    paths = schema_doc.get("paths", {})
    found = _collect_operation_ids(paths)
    missing = _REQUIRED_OPERATION_IDS - found
    assert not missing, (
        f"Missing operationIds: {sorted(missing)}\n"
        f"Found: {sorted(found)}"
    )


def test_oas6_no_admin_internal_paths(schema_doc):
    """OAS-6: admin and internal paths excluded."""
    paths = schema_doc.get("paths", {})
    violations = []
    for path in paths:
        for prefix in _EXCLUDED_PREFIXES:
            if path.startswith(prefix):
                violations.append(path)
        for pattern in _EXCLUDED_PATTERNS:
            if pattern.search(path):
                violations.append(path)
    assert not violations, f"Admin/internal paths found in public schema: {violations}"


def test_oas7_no_hardcoded_secrets(schema_text):
    """OAS-7: no literal secret values in schema."""
    for pattern in _SECRET_PATTERNS:
        match = pattern.search(schema_text)
        assert not match, f"Potential secret found in schema: {match.group()!r}"


def test_oas8_all_paths_have_responses(schema_doc):
    """OAS-8: every operation has at least one response."""
    paths = schema_doc.get("paths", {})
    violations = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(op, dict):
                continue
            responses = op.get("responses", {})
            if not responses:
                violations.append(f"{method.upper()} {path}")
    assert not violations, f"Operations without responses: {violations}"


def test_oas9_bearer_auth_defined(schema_doc):
    """OAS-9: BearerAuth security scheme defined in components."""
    schemes = (
        schema_doc
        .get("components", {})
        .get("securitySchemes", {})
    )
    assert "BearerAuth" in schemes, "BearerAuth not found in components.securitySchemes"
    scheme = schemes["BearerAuth"]
    assert scheme.get("type") == "http", "BearerAuth type must be 'http'"
    assert scheme.get("scheme") == "bearer", "BearerAuth scheme must be 'bearer'"


def test_oas10_gpt_actions_md_exists_and_seeds(gpt_actions_text):
    """OAS-10: GPT_ACTIONS.md exists and references demo seed path."""
    assert "seed_demo.sh" in gpt_actions_text, "GPT_ACTIONS.md must reference seed_demo.sh"
    assert "scripts/" in gpt_actions_text, "GPT_ACTIONS.md must reference scripts/ directory"


def test_oas11_gpt_actions_md_mcp_note(gpt_actions_text):
    """OAS-11: GPT_ACTIONS.md mentions MCP alternative."""
    assert "MCP" in gpt_actions_text, "GPT_ACTIONS.md must mention MCP alternative"
    assert "/mcp" in gpt_actions_text.lower() or "mcp" in gpt_actions_text.lower(), \
        "GPT_ACTIONS.md must reference MCP endpoint"


def test_oas12_all_refs_resolve(schema_doc):
    """OAS-12: all local $ref targets resolve within the document."""
    refs = _collect_refs(schema_doc)
    broken = [r for r in refs if r.startswith("#/") and not _resolve_local_ref(r, schema_doc)]
    assert not broken, f"Broken $ref targets: {broken}"


def test_oas13_health_no_auth(schema_doc):
    """OAS-13: /health GET is marked security: [] (no auth required)."""
    health_path = schema_doc.get("paths", {}).get("/health", {})
    get_op = health_path.get("get", {})
    security = get_op.get("security")
    assert security is not None, "/health GET must have explicit security: [] (found none)"
    assert security == [], f"/health GET must have security: [] (found {security!r})"
