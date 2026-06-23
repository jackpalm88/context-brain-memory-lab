"""Public-safe B31 supplied-text wrapper flow smoke example.

Run from a public checkout with:

    python examples/b31_supplied_text_prompt_flow_smoke.py

This example uses caller-supplied sample text only. It does not open a network
connection, read private configuration, call a provider, query a database, use
Context Brain private memory, start an API/MCP/GPT Actions runtime, generate
embeddings, or mutate durable state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from memory_lab.wrappers.bounded_tools import (  # noqa: E402
    build_supplied_text_prompt_package,
    build_supplied_text_prompt_request_shape,
)

SAMPLE_PAYLOAD: dict[str, Any] = {
    "workspace_id": "550e8400-e29b-41d4-a716-446655440000",
    "content_id": "public-b31-wrapper-smoke-sample",
    "title": "Public B31 supplied-text wrapper smoke sample",
    "source_ref": "public_example_fixture",
    "text": (
        "B31 exposes the B30 supplied-text prompt flow as a bounded wrapper "
        "contract over caller-supplied text. The flow can create a prompt "
        "package and a disabled request shape without live provider execution, "
        "database access, private Context Brain retrieval, or runtime API/MCP "
        "deployment. "
        * 3
    ),
    "metadata": {"source_type": "public_example", "classification": "sample"},
    "query": "What does the B31 supplied-text wrapper flow prove?",
    "purpose": "public usability smoke",
    "instructions": "Answer only from supplied evidence; this example does not execute an LLM.",
    "max_context_chars": 1400,
    "snippet_chars": 240,
    "max_tokens": 256,
    "temperature": 0.0,
}

NON_CLAIMS = (
    "not_llm_execution",
    "not_provider_backed_reasoning",
    "not_db_backed_retrieval",
    "not_private_context_brain_parity",
    "not_live_memory_retrieval",
    "not_embeddings_or_vector_db_execution",
    "not_api_mcp_gpt_actions_runtime_deployment",
    "not_release_tag_pypi_build_export_completion",
)


def run_smoke() -> dict[str, Any]:
    """Run the deterministic wrapper smoke and return a compact summary."""
    package_result = build_supplied_text_prompt_package(SAMPLE_PAYLOAD)
    request_result = build_supplied_text_prompt_request_shape(SAMPLE_PAYLOAD)
    llm_request = request_result.get("llm_request") or {}

    summary = {
        "ok": bool(package_result.get("ok")) and bool(request_result.get("ok")),
        "package_status": package_result.get("status"),
        "request_status": request_result.get("status"),
        "prompt_package_produced": package_result.get("prompt_package") is not None,
        "request_shape_produced": request_result.get("llm_request") is not None,
        "live_mode_enabled": llm_request.get("live_mode_enabled"),
        "backend_name": llm_request.get("backend_name"),
        "allow_fake_backend": llm_request.get("allow_fake_backend"),
        "tool_names": [package_result.get("tool_name"), request_result.get("tool_name")],
        "non_claims": sorted(set(NON_CLAIMS) | set(package_result.get("non_claims", ())) | set(request_result.get("non_claims", ())) | set(llm_request.get("non_claims", ()))),
        "limitations": sorted(set(package_result.get("limitations", ())) | set(request_result.get("limitations", ())) | set(llm_request.get("limitations", ()))),
    }

    if not summary["ok"]:
        raise SystemExit("B31 wrapper smoke failed: wrapper result was not ok")
    if not summary["prompt_package_produced"]:
        raise SystemExit("B31 wrapper smoke failed: prompt package was not produced")
    if not summary["request_shape_produced"]:
        raise SystemExit("B31 wrapper smoke failed: request shape was not produced")
    if summary["live_mode_enabled"] is not False:
        raise SystemExit("B31 wrapper smoke failed: request shape is not disabled")
    if summary["backend_name"] != "none":
        raise SystemExit("B31 wrapper smoke failed: backend is not disabled")
    if summary["allow_fake_backend"] is not False:
        raise SystemExit("B31 wrapper smoke failed: fake backend is enabled")

    return summary


def main() -> None:
    print(json.dumps(run_smoke(), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
