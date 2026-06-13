#!/usr/bin/env python3
"""
Disposable-DB smoke for ROUTER_STUB_EXPANSION_HUBS_DECISIONS_IMPLEMENT_AND_SMOKE.
Creates an isolated DB, applies migrations 000..026, seeds auth fixtures,
runs hub API smoke via FastAPI TestClient, then drops the DB.
Reads credentials only from env vars — never prints them.
"""
import hashlib
import importlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote

import psycopg2
from psycopg2.extras import RealDictCursor

WS = Path(__file__).resolve().parents[1]
MIGRATIONS = WS / "migrations"

results = []
db_name = None
admin_conn = None


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def rec(stage, status, detail=None):
    entry = {"stage": stage, "status": status, "ts": now_utc()}
    if detail is not None:
        entry["detail"] = detail
    results.append(entry)
    print(f"  {'✓' if status == 'PASS' else '✗'} {stage}: {status}" + (f" — {detail}" if isinstance(detail, str) else ""))


def fail(stage, detail):
    rec(stage, "FAIL", detail)
    raise RuntimeError(f"FAIL at {stage}: {detail}")


def _load_credentials():
    host = "localhost"
    port = 5432
    user = "contentingestor"
    # Try PGPASSWORD / POSTGRES_PASSWORD first (matches existing scripts)
    for key in ("PGPASSWORD", "POSTGRES_PASSWORD"):
        pw = os.environ.get(key, "").strip()
        if pw:
            return host, port, user, pw
    # Fall back to DATABASE_URL if set
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        p = urlparse(database_url)
        if p.password:
            return p.hostname or host, p.port or port, p.username or user, unquote(p.password)
    raise RuntimeError("No DB password: set PGPASSWORD, POSTGRES_PASSWORD, or DATABASE_URL")


def apply_migration(conn, path):
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


