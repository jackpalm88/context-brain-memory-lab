"""Intent Router — the ratified deterministic routing policy (router v0).

Question -> Intent -> Tool Plan. No LLM planning: keyword/shape matching only
(an LLM may pre-classify upstream; then intent.matched_by=llm_preclassified).
Conditional follow-ups name their trigger signal; the executor evaluates them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

MAX_CALLS_DEFAULT = 6
MAX_CALLS_DIAGNOSE = 4

# Mirrors the kernel's historical-term list (FV-FIX-3) so framework and kernel
# agree on what "historical" means.
_HISTORICAL_TERMS = (
    "previously", "before", "earlier", "originally", "used to", "history",
    "historical", "historically", "at first", "in the past", "old decision",
    "first decision",
)

_TRIGGERS = {
    "save_memory": ("remember", "save", "note that", "record decision", "record that"),
    "diagnose_system_state": ("memory healthy", "pending review", "unresolved conflict",
                              "system state", "pending proposals"),
    "verify_current_state": ("current", "still valid", "still current", "use now",
                             "do we use now", "which do we use"),
    "explain_decision": ("why did we", "explain decision", "rationale for", "why was"),
    "latest_decisions": ("what was decided", "recent decisions", "decision timeline",
                         "decisions recently", "catch me up on decisions"),
    "relationship_map": ("relate", "relates", "connections between", "map of", "graph of",
                         "relationship"),
}
# Priority: writes and health are never accidental; specific reads beat generic.
_PRIORITY = ["save_memory", "diagnose_system_state", "verify_current_state",
             "explain_decision", "latest_decisions", "relationship_map"]


@dataclass(frozen=True)
class PlanStep:
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    args_from: Optional[str] = None   # executor extractor name (deterministic registry)
    condition: Optional[str] = None   # executor predicate name; None = unconditional
    reason: str = ""                  # trigger description — every step names its why


@dataclass(frozen=True)
class RoutePlan:
    intent: str
    matched_by: str                   # exact | fallback | llm_preclassified
    historical: bool
    user_intent: str
    steps: List[PlanStep]
    max_calls: int = MAX_CALLS_DEFAULT
    notes: List[str] = field(default_factory=list)  # router-time gaps (e.g. fallback-caused skips)


def _has_any(text: str, terms) -> bool:
    return any(re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", text) for t in terms)


def detect_intent(question: str) -> str:
    text = (question or "").strip().lower()
    for intent in _PRIORITY:
        if _has_any(text, _TRIGGERS[intent]):
            return intent
    return "explain_topic"


def is_historical(question: str) -> bool:
    return _has_any((question or "").lower(), _HISTORICAL_TERMS)


def route(question: str, *, preclassified_intent: Optional[str] = None) -> RoutePlan:
    if preclassified_intent:
        intent, matched_by = preclassified_intent, "llm_preclassified"
    else:
        intent = detect_intent(question)
        matched_by = "exact" if intent != "explain_topic" or _has_any(
            question.lower(), ("what do we know", "tell me about", "summarize")
        ) else "fallback"
    historical = is_historical(question)
    builder: Callable[[str, bool], RoutePlan] = _PLAN_BUILDERS[intent]
    plan = builder(question, historical)
    return RoutePlan(
        intent=intent, matched_by=matched_by, historical=historical,
        user_intent=question, steps=plan.steps, max_calls=plan.max_calls, notes=plan.notes,
    )


def _plan(steps: List[PlanStep], max_calls: int = MAX_CALLS_DEFAULT, notes=None) -> RoutePlan:
    return RoutePlan(intent="", matched_by="", historical=False, user_intent="",
                     steps=steps, max_calls=max_calls, notes=list(notes or []))


def _latest_decisions(question: str, historical: bool) -> RoutePlan:
    return _plan([
        PlanStep("get_decision_timeline", {"limit": 10}, reason="intent sequence 3.1"),
        PlanStep("list_decision_conflicts", condition="HAS_CONFLICTED",
                 reason="timeline shows conflicted/escalated decisions"),
    ])


def _explain_decision(question: str, historical: bool) -> RoutePlan:
    # CF-002: referential entry first (content→decision join), lexical title
    # matching kept as the declared fallback — the reason strings name which
    # path resolved (referential vs lexical).
    return _plan([
        PlanStep("memory_lab_retrieval_search", {"query": question, "limit": 5},
                 reason="referential entry (CF-002): locate the decision's content first"),
        PlanStep("list_decisions_for_content", args_from="top_result_id",
                 condition="HAS_RESULTS",
                 reason="content→decision join — referential, not lexical (CF-002)"),
        PlanStep("list_decisions", {"limit": 20}, condition="NO_DECISION_LINKED",
                 reason="lexical fallback — title match (3.2)"),
        PlanStep("explain_decision", args_from="resolved_decision_id",
                 condition="DECISION_RESOLVED",
                 reason="referential link or unique lexical title match"),
        PlanStep("get_decision_lineage", args_from="resolved_decision_id",
                 condition="DECISION_RESOLVED",
                 reason="ALWAYS with rationale — lineage prevents overreach (3.2)"),
    ])


def _explain_topic(question: str, historical: bool) -> RoutePlan:
    return _plan([
        PlanStep("query_memory", {"query": question}, reason="intent sequence 3.3"),
        PlanStep("memory_lab_retrieval_search", {"query": question, "limit": 10},
                 condition="NO_CONTEXT_OR_FALLBACK",
                 reason="query_memory's own fallback pointer (no_context/fallback.suggested)"),
        # CF-002 restores the §3.3 follow-up that v0 dropped: evidence → decision.
        PlanStep("list_decisions_for_content", args_from="top_evidence_content_id",
                 condition="HAS_ASK_EVIDENCE",
                 reason="§3.3 restored (CF-002): join top evidence to its decision node"),
        PlanStep("get_decision_lineage", args_from="linked_decision_id",
                 condition="DECISION_LINKED",
                 reason="§3.3 restored (CF-002): lineage of the decision behind the evidence"),
    ])


def _verify_current_state(question: str, historical: bool) -> RoutePlan:
    steps = [
        PlanStep("memory_lab_retrieval_search", {"query": question, "limit": 5},
                 reason="intent sequence 3.4"),
        PlanStep("memory_lab_content_get", args_from="top_result_id",
                 condition="HAS_RESULTS", reason="currency fields are the point"),
    ]
    if not historical:
        # CF-003 closed: the successor is read from the scope's active anchor,
        # not probed from retrieval ranking (the v0 bounded-probe workaround).
        steps.append(PlanStep("list_current_state_anchors", args_from="superseded_scope",
                              condition="TOP_SUPERSEDED",
                              reason="read the superseded item's scope anchor — deterministic successor (CF-003)"))
        steps.append(PlanStep("memory_lab_content_get", args_from="anchor_content_id",
                              condition="TOP_SUPERSEDED",
                              reason="fetch the item the anchor names as current"))
    return _plan(steps)


def _relationship_map(question: str, historical: bool) -> RoutePlan:
    return _plan([
        PlanStep("list_hubs", {"status": "active"}, reason="term-match user's topics (3.5)"),
        PlanStep("memory_lab_edge_list", args_from="matched_hub_id",
                 condition="HUB_MATCHED", reason="neighborhood of the matched hub"),
        PlanStep("get_graph_snapshot", {"include_inferred": True, "include_curated": True},
                 condition="NO_HUB_MATCHED", reason="whole-graph fallback when no hub matches"),
    ])


def _save_memory(question: str, historical: bool) -> RoutePlan:
    text = question.strip()
    decision_shaped = bool(re.search(r"(?i)\b(decision:|we decided|record decision)\b", text))
    if decision_shaped:
        title = re.sub(r"(?i)^\s*(remember|note that|record decision|save)[:,]?\s*", "", text)
        title = (title.split(".")[0] or title)[:120]
        return _plan([
            PlanStep("create_decision_memory",
                     {"title": title, "decision_reason": text},
                     reason="decision-shaped save (3.6); lineage via explicit API when predecessor known"),
        ])
    return _plan([
        PlanStep("list_hubs", {"status": "active"}, reason="term-match topic for hub filing (3.6)"),
        PlanStep("save_and_link_to_hub", args_from="save_with_matched_hub",
                 condition="HUB_MATCHED", reason="unique hub match — file under it, scope_hint set"),
        PlanStep("memory_lab_content_create_id", args_from="save_plain",
                 condition="NO_HUB_MATCHED", reason="no hub match — plain governed save"),
    ])


def _diagnose(question: str, historical: bool) -> RoutePlan:
    return _plan([
        PlanStep("memory_lab_health", reason="health first (3.7); unhealthy stops the sequence"),
        PlanStep("list_decision_conflicts", condition="HEALTHY", reason="open contradiction candidates"),
        PlanStep("memory_lab_edge_list", {"include_archived": False}, condition="HEALTHY",
                 reason="pending inferred proposals = waiting human gate"),
        PlanStep("list_hubs", {"status": "active"}, condition="HEALTHY", reason="orientation stats"),
    ], max_calls=MAX_CALLS_DIAGNOSE)


_PLAN_BUILDERS = {
    "latest_decisions": _latest_decisions,
    "explain_decision": _explain_decision,
    "explain_topic": _explain_topic,
    "verify_current_state": _verify_current_state,
    "relationship_map": _relationship_map,
    "save_memory": _save_memory,
    "diagnose_system_state": _diagnose,
}
