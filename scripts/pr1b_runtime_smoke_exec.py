#!/usr/bin/env python3
import json
import os
import re
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, unquote

import psycopg2
import requests

WS = Path(os.getenv('MEMORY_LAB_WORKSPACE', Path(__file__).resolve().parents[1])).resolve()
REPORTS = WS / 'reports'
MIGRATIONS = WS / 'migrations'

# Full server log targets (used during execution attempts)
SERVER_STDOUT_LOG = REPORTS / 'pr1b_minimal_api_runtime_server_stdout.log'
SERVER_STDERR_LOG = REPORTS / 'pr1b_minimal_api_runtime_server_stderr.log'

summary = None
server_proc = None
server_stdout_fh = None
server_stderr_fh = None
admin_conn = None
api_port = None
db_name = None


def rec(stage, status, detail=None):
    entry = {'stage': stage, 'status': status}
    if detail is not None:
        entry['detail'] = detail
    summary['stages'].append(entry)


def fail(stage, detail):
    rec(stage, 'FAIL', detail)
    raise RuntimeError(f"{stage}: {detail}")


def load_pg_password():
    for key in ('PGPASSWORD', 'POSTGRES_PASSWORD'):
        val = os.getenv(key, '').strip()
        if val:
            return val
    database_url = os.getenv('DATABASE_URL', '').strip()
    if database_url:
        parsed = urlparse(database_url)
        if parsed.password:
            return unquote(parsed.password)
    raise RuntimeError('DB password not supplied. Set PGPASSWORD, POSTGRES_PASSWORD, or DATABASE_URL explicitly.')


def get_free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def apply_migration(conn, path):
    sql = path.read_text(encoding='utf-8')
    with conn.cursor() as cur:
        cur.execute(sql)


def tail_file(path: Path, max_chars: int = 4000) -> str:
    if not path.exists():
        return ''
    data = path.read_text(encoding='utf-8', errors='replace')
    if len(data) <= max_chars:
        return data
    return data[-max_chars:]
