from __future__ import annotations

import importlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from memory_lab.bootstrap.config import load_config

WORKSPACE_ROOT = Path(os.getenv("MEMORY_LAB_WORKSPACE", Path(__file__).resolve().parents[2])).resolve()
REPORTS_DIR = WORKSPACE_ROOT / "reports"
SUMMARY_JSON = REPORTS_DIR / "pr1a_bootstrap_smoke_summary.json"
EVIDENCE_MD = REPORTS_DIR / "PR1A_BOOTSTRAP_SMOKE_EVIDENCE.md"

MIGRATIONS = [
    "001_add_content_chunks.sql",
    "002_add_chunk_embeddings.sql",
    "003_add_graph_layer.sql",
    "004_add_alias_layer.sql",
    "005_add_hub_layer.sql",
    "006_add_hub_edges.sql",
    "007_hub_edges_v2.sql",
    "008_add_node_type.sql",
    "009_add_quick_summary.sql",
]

IMPORT_TARGETS = [
    "memory_lab.graph.store",
    "memory_lab.graph.hub_store",
    "memory_lab.graph.hub_edge_store",
    "memory_lab.graph.alias_store",
    "memory_lab.graph.adapter",
    "memory_lab.graph.hybrid_search",
    "memory_lab.graph.expansion",
    "memory_lab.graph.edge",
    "memory_lab.api.services.content_quality",
    "memory_lab.api.policies.content_quality",
    "memory_lab.api.utils.content_signatures",
]

@dataclass
class StageResult:
    name: str
    status: str
    notes: str = ""


def _run_psql(database_url: str, sql_file: Path) -> subprocess.CompletedProcess:
    cmd = ["psql", database_url, "-v", "ON_ERROR_STOP=1", "-f", str(sql_file)]
    return subprocess.run(cmd, text=True, capture_output=True)


def run_smoke() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = load_config()
    stages: List[StageResult] = []
    mode = "db_absent" if not cfg.database_url else "db_present"

    # Stage 1: import smoke
    try:
        for mod in IMPORT_TARGETS:
            importlib.import_module(mod)
        stages.append(StageResult("import_smoke", "PASS", f"Imported {len(IMPORT_TARGETS)} modules"))
    except Exception as e:
        stages.append(StageResult("import_smoke", "FAIL", f"{type(e).__name__}: {e}"))
        _write_reports(ts, mode, stages, "FAIL", db_smoke="skipped")
        return 1

    # DB-absent path
    if not cfg.database_url:
        stages.append(StageResult("db_connect", "SKIP", "DATABASE_URL missing"))
        stages.append(StageResult("migrations_001_009", "SKIP", "DATABASE_URL missing"))
        stages.append(StageResult("store_instantiation", "SKIP", "DATABASE_URL missing"))
        _write_reports(ts, mode, stages, "PASS_WITH_DB_SKIPPED", db_smoke="skipped")
        return 0

    # DB-present path
    try:
        psycopg2 = importlib.import_module("psycopg2")
        conn = psycopg2.connect(cfg.database_url)
        conn.close()
        stages.append(StageResult("db_connect", "PASS", "Connection opened/closed successfully"))
    except Exception as e:
        stages.append(StageResult("db_connect", "FAIL", f"{type(e).__name__}: {e}"))
        _write_reports(ts, mode, stages, "FAIL", db_smoke="ran")
        return 1

    try:
        mig_dir = WORKSPACE_ROOT / "migrations"
        for mig in MIGRATIONS:
            proc = _run_psql(cfg.database_url, mig_dir / mig)
            if proc.returncode != 0:
                raise RuntimeError(f"Migration {mig} failed: {proc.stderr.strip()[:500]}")
        stages.append(StageResult("migrations_001_009", "PASS", "Applied 001..009"))
    except Exception as e:
        stages.append(StageResult("migrations_001_009", "FAIL", f"{type(e).__name__}: {e}"))
        _write_reports(ts, mode, stages, "FAIL", db_smoke="ran")
        return 1

    try:
        stores_mod = importlib.import_module("memory_lab.bootstrap.stores")
        build_store_bundle = getattr(stores_mod, "build_store_bundle")
        bundle = build_store_bundle(cfg.database_url)
        _ = (bundle.graph_store, bundle.hub_store, bundle.hub_edge_store, bundle.alias_store)
        stages.append(StageResult("store_instantiation", "PASS", "Instantiated 4 store objects"))
    except Exception as e:
        stages.append(StageResult("store_instantiation", "FAIL", f"{type(e).__name__}: {e}"))
        _write_reports(ts, mode, stages, "FAIL", db_smoke="ran")
        return 1

    _write_reports(ts, mode, stages, "PASS", db_smoke="ran")
    return 0


def _write_reports(ts: str, mode: str, stages: List[StageResult], final_verdict: str, db_smoke: str) -> None:
    data: Dict[str, Any] = {
        "timestamp_utc": ts,
        "mode": mode,
        "stages": [asdict(s) for s in stages],
        "migration_scope": "001..009",
        "final_verdict": final_verdict,
        "db_smoke": db_smoke,
    }
    SUMMARY_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")

    lines = [
        "# PR1A Bootstrap Smoke Evidence",
        "",
        f"- timestamp_utc: {ts}",
        f"- mode: {mode}",
        "- scope: PR1a staging bootstrap smoke only",
        "- guardrails: no git init, no repo creation, no commit/push, no public export",
        "",
        "## Stage results",
    ]
    for s in stages:
        lines.append(f"- {s.name}: {s.status} — {s.notes}")
    lines += [
        "",
        "## Contract",
        "- migration_scope: 001..009",
        f"- db_smoke: {db_smoke}",
        f"- final_verdict: {final_verdict}",
        "",
        "## Output artifacts",
        "- reports/PR1A_BOOTSTRAP_SMOKE_EVIDENCE.md",
        "- reports/pr1a_bootstrap_smoke_summary.json",
    ]
    EVIDENCE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(run_smoke())
