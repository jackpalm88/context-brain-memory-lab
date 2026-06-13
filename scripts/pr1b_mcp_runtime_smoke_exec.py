#!/usr/bin/env python3
"""PR1B MCP runtime smoke executor (execution-gated)."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote

import anyio
import psycopg2
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

WORKSPACE = Path(__file__).resolve().parents[1]
REPORTS_DIR = WORKSPACE / "reports"
LOGS_DIR = REPORTS_DIR / "pr1b_mcp_runtime_logs"

API_LOG_OUT = LOGS_DIR / "api_stdout.log"
API_LOG_ERR = LOGS_DIR / "api_stderr.log"
MCP_LOG_OUT = LOGS_DIR / "mcp_stdout.log"
MCP_LOG_ERR = LOGS_DIR / "mcp_stderr.log"

EVIDENCE_PATH = REPORTS_DIR / "PR1B_MCP_RUNTIME_SMOKE_EVIDENCE.md"
SUMMARY_PATH = REPORTS_DIR / "pr1b_mcp_runtime_smoke_summary.json"
PASS_REVIEW_PATH = REPORTS_DIR / "PR1B_MCP_RUNTIME_PASS_REVIEW.md"


@dataclass
class StageResult:
    name: str
    status: str
    detail: str


class SmokeFailure(RuntimeError):
    pass


def utc_ts() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def make_disposable_db_name() -> str:
    return f"pr1b_mcp_smoke_{utc_ts()}"


def ensure_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def is_local_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost"}


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def safe_db_name(db_name: str) -> bool:
    return db_name.startswith("pr1b_mcp_smoke_") and db_name not in {"contentingestor", "postgres"}


def terminate_proc(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def admin_conn(db_host: str, db_port: int, db_user: str, db_password: str, db_name: str = "postgres"):
    conn = psycopg2.connect(host=db_host, port=db_port, user=db_user, password=db_password, dbname=db_name)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def create_disposable_db(db_host: str, db_port: int, db_user: str, db_password: str, db_name: str) -> None:
    conn = admin_conn(db_host, db_port, db_user, db_password, "postgres")
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        conn.close()


def terminate_db_sessions(db_host: str, db_port: int, db_user: str, db_password: str, db_name: str) -> None:
    with admin_conn(db_host, db_port, db_user, db_password, "postgres") as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (db_name,),
            )


def drop_disposable_db(db_host: str, db_port: int, db_user: str, db_password: str, db_name: str) -> None:
    conn = admin_conn(db_host, db_port, db_user, db_password, "postgres")
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    finally:
        conn.close()


def parse_migration_prefix(name: str) -> Optional[int]:
    if len(name) < 3:
        return None
    p = name[:3]
    return int(p) if p.isdigit() else None


def migration_inventory(migrations_dir: Path) -> Tuple[List[Path], List[Path]]:
    if not migrations_dir.exists():
        raise SmokeFailure(f"Missing migrations dir: {migrations_dir}")
    all_files = sorted([p for p in migrations_dir.iterdir() if p.is_file()])
    allowed: List[Path] = []
    forbidden: List[Path] = []
    for p in all_files:
        pref = parse_migration_prefix(p.name)
        if pref is None:
            continue
        if 0 <= pref <= 9:
            allowed.append(p)
        elif pref >= 10:
            forbidden.append(p)
    if not allowed:
        raise SmokeFailure("No 000..009 migrations found")
    return allowed, forbidden


def apply_migrations_000_009(db_host: str, db_port: int, db_user: str, db_password: str, db_name: str, migrations_dir: Path) -> List[str]:
    allowed, forbidden = migration_inventory(migrations_dir)
    if forbidden:
        names = ", ".join(p.name for p in forbidden)
        raise SmokeFailure(f"Forbidden 010+ migrations present: {names}")
    applied: List[str] = []
    conn = psycopg2.connect(host=db_host, port=db_port, user=db_user, password=db_password, dbname=db_name)
    try:
        with conn:
            with conn.cursor() as cur:
                for path in allowed:
                    sql = path.read_text(encoding="utf-8")
                    if sql.strip():
                        cur.execute(sql)
                    applied.append(path.name)
    finally:
        conn.close()
    return applied


def wait_http_ready(url: str, timeout_s: float = 30.0) -> None:
    import requests

    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1.5)
            if r.status_code < 500:
                return
            last_err = f"status={r.status_code}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(0.5)
    raise SmokeFailure(f"HTTP readiness timeout for {url}: {last_err}")


def _normalize_payload_dict(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common FastMCP call_tool payload shapes.

    Accepted shapes:
    - {"status": "ok", ...}
    - {"result": {"status": "ok", ...}}
    """
    if isinstance(payload.get("result"), dict):
        return payload["result"]
    return payload


