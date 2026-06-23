import importlib.util
import json
import subprocess
import sys
from pathlib import Path

EXAMPLE_PATH = Path("examples/b31_supplied_text_prompt_flow_smoke.py")
FORBIDDEN_CLAIMS = (
    "production" + " ready",
    "provider-backed" + " answer generation",
    "live llm" + " execution",
    "db/private" + " cb access",
    "live memory retrieval" + " by default",
    "embeddings/vector" + " db execution",
    "full/private" + " context brain parity",
    "release/tag/pypi" + "/build/export completion",
)
REQUIRED_NON_CLAIMS = {
    "not_llm_execution",
    "not_provider_backed_reasoning",
    "not_db_backed_retrieval",
    "not_private_context_brain_parity",
    "not_live_memory_retrieval",
    "not_embeddings_or_vector_db_execution",
    "not_api_mcp_gpt_actions_runtime_deployment",
    "not_release_tag_pypi_build_export_completion",
}


def _load_example_module():
    spec = importlib.util.spec_from_file_location("b31_supplied_text_prompt_flow_smoke", EXAMPLE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_b34_example_run_smoke_returns_bounded_success_summary():
    module = _load_example_module()

    summary = module.run_smoke()

    assert summary["ok"] is True
    assert summary["prompt_package_produced"] is True
    assert summary["request_shape_produced"] is True
    assert summary["tool_names"] == [
        "build_supplied_text_prompt_package",
        "build_supplied_text_prompt_request_shape",
    ]
    assert summary["live_mode_enabled"] is False
    assert summary["backend_name"] == "none"
    assert summary["allow_fake_backend"] is False
    assert REQUIRED_NON_CLAIMS.issubset(set(summary["non_claims"]))
    assert "no_llm_execution" in summary["limitations"]


def test_b34_example_is_runnable_from_public_checkout():
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)

    assert summary["ok"] is True
    assert summary["prompt_package_produced"] is True
    assert summary["request_shape_produced"] is True
    assert summary["live_mode_enabled"] is False
    assert summary["backend_name"] == "none"
    assert REQUIRED_NON_CLAIMS.issubset(set(summary["non_claims"]))


def test_b34_example_source_preserves_public_safe_boundaries():
    source = EXAMPLE_PATH.read_text(encoding="utf-8")
    lowered = source.lower()

    assert "memory_lab.wrappers.bounded_tools" in source
    assert "memory_lab.api" not in source
    assert "memory_lab.mcp" not in source
    assert "memory_lab.providers" not in source
    assert "psycopg" not in source
    assert "requests" not in source
    assert "httpx" not in source
    assert "openai" not in source
    assert "anthropic" not in source
    assert "os" + "." + "environ" not in source
    assert "DATABASE" + "_URL" not in source
    assert "connect" + "(" not in source
    assert "Fast" + "API" not in source
    assert "API" + "Router" not in source
    for claim in FORBIDDEN_CLAIMS:
        assert claim not in lowered