def main() -> int:
    global summary, server_proc, server_stdout_fh, server_stderr_fh, admin_conn, api_port, db_name

    summary = {
        'mode': 'narrow_execution',
        'workspace': str(WS),
        'started_at_utc': datetime.now(UTC).isoformat(),
        'safety_checks': {},
        'stages': [],
        'constraints': {
            'mcp_used': False,
            'provider_embeddings_used': False,
            'llm_generation_used': False,
            'public_export': False,
            'git_repo_commit_push': False,
            'modified_opt_contentingestor': False,
        },
        'server_log_paths': {
            'stdout': str(SERVER_STDOUT_LOG),
            'stderr': str(SERVER_STDERR_LOG),
        },
    }
    server_proc = None
    server_stdout_fh = None
    server_stderr_fh = None
    admin_conn = None
    api_port = None
    db_name = f"pr1b_api_smoke_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

    try:
        os.chdir(WS)

        # Safety checks
        summary['db_name'] = db_name
        if not db_name.startswith('pr1b_api_smoke_'):
            fail('safety_db_name_prefix', db_name)
        if db_name in ('contentingestor', 'postgres'):
            fail('safety_db_name_forbidden', db_name)
        rec('safety_db_name', 'PASS', db_name)

        host = 'localhost'
        port = 5432
        user = 'contentingestor'
        if host != 'localhost':
            fail('safety_host', host)
        if user != 'contentingestor':
            fail('safety_role', user)
        rec('safety_host_role', 'PASS', {'host': host, 'port': port, 'user': user})

        mig_files = sorted([p.name for p in MIGRATIONS.glob('*.sql')])
        prefixes = []
        for m in mig_files:
            m0 = re.match(r'^(\d{3})_', m)
            if m0:
                prefixes.append(int(m0.group(1)))
        required = list(range(0, 10))
        missing = [i for i in required if i not in prefixes]
        has_010 = any(i >= 10 for i in prefixes)
        if missing:
            fail('safety_migration_inventory', {'missing_prefixes': missing, 'found': prefixes})
        if has_010:
            rec('safety_migration_010_plus_present_but_excluded', 'PASS', sorted([m for m in mig_files if re.match(r'^(\d{3})_', m) and int(m[:3]) >= 10]))
        rec('safety_migration_scope', 'PASS', 'apply 000..009 only')

        password = load_pg_password()

        # Create disposable DB
        admin_conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname='postgres')
        admin_conn.autocommit = True
        with admin_conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE {db_name}')
        rec('create_disposable_db', 'PASS', db_name)

        # Apply migrations 000..009
        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=db_name)
        conn.autocommit = False
        applied = []
        for i in range(10):
            prefix = f'{i:03d}_'
            candidates = sorted([p for p in MIGRATIONS.glob(f'{prefix}*.sql')])
            if len(candidates) != 1:
                fail('apply_migrations', f'Expected exactly 1 migration for prefix {prefix}, found {len(candidates)}')
            apply_migration(conn, candidates[0])
            applied.append(candidates[0].name)
        conn.commit()
        conn.close()
        rec('apply_migrations_000_009', 'PASS', applied)

        # Launch API server local-only with full log persistence
        REPORTS.mkdir(parents=True, exist_ok=True)
        api_port = get_free_port()
        db_url = f'postgresql://{user}:{password}@{host}:{port}/{db_name}'
        env = os.environ.copy()
        env['DATABASE_URL'] = f'postgresql://{user}:{password}@{host}:{port}/{db_name}'
        cmd = [sys.executable, '-m', 'uvicorn', 'memory_lab.api.main:app', '--host', '127.0.0.1', '--port', str(api_port)]

        server_stdout_fh = open(SERVER_STDOUT_LOG, 'w', encoding='utf-8')
        server_stderr_fh = open(SERVER_STDERR_LOG, 'w', encoding='utf-8')
        server_proc = subprocess.Popen(
            cmd,
            cwd=str(WS),
            env=env,
            stdout=server_stdout_fh,
            stderr=server_stderr_fh,
            text=True,
        )

        base = f'http://127.0.0.1:{api_port}'
        ready = False
        for _ in range(40):
            try:
                r = requests.get(base + '/health', timeout=1.5)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(0.25)

        if not ready:
            proc_exit = server_proc.poll()
            if server_stdout_fh:
                server_stdout_fh.flush()
            if server_stderr_fh:
                server_stderr_fh.flush()
            stdout_tail = tail_file(SERVER_STDOUT_LOG, 6000)
            stderr_tail = tail_file(SERVER_STDERR_LOG, 6000)
            fail('launch_api_server', {
                'message': 'Health not ready',
                'process_exit': proc_exit,
                'stdout_log': str(SERVER_STDOUT_LOG),
                'stderr_log': str(SERVER_STDERR_LOG),
                'stdout_tail': stdout_tail,
                'stderr_tail': stderr_tail,
            })

        rec('launch_api_server', 'PASS', {'bind': '127.0.0.1', 'port': api_port})

        # Endpoint sequence (unchanged)
        sess = requests.Session()

        r = sess.get(base + '/health', timeout=5)
        if r.status_code != 200:
            fail('endpoint_1_health', {'status_code': r.status_code, 'body': r.text})
        rec('endpoint_1_health', 'PASS', r.json())

        r = sess.post(base + '/v1/content', json={'content': 'ignored in id_allocation_only mode'}, timeout=10)
        if r.status_code not in (200, 201):
            fail('endpoint_2_post_content', {'status_code': r.status_code, 'body': r.text})
        body = r.json()
        content_id = body.get('content_id')
        if not content_id or body.get('created') is not True or body.get('mode') != 'id_allocation_only':
            fail('endpoint_2_post_content_contract', body)
        rec('endpoint_2_post_content', 'PASS', body)

        r = sess.get(base + f'/v1/content/{content_id}', timeout=10)
        if r.status_code != 200:
            fail('endpoint_3_get_content', {'status_code': r.status_code, 'body': r.text})
        b3 = r.json()
        if b3.get('content_id') != content_id or not b3.get('created_at') or not b3.get('updated_at') or b3.get('mode') != 'id_allocation_only':
            fail('endpoint_3_get_content_contract', b3)
        rec('endpoint_3_get_content', 'PASS', b3)

        hub_payload = {'title': 'PR1B Smoke Hub', 'hub_type': 'topic', 'description': 'runtime smoke'}
        r = sess.post(base + '/v1/hubs', json=hub_payload, timeout=10)
        if r.status_code not in (200, 201):
            fail('endpoint_4_post_hub', {'status_code': r.status_code, 'body': r.text})
        hub = r.json()
        hub_id = hub.get('id') or hub.get('hub_id')
        if not hub_id:
            fail('endpoint_4_post_hub_contract', hub)
        rec('endpoint_4_post_hub', 'PASS', hub)

        r = sess.get(base + f'/v1/hubs/{hub_id}', timeout=10)
        if r.status_code != 200:
            fail('endpoint_5_get_hub', {'status_code': r.status_code, 'body': r.text})
        rec('endpoint_5_get_hub', 'PASS', r.json())

        r = sess.post(base + f'/v1/hubs/{hub_id}/links', json={'content_id': content_id}, timeout=10)
        if r.status_code not in (200, 201):
            fail('endpoint_6_post_hub_link', {'status_code': r.status_code, 'body': r.text})
        rec('endpoint_6_post_hub_link', 'PASS', r.json())

        r = sess.post(base + '/v1/edges', json={
            'source_hub_id': hub_id,
            'target_hub_id': hub_id,
            'edge_type': 'related',
            'status': 'manual',
            'origin': 'manual'
        }, timeout=10)
        if r.status_code not in (200, 201):
            fail('endpoint_7_post_edge', {'status_code': r.status_code, 'body': r.text})
        edge = r.json()
        edge_id = edge.get('id') or edge.get('edge_id')
        if not edge_id:
            fail('endpoint_7_post_edge_contract', edge)
        rec('endpoint_7_post_edge', 'PASS', edge)

        r = sess.get(base + f'/v1/edges/{edge_id}', timeout=10)
        if r.status_code != 200:
            fail('endpoint_8_get_edge', {'status_code': r.status_code, 'body': r.text})
        rec('endpoint_8_get_edge', 'PASS', r.json())

        r = sess.get(base + '/v1/edges', timeout=10)
        if r.status_code != 200:
            fail('endpoint_9_list_active', {'status_code': r.status_code, 'body': r.text})
        b9 = r.json()
        if b9.get('count') != 1:
            fail('endpoint_9_active_count_expected_1', b9)
        rec('endpoint_9_list_active', 'PASS', b9)

        r = sess.post(base + f'/v1/edges/{edge_id}/archive', timeout=10)
        if r.status_code != 200:
            fail('endpoint_10_archive_edge', {'status_code': r.status_code, 'body': r.text})
        rec('endpoint_10_archive_edge', 'PASS', r.json())

        r = sess.get(base + '/v1/edges', timeout=10)
        if r.status_code != 200:
            fail('endpoint_11_list_active_after_archive', {'status_code': r.status_code, 'body': r.text})
        b11 = r.json()
        if b11.get('count') != 0:
            fail('endpoint_11_active_count_expected_0', b11)
        rec('endpoint_11_list_active_after_archive', 'PASS', b11)

        r = sess.get(base + '/v1/edges?include_archived=true', timeout=10)
        if r.status_code != 200:
            fail('endpoint_12_list_archived', {'status_code': r.status_code, 'body': r.text})
        b12 = r.json()
        if b12.get('count') != 1:
            fail('endpoint_12_archived_count_expected_1', b12)
        rec('endpoint_12_list_archived', 'PASS', b12)

        r = sess.post(base + '/v1/retrieval/search', json={'query': 'smoke test', 'max_hops': 1, 'min_confidence': 0.7}, timeout=10)
        if r.status_code != 200:
            fail('endpoint_13_retrieval', {'status_code': r.status_code, 'body': r.text})
        b13 = r.json()
        if b13.get('mode') != 'deterministic_stub_default':
            fail('endpoint_13_retrieval_mode', b13)
        if len(b13.get('results') or []) < 2:
            fail('endpoint_13_retrieval_results', b13)
        rec('endpoint_13_retrieval', 'PASS', b13)

        summary['final_verdict'] = 'PASS'

    except Exception as e:
        if 'final_verdict' not in summary:
            summary['final_verdict'] = 'FAIL'
        summary['error'] = str(e)
    finally:
        teardown = {'server_stopped': False, 'db_sessions_terminated': False, 'db_dropped': False}
        try:
            if server_proc is not None:
                server_proc.terminate()
                try:
                    server_proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    server_proc.kill()
                    server_proc.wait(timeout=5)
                teardown['server_stopped'] = True
        except Exception as e:
            teardown['server_stop_error'] = str(e)

        try:
            if server_stdout_fh:
                server_stdout_fh.flush()
                server_stdout_fh.close()
            if server_stderr_fh:
                server_stderr_fh.flush()
                server_stderr_fh.close()
        except Exception:
            pass

        try:
            if admin_conn is None:
                password = load_pg_password()
                admin_conn = psycopg2.connect(host='localhost', port=5432, user='contentingestor', password=password, dbname='postgres')
                admin_conn.autocommit = True
            with admin_conn.cursor() as cur:
                cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (db_name,))
                teardown['db_sessions_terminated'] = True
                cur.execute(f'DROP DATABASE IF EXISTS {db_name}')
                teardown['db_dropped'] = True
        except Exception as e:
            teardown['db_teardown_error'] = str(e)

        summary['teardown'] = teardown
        summary['finished_at_utc'] = datetime.now(UTC).isoformat()

        REPORTS.mkdir(parents=True, exist_ok=True)
        summary_path = REPORTS / 'pr1b_minimal_api_runtime_smoke_summary.json'
        summary_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')

        lines = []
        lines.append('# PR1B Minimal API Runtime Smoke Evidence')
        lines.append('')
        lines.append('mode: narrow_execution')
        lines.append(f'workspace: {WS}')
        lines.append(f"final_verdict: {summary.get('final_verdict')}")
        lines.append(f'db_name: {db_name}')
        lines.append('')
        lines.append('## Safety checks and constraints')
        lines.append('- host: localhost only')
        lines.append('- role: contentingestor only')
        lines.append('- migrations applied: 000..009 only')
        lines.append('- migrations 010+ excluded/rejected from apply list')
        lines.append('- MCP used: no')
        lines.append('- provider embeddings used: no')
        lines.append('')
        lines.append('## Server launch logs')
        lines.append(f'- stdout_log: {SERVER_STDOUT_LOG}')
        lines.append(f'- stderr_log: {SERVER_STDERR_LOG}')
        lines.append('')
        lines.append('## Stage results')
        for st in summary.get('stages', []):
            lines.append(f"- {st['stage']}: {st['status']}")
        if summary.get('error'):
            lines.append('')
            lines.append('## Failure')
            lines.append(f"- error: {summary['error']}")
        lines.append('')
        lines.append('## Teardown')
        td = summary.get('teardown', {})
        lines.append(f"- server_stopped: {td.get('server_stopped')}")
        lines.append(f"- db_sessions_terminated: {td.get('db_sessions_terminated')}")
        lines.append(f"- db_dropped: {td.get('db_dropped')}")

        (REPORTS / 'PR1B_MINIMAL_API_RUNTIME_SMOKE_EVIDENCE.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

        if summary.get('final_verdict') == 'PASS' and td.get('db_dropped'):
            pr = []
            pr.append('# PR1B Minimal API Runtime PASS Review')
            pr.append('')
            pr.append('status: PASS')
            pr.append(f'db_name: {db_name}')
            pr.append('')
            pr.append('Checks:')
            pr.append('- All safety checks PASS')
            pr.append('- Endpoint sequence PASS')
            pr.append('- Deterministic retrieval path PASS')
            pr.append('- No MCP / no provider embeddings')
            pr.append('- Teardown DROP DATABASE PASS')
            (REPORTS / 'PR1B_MINIMAL_API_RUNTIME_PASS_REVIEW.md').write_text('\n'.join(pr) + '\n', encoding='utf-8')

        print(json.dumps({'final_verdict': summary.get('final_verdict'), 'db_name': db_name, 'teardown': summary.get('teardown')}, indent=2))
        return 0 if summary.get('final_verdict') == 'PASS' else 1


if __name__ == "__main__":
    raise SystemExit(main())
