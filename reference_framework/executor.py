"""Tool Executor — executes the router's plan; invents nothing.

Conditions and argument extractors are closed, deterministic registries.
Budgets, the no-repeat guard and the single-reroute degradation rule come
from the ratified router policy (§4/§6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from reference_framework.hub_match import match_hubs
from reference_framework.router import PlanStep, RoutePlan


@dataclass
class TraceStep:
    step_id: str
    tool: str
    args_digest: str
    outcome: str                     # ok | error | empty | skipped
    reason: str
    result: Any = None
    condition: Optional[str] = None
    condition_fired: Optional[bool] = None


@dataclass
class ExecutionState:
    plan: RoutePlan
    trace: List[TraceStep] = field(default_factory=list)
    degradations: List[Dict[str, Any]] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    calls_made: int = 0
    seen_calls: set = field(default_factory=set)

    def results_for(self, tool: str) -> List[Any]:
        # empty is a valid outcome whose signals (no_context, fallback…) must be
        # readable by conditions — only errors and skips are excluded.
        return [t.result for t in self.trace if t.tool == tool and t.outcome in ("ok", "empty")]

    def last_ok(self) -> Optional[TraceStep]:
        for step in reversed(self.trace):
            if step.outcome == "ok":
                return step
        return None


# ---------------------------------------------------------------------------
# Result-shape helpers (tolerant of list vs envelope responses)
# ---------------------------------------------------------------------------

def _rows(result: Any, *keys: str) -> List[Dict[str, Any]]:
    if isinstance(result, list):
        return [r for r in result if isinstance(r, dict)]
    if isinstance(result, dict):
        for key in keys:
            value = result.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _timeline_rows(result: Any) -> List[Dict[str, Any]]:
    """get_decision_timeline returns STATUS-BUCKETED lists (active/superseded/
    reversed/draft + total) — a consumer finding from the live smoke; the
    manifest's output_kind does not describe this granularity."""
    rows = _rows(result, "decisions", "timeline", "items")
    if rows:
        return rows
    if isinstance(result, dict):
        for bucket in ("active", "superseded", "reversed", "draft"):
            rows.extend(r for r in (result.get(bucket) or []) if isinstance(r, dict))
    return rows


def _search_rows(state: ExecutionState) -> List[Dict[str, Any]]:
    for result in state.results_for("memory_lab_retrieval_search"):
        rows = _rows(result, "results", "evidence", "items")
        if rows:
            return rows
    return []


def _hub_rows(state: ExecutionState) -> List[Dict[str, Any]]:
    for result in state.results_for("list_hubs"):
        rows = _rows(result, "hubs", "items", "results")
        if rows:
            return rows
    return []


def _matched_hubs(state: ExecutionState) -> List[Dict[str, Any]]:
    return match_hubs(state.plan.user_intent, _hub_rows(state))


def _decision_rows(state: ExecutionState) -> List[Dict[str, Any]]:
    for result in state.results_for("list_decisions"):
        rows = _rows(result, "decisions", "items", "results")
        if rows:
            return rows
    return []


def _matched_decisions(state: ExecutionState) -> List[Dict[str, Any]]:
    words = {w for w in re.split(r"[^a-z0-9]+", state.plan.user_intent.lower()) if len(w) >= 4}
    scored = []
    for row in _decision_rows(state):
        title_tokens = {w for w in re.split(r"[^a-z0-9]+", str(row.get("title", "")).lower()) if len(w) >= 4}
        overlap = len(words & title_tokens)
        if overlap:
            scored.append((overlap, row))
    if not scored:
        return []
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("decision_id"))))
    best = scored[0][0]
    return [row for overlap, row in scored if overlap == best]


def _top_content(state: ExecutionState) -> Optional[Dict[str, Any]]:
    results = state.results_for("memory_lab_content_get")
    return results[0] if results else None


# ---------------------------------------------------------------------------
# Condition predicates (closed registry — §3 `?()` rules)
# ---------------------------------------------------------------------------

def _p_has_conflicted(state: ExecutionState) -> bool:
    for result in state.results_for("get_decision_timeline"):
        for row in _timeline_rows(result):
            if row.get("decision_status") == "conflicted" or row.get("conflict_escalation_id"):
                return True
    return False


def _p_decision_match_unique(state: ExecutionState) -> bool:
    return len(_matched_decisions(state)) == 1


def _p_no_context_or_fallback(state: ExecutionState) -> bool:
    for result in state.results_for("query_memory"):
        if isinstance(result, dict):
            fallback = result.get("fallback") or {}
            if result.get("no_context") or fallback.get("suggested"):
                return True
    return False


def _p_has_results(state: ExecutionState) -> bool:
    return bool(_search_rows(state))


def _p_top_superseded(state: ExecutionState) -> bool:
    top = _top_content(state)
    return bool(top) and top.get("is_current") is False


