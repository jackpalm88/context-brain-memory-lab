"""Gap-4: deterministic inferred-edge producer (EDGE-INF-1).

Production analog: app/scripts/auto_extract_edges.py (tag co-occurrence +
LLM extraction). Public rewrite invariant: computed proposals only —
provider-free, deterministic, workspace-scoped. Nothing becomes a curated
edge without the existing human gate (approve_inferred_edge /
reject_inferred_edge consumers, migration 007 'inferred' status).

Two deterministic signals over one workspace:

  co_membership_v1 — two active hubs share >= min_shared linked content rows
                     (cb_hub_content overlap)
  tag_alignment_v1 — content topic_tags mention terms of two hubs in
                     >= min_cooccur documents (hub terms = title + aliases +
                     related_terms, normalized)

Proposals are inserted as status='inferred', origin='ai_suggested' with
ON CONFLICT DO NOTHING on the active edge_key: existing manual, approved,
and rejected edges are never overwritten, and rejected pairs are never
resurrected.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg2.extras import RealDictCursor

from memory_lab.graph.hub_edge_store import _compute_edge_key

logger = logging.getLogger(__name__)

PRODUCER_VERSION = "edge_inference_v1"
PROPOSED_EDGE_TYPE = "related"  # symmetric, always valid in ALL_TYPES

_BASE_CONFIDENCE = 0.75
_CONFIDENCE_STEP = 0.01
_CONFIDENCE_CAP = 0.95

_NORM_RE = re.compile(r"[_\-/]+")
_SPACE_RE = re.compile(r"\s+")

# Tags that carry no concept signal (production _NOISE_TAGS analog, generic only)
NOISE_TAGS = {"placeholder", "system_generated", "no_content", "fallback"}


def normalize_term(term: str) -> str:
    """Lowercase, fold snake/kebab/slash separators to spaces, collapse whitespace."""
    lowered = _NORM_RE.sub(" ", (term or "").strip().lower())
    return _SPACE_RE.sub(" ", lowered).strip()


@dataclass
class EdgeProposal:
    source_hub_id: str
    target_hub_id: str
    edge_type: str
    confidence: float
    reason: str
    detection_rules: List[str] = field(default_factory=list)
    evidence_count: int = 0

    @property
    def edge_key(self) -> str:
        return _compute_edge_key(self.source_hub_id, self.target_hub_id, self.edge_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_hub_id": self.source_hub_id,
            "target_hub_id": self.target_hub_id,
            "edge_type": self.edge_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "detection_rules": list(self.detection_rules),
            "evidence_count": self.evidence_count,
            "edge_key": self.edge_key,
        }


def _scaled_confidence(evidence: int, threshold: int) -> float:
    return round(min(_CONFIDENCE_CAP, _BASE_CONFIDENCE + _CONFIDENCE_STEP * (evidence - threshold)), 3)


def _pair_proposal(hub_a: str, hub_b: str, evidence: int, threshold: int, rule: str, reason: str) -> EdgeProposal:
    source, target = sorted([hub_a, hub_b])
    return EdgeProposal(
        source_hub_id=source,
        target_hub_id=target,
        edge_type=PROPOSED_EDGE_TYPE,
        confidence=_scaled_confidence(evidence, threshold),
        reason=reason,
        detection_rules=[rule],
        evidence_count=evidence,
    )


def propose_from_co_membership(
    memberships: Iterable[Tuple[str, str]], *, min_shared: int = 3
) -> List[EdgeProposal]:
    """Hub pairs whose linked-content sets overlap in >= min_shared rows.

    memberships: (hub_id, content_id) pairs from cb_hub_content.
    """
    contents_by_hub: Dict[str, Set[str]] = defaultdict(set)
    for hub_id, content_id in memberships:
        if hub_id and content_id:
            contents_by_hub[str(hub_id)].add(str(content_id))

    proposals: List[EdgeProposal] = []
    for hub_a, hub_b in combinations(sorted(contents_by_hub), 2):
        shared = len(contents_by_hub[hub_a] & contents_by_hub[hub_b])
        if shared < max(1, min_shared):
            continue
        proposals.append(_pair_proposal(
            hub_a, hub_b, shared, min_shared, "co_membership_v1",
            f"co_membership: {shared} shared content items",
        ))
    return proposals


def _hub_term_index(hubs: Sequence[Dict[str, Any]]) -> Dict[str, Set[str]]:
    """hub_id -> normalized term set (title + aliases + related_terms)."""
    index: Dict[str, Set[str]] = {}
    for hub in hubs:
        terms = {normalize_term(hub.get("title") or "")}
        for term_list in (hub.get("aliases") or [], hub.get("related_terms") or []):
            terms.update(normalize_term(t) for t in term_list)
        terms.discard("")
        if terms:
            index[str(hub["hub_id"])] = terms
    return index


def propose_from_tag_alignment(
    hubs: Sequence[Dict[str, Any]],
    contents: Iterable[Tuple[str, Sequence[str]]],
    *,
    min_cooccur: int = 3,
) -> List[EdgeProposal]:
    """Hub pairs co-mentioned by content topic_tags in >= min_cooccur documents.

    A content row "mentions" a hub when any of its normalized topic_tags equals
    one of the hub's normalized terms. contents: (content_id, topic_tags) rows.
    """
    term_index = _hub_term_index(hubs)
    if len(term_index) < 2:
        return []

    pair_docs: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for content_id, tags in contents:
        norm_tags = {normalize_term(t) for t in (tags or []) if t and t not in NOISE_TAGS}
        norm_tags.discard("")
        if len(norm_tags) < 1:
            continue
        mentioned = sorted(h for h, terms in term_index.items() if terms & norm_tags)
        for hub_a, hub_b in combinations(mentioned, 2):
            pair_docs[(hub_a, hub_b)].add(str(content_id))

    proposals: List[EdgeProposal] = []
    for (hub_a, hub_b), docs in pair_docs.items():
        if len(docs) < max(1, min_cooccur):
            continue
        proposals.append(_pair_proposal(
            hub_a, hub_b, len(docs), min_cooccur, "tag_alignment_v1",
            f"tag_alignment: co-mentioned in {len(docs)} documents",
        ))
    return proposals


def merge_proposals(*proposal_lists: List[EdgeProposal]) -> List[EdgeProposal]:
    """Merge by edge_key: keep the higher-confidence proposal, union the rules.

    Deterministic order: confidence desc, then edge_key asc.
    """
    merged: Dict[str, EdgeProposal] = {}
    for proposals in proposal_lists:
        for proposal in proposals:
            existing = merged.get(proposal.edge_key)
            if existing is None:
                merged[proposal.edge_key] = proposal
                continue
            keep, other = (proposal, existing) if proposal.confidence > existing.confidence else (existing, proposal)
            keep.detection_rules = sorted(set(keep.detection_rules) | set(other.detection_rules))
            keep.reason = f"{keep.reason}; {other.reason}"
            merged[proposal.edge_key] = keep
    return sorted(merged.values(), key=lambda p: (-p.confidence, p.edge_key))


# ---------------------------------------------------------------------------
# Workspace fetch + persist
# ---------------------------------------------------------------------------

def _fetch_memberships(conn: Any, workspace_id: str) -> List[Tuple[str, str]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT hc.hub_id::text AS hub_id, hc.content_id::text AS content_id
              FROM cb_hub_content hc
              JOIN cb_hubs h ON h.hub_id = hc.hub_id
             WHERE hc.workspace_id = %s::uuid
               AND h.workspace_uuid = %s::uuid
               AND h.status = 'active'
            """,
            (workspace_id, workspace_id),
        )
        return [(r["hub_id"], r["content_id"]) for r in cur.fetchall()]


