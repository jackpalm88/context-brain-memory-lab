"""Evidence Package Builder — all tool results become ONE format (EP v0, ratified).

The Reasoner sees only the package, never MCP responses. The builder copies —
it computes nothing: currency, trust, authority and provenance are transcribed
from responses; authority is assigned mechanically from the source tool.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reference_framework.executor import ExecutionState, TraceStep, _rows, _timeline_rows

PACKAGE_VERSION = "0.1"
MAX_ITEMS_DEFAULT = 50

# Mechanical authority ladder (EP §6): source tool -> level. Never content-derived.
_AUTHORITY = {
    "get_decision_timeline": ("curated", True),
    "list_decisions": ("curated", True),
    "explain_decision": ("curated", True),
    "get_decision_lineage": ("curated", True),
    "query_memory": ("derived", False),
    "memory_lab_retrieval_search": ("governed_save", False),
    "memory_lab_content_get": ("governed_save", False),
}

_TRUST_BASIS = {
    "query_memory": "ask count-based floor",
    "memory_lab_retrieval_search": "retrieval composite",
}


def _currency(row: Dict[str, Any]) -> Dict[str, Any]:
    is_current = row.get("is_current")
    if row.get("conflict_escalation_id") or row.get("tier") == "conflicted":
        status = "pending_review"
    elif is_current is True:
        status = "current"
    elif is_current is False:
        status = "superseded"
    elif is_current is None and "is_current" in row:
        status = "unscoped"
    else:
        status = "unknown"
    return {
        "status": status,
        "scope": row.get("current_state_scope"),
        "scope_source": row.get("current_state_scope_source"),
        "supersedes_id": row.get("cs_supersedes_content_id"),
        # OpenCB records THAT a supersession happened, not what kind (EP §5):
        "supersession_semantics": "unknown",
    }


def _trust(row: Dict[str, Any], tool: str) -> Dict[str, Any]:
    confidence = row.get("confidence")
    return {
        "result_trust": row.get("result_trust"),
        "confidence": float(confidence) if confidence is not None else None,
        "confidence_basis": _TRUST_BASIS.get(tool, "none reported") if confidence is not None else "none reported",
    }


def _item(item_no: int, kind: str, statement: str, tool: str, source_id: str,
          call_ref: str, row: Dict[str, Any], statement_kind: str = "verbatim",
          derived_from: Optional[List[str]] = None) -> Dict[str, Any]:
    level, gated = _AUTHORITY.get(tool, ("governed_save", False))
    provenance = {k: row[k] for k in
                  ("retrieval_path", "source_path", "ranking_reason", "score_components", "knowledge_path")
                  if row.get(k) is not None}
    item = {
        "item_id": f"evi_{item_no:03d}",
        "kind": kind,
        "statement": statement,
        "statement_kind": statement_kind,
        "source": {"tool": tool, "source_id": source_id,
                   "chunk_id": row.get("chunk_id"), "call_ref": call_ref},
        "provenance": provenance,
        "authority": {"level": level, "human_gated": gated},
        "currency": _currency(row),
        "trust": _trust(row, tool),
        "governance": {k: row[k] for k in ("tier", "conflict_escalation_id") if row.get(k) is not None},
    }
    if derived_from is not None:
        item["derived_from"] = derived_from
    return item


def _mint_items(step: TraceStep, counter: List[int]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    def nxt() -> int:
        counter[0] += 1
        return counter[0]

    result, tool, ref = step.result, step.tool, step.step_id

    if tool == "memory_lab_retrieval_search":
        for row in _rows(result, "results", "evidence", "items"):
            statement = str(row.get("text") or row.get("snippet") or "").strip()
            if statement:
                items.append(_item(nxt(), "content_evidence", statement, tool,
                                   str(row.get("content_id") or row.get("id")), ref, row))

    elif tool == "memory_lab_content_get" and isinstance(result, dict):
        statement = str(result.get("quick_summary") or result.get("content_id") or "")
        items.append(_item(nxt(), "content_record", statement, tool,
                           str(result.get("content_id")), ref, result))

    elif tool in ("get_decision_timeline", "list_decisions") and step.outcome == "ok":
        rows = _timeline_rows(result) if tool == "get_decision_timeline" else _rows(result, "decisions", "items")
        for row in rows:
            statement = str(row.get("title") or "")
            items.append(_item(nxt(), "decision_record", statement, tool,
                               str(row.get("decision_id")), ref, row))

    elif tool == "explain_decision" and isinstance(result, dict):
        statement = " — ".join(s for s in (result.get("title"), result.get("decision_reason")) if s)
        items.append(_item(nxt(), "decision_record", statement, tool,
                           str(result.get("decision_id")), ref, result))

    elif tool == "query_memory" and isinstance(result, dict) and result.get("ok") is not False:
        evidence_refs: List[str] = []
        for row in result.get("evidence") or []:
            statement = str(row.get("snippet") or "").strip()
            if statement:
                evidence_item = _item(nxt(), "content_evidence", statement,
                                      "query_memory", str(row.get("content_id")), ref, row)
                evidence_item["authority"] = {"level": "governed_save", "human_gated": False}
                items.append(evidence_item)
                evidence_refs.append(evidence_item["item_id"])
        if result.get("answer") and not result.get("no_context"):
            items.append(_item(nxt(), "derived_answer", str(result["answer"]), tool, "ask",
                               ref, result, statement_kind="tool_derived",
                               derived_from=evidence_refs))
    return items


def build_package(state: ExecutionState, *, max_items: int = MAX_ITEMS_DEFAULT) -> Dict[str, Any]:
    plan = state.plan
    counter = [0]
    items: List[Dict[str, Any]] = []
    for step in state.trace:
        if step.outcome == "ok":
            items.extend(_mint_items(step, counter))

    gaps = list(state.gaps)
    if len(items) > max_items:
        omitted = len(items) - max_items
        items = items[:max_items]
        gaps.append(f"package truncated: {omitted} items omitted due to max_items={max_items}")

    conflicts: List[Dict[str, Any]] = []
    for step in state.trace:
        if step.tool == "list_decision_conflicts" and step.outcome == "ok":
            for row in _rows(step.result, "conflicts", "items", "results", "candidates"):
                conflicts.append({**row, "resolution": "none"})
    for item in items:
        if item["currency"]["status"] == "pending_review":
            conflicts.append({
                "conflict_escalation_id": item["governance"].get("conflict_escalation_id"),
                "side_refs": [item["item_id"]],
                "resolution": "none",
            })

    graph_context = _graph_context(state)

    for degradation in state.degradations:
        degradation.setdefault("reasoner_guidance", "report the limitation; do not improvise around it")

    return {
        "evidence_package": {
            "package_version": PACKAGE_VERSION,
            "package_id": f"epk_{uuid.uuid4()}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "workspace_id": None,   # ambient (token-scoped); populated when known
            "intent": {
                "user_intent": plan.user_intent,
                "interpreted_as": [
                    {"tool": t.tool, "args": t.args_digest}
                    for t in state.trace if t.outcome in ("ok", "error", "empty")
                ],
                "historical": plan.historical,
                "matched_by": plan.matched_by,
                "intent_name": plan.intent,
            },
            "items": items,
            "lineage": _lineage(state),
            "conflicts": conflicts,
            "graph_context": graph_context,
            "degradations": state.degradations,
            "execution_trace": [
                {"step": t.step_id, "tool": t.tool, "args_digest": t.args_digest,
                 "outcome": t.outcome, "reason": t.reason,
                 **({"condition": t.condition, "condition_fired": t.condition_fired}
                    if t.condition else {})}
                for t in state.trace
            ],
            "gaps": gaps,
        }
    }


def _lineage(state: ExecutionState) -> List[Dict[str, Any]]:
    chains = []
    for step in state.trace:
        if step.tool == "get_decision_lineage" and step.outcome == "ok" and isinstance(step.result, dict):
            result = step.result
            nodes = (
                [{"decision_id": a.get("decision_id"), "status": a.get("decision_status")}
                 for a in result.get("ancestors", [])]
                + [{"decision_id": result.get("decision_id"), "status": "active"}]
                + [{"decision_id": d.get("decision_id"), "status": d.get("decision_status")}
                   for d in result.get("descendants", [])]
            )
            chains.append({
                "chain_id": f"lin_{len(chains) + 1:02d}",
                "nodes": nodes,
                "relation": "supersedes",
                "complete": not result.get("depth_limit_reached", False),
            })
            if result.get("depth_limit_reached"):
                state.gaps.append("lineage truncated (depth_limit_reached)")
    return chains


def _graph_context(state: ExecutionState) -> Optional[Dict[str, Any]]:
    hubs, edges = [], []
    for step in state.trace:
        if step.outcome != "ok":
            continue
        if step.tool == "list_hubs" and state.plan.intent == "relationship_map":
            hubs = [{"hub_id": h.get("hub_id"), "title": h.get("title"), "aliases": h.get("aliases")}
                    for h in _rows(step.result, "hubs", "items", "results")]
        if step.tool in ("memory_lab_edge_list", "get_graph_snapshot"):
            edges = [{k: e.get(k) for k in ("source_hub_id", "target_hub_id", "type", "status", "origin", "confidence")}
                     for e in _rows(step.result, "edges", "items", "results")]
    if not hubs and not edges:
        return None
    if any(e.get("status") == "inferred" for e in edges):
        state.gaps.append("map includes machine-proposed (unapproved) edges, marked by status")
    return {
        "authoritative_note": "curated hub graph context; corroboration only, not proof",
        "hubs": hubs,
        "edges": edges,
    }
