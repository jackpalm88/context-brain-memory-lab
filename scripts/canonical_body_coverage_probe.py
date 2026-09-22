#!/usr/bin/env python3
"""Canonical-body verified-reconstruction coverage probe (Patch 1, Phase C).

Read-only. Reuses memory_lab.content.canonical_body (the same helper covered
by tests/unit/test_canonical_body_reconstruction.py) against the live corpus
to measure what fraction of existing content_items can be recovered as
hash-verified from persisted content_chunks, before any API surface is wired
up. This is the evidence gate for Patch 1's go/no-go
(engineering plan §8 / OpenCB decision 5533831e-c751-434a-8ae7-f8f40cdaf0f8).

Guarantees:
    - SELECT-only. No INSERT/UPDATE/DELETE, no schema change, no commit.
    - Never prints body text or chunk text -- aggregate counts only.
    - Workspace-scopable via --workspace-id; otherwise scans all workspaces.

Usage:
    python scripts/canonical_body_coverage_probe.py \\
        --dsn "host=127.0.0.1 port=5433 dbname=cbml user=cbml password=..." \\
        [--workspace-id <UUID>] [--limit 5000] [--output-json]

Exit codes:
    0  probe completed (regardless of coverage outcome)
    1  bad arguments / connection failure
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("canonical_body_coverage_probe")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Read-only coverage probe for canonical-body verified reconstruction.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--dsn", required=True,
                   help="libpq DSN string, e.g. 'host=127.0.0.1 port=5433 dbname=cbml user=cbml password=...'")
    p.add_argument("--workspace-id", default=None,
                   help="Scope the probe to one workspace UUID (default: all workspaces).")
    p.add_argument("--limit", type=int, default=None,
                   help="Max content_items rows to scan (default: no limit).")
    p.add_argument("--output-json", action="store_true",
                   help="Print the final aggregate report as JSON to stdout.")
    return p.parse_args()


def _connect(dsn: str):
    try:
        import psycopg2
        conn = psycopg2.connect(dsn)
        conn.set_session(readonly=True, autocommit=True)
        return conn
    except Exception as exc:
        logger.error("DB connection failed: %s", exc)
        sys.exit(1)


def run_probe(conn, *, workspace_id: str | None, limit: int | None) -> dict:
    from memory_lab.content.canonical_body import (
        FIDELITY_HASH_VERIFIED,
        FIDELITY_UNAVAILABLE,
        FIDELITY_UNVERIFIABLE,
        PersistedChunk,
        diagnose_reconstruction,
    )

    counts = {
        "total_with_hash": 0,
        "hash_verified": 0,
        "unverifiable": 0,
        "unavailable": 0,
        "single_chunk_verified": 0,
        "multi_chunk_verified": 0,
        "index_gap_or_duplicate": 0,
        "hash_mismatch": 0,
        "possible_line_ending_normalization": 0,
        "possible_max_chunk_truncation": 0,
    }

    where = ["ci.content_hash IS NOT NULL"]
    params: list = []
    if workspace_id:
        where.append("ci.workspace_id = %s::uuid")
        params.append(workspace_id)
    query = f"""
        SELECT ci.content_id::text, ci.content_hash
          FROM content_items ci
         WHERE {' AND '.join(where)}
         ORDER BY ci.created_at
    """
    if limit:
        query += " LIMIT %s"
        params.append(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    counts["total_with_hash"] = len(rows)
    logger.info("Scanning %d content_items rows with a stored content_hash...", len(rows))

    with conn.cursor() as chunk_cur:
        for content_id, content_hash in rows:
            chunk_cur.execute(
                "SELECT chunk_index, chunk_text FROM content_chunks WHERE content_id = %s::uuid ORDER BY chunk_index",
                (content_id,),
            )
            chunk_rows = chunk_cur.fetchall()
            chunks = [PersistedChunk(idx, text) for idx, text in chunk_rows]

            diag = diagnose_reconstruction(chunks, content_hash)

            if diag.fidelity == FIDELITY_HASH_VERIFIED:
                counts["hash_verified"] += 1
                if len(chunks) <= 1:
                    counts["single_chunk_verified"] += 1
                else:
                    counts["multi_chunk_verified"] += 1
            elif diag.fidelity == FIDELITY_UNVERIFIABLE:
                counts["unverifiable"] += 1
                if diag.reason in ("chunk_index_gap", "duplicate_chunk_index"):
                    counts["index_gap_or_duplicate"] += 1
                elif diag.reason.startswith("hash_mismatch"):
                    counts["hash_mismatch"] += 1
                if diag.reason == "hash_mismatch_possible_max_chunk_truncation":
                    counts["possible_max_chunk_truncation"] += 1
                if diag.possible_line_ending_normalization:
                    counts["possible_line_ending_normalization"] += 1
            elif diag.fidelity == FIDELITY_UNAVAILABLE:
                counts["unavailable"] += 1

    total = counts["total_with_hash"] or 1
    counts["hash_verified_coverage_pct"] = round(100.0 * counts["hash_verified"] / total, 2)
    return counts


def main() -> None:
    args = _parse_args()
    conn = _connect(args.dsn)
    try:
        report = run_probe(conn, workspace_id=args.workspace_id, limit=args.limit)
    finally:
        conn.close()

    if args.output_json:
        print(json.dumps(report, indent=2))
    else:
        print("\n[canonical-body coverage probe] aggregate counts (no body text, read-only):")
        for key, value in report.items():
            print(f"  {key:<38}: {value}")
        print()


if __name__ == "__main__":
    main()
