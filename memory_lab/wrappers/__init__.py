"""B24 bounded wrapper adapter package.

The public entry points in this package are deterministic contract adapters over
caller-supplied payloads. They do not deploy MCP, GPT Actions, API routes, data
stores, providers, embeddings, or vector systems.
"""

from __future__ import annotations

from .bounded_tools import (
    build_supplied_prompt_package,
    build_supplied_text_prompt_package,
    build_supplied_text_prompt_request_shape,
    evaluate_supplied_circuit_state,
    rank_supplied_context_candidates,
    score_supplied_ingestion_signals,
    validate_supplied_structured_response,
)

__all__ = [
    "validate_supplied_structured_response",
    "score_supplied_ingestion_signals",
    "evaluate_supplied_circuit_state",
    "rank_supplied_context_candidates",
    "build_supplied_prompt_package",
    "build_supplied_text_prompt_package",
    "build_supplied_text_prompt_request_shape",
]
