"""B10 classify catchup helper and thin admin CLI.

Public-safe constraints:
- provider-free heuristic_v1 only
- no timed background runner
- no private/prod dependencies
- dry-run by default
- classify-owned writes only; current-state fields are owned exclusively by the resolver
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import psycopg2
from psycopg2.extras import RealDictCursor

from memory_lab.current_state.resolver import resolve_current_state_after_ingest
from memory_lab.ingestion.classify_pipeline import ClassificationResult, classify

logger = logging.getLogger(__name__)

_CLASSIFIER_VERSION = "heuristic_v1"
_RESOLVER_CONFIDENCE_THRESHOLD = 0.70
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000
_DEFAULT_BATCH_SIZE = 100


@dataclass(frozen=True)
class CatchupCandidate:
    content_id: str
    workspace_id: Optional[str]
    content_text: str
    tier: Optional[str] = None
    composite_score: Optional[float] = None


@dataclass
class CatchupRowResult:
    content_id: str
    workspace_id: Optional[str]
    status: str
    memory_type: Optional[str] = None
    memory_sub_type: Optional[str] = None
    classify_confidence: Optional[float] = None
    resolver_status: Optional[str] = None
    resolver_reason: Optional[str] = None
    would_call_resolver: bool = False
    error: Optional[str] = None


@dataclass
class CatchupSummary:
    dry_run: bool
    limit: int
    batch_size: int
    workspace_id: Optional[str]
    all_workspaces: bool
    before_unclassified_count: int = 0
    selected_count: int = 0
    classified_count: int = 0
    skipped_already_classified_count: int = 0
    skipped_no_usable_text_count: int = 0
    resolver_called_count: int = 0
    resolver_skipped_low_confidence_count: int = 0
    failed_count: int = 0
    after_unclassified_count: int = 0
    rows: List[CatchupRowResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["rows"] = [asdict(row) for row in self.rows]
        return data


ConnectionFactory = Callable[[], Any]
Classifier = Callable[..., ClassificationResult]
Resolver = Callable[..., Any]


class ClassifyCatchupJob:
    """Backfill unclassified persisted content rows using heuristic_v1.

    The helper intentionally does not insert content, schedule work, call providers,
    or directly write current-state fields.  It selects persisted rows with
    ``memory_type IS NULL``, reconstructs text from ``content_chunks``, writes
    classify-owned fields, and optionally invokes the current-state resolver for
    high-confidence classifications.
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        *,
        conn_factory: Optional[ConnectionFactory] = None,
        classifier: Classifier = classify,
        resolver: Resolver = resolve_current_state_after_ingest,
    ) -> None:
        self.database_url = database_url or os.environ.get("DATABASE_URL", "")
        self._conn_factory = conn_factory
        self._classifier = classifier
        self._resolver = resolver
        if self._conn_factory is None and not self.database_url:
            raise ValueError("DATABASE_URL is required unless conn_factory is provided")

    def _conn(self):
        if self._conn_factory is not None:
            return self._conn_factory()
        return psycopg2.connect(self.database_url)

    def run(
        self,
        *,
        dry_run: bool = True,
        limit: int = _DEFAULT_LIMIT,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        workspace_id: Optional[str] = None,
        all_workspaces: bool = False,
    ) -> CatchupSummary:
        """Run a bounded classify catchup pass.

        Dry-run is the default and performs zero writes.  Non-dry-run without a
        workspace filter requires ``all_workspaces=True`` as an explicit operator
        acknowledgement.
        """
        limit = _normalize_limit(limit)
        batch_size = _normalize_batch_size(batch_size)
        if not dry_run and not workspace_id and not all_workspaces:
            raise ValueError("non-dry-run catchup requires workspace_id or all_workspaces=True")

        summary = CatchupSummary(
            dry_run=dry_run,
            limit=limit,
            batch_size=batch_size,
            workspace_id=workspace_id,
            all_workspaces=all_workspaces,
        )
        summary.before_unclassified_count = self._count_unclassified(workspace_id)
        candidates = self._select_candidates(limit=limit, workspace_id=workspace_id)
        summary.selected_count = len(candidates)

        for candidate in candidates:
            row_result = self._process_candidate(candidate, dry_run=dry_run)
            summary.rows.append(row_result)
            if row_result.status == "classified":
                summary.classified_count += 1
            elif row_result.status == "skipped_already_classified":
                summary.skipped_already_classified_count += 1
            elif row_result.status == "skipped_no_usable_text":
                summary.skipped_no_usable_text_count += 1
            elif row_result.status == "failed":
                summary.failed_count += 1

            if row_result.resolver_status is not None:
                summary.resolver_called_count += 1
            elif row_result.would_call_resolver:
                # dry-run high-confidence candidate
                pass
            elif row_result.classify_confidence is not None and row_result.classify_confidence < _RESOLVER_CONFIDENCE_THRESHOLD:
                summary.resolver_skipped_low_confidence_count += 1

        summary.after_unclassified_count = self._count_unclassified(workspace_id)
        return summary

    def _count_unclassified(self, workspace_id: Optional[str]) -> int:
        with self._conn() as conn:
            with conn.cursor() as cur:
                if workspace_id:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                          FROM content_items
                         WHERE memory_type IS NULL
                           AND workspace_id = %s::uuid
                        """,
                        (workspace_id,),
                    )
                else:
                    cur.execute("SELECT COUNT(*) FROM content_items WHERE memory_type IS NULL")
                row = cur.fetchone()
        return int(row[0] if not isinstance(row, dict) else row.get("count", 0))

    def _select_candidates(self, *, limit: int, workspace_id: Optional[str]) -> List[CatchupCandidate]:
        with self._conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                params: List[Any] = []
                workspace_clause = ""
                if workspace_id:
                    workspace_clause = "AND ci.workspace_id = %s::uuid"
                    params.append(workspace_id)
                params.append(limit)
                cur.execute(
                    f"""
                    SELECT
                        ci.content_id::text AS content_id,
                        ci.workspace_id::text AS workspace_id,
                        ci.tier::text AS tier,
                        ci.composite_score,
                        COALESCE(
                            string_agg(ch.chunk_text, E'\n\n' ORDER BY ch.chunk_index),
                            ''
                        ) AS content_text
                      FROM content_items ci
                      LEFT JOIN content_chunks ch ON ch.content_id = ci.content_id
                     WHERE ci.memory_type IS NULL
                       {workspace_clause}
                     GROUP BY ci.content_id, ci.workspace_id, ci.tier, ci.composite_score, ci.created_at
                     ORDER BY ci.created_at ASC
                     LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        return [
            CatchupCandidate(
                content_id=row["content_id"],
                workspace_id=row.get("workspace_id"),
                tier=row.get("tier"),
                composite_score=row.get("composite_score"),
                content_text=row.get("content_text") or "",
            )
            for row in rows
        ]

    def _process_candidate(self, candidate: CatchupCandidate, *, dry_run: bool) -> CatchupRowResult:
        if not (candidate.content_text or "").strip():
            return CatchupRowResult(
                content_id=candidate.content_id,
                workspace_id=candidate.workspace_id,
                status="skipped_no_usable_text",
            )

        try:
            result = self._classifier(
                content=candidate.content_text,
                tier=candidate.tier,
                composite_score=candidate.composite_score,
            )
        except Exception as exc:  # pragma: no cover - classify normally never raises
            logger.warning("[classify_catchup] classify failed for %s: %s", candidate.content_id, exc)
            return CatchupRowResult(
                content_id=candidate.content_id,
                workspace_id=candidate.workspace_id,
                status="failed",
                error=str(exc),
            )

        would_resolve = result.confidence >= _RESOLVER_CONFIDENCE_THRESHOLD
        row_result = CatchupRowResult(
            content_id=candidate.content_id,
            workspace_id=candidate.workspace_id,
            status="dry_run" if dry_run else "classified",
            memory_type=result.memory_type,
            memory_sub_type=result.memory_sub_type,
            classify_confidence=result.confidence,
            would_call_resolver=would_resolve,
        )
        if dry_run:
            return row_result

        try:
            write_status = self._write_classification(candidate, result)
            if write_status == "skipped_already_classified":
                row_result.status = "skipped_already_classified"
                return row_result

            if would_resolve:
                with self._conn() as conn:
                    resolution = self._resolver(
                        conn,
                        workspace_id=candidate.workspace_id,
                        content_id=candidate.content_id,
                        memory_type=result.memory_type,
                        memory_sub_type=result.memory_sub_type,
                        classify_confidence=result.confidence,
                        signals=result.signals,
                        project_topic=result.project_topic,
                        domain_hint=result.domain_hint,
                        content_text=candidate.content_text,
                    )
                row_result.resolver_status = getattr(resolution, "status", None)
                row_result.resolver_reason = getattr(resolution, "reason", None)
        except Exception as exc:
            logger.warning("[classify_catchup] write failed for %s: %s", candidate.content_id, exc)
            return CatchupRowResult(
                content_id=candidate.content_id,
                workspace_id=candidate.workspace_id,
                status="failed",
                memory_type=result.memory_type,
                memory_sub_type=result.memory_sub_type,
                classify_confidence=result.confidence,
                would_call_resolver=would_resolve,
                error=str(exc),
            )
        return row_result

    def _write_classification(self, candidate: CatchupCandidate, result: ClassificationResult) -> str:
        """Write classify-owned fields only; never current-state fields."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT memory_type
                      FROM content_items
                     WHERE content_id = %s::uuid
                     LIMIT 1
                    """,
                    (candidate.content_id,),
                )
                existing = cur.fetchone()
                existing_type = existing[0] if existing and not isinstance(existing, dict) else (existing or {}).get("memory_type") if existing else None
                if existing_type is not None:
                    return "skipped_already_classified"

                cur.execute(
                    """
                    SELECT 1 FROM cb_classification_history
                     WHERE content_id = %s::uuid
                       AND memory_type = %s
                       AND classifier_version = %s
                       AND is_active_classification = TRUE
                     LIMIT 1
                    """,
                    (candidate.content_id, result.memory_type, _CLASSIFIER_VERSION),
                )
                if cur.fetchone():
                    cur.execute(
                        """
                        UPDATE content_items
                           SET memory_type         = %s,
                               memory_sub_type     = %s,
                               classify_confidence = %s,
                               classified_at       = NOW()
                         WHERE content_id = %s::uuid
                           AND memory_type IS NULL
                        """,
                        (result.memory_type, result.memory_sub_type, result.confidence, candidate.content_id),
                    )
                    conn.commit()
                    return "classified"

                cur.execute(
                    """
                    UPDATE content_items
                       SET memory_type         = %s,
                           memory_sub_type     = %s,
                           classify_confidence = %s,
                           classified_at       = NOW()
                     WHERE content_id = %s::uuid
                       AND memory_type IS NULL
                    """,
                    (result.memory_type, result.memory_sub_type, result.confidence, candidate.content_id),
                )

                cur.execute(
                    """
                    UPDATE cb_classification_history
                       SET is_active_classification = FALSE
                     WHERE content_id = %s::uuid
                       AND is_active_classification = TRUE
                    """,
                    (candidate.content_id,),
                )

                if candidate.workspace_id:
                    cur.execute(
                        """
                        INSERT INTO cb_classification_history
                            (workspace_id, content_id, memory_type, memory_sub_type,
                             classify_confidence, classifier_version, project_topic,
                             classification_signals, is_active_classification)
                        VALUES
                            (%s::uuid, %s::uuid, %s, %s, %s,
                             %s, %s, %s::jsonb, TRUE)
                        """,
                        (
                            candidate.workspace_id,
                            candidate.content_id,
                            result.memory_type,
                            result.memory_sub_type,
                            result.confidence,
                            _CLASSIFIER_VERSION,
                            result.project_topic,
                            json.dumps(result.signals),
                        ),
                    )

                if result.domain_hint and result.confidence >= _RESOLVER_CONFIDENCE_THRESHOLD and candidate.workspace_id:
                    cur.execute(
                        """
                        INSERT INTO cb_discovered_domains (workspace_id, domain_name, source)
                        VALUES (%s::uuid, %s, 'auto_classify')
                        ON CONFLICT (workspace_id, domain_name) DO NOTHING
                        """,
                        (candidate.workspace_id, result.domain_hint),
                    )
                    cur.execute(
                        """
                        UPDATE content_items
                           SET domain_id = (
                               SELECT domain_id FROM cb_discovered_domains
                                WHERE workspace_id = %s::uuid
                                  AND domain_name = %s
                                LIMIT 1
                           )
                         WHERE content_id = %s::uuid
                        """,
                        (candidate.workspace_id, result.domain_hint, candidate.content_id),
                    )

                conn.commit()
        return "classified"


