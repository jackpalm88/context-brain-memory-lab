from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class IntentDetection:
    intent: str
    confidence: float
    matched_rule: str


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def detect_intent(query: str) -> IntentDetection:
    """Deterministic public intent detector. No provider calls."""
    text = (query or "").strip().lower()
    if not text:
        return IntentDetection(intent="unknown", confidence=0.0, matched_rule="empty")

    if _has_any(text, ("compare", "difference", "differences", "tradeoff", "trade-off")) or re.search(r"\bvs\.?\b", text):
        return IntentDetection(intent="compare", confidence=0.8, matched_rule="compare_terms")
    if _has_any(text, ("summarize", "summary", "recap", "condense", "main points")):
        return IntentDetection(intent="summarize", confidence=0.82, matched_rule="summarize_terms")
    if _has_any(text, ("find", "locate", "search for", "show me", "retrieve")):
        return IntentDetection(intent="find", confidence=0.78, matched_rule="find_terms")
    if _has_any(text, ("theme", "themes", "pattern", "patterns", "synthesize", "implications")):
        return IntentDetection(intent="synthesis", confidence=0.72, matched_rule="synthesis_terms")
    if re.match(r"^(what|who|when|where|why|how)\b", text) or text.endswith("?"):
        return IntentDetection(intent="factual", confidence=0.7, matched_rule="question_shape")
    if len(text.split()) <= 2:
        return IntentDetection(intent="find", confidence=0.55, matched_rule="short_query")
    return IntentDetection(intent="factual", confidence=0.5, matched_rule="default_factual")
