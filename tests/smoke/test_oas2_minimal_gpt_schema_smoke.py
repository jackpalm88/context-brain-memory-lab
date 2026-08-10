"""OAS-2 schema smoke — the MINIMAL GPT Actions schema (10 read/answer ops).

GPT tool selection works best with a small, well-described surface; this file
pins that the minimal schema stays minimal, read-only, and GPT-importable:
  M-1  File exists, parses, is OpenAPI 3.x
  M-2  Exactly the ratified 10 operationIds, camelCase
  M-3  Read-only: no write verbs beyond the two POST read-semantics ops
  M-4  Every operation is x-openai-isConsequential: false
  M-5  BearerAuth defined; health opts out (security: [])
  M-6  servers present with a concrete https URL
  M-7  Every operation has a description (tool-selection quality)
  M-8  All $ref targets resolve; no hardcoded secrets
  M-9  answerFromMemory declares the REST truth: status + insufficient_evidence,
       never the MCP-only no_context boolean (GPT UX review 2026-07-10, A1)
  M-10 Every parameter carries a description (A3)
  M-11 Response arrays declare their chaining keys — content_id / decision_id /
       is_current are schema-visible, not opaque objects (A2)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

pytestmark = [pytest.mark.smoke, pytest.mark.provider_optional, pytest.mark.public_safe]

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "openapi" / "gpt-actions.minimal.openapi.yaml"

_EXPECTED_OPERATION_IDS = {
    "checkMemoryHealth",
    "retrieveMemoryEvidence",
    "answerFromMemory",
    "getContentById",
    "listHubs",
    "listDecisions",
    "explainDecision",
    "getDecisionLineage",
    "listCurrentStateAnchors",
    "listDecisionsForContent",
}

# POST here is read-semantics (search/ask bodies), not writes.
_ALLOWED_POST_OPERATIONS = {"retrieveMemoryEvidence", "answerFromMemory"}


@pytest.fixture(scope="module")
def doc() -> Dict[str, Any]:
    assert _SCHEMA_PATH.exists(), f"Schema file not found: {_SCHEMA_PATH}"
    with _SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _operations(doc):
    for path, methods in doc["paths"].items():
        for method, op in methods.items():
            if isinstance(op, dict) and "operationId" in op:
                yield path, method, op


def test_m1_parses_and_is_openapi_3x(doc):
    assert str(doc["openapi"]).startswith("3."), "must be OpenAPI 3.x"
    assert "paths" in doc and "info" in doc and "components" in doc


def test_m2_exactly_the_ratified_ten_operations(doc):
    ids = {op["operationId"] for _, _, op in _operations(doc)}
    assert ids == _EXPECTED_OPERATION_IDS, (
        f"minimal set drifted: extra={ids - _EXPECTED_OPERATION_IDS}, "
        f"missing={_EXPECTED_OPERATION_IDS - ids}"
    )
    for op_id in ids:
        assert re.fullmatch(r"[a-z]+(?:[A-Z][a-z0-9]+)+", op_id), f"not camelCase: {op_id}"


def test_m3_read_only_surface(doc):
    for path, method, op in _operations(doc):
        if method == "get":
            continue
        assert method == "post" and op["operationId"] in _ALLOWED_POST_OPERATIONS, (
            f"write-shaped operation in the minimal GPT schema: {method.upper()} {path}"
        )
    assert not any(m in methods for methods in doc["paths"].values()
                   for m in ("put", "patch", "delete"))


def test_m4_every_operation_is_non_consequential(doc):
    for path, _, op in _operations(doc):
        assert op.get("x-openai-isConsequential") is False, (
            f"{path}: read-only ops must declare x-openai-isConsequential: false"
        )


def test_m5_bearer_auth_and_health_optout(doc):
    schemes = doc["components"]["securitySchemes"]
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"
    assert doc["security"] == [{"BearerAuth": []}]
    health = doc["paths"]["/health"]["get"]
    assert health["security"] == [], "health must not require auth"


def test_m6_concrete_https_server(doc):
    servers = doc.get("servers") or []
    assert servers and servers[0]["url"].startswith("https://"), "GPT Actions require an https server URL"


def test_m7_descriptions_everywhere(doc):
    for path, _, op in _operations(doc):
        assert len(op.get("description", "")) >= 40, (
            f"{path}: GPT tool selection needs a substantive description"
        )
        assert len(op["description"]) <= 300, (
            f"{path}: GPT Actions builder rejects operation descriptions over "
            f"300 chars (got {len(op['description'])})"
        )
        assert op.get("summary"), f"{path}: summary required"


def _op_by_id(doc, operation_id):
    for _, _, op in _operations(doc):
        if op["operationId"] == operation_id:
            return op
    raise AssertionError(f"operation not found: {operation_id}")


def _response_properties(op):
    return op["responses"]["200"]["content"]["application/json"]["schema"].get("properties", {})


def test_m9_answer_envelope_matches_rest_truth(doc):
    props = _response_properties(_op_by_id(doc, "answerFromMemory"))
    assert "no_context" not in props, (
        "no_context is an MCP-layer enrichment; the REST /v1/ask response never carries it"
    )
    # ask_projection.py emits exactly ok | insufficient_evidence | unsupported_intent.
    # The 2026-07-10 fix pinned a fictional 'no_context' status here; the
    # 2026-08-10 release-truth audit (P0-4) corrected schema AND pin together.
    enum = set(props["status"].get("enum", []))
    assert enum == {"ok", "insufficient_evidence", "unsupported_intent"}, (
        f"status enum must match ask_projection.py statuses, got: {sorted(enum)}"
    )
    assert "insufficient_evidence" in props


def test_m10_every_parameter_has_a_description(doc):
    for path, _, op in _operations(doc):
        for param in op.get("parameters", []):
            assert len(param.get("description", "")) >= 20, (
                f"{path}: parameter '{param.get('name')}' needs a substantive description"
            )


def test_m11_response_arrays_declare_chaining_keys(doc):
    schemas = doc["components"]["schemas"]
    for name, keys in {
        "EvidenceItem": ("content_id", "is_current", "current_state_scope"),
        "Citation": ("content_id",),
        "LineageNode": ("decision_id",),
        "CurrentStateAnchor": ("content_id", "scope", "supersedes_content_id"),
    }.items():
        props = schemas[name]["properties"]
        for key in keys:
            assert key in props, f"components.schemas.{name} must declare '{key}'"
    array_refs = {
        "retrieveMemoryEvidence": {"results": "EvidenceItem"},
        "answerFromMemory": {"evidence": "EvidenceItem", "citations": "Citation"},
        "getDecisionLineage": {"ancestors": "LineageNode", "descendants": "LineageNode"},
        "listCurrentStateAnchors": {"anchors": "CurrentStateAnchor"},
    }
    for op_id, fields in array_refs.items():
        props = _response_properties(_op_by_id(doc, op_id))
        for field, schema_name in fields.items():
            ref = props[field]["items"].get("$ref", "")
            assert ref == f"#/components/schemas/{schema_name}", (
                f"{op_id}.{field} items must reference {schema_name}, got: {ref or 'opaque object'}"
            )


def test_m8_refs_resolve_and_no_secrets(doc):
    text = _SCHEMA_PATH.read_text(encoding="utf-8")
    for ref in re.findall(r'\$ref:\s*"#/([^"]+)"', text):
        node: Any = doc
        for part in ref.split("/"):
            assert isinstance(node, dict) and part in node, f"unresolved $ref: #{ref}"
            node = node[part]
    assert not re.search(r"(sk-[A-Za-z0-9]{10,}|password\s*[:=]\s*\S+)", text, re.IGNORECASE)
