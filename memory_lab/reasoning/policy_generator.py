from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReasoningPolicy:
    intent: str
    top_k: int
    require_citations: bool
    min_evidence_items: int
    fallback_behavior: str
    insufficient_evidence_behavior: str
    snippet_char_limit: int = 320


def policy_for_intent(intent: str, requested_top_k: int = 5) -> ReasoningPolicy:
    """Create deterministic public policy from intent."""
    safe_top_k = max(1, min(int(requested_top_k or 5), 10))
    if intent == "unknown":
        return ReasoningPolicy(
            intent=intent,
            top_k=min(safe_top_k, 5),
            require_citations=False,
            min_evidence_items=0,
            fallback_behavior="unsupported_intent",
            insufficient_evidence_behavior="ask_for_clearer_question",
        )
    if intent in {"compare", "synthesis"}:
        return ReasoningPolicy(
            intent=intent,
            top_k=safe_top_k,
            require_citations=True,
            min_evidence_items=2,
            fallback_behavior="partial_or_insufficient_evidence",
            insufficient_evidence_behavior="insufficient_workspace_evidence",
        )
    if intent in {"summarize", "find"}:
        return ReasoningPolicy(
            intent=intent,
            top_k=safe_top_k,
            require_citations=True,
            min_evidence_items=1,
            fallback_behavior="insufficient_evidence",
            insufficient_evidence_behavior="insufficient_workspace_evidence",
        )
    return ReasoningPolicy(
        intent="factual",
        top_k=min(safe_top_k, 5),
        require_citations=True,
        min_evidence_items=1,
        fallback_behavior="insufficient_evidence",
        insufficient_evidence_behavior="insufficient_workspace_evidence",
    )
