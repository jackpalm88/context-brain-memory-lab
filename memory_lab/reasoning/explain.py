from __future__ import annotations

from typing import Any

from memory_lab.context_packs.models import ContextPackBuildResponse
from memory_lab.reasoning.models import ReasoningProviderMetadata, ReasoningRequest, ReasoningTraversalStep

BASE_LIMITATIONS = [
    "B13 structures and explains evidence paths only.",
    "No truth arbitration is performed.",
    "No automatic conflict resolution is performed.",
    "No graph or database mutation is performed by the runtime reasoning path.",
    "Provider-backed synthesis is disabled unless explicitly requested and configured.",
]

BASE_NON_CLAIMS = [
    "no_answer_field",
    "no_verdict",
    "no_forbidden_public_response_fields",
    "no_resolution",
    "no_private_ask_v2_port",
    "no_private_prompt_copy",
    "no_graph_mutation",
    "no_provider_call_by_default",
]


def build_conflict_warnings(context_pack: ContextPackBuildResponse) -> list[str]:
    warnings: list[str] = []
    if context_pack.conflict_candidates:
        warnings.append(f"{len(context_pack.conflict_candidates)} unresolved conflict candidate(s) surfaced; human review required.")
    if context_pack.counterfindings:
        warnings.append(f"{len(context_pack.counterfindings)} counterfinding evidence item(s) preserved for human review without conflict resolution.")
    if context_pack.stale_or_superseded_items:
        warnings.append(f"{len(context_pack.stale_or_superseded_items)} stale/superseded signal(s) surfaced; stale does not mean false.")
    return warnings


def deterministic_explanation(
    *,
    context_pack: ContextPackBuildResponse,
    request: ReasoningRequest,
    traversal_steps: list[ReasoningTraversalStep],
    provider_metadata: ReasoningProviderMetadata,
) -> dict[str, Any]:
    return {
        "summary": "Reasoning was computed from the B12 context pack with deterministic read-only traversal.",
        "evidence_inclusion": {
            "supporting_evidence_count": len(context_pack.supporting_evidence),
            "current_state_signal_count": len(context_pack.current_state_signals),
            "counterfinding_count": len(context_pack.counterfindings),
            "stale_or_superseded_count": len(context_pack.stale_or_superseded_items),
            "rule": "Evidence refs are copied from the context pack and ordered deterministically by rank/content/evidence id.",
        },
        "current_and_stale_signals": {
            "current_signals_explained": "Current-state signals indicate currently marked evidence in public metadata.",
            "stale_signals_explained": "Stale/superseded signals are warnings only and do not invalidate evidence automatically.",
        },
        "conflict_and_counterfinding_warnings": build_conflict_warnings(context_pack),
        "provider_state": {
            "attempted": provider_metadata.attempted,
            "provider": provider_metadata.provider,
            "degraded": provider_metadata.degraded,
            "failure_reason": provider_metadata.failure_reason,
        },
        "limits": {"max_hops": request.max_hops, "hard_cap_max_hops": 3, "traversal_step_count": len(traversal_steps)},
        "scope_boundary": "Public B12 context-pack primitives only; no private ask_v2 prompts or hidden provider calls.",
    }
