"""MCP workspace-scoping fix -- end-to-end regression + role-isolation proof.

Runs the REAL REST API and REAL MCP streamable-http server (both production
code, unmocked) against a disposable, freshly migrated Postgres database, with
real API keys inserted directly into auth_subjects/api_keys/workspace_memberships
-- the same tables MCPBearerAuthMiddleware and the REST auth dependency both
read in production.

Proves the fix from docs/MCP_WORKSPACE_SCOPING_FIX_PLAN.md (OpenCB decisions
2b1c676b-4b2c-48ca-b253-d7b6428e1d75 / 4294c3da-1fb3-4816-b3f6-a31c53e78295 /
0ac855b1-634e-49b8-bdcb-7c74f474179a):

1. Regression repro: the EXACT scenario that leaked before the fix (a reader
   API key bound only to a foreign workspace, calling an MCP tool with no
   workspace_id argument) now correctly fails instead of returning data.
2. Centralized-seam: the same isolation holds across two different
   workspace-scoped tools (get_canonical_body_verified, memory_lab_content_get),
   proving the fix isn't wired for only one endpoint.
3. Positive path: the correct-workspace caller still succeeds normally.
4. Role isolation: a reader-role caller's forwarded token cannot perform a
   write operation over MCP -- REST denies it exactly as it would a direct
   REST call with that same reader key, proving MCP no longer elevates
   privilege via a shared credential.
5. Multi-workspace caller: a caller who is a real member of two workspaces
   can still select between them via an explicit workspace_id argument.

ENVIRONMENT: CB_TEST_ADMIN_DSN as in the other integration suites; skips with
SKIPPED_NO_PUBLIC_STYLE_TEST_DSN when unset.
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import logging
import os
import socket
import threading
import time
import uuid
from urllib.parse import urlparse, urlunparse

import pytest

logging.disable(logging.CRITICAL)


def _psycopg2():
    module = pytest.importorskip(
        "psycopg2",
        reason="SKIPPED_OPTIONAL_PSYCOPG2_UNAVAILABLE — install psycopg2-binary to run DB integration tests.",
    )
    __import__("psycopg2.extensions")
    return module


pytestmark = [pytest.mark.integration, pytest.mark.public_safe, pytest.mark.provider_optional]

_ADMIN_DSN = os.environ.get("CB_TEST_ADMIN_DSN", "").strip()
_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "migrations")
_SKIP_MIGRATION_IDS = {"002"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def test_dsn():
    if not _ADMIN_DSN:
        pytest.skip(
            "SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — CB_TEST_ADMIN_DSN not set. "
            "Provide a dedicated CB test Postgres: "
            "CB_TEST_ADMIN_DSN=postgresql://cb_test:cb_test@localhost:5433/postgres"
        )
    disposable_db = f"cb_mcp_wsscope_{int(time.time())}"
    try:
        admin_conn = _psycopg2().connect(_ADMIN_DSN)
        admin_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        with admin_conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE "{disposable_db}";')
        admin_conn.close()
    except Exception as exc:
        pytest.skip(f"SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — could not connect to CB_TEST_ADMIN_DSN: {exc}")

    parts = urlparse(_ADMIN_DSN)
    db_dsn = urlunparse(parts._replace(path=f"/{disposable_db}"))

    db_conn = _psycopg2().connect(db_dsn)
    db_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        for mig_path in sorted(glob.glob(os.path.join(_MIGRATIONS_DIR, "*.sql"))):
            migration_id = os.path.basename(mig_path).split("_")[0]
            if migration_id in _SKIP_MIGRATION_IDS:
                continue
            with open(mig_path) as fh:
                sql = fh.read()
            if migration_id == "000":
                sql = sql.replace(
                    "CREATE EXTENSION IF NOT EXISTS vector;",
                    "-- pgvector stripped for CB test env",
                )
            with db_conn.cursor() as cur:
                cur.execute(sql)
    except Exception as exc:
        db_conn.close()
        _drop_disposable_db(disposable_db)
        pytest.skip(f"SKIPPED_NO_PUBLIC_STYLE_TEST_DSN — migration apply failed: {exc}")
    finally:
        db_conn.close()

    yield db_dsn

    _drop_disposable_db(disposable_db)


def _drop_disposable_db(db_name: str) -> None:
    try:
        admin_conn = _psycopg2().connect(_ADMIN_DSN)
        admin_conn.set_isolation_level(_psycopg2().extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid();",
                (db_name,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db_name}";')
        admin_conn.close()
    except Exception:
        pass


def _insert_workspace(dsn: str, slug: str) -> str:
    ws_id = str(uuid.uuid4())
    conn = _psycopg2().connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO cb_workspaces (workspace_id, slug, title) VALUES (%s::uuid, %s, %s)",
                (ws_id, slug, slug),
            )
        conn.commit()
    finally:
        conn.close()
    return ws_id


def _create_api_key(dsn: str, workspace_ids: list[str], role: str) -> str:
    """Insert a real auth_subject + api_key + workspace_memberships row(s) directly
    (same tables MCPBearerAuthMiddleware / REST auth read). Returns the raw token."""
    raw_token = f"test_{uuid.uuid4().hex}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    subject_id = str(uuid.uuid4())
    conn = _psycopg2().connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth_subjects (auth_subject_id, subject_type, status) VALUES (%s::uuid, 'service_agent', 'active')",
                (subject_id,),
            )
            cur.execute(
                "INSERT INTO api_keys (auth_subject_id, key_hash, key_prefix, status) VALUES (%s::uuid, %s, %s, 'active')",
                (subject_id, token_hash, raw_token[:12]),
            )
            for ws_id in workspace_ids:
                cur.execute(
                    "INSERT INTO workspace_memberships (workspace_id, auth_subject_id, role, status) "
                    "VALUES (%s::uuid, %s::uuid, %s, 'active')",
                    (ws_id, subject_id, role),
                )
        conn.commit()
    finally:
        conn.close()
    return raw_token


def _seed_content(dsn: str, workspace_id: str, text: str) -> str:
    """Directly seed one hash-verified single-chunk content item -- avoids depending
    on the write path / governance scoring for this auth-focused suite."""
    content_id = str(uuid.uuid4())
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    conn = _psycopg2().connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO content_items (content_id, workspace_id, content_hash, node_type) "
                "VALUES (%s::uuid, %s::uuid, %s, 'raw_note')",
                (content_id, workspace_id, content_hash),
            )
            cur.execute(
                "INSERT INTO content_chunks (content_id, chunk_index, chunk_text) VALUES (%s::uuid, 0, %s)",
                (content_id, text),
            )
        conn.commit()
    finally:
        conn.close()
    return content_id


async def _run_uvicorn(app, port: int):
    """Run a uvicorn server as a task on the CURRENT event loop."""
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:
        raise RuntimeError(f"server on port {port} did not start")
    return server, task


def _run_uvicorn_in_thread(app, port: int):
    """Run a uvicorn server on its OWN event loop in a dedicated OS thread.

    Required for the REST server specifically: MCP tool execution makes a
    fully synchronous (blocking) `requests` call back to REST on the SAME
    thread that runs the MCP server's own event loop (mcp.server.fastmcp
    calls sync tool functions directly, not via a thread pool). If REST ran
    on that same loop, that blocking call would deadlock the loop REST needs
    to respond on. Production doesn't have this issue -- REST and MCP are
    separate OS processes there. This is purely a test-harness necessity.
    """
    import uvicorn

    ready = threading.Event()
    holder: dict = {}

    def _target():
        async def _serve():
            config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
            server = uvicorn.Server(config)
            holder["server"] = server
            serve_task = asyncio.ensure_future(server.serve())
            for _ in range(200):
                if server.started:
                    break
                await asyncio.sleep(0.02)
            ready.set()
            await serve_task

        asyncio.run(_serve())

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    if not ready.wait(timeout=10):
        raise RuntimeError(f"REST server on port {port} did not start")
    return holder, thread


def _stop_uvicorn_in_thread(holder: dict, thread: threading.Thread) -> None:
    server = holder.get("server")
    if server is not None:
        server.should_exit = True
    thread.join(timeout=10)


async def _call_tool(mcp_url: str, token: str, tool: str, args: dict):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool, args)


def test_workspace_scoping_fix_end_to_end(test_dsn):
    ws_a = _insert_workspace(test_dsn, f"a-{uuid.uuid4().hex[:8]}")
    ws_b = _insert_workspace(test_dsn, f"b-{uuid.uuid4().hex[:8]}")

    reader_a = _create_api_key(test_dsn, [ws_a], "reader")
    reader_b_foreign = _create_api_key(test_dsn, [ws_b], "reader")
    multi_owner = _create_api_key(test_dsn, [ws_a, ws_b], "owner")

    content_a_id = _seed_content(test_dsn, ws_a, "content that belongs only to workspace A")
    content_b_id = _seed_content(test_dsn, ws_b, "content that belongs only to workspace B")

    rest_port = _free_port()
    mcp_port = _free_port()

    _ENV_KEYS = (
        "DATABASE_URL", "MEMORY_LAB_AUTH_MODE", "MEMORY_LAB_API_HOST", "MEMORY_LAB_API_PORT",
        "MEMORY_LAB_API_SCHEME", "MEMORY_LAB_HTTP_MCP_AUTH", "MEMORY_LAB_MCP_HTTP_PORT",
        "MEMORY_LAB_API_TOKEN", "MEMORY_LAB_MCP_API_TOKEN", "MEMORY_LAB_MCP_DEFAULT_WORKSPACE_ID",
    )
    _original_env = {k: os.environ.get(k) for k in _ENV_KEYS}

    async def scenario():
        os.environ["DATABASE_URL"] = test_dsn
        os.environ["MEMORY_LAB_AUTH_MODE"] = "api_key"
        os.environ["MEMORY_LAB_API_HOST"] = "127.0.0.1"
        os.environ["MEMORY_LAB_API_PORT"] = str(rest_port)
        os.environ["MEMORY_LAB_API_SCHEME"] = "http"
        os.environ["MEMORY_LAB_HTTP_MCP_AUTH"] = "api_key"
        os.environ["MEMORY_LAB_MCP_HTTP_PORT"] = str(mcp_port)
        os.environ.pop("MEMORY_LAB_API_TOKEN", None)
        os.environ.pop("MEMORY_LAB_MCP_API_TOKEN", None)
        os.environ.pop("MEMORY_LAB_MCP_DEFAULT_WORKSPACE_ID", None)

        from memory_lab.api.main import create_app
        rest_app = create_app()
        rest_holder, rest_thread = _run_uvicorn_in_thread(rest_app, rest_port)

        # Deliberately NOT importlib.reload()-ing anything here. reload() replaces
        # a module's classes with NEW objects in-place, but every OTHER test file
        # already collected this session (pytest imports all test modules up
        # front, before any test body runs) may hold a direct reference to the
        # OLD class objects (e.g. `except MemoryLabApiError`) -- reload() would
        # silently break those isinstance/except checks for the rest of the
        # session. build_asgi_app() and the http_config getters all read os.environ
        # fresh on every call, so a plain call is enough to pick up this test's env.
        import memory_lab.mcp.client as mcp_client
        import memory_lab.mcp.http_server as http_server
        mcp_app = http_server.build_asgi_app()
        mcp_server, mcp_task = await _run_uvicorn(mcp_app, mcp_port)

        mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"

        try:
            # --- 1. Regression repro: foreign-workspace reader, no workspace_id arg ---
            result = await _call_tool(mcp_url, reader_b_foreign, "get_canonical_body_verified", {"content_id": content_a_id})
            payload = _tool_result_json(result)
            assert payload.get("ok") is False, f"expected structured error, got: {payload}"
            assert payload["error"]["status_code"] in (401, 403, 404), payload
            assert "content that belongs only to workspace A" not in str(payload)

            # --- 2. Centralized-seam: same isolation on a second, different tool ---
            result2 = await _call_tool(mcp_url, reader_b_foreign, "memory_lab_content_get", {"content_id": content_a_id})
            payload2 = _tool_result_json(result2)
            assert payload2.get("ok") is False, f"expected structured error, got: {payload2}"
            assert "content that belongs only to workspace A" not in str(payload2)

            # --- 3. Positive path: correct-workspace caller still works ---
            result3 = await _call_tool(mcp_url, reader_a, "get_canonical_body_verified", {"content_id": content_a_id})
            payload3 = _tool_result_json(result3)
            assert payload3.get("fidelity") == "hash-verified", payload3
            assert payload3.get("body") == "content that belongs only to workspace A"

            # --- 4. Role isolation: reader token cannot write ---
            result4 = await _call_tool(mcp_url, reader_a, "memory_lab_content_create_id", {"content": "reader should not be able to write this"})
            payload4 = _tool_result_json(result4)
            assert payload4.get("ok") is False, f"expected write to be denied, got: {payload4}"
            assert payload4["error"]["status_code"] in (401, 403), payload4

            # --- 5. Multi-workspace caller selects via explicit workspace_id ---
            result5a = await _call_tool(
                mcp_url, multi_owner, "get_canonical_body_verified", {"content_id": content_a_id, "workspace_id": ws_a}
            )
            payload5a = _tool_result_json(result5a)
            assert payload5a.get("fidelity") == "hash-verified", payload5a

            result5b = await _call_tool(
                mcp_url, multi_owner, "get_canonical_body_verified", {"content_id": content_b_id, "workspace_id": ws_b}
            )
            payload5b = _tool_result_json(result5b)
            assert payload5b.get("fidelity") == "hash-verified", payload5b
            assert payload5b.get("body") == "content that belongs only to workspace B"
        finally:
            mcp_server.should_exit = True
            await mcp_task
            _stop_uvicorn_in_thread(rest_holder, rest_thread)
            # Reset module-level auth state this test's real middleware set, so it
            # can't leak into other tests sharing this pytest process (e.g. a stray
            # is_authenticated_http_mode_active()=True would fail-close unrelated
            # from_env() calls elsewhere).
            mcp_client.set_authenticated_http_mode_active(False)
            token = mcp_client.set_caller_auth_context(None)
            mcp_client.reset_caller_auth_context(token)

    try:
        asyncio.run(scenario())
    finally:
        for key, value in _original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _tool_result_json(result) -> dict:
    import json

    return json.loads(result.content[0].text)