def tok_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def main() -> int:
    global db_name, admin_conn

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    db_name = f"router_stub_hubs_{ts}"

    # Safety: name must match expected prefix and not be a system DB
    assert db_name.startswith("router_stub_hubs_"), f"bad db name: {db_name}"
    assert db_name not in ("contentingestor", "postgres", "template0", "template1")

    print(f"\n=== ROUTER_STUB_HUBS_SMOKE [{ts}] ===")
    print(f"DB: {db_name}\n")

    try:
        host, port, user, password = _load_credentials()
        rec("credentials_loaded", "PASS", f"host={host} port={port} user={user}")

        # ── Create disposable DB ──────────────────────────────────────────────
        admin_conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname="postgres")
        admin_conn.autocommit = True
        with admin_conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE {db_name}")
        rec("create_db", "PASS", db_name)

        # Build db_url for in-process use only — never logged
        db_url = f"postgresql://{user}:{password}@{host}:{port}/{db_name}"  # noqa: S106 (internal only)

        # ── Apply migrations 000..026 ─────────────────────────────────────────
        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=db_name)
        conn.autocommit = False
        applied = []
        for i in range(27):  # 000..026
            prefix = f"{i:03d}_"
            candidates = sorted(MIGRATIONS.glob(f"{prefix}*.sql"))
            if len(candidates) != 1:
                fail("apply_migrations", f"Expected exactly 1 file for prefix {prefix}, found {len(candidates)}")
            apply_migration(conn, candidates[0])
            applied.append(candidates[0].name)
        conn.commit()
        conn.close()
        rec("apply_migrations_000_026", "PASS", f"{len(applied)} migrations applied")

        # ── Seed fixtures ─────────────────────────────────────────────────────
        seed_conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=db_name)
        seed_conn.autocommit = False

        ws_a_id = str(uuid.uuid4())
        ws_b_id = str(uuid.uuid4())
        owner_subject_id  = str(uuid.uuid4())
        writer_subject_id = str(uuid.uuid4())
        reader_subject_id = str(uuid.uuid4())
        nomember_subject_id = str(uuid.uuid4())

        owner_token  = f"ownerkey_{uuid.uuid4().hex}"
        writer_token = f"writerkey_{uuid.uuid4().hex}"
        reader_token = f"readerkey_{uuid.uuid4().hex}"
        nomember_token = f"nomemberkey_{uuid.uuid4().hex}"
        ws_b_owner_token = f"wsbowner_{uuid.uuid4().hex}"
        ws_b_owner_subject_id = str(uuid.uuid4())

        with seed_conn.cursor() as cur:
            # Workspaces
            cur.execute(
                "INSERT INTO cb_workspaces (workspace_id, slug, title, status, is_default) VALUES (%s::uuid, %s, %s, 'active', true)",
                (ws_a_id, "ws-a", "Workspace A"),
            )
            cur.execute(
                "INSERT INTO cb_workspaces (workspace_id, slug, title, status, is_default) VALUES (%s::uuid, %s, %s, 'active', false)",
                (ws_b_id, "ws-b", "Workspace B"),
            )

            # Auth subjects
            for sid, stype in [
                (owner_subject_id, "human"),
                (writer_subject_id, "human"),
                (reader_subject_id, "human"),
                (nomember_subject_id, "human"),
                (ws_b_owner_subject_id, "human"),
            ]:
                cur.execute(
                    "INSERT INTO auth_subjects (auth_subject_id, subject_type, status) VALUES (%s::uuid, %s, 'active')",
                    (sid, stype),
                )

            # API keys
            for tok, sid in [
                (owner_token, owner_subject_id),
                (writer_token, writer_subject_id),
                (reader_token, reader_subject_id),
                (nomember_token, nomember_subject_id),
                (ws_b_owner_token, ws_b_owner_subject_id),
            ]:
                cur.execute(
                    "INSERT INTO api_keys (auth_subject_id, key_hash, key_prefix, status) VALUES (%s::uuid, %s, %s, 'active')",
                    (sid, tok_hash(tok), tok[:12]),
                )

            # Workspace memberships (ws_a)
            for sid, role in [
                (owner_subject_id, "owner"),
                (writer_subject_id, "writer"),
                (reader_subject_id, "reader"),
            ]:
                cur.execute(
                    "INSERT INTO workspace_memberships (auth_subject_id, workspace_id, role, status) VALUES (%s::uuid, %s::uuid, %s, 'active')",
                    (sid, ws_a_id, role),
                )
            # ws_b owner
            cur.execute(
                "INSERT INTO workspace_memberships (auth_subject_id, workspace_id, role, status) VALUES (%s::uuid, %s::uuid, %s, 'active')",
                (ws_b_owner_subject_id, ws_b_id, "owner"),
            )

        seed_conn.commit()
        seed_conn.close()
        rec("seed_fixtures", "PASS", "2 workspaces, 5 subjects, 5 api keys, 4 memberships")

        # ── FastAPI TestClient ────────────────────────────────────────────────
        os.environ["DATABASE_URL"] = db_url
        os.environ["MEMORY_LAB_AUTH_MODE"] = "api_key"
        os.environ["MEMORY_LAB_AUTH_AUDIT_ENABLED"] = "true"

        # Force reimport of settings (cached)
        for mod_name in list(sys.modules.keys()):
            if "memory_lab" in mod_name:
                del sys.modules[mod_name]

        from memory_lab.api.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)

        def hdr(token, ws_id=None):
            h = {"Authorization": f"Bearer {token}"}
            if ws_id:
                h["X-Workspace-ID"] = ws_id
            return h

        # ── 1. Health ─────────────────────────────────────────────────────────
        r = client.get("/health")
        assert r.status_code == 200, f"health {r.status_code}"
        rec("health", "PASS")

        # ── 2. Writer creates hub in ws_a ─────────────────────────────────────
        r = client.post(
            "/v1/hubs",
            json={"title": "Smoke Hub A", "hub_type": "topic"},
            headers=hdr(writer_token, ws_a_id),
        )
        assert r.status_code in (200, 201), f"create_hub got {r.status_code}: {r.text}"
        hub_a = r.json()
        hub_a_id = hub_a.get("hub_id") or hub_a.get("id")
        assert hub_a_id, f"no hub_id in create response: {hub_a}"
        rec("create_hub_writer", "PASS", f"hub_id={hub_a_id}")

        # ── 3. Reader lists hubs — sees hub_a ─────────────────────────────────
        r = client.get("/v1/hubs", headers=hdr(reader_token, ws_a_id))
        assert r.status_code == 200, f"list_hubs got {r.status_code}: {r.text}"
        listed = r.json()
        assert isinstance(listed, list), f"list_hubs not a list: {listed}"
        ids_listed = [h.get("hub_id") for h in listed]
        assert hub_a_id in ids_listed, f"hub_a_id not in list: {ids_listed}"
        rec("list_hubs_reader", "PASS", f"{len(listed)} hub(s) returned, hub_a present")

        # ── 4. Reader cannot update hub → 403 ────────────────────────────────
        r = client.patch(
            f"/v1/hubs/{hub_a_id}",
            json={"title": "Reader Renamed"},
            headers=hdr(reader_token, ws_a_id),
        )
        assert r.status_code == 403, f"reader update should be 403, got {r.status_code}: {r.text}"
        rec("reader_cannot_update_403", "PASS")

        # ── 5. Writer updates hub → 200 ───────────────────────────────────────
        r = client.patch(
            f"/v1/hubs/{hub_a_id}",
            json={"title": "Updated Smoke Hub A"},
            headers=hdr(writer_token, ws_a_id),
        )
        assert r.status_code == 200, f"writer update got {r.status_code}: {r.text}"
        updated = r.json()
        assert updated.get("title") == "Updated Smoke Hub A", f"title not updated: {updated}"
        rec("writer_update_hub", "PASS", "title updated correctly")

        # ── 6. Cross-workspace update blocked ────────────────────────────────
        # ws_b owner knows hub_a_id but is in workspace B → must not overwrite
        r = client.patch(
            f"/v1/hubs/{hub_a_id}",
            json={"title": "Cross-WS Hijack"},
            headers=hdr(ws_b_owner_token, ws_b_id),
        )
        assert r.status_code == 404, f"cross-ws update should be 404, got {r.status_code}: {r.text}"
        rec("cross_workspace_update_blocked_404", "PASS")

        # ── 7. List is workspace-scoped (ws_b returns empty) ─────────────────
        r = client.get("/v1/hubs", headers=hdr(ws_b_owner_token, ws_b_id))
        assert r.status_code == 200, f"ws_b list got {r.status_code}: {r.text}"
        ws_b_list = r.json()
        assert isinstance(ws_b_list, list)
        ws_b_ids = [h.get("hub_id") for h in ws_b_list]
        assert hub_a_id not in ws_b_ids, f"hub_a leaked into ws_b list: {ws_b_ids}"
        rec("list_workspace_scoped", "PASS", f"ws_b list={len(ws_b_list)}, hub_a not leaked")

        # ── 8. No token → 401 ─────────────────────────────────────────────────
        r = client.get("/v1/hubs")
        assert r.status_code == 401, f"no-token should be 401, got {r.status_code}"
        rec("no_token_401", "PASS")

        # ── 9. No membership → 403 ────────────────────────────────────────────
        r = client.get("/v1/hubs", headers=hdr(nomember_token, ws_a_id))
        assert r.status_code == 403, f"no-membership should be 403, got {r.status_code}: {r.text}"
        rec("no_membership_403", "PASS")

        # ── 10. Unknown workspace → 404 ───────────────────────────────────────
        r = client.get("/v1/hubs", headers={**hdr(reader_token), "X-Workspace-ID": str(uuid.uuid4())})
        assert r.status_code == 404, f"unknown ws should be 404, got {r.status_code}"
        rec("unknown_workspace_404", "PASS")

        # ── 11. Malformed workspace ID → 400 ─────────────────────────────────
        r = client.get("/v1/hubs", headers={**hdr(reader_token), "X-Workspace-ID": "not-a-uuid"})
        assert r.status_code == 400, f"malformed ws should be 400, got {r.status_code}"
        rec("malformed_workspace_400", "PASS")

        # ── 12. Regression: existing create/get/link still work ───────────────
        r = client.get(f"/v1/hubs/{hub_a_id}", headers=hdr(reader_token, ws_a_id))
        assert r.status_code == 200, f"get_hub regression got {r.status_code}: {r.text}"
        rec("regression_get_hub", "PASS")

        # ── 13. Archive hub via PATCH status ─────────────────────────────────
        r = client.patch(
            f"/v1/hubs/{hub_a_id}",
            json={"status": "archived"},
            headers=hdr(owner_token, ws_a_id),
        )
        assert r.status_code == 200, f"archive got {r.status_code}: {r.text}"
        assert r.json().get("status") == "archived", f"status not archived: {r.json()}"
        rec("archive_hub_patch_status", "PASS")

        # ── 14. Archived hub no longer in default list (status=active) ────────
        r = client.get("/v1/hubs", headers=hdr(reader_token, ws_a_id))
        active_ids = [h.get("hub_id") for h in r.json()]
        assert hub_a_id not in active_ids, "archived hub still appears in active list"
        rec("archived_hub_excluded_from_active_list", "PASS")

        final_verdict = "PASS"
        rec("final_verdict", "PASS", "all checks passed")

    except Exception as exc:
        final_verdict = "FAIL"
        rec("final_verdict", "FAIL", str(exc))

    finally:
        # ── Teardown ──────────────────────────────────────────────────────────
        try:
            if admin_conn:
                with admin_conn.cursor() as cur:
                    cur.execute(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (db_name,))
                    cur.execute(f"DROP DATABASE IF EXISTS {db_name}")
                admin_conn.close()
            rec("teardown_db", "PASS", f"dropped {db_name}")
        except Exception as te:
            rec("teardown_db", "FAIL", str(te))

        # Verify DB is gone
        try:
            host, port, user, password = _load_credentials()
            vc = psycopg2.connect(host=host, port=port, user=user, password=password, dbname="postgres")
            vc.autocommit = True
            with vc.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
                absent = cur.fetchone() is None
            vc.close()
            if absent:
                rec("teardown_verify_absent", "PASS", f"{db_name} confirmed absent")
            else:
                rec("teardown_verify_absent", "FAIL", f"{db_name} still present after drop")
        except Exception as ve:
            rec("teardown_verify_absent", "FAIL", str(ve))

    return 0 if final_verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