def _p_has_ask_evidence(state: ExecutionState) -> bool:
    for result in state.results_for("query_memory"):
        if isinstance(result, dict) and any(
            isinstance(row, dict) and row.get("content_id") for row in result.get("evidence") or []
        ):
            return True
    return bool(_search_rows(state))


def _decision_link_rows(state: ExecutionState) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for result in state.results_for("list_decisions_for_content"):
        rows.extend(_rows(result, "decisions"))
    return rows


def _p_decision_linked(state: ExecutionState) -> bool:
    return bool(_decision_link_rows(state))


def _p_no_decision_linked(state: ExecutionState) -> bool:
    return not _p_decision_linked(state)


def _p_decision_resolved(state: ExecutionState) -> bool:
    return bool(_decision_link_rows(state)) or len(_matched_decisions(state)) == 1


def _p_hub_matched(state: ExecutionState) -> bool:
    return len(_matched_hubs(state)) >= 1


def _p_no_hub_matched(state: ExecutionState) -> bool:
    return not _p_hub_matched(state)


def _p_healthy(state: ExecutionState) -> bool:
    for result in state.results_for("memory_lab_health"):
        if isinstance(result, dict) and result.get("status") == "ok":
            return True
    return False


CONDITIONS: Dict[str, Callable[[ExecutionState], bool]] = {
    "HAS_CONFLICTED": _p_has_conflicted,
    "DECISION_MATCH_UNIQUE": _p_decision_match_unique,
    "HAS_ASK_EVIDENCE": _p_has_ask_evidence,
    "DECISION_LINKED": _p_decision_linked,
    "NO_DECISION_LINKED": _p_no_decision_linked,
    "DECISION_RESOLVED": _p_decision_resolved,
    "NO_CONTEXT_OR_FALLBACK": _p_no_context_or_fallback,
    "HAS_RESULTS": _p_has_results,
    "TOP_SUPERSEDED": _p_top_superseded,
    "HUB_MATCHED": _p_hub_matched,
    "NO_HUB_MATCHED": _p_no_hub_matched,
    "HEALTHY": _p_healthy,
}


# ---------------------------------------------------------------------------
# Argument extractors (closed registry)
# ---------------------------------------------------------------------------

def _x_top_result_id(state: ExecutionState) -> Optional[Dict[str, Any]]:
    rows = _search_rows(state)
    if not rows:
        return None
    return {"content_id": str(rows[0].get("content_id") or rows[0].get("id"))}


def _x_next_result_id(state: ExecutionState) -> Optional[Dict[str, Any]]:
    rows = _search_rows(state)
    fetched = {str((r or {}).get("content_id")) for r in state.results_for("memory_lab_content_get")}
    for row in rows[1:]:
        cid = str(row.get("content_id") or row.get("id"))
        if cid not in fetched:
            return {"content_id": cid}
    return None


def _x_superseded_scope(state: ExecutionState) -> Optional[Dict[str, Any]]:
    top = _top_content(state)
    scope = (top or {}).get("current_state_scope")
    if not scope:
        return None
    return {"scope": str(scope)}


def _x_anchor_content_id(state: ExecutionState) -> Optional[Dict[str, Any]]:
    fetched = {str((r or {}).get("content_id")) for r in state.results_for("memory_lab_content_get")}
    for result in state.results_for("list_current_state_anchors"):
        for row in _rows(result, "anchors"):
            cid = row.get("content_id")
            if cid and str(cid) not in fetched:
                return {"content_id": str(cid)}
    return None


def _x_matched_decision_id(state: ExecutionState) -> Optional[Dict[str, Any]]:
    matches = _matched_decisions(state)
    if len(matches) != 1:
        return None
    return {"decision_id": str(matches[0].get("decision_id"))}


def _x_top_evidence_content_id(state: ExecutionState) -> Optional[Dict[str, Any]]:
    for result in state.results_for("query_memory"):
        if isinstance(result, dict):
            for row in result.get("evidence") or []:
                if isinstance(row, dict) and row.get("content_id"):
                    return {"content_id": str(row["content_id"])}
    rows = _search_rows(state)
    if rows:
        return {"content_id": str(rows[0].get("content_id") or rows[0].get("id"))}
    return None


def _x_linked_decision_id(state: ExecutionState) -> Optional[Dict[str, Any]]:
    rows = _decision_link_rows(state)
    if not rows:
        return None
    return {"decision_id": str(rows[0].get("decision_id"))}


def _x_resolved_decision_id(state: ExecutionState) -> Optional[Dict[str, Any]]:
    # referential (CF-002 by-content join) beats lexical title matching
    return _x_linked_decision_id(state) or _x_matched_decision_id(state)


def _x_matched_hub_id(state: ExecutionState) -> Optional[Dict[str, Any]]:
    hubs = _matched_hubs(state)
    if not hubs:
        return None
    return {"hub_id": str(hubs[0].get("hub_id"))}