def _extract_call_tool_payload(result: Any) -> Dict[str, Any]:
    if getattr(result, "isError", False):
        raise SmokeFailure("MCP call_tool returned isError=true")
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return _normalize_payload_dict(structured)
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return _normalize_payload_dict(parsed)
                except Exception:
                    pass
    raise SmokeFailure("Unable to parse MCP tool payload")


def _sanitize_args(args: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in args.items():
        if any(t in k.lower() for t in ("password", "secret", "token", "key")):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


def _flatten_exception_group(exc: BaseException) -> Dict[str, Any]:
    details: Dict[str, Any] = {
        "exception_group_type": None,
        "sub_exception_count": 0,
        "sub_exception_classes": [],
        "sub_exception_messages": [],
        "traceback": traceback.format_exc(),
    }
    if isinstance(exc, ExceptionGroup):
        details["exception_group_type"] = exc.__class__.__name__
        details["sub_exception_count"] = len(exc.exceptions)
        details["sub_exception_classes"] = [e.__class__.__name__ for e in exc.exceptions]
        details["sub_exception_messages"] = [str(e) for e in exc.exceptions]
    return details


async def _call_tool_checked(
    session: ClientSession,
    trace: List[Dict[str, Any]],
    diag: Dict[str, Any],
    tool_name: str,
    args: Dict[str, Any],
) -> Dict[str, Any]:
    sanitized = _sanitize_args(args)
    diag["current_tool"] = tool_name
    diag["failing_tool"] = tool_name  # pre-set before call starts
    trace.append({"tool_name": tool_name, "args": sanitized, "stage": "start"})
    try:
        raw_result = await session.call_tool(tool_name, args)
        if tool_name == "memory_lab_health":
            diag["health_call_raw_result"] = {
                "isError": bool(getattr(raw_result, "isError", False)),
                "structuredContent": getattr(raw_result, "structuredContent", None),
                "content": [getattr(x, "text", None) for x in (getattr(raw_result, "content", None) or [])],
            }
        payload = _extract_call_tool_payload(raw_result)
        trace.append({"tool_name": tool_name, "args": sanitized, "stage": "end", "status": "ok", "normalized_payload": payload if tool_name == "memory_lab_health" else None})
        return payload
    except Exception as exc:
        trace_item: Dict[str, Any] = {
            "tool_name": tool_name,
            "args": sanitized,
            "stage": "end",
            "status": "error",
            "exception_class": exc.__class__.__name__,
            "exception_message": str(exc),
            "traceback": traceback.format_exc(),
        }
        if isinstance(exc, ExceptionGroup):
            trace_item["exception_group"] = {
                "sub_exception_count": len(exc.exceptions),
                "sub_exception_classes": [e.__class__.__name__ for e in exc.exceptions],
                "sub_exception_messages": [str(e) for e in exc.exceptions],
            }
        trace.append(trace_item)
        diag["exception_group_details"] = _flatten_exception_group(exc)
        raise SmokeFailure(f"failing_tool={tool_name}; exception_class={exc.__class__.__name__}; message={str(exc)}") from exc


async def _run_mcp_protocol_sequence(server_params: StdioServerParameters) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "mcp_phase": "not_started",
        "failing_tool": None,
        "current_tool": None,
        "mcp_call_tool_trace": [],
        "exception_group_details": {
            "exception_group_type": None,
            "sub_exception_count": 0,
            "sub_exception_classes": [],
            "sub_exception_messages": [],
            "traceback": None,
        },
    }
    trace: List[Dict[str, Any]] = out["mcp_call_tool_trace"]

    try:
        out["mcp_phase"] = "stdio_client_open"
        with MCP_LOG_ERR.open("w", encoding="utf-8") as mcp_err:
            async with stdio_client(server_params, errlog=mcp_err) as streams:
                read_stream, write_stream = streams
                out["mcp_phase"] = "client_session_open"
                async with ClientSession(read_stream, write_stream) as session:
                    out["mcp_phase"] = "initialize"
                    await session.initialize()

                    out["mcp_phase"] = "list_tools"
                    tools_result = await session.list_tools()
                    available = [t.name for t in tools_result.tools]
                    MCP_LOG_OUT.write_text(json.dumps({"listed_tools": available}, indent=2), encoding="utf-8")

                    required = [
                        "memory_lab_health", "memory_lab_content_create_id", "memory_lab_content_get",
                        "memory_lab_hub_create", "memory_lab_hub_get", "memory_lab_hub_link_content",
                        "memory_lab_edge_create", "memory_lab_edge_get", "memory_lab_edge_list",
                        "memory_lab_edge_archive", "memory_lab_retrieval_search",
                    ]
                    missing = [n for n in required if n not in available]
                    if missing:
                        raise SmokeFailure(f"MCP list_tools missing required tools: {', '.join(missing)}")

                    out["mcp_phase"] = "call_tools"
                    health = await _call_tool_checked(session, trace, out, "memory_lab_health", {})
                    if health.get("status") != "ok":
                        raise SmokeFailure("health check failed: expected status=ok")
                    out["health"] = health

                    create = await _call_tool_checked(session, trace, out, "memory_lab_content_create_id", {})
                    cid = create.get("content_id")
                    if not cid:
                        raise SmokeFailure("content_create_id missing content_id")
                    if create.get("mode") != "id_allocation_only":
                        raise SmokeFailure("content_create_id mode != id_allocation_only")
                    out["content_create"] = create

                    getc = await _call_tool_checked(session, trace, out, "memory_lab_content_get", {"content_id": cid})
                    if getc.get("content_id") != cid:
                        raise SmokeFailure("content_get id mismatch")
                    out["content_get"] = getc

                    hub = await _call_tool_checked(session, trace, out, "memory_lab_hub_create", {"title": "PR1B MCP Smoke Hub"})
                    hid = hub.get("hub_id") or hub.get("id")
                    if not hid:
                        raise SmokeFailure("hub_create missing hub_id")
                    out["hub_create"] = hub

                    out["hub_get"] = await _call_tool_checked(session, trace, out, "memory_lab_hub_get", {"hub_id": hid})
                    link = await _call_tool_checked(session, trace, out, "memory_lab_hub_link_content", {"hub_id": hid, "content_id": cid})
                    if not link.get("linked", False):
                        raise SmokeFailure("hub_link_content linked!=true")
                    out["hub_link"] = link

                    hub2 = await _call_tool_checked(session, trace, out, "memory_lab_hub_create", {"title": "PR1B MCP Smoke Hub 2"})
                    hid2 = hub2.get("hub_id") or hub2.get("id")
                    if not hid2:
                        raise SmokeFailure("hub_create#2 missing hub_id")

                    edge = await _call_tool_checked(session, trace, out, "memory_lab_edge_create", {"source_hub_id": hid, "target_hub_id": hid2, "edge_type": "related"})
                    eid = edge.get("id") or edge.get("edge_id")
                    if not eid:
                        raise SmokeFailure("edge_create missing edge id")
                    out["edge_create"] = edge

                    out["edge_get"] = await _call_tool_checked(session, trace, out, "memory_lab_edge_get", {"edge_id": eid})
                    out["edge_list_before"] = await _call_tool_checked(session, trace, out, "memory_lab_edge_list", {})

                    arc = await _call_tool_checked(session, trace, out, "memory_lab_edge_archive", {"edge_id": eid})
                    if not arc.get("archived", False):
                        raise SmokeFailure("edge_archive archived!=true")
                    out["edge_archive"] = arc

                    edge_list_active = await _call_tool_checked(session, trace, out, "memory_lab_edge_list", {"include_archived": False})
                    if int(edge_list_active.get("count", 0)) != 0:
                        raise SmokeFailure("active edge count expected 0 after archive")
                    out["edge_list_active"] = edge_list_active

                    edge_list_arch = await _call_tool_checked(session, trace, out, "memory_lab_edge_list", {"include_archived": True})
                    if int(edge_list_arch.get("count", 0)) < 1:
                        raise SmokeFailure("archived edge count expected >=1")
                    out["edge_list_archived"] = edge_list_arch

                    ret = await _call_tool_checked(session, trace, out, "memory_lab_retrieval_search", {"query": "smoke", "limit": 5})
                    if ret.get("mode") != "deterministic_stub_default":
                        raise SmokeFailure("retrieval mode != deterministic_stub_default")
                    out["retrieval"] = ret

                    out["mcp_phase"] = "completed"
                    out["failing_tool"] = None

    except Exception as exc:
        if out.get("failing_tool") is None:
            out["failing_tool"] = out.get("current_tool")
        if out.get("exception_group_details", {}).get("traceback") in (None, ""):
            out["exception_group_details"] = _flatten_exception_group(exc)
        raise

    return out


