"""Shared B24 capability metadata for bounded supplied-input wrappers."""

from __future__ import annotations

from typing import Any, Mapping

B24_WRAPPER_MODE = "deterministic_public_safe_supplied_input_only"
B24_INPUT_SCOPE = "caller_supplied_payload_only"

SHARED_LIMITATIONS: tuple[str, ...] = (
    "caller_supplied_input_only",
    "deterministic_public_safe_processing_only",
    "no_live_backend",
    "no_db_access",
    "no_private_context_brain_access",
    "no_provider_call",
    "no_embeddings_generated",
    "no_vector_db_query",
    "no_stored_content_fetch",
    "not_a_production_deployment",
)

SHARED_NON_CLAIMS: tuple[str, ...] = (
    "not_production_mcp_readiness",
    "not_gpt_actions_production_readiness",
    "not_full_context_brain_readiness",
    "not_private_context_brain_parity",
    "not_live_memory_retrieval",
    "not_live_semantic_search",
    "not_provider_backed_intelligence",
    "not_semantic_truth_validation",
    "not_production_dlp",
    "not_auth_or_secrets_layer",
)

TOOL_NAMES: tuple[str, ...] = (
    "validate_supplied_structured_response",
    "score_supplied_ingestion_signals",
    "evaluate_supplied_circuit_state",
    "rank_supplied_context_candidates",
    "build_supplied_prompt_package",
)


def capability_metadata(capability: str, degraded_reason: str | None = None) -> dict[str, Any]:
    """Return the mandatory B24 top-level metadata block for a wrapper."""
    return {
        "capability": capability,
        "mode": B24_WRAPPER_MODE,
        "input_scope": B24_INPUT_SCOPE,
        "live_backend_used": False,
        "requires_provider": False,
        "requires_db": False,
        "requires_private_context_brain": False,
        "uses_embeddings": False,
        "uses_vector_db": False,
        "mutates_state": False,
        "limitations": list(SHARED_LIMITATIONS),
        "non_claims": list(SHARED_NON_CLAIMS),
        "degraded_reason": degraded_reason,
    }


def attach_metadata(payload: Mapping[str, Any], capability: str, degraded_reason: str | None = None) -> dict[str, Any]:
    """Copy a result payload and attach mandatory B24 capability metadata."""
    out = dict(payload)
    out["capability_metadata"] = capability_metadata(capability, degraded_reason)
    return out
