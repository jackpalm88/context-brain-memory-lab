#!/usr/bin/env python3
"""EMB-1C: Embedding Backfill CLI.

Fills missing embeddings on existing content_chunks rows using the current
multi-chunk semantics (EMB-1B).  Supports dry-run and live execution modes.

Usage:
    # Dry-run — scan and report eligible chunks, no writes:
    PYTHONPATH=/opt/cbml python3 scripts/embedding_backfill.py \\
        --dsn "host=... dbname=... user=... password=..." \\
        --dry-run

    # Live — embed all eligible chunks in the DB:
    PYTHONPATH=/opt/cbml python3 scripts/embedding_backfill.py \\
        --dsn "host=..." \\
        --provider openai \\
        --api-key "$OPENAI_API_KEY"

    # Workspace-scoped live run with limits:
    PYTHONPATH=/opt/cbml python3 scripts/embedding_backfill.py \\
        --dsn "host=..." \\
        --provider openai \\
        --api-key "$OPENAI_API_KEY" \\
        --workspace-id "xxxxxxxx-..." \\
        --batch-size 50 \\
        --limit 500

Environment variable alternative for secrets:
    BACKFILL_OPENAI_API_KEY   (checked if --api-key is not supplied)

Exit codes:
    0  success (or dry-run complete)
    1  configuration error
    2  partial failure (some chunks failed, some stored — check warnings)
    3  total failure (all attempts failed)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("embedding_backfill")

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Backfill missing embeddings on content_chunks (EMB-1C).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--dsn", required=True,
                   help="libpq DSN string, e.g. 'host=127.0.0.1 dbname=cbml user=cbml password=...'")
    p.add_argument("--dry-run", action="store_true",
                   help="Scan eligible chunks and print plan; no embeddings written.")
    p.add_argument("--provider", default="openai",
                   help="Embedding provider name (default: openai).")
    p.add_argument("--api-key",
                   help="Provider API key (or set BACKFILL_OPENAI_API_KEY).")
    p.add_argument("--workspace-id",
                   help="Scope backfill to this workspace UUID (optional).")
    p.add_argument("--batch-size", type=int, default=100,
                   help="Commit every N chunks during live execution (default: 100).")
    p.add_argument("--limit", type=int, default=None,
                   help="Max chunks to process per run (default: no limit).")
    p.add_argument("--output-json", action="store_true",
                   help="Print final stats as JSON to stdout.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def _make_backend(args: argparse.Namespace):
    """Build an EmbeddingBackend from CLI args. Returns None for dry-run."""
    if args.dry_run:
        return None

    api_key = args.api_key or os.environ.get("BACKFILL_OPENAI_API_KEY")
    if not api_key:
        logger.error(
            "Live execution requires --api-key or BACKFILL_OPENAI_API_KEY env var."
        )
        sys.exit(1)

    try:
        from memory_lab.providers.openai_embedding_backend import OpenAIEmbeddingBackend
        backend = OpenAIEmbeddingBackend(api_key=api_key)
        if not backend.is_configured:
            logger.error("EmbeddingBackend reports is_configured=False after init.")
            sys.exit(1)
        return backend
    except ImportError as exc:
        logger.error("Could not import OpenAIEmbeddingBackend: %s", exc)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Connection factory
# ---------------------------------------------------------------------------

def _make_conn_factory(dsn: str):
    def _factory():
        try:
            import psycopg2
            return psycopg2.connect(dsn)
        except Exception as exc:
            logger.error("DB connection failed: %s", exc)
            sys.exit(1)
    return _factory


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    from memory_lab.ingestion.embedding_backfill import (
        BackfillPlan,
        BackfillStats,
        EmbeddingBackfillRunner,
    )

    conn_factory = _make_conn_factory(args.dsn)
    backend = _make_backend(args)

    runner = EmbeddingBackfillRunner(
        conn_factory=conn_factory,
        embedding_backend=backend,
        workspace_id=args.workspace_id or None,
        batch_size=args.batch_size,
        limit=args.limit,
    )

    # ---- dry-run ----
    if args.dry_run:
        plan: BackfillPlan = runner.dry_run()
        if args.output_json:
            print(json.dumps({
                "mode": "dry_run",
                "eligible": plan.eligible,
                "workspace_id": plan.workspace_id,
                "limit": plan.limit,
                "batch_size": plan.batch_size,
                "sample_chunk_ids": list(plan.sample_chunk_ids),
                "note": plan.note,
            }, indent=2))
        else:
            print(f"\n[dry-run] eligible chunks : {plan.eligible}")
            print(f"[dry-run] workspace_id   : {plan.workspace_id or '(all)'}")
            print(f"[dry-run] limit          : {plan.limit or '(none)'}")
            print(f"[dry-run] batch_size     : {plan.batch_size}")
            if plan.sample_chunk_ids:
                print(f"[dry-run] sample ids     : {', '.join(plan.sample_chunk_ids[:5])}")
            print(f"[dry-run] {plan.note}\n")
        sys.exit(0)

    # ---- live ----
    logger.info(
        "Starting live backfill — workspace=%s limit=%s batch_size=%d",
        args.workspace_id or "(all)", args.limit or "(none)", args.batch_size,
    )
    stats: BackfillStats = runner.execute()

    if args.output_json:
        print(json.dumps({
            "mode": "execute",
            "eligible": stats.eligible,
            "attempted": stats.attempted,
            "stored": stats.stored,
            "failed": stats.failed,
            "success_rate": round(stats.success_rate, 4),
            "warnings": list(stats.warnings),
        }, indent=2))
    else:
        print(f"\n[backfill] eligible   : {stats.eligible}")
        print(f"[backfill] attempted  : {stats.attempted}")
        print(f"[backfill] stored     : {stats.stored}")
        print(f"[backfill] failed     : {stats.failed}")
        print(f"[backfill] success%%  : {stats.success_rate:.1%}")
        if stats.warnings:
            print(f"[backfill] warnings   :")
            for w in stats.warnings:
                print(f"  - {w}")
        print()

    # exit codes
    if stats.attempted == 0:
        logger.info("Nothing to embed — all chunks already have embeddings.")
        sys.exit(0)
    elif stats.failed == 0:
        sys.exit(0)
    elif stats.stored > 0:
        logger.warning("Partial failure: %d stored, %d failed.", stats.stored, stats.failed)
        sys.exit(2)
    else:
        logger.error("All %d attempts failed.", stats.failed)
        sys.exit(3)


if __name__ == "__main__":
    main()
