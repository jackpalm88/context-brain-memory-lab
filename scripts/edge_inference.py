"""EDGE-INF-1 — deterministic inferred-edge producer CLI (gap-4).

Computes hub-to-hub edge proposals for one workspace from two deterministic
signals (content co-membership, topic-tag alignment) and writes them as
status='inferred', origin='ai_suggested' rows in cb_hub_edges. Existing
manual / approved / rejected edges are never touched; the human gate
(approve_inferred_edge / reject_inferred_edge) stays the only path to a
curated edge.

Usage:
    python scripts/edge_inference.py \
        --dsn "host=127.0.0.1 dbname=cbml user=cbml password=..." \
        --workspace-id <UUID> \
        --dry-run

    # live run
    python scripts/edge_inference.py --dsn ... --workspace-id <UUID>

Exit codes:
    0  success (or dry-run complete)
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
logger = logging.getLogger("edge_inference")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Propose inferred hub-to-hub edges for one workspace (EDGE-INF-1).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--dsn", required=True,
                   help="libpq DSN string, e.g. 'host=127.0.0.1 dbname=cbml user=cbml password=...'")
    p.add_argument("--workspace-id", required=True,
                   help="Workspace UUID to scope the inference run (required).")
    p.add_argument("--min-shared", type=int, default=3,
                   help="Min shared linked-content rows for co-membership pairs (default: 3).")
    p.add_argument("--min-cooccur", type=int, default=3,
                   help="Min co-mentioning documents for tag-alignment pairs (default: 3).")
    p.add_argument("--max-proposals", type=int, default=50,
                   help="Cap on proposals per run, highest confidence first (default: 50).")
    p.add_argument("--dry-run", action="store_true",
                   help="Compute and print proposals; write nothing.")
    p.add_argument("--output-json", action="store_true",
                   help="Print the full report as JSON to stdout.")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    import psycopg2
    from memory_lab.graph.edge_inference import run_edge_inference

    try:
        conn = psycopg2.connect(args.dsn)
    except Exception as exc:
        logger.error("connection failed: %s", exc)
        return 1

    try:
        report = run_edge_inference(
            conn,
            workspace_id=args.workspace_id,
            min_shared=args.min_shared,
            min_cooccur=args.min_cooccur,
            max_proposals=args.max_proposals,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()

    if args.output_json:
        print(json.dumps(report, indent=2))
    else:
        mode = "dry-run" if report["dry_run"] else "live"
        print(f"[{mode}] workspace      : {report['workspace_id']}")
        print(f"[{mode}] hubs considered: {report['hubs_considered']}")
        print(f"[{mode}] proposals      : {report['proposals_total']} "
              f"(co_membership={report['proposals_co_membership']}, "
              f"tag_alignment={report['proposals_tag_alignment']})")
        if not report["dry_run"]:
            print(f"[{mode}] inserted       : {report['inserted']}")
            print(f"[{mode}] skipped        : {report['skipped_existing']} (existing active edges)")
        for p in report["proposals"][:20]:
            rules = "+".join(p["detection_rules"])
            print(f"  {p['source_hub_id'][:8]} -[{p['edge_type']}]-> {p['target_hub_id'][:8]} "
                  f"conf={p['confidence']} evidence={p['evidence_count']} ({rules})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
