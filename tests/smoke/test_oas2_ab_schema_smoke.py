"""OAS-2 schema smoke — the canonical two-part CustomGPT Action schema (A + B).

Replaces the removed single "minimal" schema (OpenCB decision
`df97aa73-0730-4e04-bd16-b86845ccb160`, 2026-08-10): A+B is the real
production integration — the split exists ONLY because ChatGPT Actions
enforces <30 tools per schema, not because OpenCB is conceptually two
systems. This file pins that split honestly:
  AB-1  Both files exist, parse, are OpenAPI 3.x
  AB-2  Each file stays under the 30-operation ChatGPT Actions limit
  AB-3  camelCase operationIds; no accidental duplicate within one file
  AB-4  listHubs + getHub are the ONLY operationIds intentionally shared
        across both files (decision `7c422dc5-87f2-4fb5-8ce8-72c07f064d96`)
  AB-5  Every operation is x-openai-isConsequential: false
  AB-6  BearerAuth defined; health opts out where present
  AB-7  servers present, identical placeholder host in both files
  AB-8  Every operation has a description (<=300 chars) and a summary
  AB-9  Every parameter carries a description
  AB-10 All $ref targets resolve; no hardcoded secrets
  AB-11 The decision reference inside each description names the currently
        ACTIVE decision (7c422dc5), not just the superseded origin
        (63b32b15) — guards against the exact staleness this schema had
        before the 2026-08-10 fix
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

pytestmark = [pytest.mark.smoke, pytest.mark.provider_optional, pytest.mark.public_safe]

_DIR = Path(__file__).resolve().parents[2] / "openapi"
_SCHEMA_A = _DIR / "customgpt-action-A-crud-decisions.openapi.yaml"
_SCHEMA_B = _DIR / "customgpt-action-B-discovery-curation.openapi.yaml"

_MAX_OPS_PER_SCHEMA = 30  # ChatGPT Actions platform limit
_EXPECTED_SHARED_OPS = {"listHubs", "getHub"}
_ACTIVE_SPLIT_DECISION = "7c422dc5-87f2-4fb5-8ce8-72c07f064d96"


@pytest.fixture(scope="module", params=[_SCHEMA_A, _SCHEMA_B], ids=["A", "B"])
def doc(request) -> Dict[str, Any]:
    path = request.param
    assert path.exists(), f"Schema file not found: {path}"
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def doc_a() -> Dict[str, Any]:
    return yaml.safe_load(_SCHEMA_A.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def doc_b() -> Dict[str, Any]:
    return yaml.safe_load(_SCHEMA_B.read_text(encoding="utf-8"))


def _operations(doc):
    for path, methods in doc["paths"].items():
        for method, op in methods.items():
            if isinstance(op, dict) and "operationId" in op:
                yield path, method, op


def test_ab1_parses_and_is_openapi_3x(doc):
    assert str(doc["openapi"]).startswith("3.")
    assert "paths" in doc and "info" in doc and "components" in doc


def test_ab2_under_chatgpt_actions_tool_limit(doc):
    op_ids = [op["operationId"] for _, _, op in _operations(doc)]
    assert len(op_ids) < _MAX_OPS_PER_SCHEMA, (
        f"{len(op_ids)} operations exceeds the ChatGPT Actions <30-tool limit"
    )


def test_ab3_camelcase_and_no_internal_duplicates(doc):
    op_ids = [op["operationId"] for _, _, op in _operations(doc)]
    assert len(op_ids) == len(set(op_ids)), f"duplicate operationId within one file: {op_ids}"
    for op_id in op_ids:
        assert re.fullmatch(r"[a-z]+(?:[A-Z][a-z0-9]+)+", op_id), f"not camelCase: {op_id}"


def test_ab4_only_hub_lookup_ops_are_shared(doc_a, doc_b):
    ids_a = {op["operationId"] for _, _, op in _operations(doc_a)}
    ids_b = {op["operationId"] for _, _, op in _operations(doc_b)}
    shared = ids_a & ids_b
    assert shared == _EXPECTED_SHARED_OPS, (
        f"unexpected operationId overlap between A and B: {shared - _EXPECTED_SHARED_OPS}, "
        f"missing expected overlap: {_EXPECTED_SHARED_OPS - shared}"
    )


def test_ab5_every_operation_is_non_consequential(doc):
    for path, _, op in _operations(doc):
        assert op.get("x-openai-isConsequential") is False, (
            f"{path}: must declare x-openai-isConsequential: false"
        )


def test_ab6_bearer_auth_defined(doc):
    schemes = doc["components"]["securitySchemes"]
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"
    assert doc["security"] == [{"BearerAuth": []}]
    health = doc["paths"].get("/health", {}).get("get")
    if health is not None:
        assert health["security"] == [], "health must not require auth"


def test_ab7_servers_present_and_identical_placeholder(doc_a, doc_b):
    servers_a = doc_a.get("servers") or []
    servers_b = doc_b.get("servers") or []
    assert servers_a and servers_a[0]["url"].startswith("https://")
    assert servers_b and servers_b[0]["url"].startswith("https://")
    assert servers_a[0]["url"] == servers_b[0]["url"], (
        "Action A and Action B must point to the same host — they are one "
        "integration split across two files, not two deployments"
    )


def test_ab8_descriptions_and_summaries(doc):
    for path, _, op in _operations(doc):
        assert len(op.get("description", "")) >= 20, f"{path}: needs a substantive description"
        assert len(op["description"]) <= 300, (
            f"{path}: GPT Actions builder rejects operation descriptions over 300 chars"
        )
        assert op.get("summary"), f"{path}: summary required"


def test_ab9_every_parameter_has_a_description(doc):
    for path, _, op in _operations(doc):
        for param in op.get("parameters", []):
            assert len(param.get("description", "")) >= 5, (
                f"{path}: parameter '{param.get('name')}' needs a description"
            )


def test_ab10_refs_resolve_and_no_secrets(doc):
    text = None
    for candidate in (_SCHEMA_A, _SCHEMA_B):
        if yaml.safe_load(candidate.read_text(encoding="utf-8")) == doc:
            text = candidate.read_text(encoding="utf-8")
            break
    assert text is not None
    for ref in re.findall(r'\$ref:\s*"#/([^"]+)"', text):
        node: Any = doc
        for part in ref.split("/"):
            assert isinstance(node, dict) and part in node, f"unresolved $ref: #{ref}"
            node = node[part]
    assert not re.search(r"(sk-[A-Za-z0-9]{10,}|password\s*[:=]\s*\S+)", text, re.IGNORECASE)


def test_ab11_description_names_the_active_split_decision(doc):
    full_text = str(doc["info"]["description"])
    assert _ACTIVE_SPLIT_DECISION in full_text, (
        "schema description must name the ACTIVE split decision "
        f"({_ACTIVE_SPLIT_DECISION}), not just the superseded origin one — "
        "this is the exact staleness the 2026-08-10 fix corrected"
    )
