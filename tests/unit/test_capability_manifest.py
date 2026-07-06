"""Hermetic drift test — capability manifest vs APPROVED_TOOLS.

The manifest (memory_lab/mcp/capability_manifest.yaml) is the MACHINE layer of
tool semantics; docstrings are the human layer. This test keeps the machine
layer in lockstep with the code: names, signatures, and closed vocabularies.
A tool added/removed/renamed without a manifest update fails here, as does a
manifest entry naming inputs the function does not accept.

Pure-Python; no DB; no provider calls.
"""

import inspect
from pathlib import Path

import pytest
import yaml

from memory_lab.mcp.tools import APPROVED_TOOLS
from memory_lab.version import __version__

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "memory_lab" / "mcp" / "capability_manifest.yaml"

ROLES = {"liveness", "write", "read", "search", "answer", "curate", "govern", "lineage", "diagnose"}
DETERMINISM = {"deterministic", "deterministic_core", "provider_opt_in"}
OUTPUT_KINDS = {"status", "id_envelope", "record", "record_list", "ranked_evidence",
                "answer_envelope", "graph_snapshot", "preview_list", "lineage_tree",
                "timeline", "conflict_list", "ack"}
ROUTING = {"normal", "discouraged", "alias"}
REQUIRED_FIELDS = ("name", "role", "answers", "use_when", "determinism",
                   "required_inputs", "output_kind", "suggested_followups", "failure")

# workspace_id is ambient (resolved from auth/env) — never listed per-tool.
AMBIENT_PARAMS = {"workspace_id"}


def _manifest():
    return yaml.safe_load(MANIFEST_PATH.read_text())


def _entries():
    return {entry["name"]: entry for entry in _manifest()["tools"]}


def test_manifest_parses_and_versions():
    manifest = _manifest()
    assert manifest["manifest_version"] == "0.1"
    assert manifest["opencb_version"] == __version__, (
        "opencb_version must track memory_lab.version.__version__"
    )


def test_manifest_covers_exactly_the_approved_tools():
    names = [e["name"] for e in _manifest()["tools"]]
    assert len(names) == len(set(names)), "duplicate manifest entries"
    assert set(names) == set(APPROVED_TOOLS), (
        f"drift: only-in-manifest={set(names) - set(APPROVED_TOOLS)}, "
        f"only-in-code={set(APPROVED_TOOLS) - set(names)}"
    )


def test_every_entry_has_required_fields_and_vocabularies():
    for name, entry in _entries().items():
        for field in REQUIRED_FIELDS:
            assert field in entry, f"{name}: missing required field {field!r}"
        assert entry["role"] in ROLES, f"{name}: bad role {entry['role']!r}"
        assert entry["determinism"] in DETERMINISM, f"{name}: bad determinism"
        assert entry["output_kind"] in OUTPUT_KINDS, f"{name}: bad output_kind"
        assert entry.get("routing", "normal") in ROUTING, f"{name}: bad routing"
        assert isinstance(entry["answers"], list) and entry["answers"], f"{name}: answers empty"
        assert all(isinstance(a, str) and a.strip() for a in entry["answers"]), f"{name}: blank answer"
        assert isinstance(entry["use_when"], str) and len(entry["use_when"]) >= 20, f"{name}: thin use_when"
        assert isinstance(entry["failure"], str) and len(entry["failure"]) >= 10, f"{name}: thin failure"


def test_followups_reference_approved_tools():
    for name, entry in _entries().items():
        for followup in entry["suggested_followups"]:
            assert followup["tool"] in APPROVED_TOOLS, (
                f"{name}: followup references unknown tool {followup['tool']!r}"
            )
            assert isinstance(followup["when"], str) and followup["when"].strip(), (
                f"{name}: followup without a 'when'"
            )


def test_declared_inputs_exist_in_function_signatures():
    for name, entry in _entries().items():
        params = set(inspect.signature(APPROVED_TOOLS[name]).parameters)
        declared = set(entry["required_inputs"]) | set(entry.get("optional_inputs", []))
        unknown = declared - params
        assert not unknown, f"{name}: manifest declares inputs not in signature: {sorted(unknown)}"


def test_no_default_params_are_declared_required():
    # Every parameter WITHOUT a default (except ambient workspace_id) must appear
    # in required_inputs — the manifest may add semantic requirements (e.g.
    # content, required by contract though the signature defaults it), never fewer.
    for name, entry in _entries().items():
        signature = inspect.signature(APPROVED_TOOLS[name])
        no_default = {
            p.name for p in signature.parameters.values()
            if p.default is inspect.Parameter.empty and p.name not in AMBIENT_PARAMS
        }
        missing = no_default - set(entry["required_inputs"])
        assert not missing, f"{name}: signature-required params absent from manifest: {sorted(missing)}"


def test_honesty_and_routing_markers_present_where_ratified():
    entries = _entries()
    assert entries["update_node_metadata"].get("routing") == "discouraged"
    assert entries["list_graph_snapshot"].get("routing") == "alias"
    for shim in ("update_node_metadata", "classify_content_node",
                 "list_graph_snapshot", "save_and_link_to_hub",
                 "memory_lab_retrieval_search", "list_decision_conflicts"):
        assert entries[shim].get("honest_contract"), f"{shim}: honest_contract required"


def test_provider_opt_in_is_exactly_query_memory():
    # The determinism doctrine: exactly one tool may reach a provider, and only
    # via opt-in. Widening this set is a contract change, not a manifest edit.
    opt_in = {n for n, e in _entries().items() if e["determinism"] == "provider_opt_in"}
    assert opt_in == {"query_memory"}