def _save_content(state: ExecutionState) -> str:
    text = state.plan.user_intent
    return re.sub(r"(?i)^\s*(remember|note that|save)[:,]?\s*", "", text).strip()


def _x_save_with_matched_hub(state: ExecutionState) -> Optional[Dict[str, Any]]:
    hubs = _matched_hubs(state)
    if len(hubs) != 1:
        return None
    title = str(hubs[0].get("title") or "")
    return {
        "content": _save_content(state),
        "hub_id": str(hubs[0].get("hub_id")),
        "save_purpose": "reference-framework save",
        # FV-5 lesson codified as routing law: pass scope_hint whenever the topic is known.
        "scope_hint": re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:120] or None,
    }


def _x_save_plain(state: ExecutionState) -> Optional[Dict[str, Any]]:
    return {"content": _save_content(state)}


EXTRACTORS: Dict[str, Callable[[ExecutionState], Optional[Dict[str, Any]]]] = {
    "top_result_id": _x_top_result_id,
    "next_result_id": _x_next_result_id,
    "superseded_scope": _x_superseded_scope,
    "anchor_content_id": _x_anchor_content_id,
    "matched_decision_id": _x_matched_decision_id,
    "top_evidence_content_id": _x_top_evidence_content_id,
    "linked_decision_id": _x_linked_decision_id,
    "resolved_decision_id": _x_resolved_decision_id,
    "matched_hub_id": _x_matched_hub_id,
    "save_with_matched_hub": _x_save_with_matched_hub,
    "save_plain": _x_save_plain,
}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _digest(args: Dict[str, Any]) -> str:
    return " ".join(f"{k}={str(v)[:60]}" for k, v in sorted(args.items())) or "(no args)"


def _classify_outcome(result: Any) -> str:
    if isinstance(result, dict) and result.get("ok") is False:
        return "error"
    rows = _rows(result, "results", "items", "hubs", "decisions", "evidence", "edges", "conflicts", "timeline", "anchors")
    if isinstance(result, (list,)) and not result:
        return "empty"
    if isinstance(result, dict) and not result:
        return "empty"
    if rows == [] and isinstance(result, dict) and any(
        k in result for k in ("results", "items", "hubs", "decisions", "evidence", "edges", "conflicts", "anchors")
    ):
        return "empty"
    return "ok"


def execute(plan: RoutePlan, tool_registry: Dict[str, Callable[..., Any]]) -> ExecutionState:
    """Run the plan against a tool registry (production: memory_lab.mcp.tools.APPROVED_TOOLS)."""
    state = ExecutionState(plan=plan)
    step_no = 0

    for planned in plan.steps:
        step_no += 1
        step_id = f"step_{step_no:02d}"

        if planned.condition is not None:
            fired = CONDITIONS[planned.condition](state)
            if not fired:
                state.trace.append(TraceStep(step_id, planned.tool, "(condition not fired)",
                                             "skipped", planned.reason, None,
                                             planned.condition, False))
                continue

        if state.calls_made >= plan.max_calls:
            state.trace.append(TraceStep(step_id, planned.tool, "(budget exhausted)",
                                         "skipped", planned.reason))
            state.gaps.append(f"follow-up {planned.tool} skipped: budget ({plan.max_calls} calls)")
            continue

        args = dict(planned.args)
        if planned.args_from is not None:
            extracted = EXTRACTORS[planned.args_from](state)
            if extracted is None:
                state.trace.append(TraceStep(step_id, planned.tool, "(extractor found no target)",
                                             "skipped", planned.reason,
                                             None, planned.condition, planned.condition is not None))
                state.gaps.append(f"{planned.tool} skipped: {planned.args_from} unresolved")
                continue
            args.update({k: v for k, v in extracted.items() if v is not None})

        call_key = (planned.tool, _digest(args))
        if call_key in state.seen_calls:
            state.trace.append(TraceStep(step_id, planned.tool, _digest(args),
                                         "skipped", "no-repeat guard (§6.2)"))
            continue
        state.seen_calls.add(call_key)

        state.calls_made += 1
        try:
            result = tool_registry[planned.tool](**args)
        except Exception as exc:                      # tool layer normally never raises
            result = {"ok": False, "error": {"type": "framework_call_error", "message": str(exc)}}
        outcome = _classify_outcome(result)
        state.trace.append(TraceStep(step_id, planned.tool, _digest(args), outcome,
                                     planned.reason, result,
                                     planned.condition, True if planned.condition else None))
        if outcome == "error":
            state.degradations.append({
                "type": "tool_error", "call_ref": step_id,
                "error": (result.get("error") if isinstance(result, dict) else {"message": str(result)}),
                "effect": f"{planned.tool} unavailable; downstream steps may be skipped",
            })
        if outcome == "empty":
            state.degradations.append({
                "type": "empty_result", "call_ref": step_id,
                "effect": f"{planned.tool} returned no rows",
            })

    state.gaps.extend(plan.notes)
    return state
