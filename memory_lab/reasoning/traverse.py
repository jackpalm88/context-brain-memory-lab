from __future__ import annotations

from typing import Any, Iterable, List

from memory_lab.context_packs.models import ContextPackBuildResponse
from memory_lab.reasoning.models import ReasoningRequest, ReasoningTraversalStep


def _as_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return dict(item)


def collect_evidence_refs(context_pack: ContextPackBuildResponse) -> list[dict[str, Any]]:
    """Return stable, de-duplicated evidence refs from a public B12 context pack."""
    buckets: Iterable[Any] = (
        list(context_pack.supporting_evidence)
        + list(context_pack.current_state_signals)
        + list(context_pack.counterfindings)
        + list(context_pack.stale_or_superseded_items)
    )
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in buckets:
        row = _as_dict(item)
        evidence_id = str(row.get("evidence_id") or "").strip()
        content_id = str(row.get("content_id") or "").strip()
        key = evidence_id or content_id
        if not key or key in seen:
            continue
        seen.add(key)
        refs.append(row)
    refs.sort(key=lambda r: (int(r.get("rank") or 999999), str(r.get("content_id") or ""), str(r.get("evidence_id") or "")))
    return refs


def build_traversal_steps(context_pack: ContextPackBuildResponse, request: ReasoningRequest) -> list[ReasoningTraversalStep]:
    """Build deterministic read-only traversal steps.

    B13 traverses the evidence container and public current/conflict signals only.
    It does not mutate a graph, decide truth, or resolve conflicts.
    """
    max_hops = min(max(int(request.max_hops or 2), 1), 3)
    steps: List[ReasoningTraversalStep] = []
    step_no = 0

    support_ids = [e.evidence_id for e in context_pack.supporting_evidence]
    step_no += 1
    steps.append(
        ReasoningTraversalStep(
            step_id=f"step_{step_no:02d}",
            hop=0,
            source="reasoning_request",
            relation="builds_context_pack",
            target=context_pack.context_pack_id,
            evidence_ids=support_ids,
            rationale="The reasoning layer starts from the public B12 context pack built for the query/scope.",
        )
    )

    if max_hops >= 1:
        for evidence in sorted(context_pack.supporting_evidence, key=lambda e: (e.rank or 999999, e.content_id, e.evidence_id)):
            step_no += 1
            steps.append(
                ReasoningTraversalStep(
                    step_id=f"step_{step_no:02d}",
                    hop=1,
                    source=context_pack.context_pack_id,
                    relation="includes_supporting_evidence",
                    target=evidence.content_id,
                    evidence_ids=[evidence.evidence_id],
                    rationale="Supporting evidence is included by the B12 retrieval/context-pack path.",
                )
            )

    if max_hops >= 2:
        for evidence in sorted(context_pack.current_state_signals, key=lambda e: (e.rank or 999999, e.content_id, e.evidence_id)):
            step_no += 1
            steps.append(
                ReasoningTraversalStep(
                    step_id=f"step_{step_no:02d}",
                    hop=2,
                    source=evidence.content_id,
                    relation="has_current_state_signal",
                    target=evidence.current_state_scope or context_pack.scope or "current_state",
                    evidence_ids=[evidence.evidence_id],
                    rationale="Current-state metadata is surfaced as a signal, not as proof that other evidence is false.",
                )
            )
        for evidence in sorted(context_pack.stale_or_superseded_items, key=lambda e: (e.rank or 999999, e.content_id, e.evidence_id)):
            step_no += 1
            steps.append(
                ReasoningTraversalStep(
                    step_id=f"step_{step_no:02d}",
                    hop=2,
                    source=evidence.content_id,
                    relation="has_stale_or_superseded_signal",
                    target=evidence.cs_supersedes_content_id or "supersession_signal",
                    evidence_ids=[evidence.evidence_id],
                    rationale="Stale/superseded metadata is a warning signal only; B13 does not arbitrate truth.",
                )
            )
        for conflict in sorted(context_pack.conflict_candidates, key=lambda c: (str(c.get("severity") or ""), str(c.get("conflict_id") or c.get("candidate_id") or ""))):
            ev_ids = [str(e.get("evidence_id")) for e in conflict.get("evidence", []) if e.get("evidence_id")]
            step_no += 1
            steps.append(
                ReasoningTraversalStep(
                    step_id=f"step_{step_no:02d}",
                    hop=2,
                    source=context_pack.context_pack_id,
                    relation="surfaces_unresolved_conflict_candidate",
                    target=str(conflict.get("conflict_id") or conflict.get("candidate_id") or "conflict_candidate"),
                    evidence_ids=ev_ids,
                    rationale="Conflict candidates are warnings for human review and are not automatically resolved.",
                )
            )

    if max_hops >= 3:
        for evidence in sorted(context_pack.counterfindings, key=lambda e: (e.rank or 999999, e.content_id, e.evidence_id)):
            step_no += 1
            steps.append(
                ReasoningTraversalStep(
                    step_id=f"step_{step_no:02d}",
                    hop=3,
                    source=context_pack.context_pack_id,
                    relation="includes_counterfinding_evidence",
                    target=evidence.content_id,
                    evidence_ids=[evidence.evidence_id],
                    rationale="Counterfinding evidence is preserved for human review without conflict resolution.",
                )
            )

    return steps