def invoke_tools_sequence_via_mcp_stdio(mcp_cmd: List[str], env: Dict[str, str]) -> Dict[str, Any]:
    params = StdioServerParameters(command=mcp_cmd[0], args=mcp_cmd[1:], env=env, cwd=str(WORKSPACE))
    return anyio.run(_run_mcp_protocol_sequence, params)


def write_summary(payload: Dict[str, Any]) -> None:
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_evidence_md(summary: Dict[str, Any]) -> None:
    stages_md = "\n".join(f"- {s['name']}: {s['status']} ({s['detail']})" for s in summary.get("stages", []))
    text = f"""# PR1B MCP Runtime Smoke Evidence

mode: runtime_execution
workspace: {WORKSPACE}

## Final verdict
- {summary.get('final_verdict')}

## Execution envelope
- db_name: {summary.get('db_name')}
- db_host: {summary.get('db_host')}
- db_role: {summary.get('db_role')}
- migrations_scope: 000..009 only
- local_only: true

## Stage results
{stages_md}

## MCP diagnostics
- mcp_phase: {summary.get('mcp_phase')}
- failing_tool: {summary.get('failing_tool')}
- exception_group_details: {json.dumps(summary.get('exception_group_details', {}), ensure_ascii=False)}
- mcp_call_tool_trace_count: {len(summary.get('mcp_call_tool_trace', []))}

## Logs
- API stdout: {API_LOG_OUT}
- API stderr: {API_LOG_ERR}
- MCP stdout: {MCP_LOG_OUT}
- MCP stderr: {MCP_LOG_ERR}
"""
    EVIDENCE_PATH.write_text(text, encoding="utf-8")