def _fetch_hubs(conn: Any, workspace_id: str) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT hub_id::text AS hub_id, title, aliases, related_terms
              FROM cb_hubs
             WHERE workspace_uuid = %s::uuid
               AND status = 'active'
            """,
            (workspace_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _fetch_tagged_contents(conn: Any, workspace_id: str) -> List[Tuple[str, List[str]]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT content_id::text AS content_id, topic_tags
              FROM content_items
             WHERE workspace_id = %s::uuid
               AND topic_tags IS NOT NULL
               AND array_length(topic_tags, 1) >= 1
               AND (tier IS NULL OR tier::text NOT IN ('archived', 'conflicted'))
            """,
            (workspace_id,),
        )
        return [(r["content_id"], list(r["topic_tags"] or [])) for r in cur.fetchall()]


def persist_edge_proposals(
    conn: Any,
    proposals: Sequence[EdgeProposal],
    *,
    workspace_id: str,
    created_by: str = PRODUCER_VERSION,
) -> Dict[str, int]:
    """INSERT proposals as inferred/ai_suggested rows; active-key conflicts skip.

    ON CONFLICT DO NOTHING on idx_cb_hub_edges_key_active means an existing
    manual, approved, needs_review, inferred, or rejected edge for the same
    pair+type is left untouched — the producer never re-opens a human decision.
    Caller owns the connection; commits once on success.
    """
    inserted = 0
    skipped_existing = 0
    with conn.cursor() as cur:
        for proposal in proposals:
            cur.execute(
                """
                INSERT INTO cb_hub_edges
                    (source_hub_id, target_hub_id, workspace_id, type, status, origin,
                     confidence, reason, edge_key, created_by)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, 'inferred', 'ai_suggested',
                        %s, %s, %s, %s)
                ON CONFLICT (edge_key) WHERE archived_at IS NULL DO NOTHING
                RETURNING id::text
                """,
                (
                    proposal.source_hub_id,
                    proposal.target_hub_id,
                    workspace_id,
                    proposal.edge_type,
                    proposal.confidence,
                    f"[{'+'.join(proposal.detection_rules)}] {proposal.reason}"[:500],
                    proposal.edge_key,
                    created_by,
                ),
            )
            if cur.fetchone():
                inserted += 1
            else:
                skipped_existing += 1
    conn.commit()
    return {"inserted": inserted, "skipped_existing": skipped_existing}


