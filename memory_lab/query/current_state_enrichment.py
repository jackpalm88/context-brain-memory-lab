"""FV-FIX-3: current-state awareness for the /v1/ask answer path.

The current-state resolver already computes content_items.is_current,
current_state_scope and cs_supersedes_content_id at ingest, but /v1/ask
never read them, so an obsolete memory looked exactly as authoritative as
the decision that superseded it.

This module enriches already-retrieved ask evidence with those fields and
applies a stable in-scope preference: when a current item and a superseded
item share the same current_state_scope, the superseded one is demoted
below it. It deliberately does NOT touch retrieval or ranking — order
between items of different scopes (and items without current-state data)
is preserved exactly. Historical questions keep the original order so
superseded items remain fully citable as history.

Best-effort: any DB failure returns the evidence unchanged; ask never
degrades because of this enrichment.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from memory_lab.reasoning.models import EvidenceItem

logger = logging.getLogger(__name__)

# Deterministic historical-question markers: when present, superseded
# evidence is what the caller is asking about, so no demotion happens.
_HISTORICAL_TERMS = (
    "previously",
    "before",
    "earlier",
    "originally",
    "used to",
    "history",
    "historical",
    "historically",
    "at first",
    "in the past",
    "old decision",
    "first decision",
)


def is_historical_query(query: str) -> bool:
    text = (query or "").strip().lower()
    if not text:
        return False
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text)
        for term in _HISTORICAL_TERMS
    )


def fetch_current_state_rows(database_url: str, content_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Read resolver-owned current-state fields for the given content ids."""
    if not content_ids:
        return {}
    import psycopg2

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content_id::text,
                       is_current,
                       current_state_scope,
                       cs_supersedes_content_id::text
                  FROM content_items
                 WHERE content_id = ANY(%s::uuid[])
                """,
                (content_ids,),
            )
            return {
                row[0]: {
                    "is_current": row[1],
                    "current_state_scope": row[2],
                    "cs_supersedes_content_id": row[3],
                }
                for row in cur.fetchall()
            }


def _annotated(item: EvidenceItem, state: dict[str, Any]) -> EvidenceItem:
    metadata = dict(item.metadata or {})
    metadata["is_current"] = state["is_current"]
    if state["current_state_scope"] is not None:
        metadata["current_state_scope"] = state["current_state_scope"]
    if state["cs_supersedes_content_id"] is not None:
        metadata["cs_supersedes_content_id"] = state["cs_supersedes_content_id"]
    return item.model_copy(
        update={
            "is_current": state["is_current"],
            "current_state_scope": state["current_state_scope"],
            "cs_supersedes_content_id": state["cs_supersedes_content_id"],
            "metadata": metadata,
        }
    )


def enrich_evidence_with_current_state(
    evidence: list[EvidenceItem],
    *,
    database_url: Optional[str],
    query: str,
) -> list[EvidenceItem]:
    """Annotate ask evidence with current-state fields and apply in-scope preference.

    Returns the input unchanged on any failure or when no current-state data exists.
    """
    if not evidence or not database_url:
        return evidence

    try:
        rows = fetch_current_state_rows(database_url, [e.content_id for e in evidence])
    except Exception as exc:
        logger.warning("[ask] current-state enrichment skipped: %s", exc)
        return evidence
    if not rows:
        return evidence

    annotated: list[EvidenceItem] = []
    for item in evidence:
        state = rows.get(item.content_id)
        if state is not None and state["is_current"] is not None:
            annotated.append(_annotated(item, state))
        else:
            annotated.append(item)

    if is_historical_query(query):
        return annotated

    # Stable in-scope demotion: superseded items sink below items of scopes that
    # have a current item; everything else keeps its exact retrieval order.
    scopes_with_current = {
        e.current_state_scope
        for e in annotated
        if e.is_current is True and e.current_state_scope
    }

    def _demoted(item: EvidenceItem) -> bool:
        return item.is_current is False and item.current_state_scope in scopes_with_current

    if not any(_demoted(e) for e in annotated):
        return annotated

    reordered = sorted(annotated, key=_demoted)  # stable: only the demoted flag moves items
    result: list[EvidenceItem] = []
    for rank, item in enumerate(reordered, start=1):
        update: dict[str, Any] = {"rank": rank}
        if _demoted(item):
            update["ranking_reason"] = (
                f"Demoted below the current item of current-state scope "
                f"'{item.current_state_scope}': this item was superseded."
            )
        result.append(item.model_copy(update=update))
    return result