def resolve_db_password(cli_value: str) -> str:
    if cli_value:
        return cli_value
    for key in ("PGPASSWORD", "POSTGRES_PASSWORD"):
        env_pw = os.getenv(key, "").strip()
        if env_pw:
            return env_pw
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        parsed = urlparse(database_url)
        if parsed.password:
            return unquote(parsed.password)
    return ""


def write_pass_review_if_full_pass(summary: Dict[str, Any]) -> None:
    if summary.get("final_verdict") != "PASS":
        return
    PASS_REVIEW_PATH.write_text("# PR1B MCP Runtime PASS Review\n\nGenerated only on full PASS.\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="PR1B MCP runtime smoke executor")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--db-host", default=os.getenv("PGHOST", "localhost"))
    parser.add_argument("--db-port", type=int, default=int(os.getenv("PGPORT", "5432")))
    parser.add_argument("--db-user", default=os.getenv("PGUSER", "contentingestor"))
    parser.add_argument("--db-password", default="")
    parser.add_argument("--db-name", default=None)
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=51251)
    parser.add_argument("--mcp-host", default="127.0.0.1")
    parser.add_argument("--mcp-port", type=int, default=51261)
    args = parser.parse_args()

    if not args.execute:
        print("REFUSAL: runtime/destructive steps disabled by default. Use --execute only in approved execution gate.")
        return 2

    db_password = resolve_db_password(args.db_password)
    if not db_password:
        raise SystemExit("DB password not supplied")

    ensure_dirs()
    db_name = args.db_name or make_disposable_db_name()
    stages: List[StageResult] = []
    api_proc: Optional[subprocess.Popen] = None
    final_verdict = "FAIL"
    detail = "Uninitialized"
    applied_migrations: List[str] = []
    tool_outcomes: Dict[str, Any] = {
        "mcp_phase": "not_started",
        "failing_tool": None,
        "mcp_call_tool_trace": [],
        "exception_group_details": {
            "exception_group_type": None,
            "sub_exception_count": 0,
            "sub_exception_classes": [],
            "sub_exception_messages": [],
            "traceback": None,
        },
    }

    try:
        if not is_local_host(args.db_host):
            raise SmokeFailure(f"Unsafe DB host: {args.db_host}")
        if args.db_user != "contentingestor":
            raise SmokeFailure(f"Unsafe DB role: {args.db_user}")
        if not safe_db_name(db_name):
            raise SmokeFailure(f"Unsafe DB name: {db_name}")
        if not is_local_host(args.api_host) or not is_local_host(args.mcp_host):
            raise SmokeFailure("API/MCP host must be local-only")
        if not port_is_free(args.api_host, args.api_port):
            raise SmokeFailure(f"API port busy: {args.api_host}:{args.api_port}")

        allowed, forbidden = migration_inventory(WORKSPACE / "migrations")
        if forbidden:
            raise SmokeFailure("Migration inventory includes 010+ files; execution rejected")
        stages.append(StageResult("preflight", "PASS", "Safety checks and migration inventory passed"))

        create_disposable_db(args.db_host, args.db_port, args.db_user, db_password, db_name)
        stages.append(StageResult("db_create", "PASS", f"Created {db_name}"))

        applied_migrations = apply_migrations_000_009(args.db_host, args.db_port, args.db_user, db_password, db_name, WORKSPACE / "migrations")
        stages.append(StageResult("migrate_000_009", "PASS", f"Applied {len(applied_migrations)} migrations"))

        env = os.environ.copy()
        env["DATABASE_URL"] = f"postgresql://{args.db_user}:{db_password}@{args.db_host}:{args.db_port}/{db_name}"
        env["MEMORY_LAB_API_HOST"] = args.api_host
        env["MEMORY_LAB_API_PORT"] = str(args.api_port)

        with API_LOG_OUT.open("w", encoding="utf-8") as api_out, API_LOG_ERR.open("w", encoding="utf-8") as api_err:
            api_cmd = [str(WORKSPACE / ".venv/bin/python"), "-m", "uvicorn", "memory_lab.api.main:app", "--host", args.api_host, "--port", str(args.api_port)]
            mcp_cmd = [str(WORKSPACE / ".venv/bin/python"), "-m", "memory_lab.mcp.server"]
            api_proc = subprocess.Popen(api_cmd, cwd=str(WORKSPACE), env=env, stdout=api_out, stderr=api_err)
            wait_http_ready(f"http://{args.api_host}:{args.api_port}/health", timeout_s=30.0)
            stages.append(StageResult("api_start", "PASS", "API started and health reachable"))

            tool_outcomes = invoke_tools_sequence_via_mcp_stdio(mcp_cmd=mcp_cmd, env=env)
            stages.append(StageResult("mcp_start", "PASS", "MCP stdio session initialized"))
            stages.append(StageResult("tool_sequence", "PASS", f"Validated {len(tool_outcomes)} MCP protocol tool outputs"))

        final_verdict = "PASS"
        detail = "All stages passed"

    except Exception as exc:
        final_verdict = "FAIL"
        detail = str(exc)
        if not tool_outcomes.get("exception_group_details", {}).get("traceback"):
            tool_outcomes["exception_group_details"] = _flatten_exception_group(exc)
        stages.append(StageResult("error", "FAIL", detail))
    finally:
        teardown_ok = True
        teardown_detail: List[str] = ["mcp_stopped"]
        try:
            terminate_proc(api_proc)
            teardown_detail.append("api_stopped")
        except Exception as exc:
            teardown_ok = False
            teardown_detail.append(f"api_stop_fail:{exc}")
        try:
            terminate_db_sessions(args.db_host, args.db_port, args.db_user, db_password, db_name)
            teardown_detail.append("db_sessions_terminated")
        except Exception as exc:
            teardown_ok = False
            teardown_detail.append(f"db_terminate_fail:{exc}")
        try:
            drop_disposable_db(args.db_host, args.db_port, args.db_user, db_password, db_name)
            teardown_detail.append("db_dropped")
        except Exception as exc:
            teardown_ok = False
            teardown_detail.append(f"db_drop_fail:{exc}")

        stages.append(StageResult("teardown", "PASS" if teardown_ok else "FAIL", ";".join(teardown_detail)))
        if final_verdict == "PASS" and not teardown_ok:
            final_verdict = "FAIL"
            detail = "Execution stages passed but teardown failed"

    summary = {
        "gate": "PR1B_MCP_RUNTIME_SMOKE_EXECUTION_GO",
        "workspace": str(WORKSPACE),
        "db_host": args.db_host,
        "db_port": args.db_port,
        "db_role": args.db_user,
        "db_name": db_name,
        "applied_migrations": applied_migrations,
        "tool_sequence": [
            "memory_lab_health", "memory_lab_content_create_id", "memory_lab_content_get",
            "memory_lab_hub_create", "memory_lab_hub_get", "memory_lab_hub_link_content",
            "memory_lab_edge_create", "memory_lab_edge_get", "memory_lab_edge_list",
            "memory_lab_edge_archive", "memory_lab_edge_list", "memory_lab_edge_list",
            "memory_lab_retrieval_search"
        ],
        "mcp_phase": tool_outcomes.get("mcp_phase"),
        "failing_tool": tool_outcomes.get("failing_tool"),
        "mcp_call_tool_trace": tool_outcomes.get("mcp_call_tool_trace", []),
        "exception_group_details": tool_outcomes.get("exception_group_details", {}),
        "health_call_raw_result": tool_outcomes.get("health_call_raw_result"),
        "final_verdict": final_verdict,
        "detail": detail,
        "stages": [s.__dict__ for s in stages],
        "truthful_boundaries": {
            "no_partial_success_pass": True,
            "provider_embeddings_proven": False,
            "llm_generation_proven": False,
            "public_export_proven": False,
            "installable_package_flow_proven": False
        }
    }

    write_summary(summary)
    write_evidence_md(summary)
    write_pass_review_if_full_pass(summary)
    return 0 if final_verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