def _normalize_limit(limit: int) -> int:
    try:
        value = int(limit)
    except Exception as exc:
        raise ValueError("limit must be an integer") from exc
    if value < 1:
        raise ValueError("limit must be >= 1")
    return min(value, _MAX_LIMIT)


def _normalize_batch_size(batch_size: int) -> int:
    try:
        value = int(batch_size)
    except Exception as exc:
        raise ValueError("batch_size must be an integer") from exc
    if value < 1:
        raise ValueError("batch_size must be >= 1")
    return min(value, _MAX_LIMIT)


def run_classify_catchup(
    *,
    database_url: Optional[str] = None,
    dry_run: bool = True,
    limit: int = _DEFAULT_LIMIT,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    workspace_id: Optional[str] = None,
    all_workspaces: bool = False,
) -> CatchupSummary:
    job = ClassifyCatchupJob(database_url=database_url)
    return job.run(
        dry_run=dry_run,
        limit=limit,
        batch_size=batch_size,
        workspace_id=workspace_id,
        all_workspaces=all_workspaces,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="B10 classify catchup helper (dry-run by default)")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--workspace-id", default=None)
    parser.add_argument("--all-workspaces", action="store_true")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false", help="perform writes; requires --workspace-id or --all-workspaces")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_classify_catchup(
            database_url=args.database_url,
            dry_run=args.dry_run,
            limit=args.limit,
            batch_size=args.batch_size,
            workspace_id=args.workspace_id,
            all_workspaces=args.all_workspaces,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(summary.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via CLI smoke if needed
    raise SystemExit(main())