def run_edge_inference(
    conn: Any,
    *,
    workspace_id: str,
    min_shared: int = 3,
    min_cooccur: int = 3,
    max_proposals: int = 50,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Compute and (unless dry_run) persist inferred edge proposals for one workspace."""
    if not workspace_id:
        raise ValueError("workspace_id is required — the producer is workspace-scoped")

    memberships = _fetch_memberships(conn, workspace_id)
    hubs = _fetch_hubs(conn, workspace_id)
    contents = _fetch_tagged_contents(conn, workspace_id)

    co_membership = propose_from_co_membership(memberships, min_shared=min_shared)
    tag_alignment = propose_from_tag_alignment(hubs, contents, min_cooccur=min_cooccur)
    proposals = merge_proposals(co_membership, tag_alignment)[: max(0, max_proposals)]

    report: Dict[str, Any] = {
        "workspace_id": workspace_id,
        "producer": PRODUCER_VERSION,
        "dry_run": dry_run,
        "hubs_considered": len(hubs),
        "membership_rows": len(memberships),
        "tagged_content_rows": len(contents),
        "proposals_co_membership": len(co_membership),
        "proposals_tag_alignment": len(tag_alignment),
        "proposals_total": len(proposals),
        "proposals": [p.to_dict() for p in proposals],
        "deterministic": True,
        "provider_backed": False,
        "human_gate": "approve_inferred_edge / reject_inferred_edge",
    }
    if dry_run:
        report.update({"inserted": 0, "skipped_existing": 0})
        return report

    report.update(persist_edge_proposals(conn, proposals, workspace_id=workspace_id))
    logger.info(
        "[edge_inference] workspace=%s proposals=%d inserted=%d skipped=%d",
        workspace_id, len(proposals), report["inserted"], report["skipped_existing"],
    )
    return report
