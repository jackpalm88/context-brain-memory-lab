"""memory_lab/query/ask_audit.py

DX-3 Part A — Ask Observability.

Emits a single cb_audit_events row for every /v1/ask execution.
Recorded fields (all stored in `metadata` JSONB):

    latency_ms          int       wall-clock inside QueryService.execute()
    retrieval_path      str       primary retrieval path category (see _derive_path)
    result_status       str       AskResponse.status  (ok / insufficient_evidence / …)
    result_mode         str       AskResponse.mode    (deterministic / provider_backed / degraded)
    evidence_count      int       len(ask_evidence) passed to synthesize_answer
    degraded            bool      AskResponse.degraded
    degraded_reason     str|None  AskResponse.degraded_reason if available
    provider_used       bool      mode == "provider_backed"
    requested_scope     dict|None raw AskRequest.retrieval_scope, or null (docs/DESIGN_SCOPED_RETRIEVAL.md)
    scope_enforcement   str       always "pre_filter" under this design

retrieval_path categories (mirrors values already present in RetrievalAdapter rows):
    deterministic           — only deterministic BM25/keyword path used
    pgvector               — pgvector KNN was primary contributor
    graph_rescue_zero      — graph expansion triggered, no evidence after expansion
    graph_rescue_nonzero   — graph expansion triggered, evidence found
    no_context             — zero results from all paths

Design constraints:
    - No new DB tables; writes to existing cb_audit_events.
    - Never raises into caller; all DB errors are swallowed with a log.
    - No imports from reasoning or retrieval layers (avoids circular deps).
    - Hermetic: db_url is injected, not read from env inside this module.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import psycopg2

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retrieval path derivation
# ---------------------------------------------------------------------------

_PATH_PGVECTOR = "pgvector"
_PATH_DETERMINISTIC = "deterministic"
_PATH_GRAPH_RESCUE_NONZERO = "graph_rescue_nonzero"
_PATH_GRAPH_RESCUE_ZERO = "graph_rescue_zero"
_PATH_NO_CONTEXT = "no_context"


def derive_retrieval_path(
    stage_metrics: Optional[Dict[str, Any]],
    evidence_count: int,
) -> str:
    """Derive a single retrieval_path category from RetrievalAdapter stage_metrics.

    Priority order (first match wins):
    1. no_context  — zero evidence regardless of path
    2. pgvector    — pgvector stage was used and contributed results
    3. graph_rescue_nonzero / graph_rescue_zero — graph expansion was used
    4. deterministic — only deterministic path used
    """
    if evidence_count == 0:
        return _PATH_NO_CONTEXT

    if not stage_metrics:
        return _PATH_DETERMINISTIC

    pgvector = stage_metrics.get("pgvector", {})
    if pgvector.get("used") and pgvector.get("output_count", 0) > 0:
        return _PATH_PGVECTOR

    graph = stage_metrics.get("graph_expansion", {})
    if graph.get("used"):
        return _PATH_GRAPH_RESCUE_NONZERO if evidence_count > 0 else _PATH_GRAPH_RESCUE_ZERO

    return _PATH_DETERMINISTIC


# ---------------------------------------------------------------------------
# Audit writer
# ---------------------------------------------------------------------------

def record_ask_event(
    *,
    database_url: str,
    workspace_id: Optional[str],
    latency_ms: int,
    retrieval_path: str,
    result_status: str,
    result_mode: str,
    evidence_count: int,
    degraded: bool,
    degraded_reason: Optional[str],
    provider_used: bool,
    requested_scope: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert one row into cb_audit_events for an /v1/ask execution.

    Silently swallows all errors — observability must never break ask.
    """
    try:
        metadata = {
            "latency_ms": latency_ms,
            "retrieval_path": retrieval_path,
            "result_status": result_status,
            "result_mode": result_mode,
            "evidence_count": evidence_count,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "provider_used": provider_used,
            # docs/DESIGN_SCOPED_RETRIEVAL.md §6.6: requested_scope is the raw
            # retrieval_scope the caller sent (or null). scope_enforcement is
            # always "pre_filter" under this design (scope is never applied
            # post-hoc) — recorded on every event so a future post-hoc code path
            # cannot silently regress provenance truthfulness without the audit
            # record admitting it.
            "requested_scope": requested_scope,
            "scope_enforcement": "pre_filter",
        }

        with psycopg2.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cb_audit_events
                        (event_type, workspace_id, decision, reason_code, metadata)
                    VALUES
                        ('ask', %s::uuid, 'allow', %s, %s::jsonb)
                    """,
                    (
                        workspace_id,
                        retrieval_path,          # reason_code = retrieval_path (indexed TEXT)
                        json.dumps(metadata),
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ask_audit: failed to record event — %s", exc)
