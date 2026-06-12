"""Unit tests for B10 classify catchup helper.

Provider-free; no timed background runner; no production dependencies.
"""

import inspect
from dataclasses import dataclass

import pytest

from memory_lab.ingestion.classify_pipeline import ClassificationResult

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

_WS1 = "00000000-0000-0000-0000-000000000001"
_WS2 = "00000000-0000-0000-0000-000000000002"
_C1 = "10000000-0000-0000-0000-000000000001"
_C2 = "10000000-0000-0000-0000-000000000002"


class FakeCursor:
    def __init__(self, conn, cursor_factory=None):
        self.conn = conn
        self.cursor_factory = cursor_factory
        self.last_rows = []
        self.execute_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.execute_calls.append((sql, params))
        self.conn.sql_calls.append((sql, params))
        s = " ".join(sql.split()).lower()
        params = params or ()
        if s.startswith("select count(*)"):
            ws = params[0] if params else None
            self.last_rows = [(sum(1 for r in self.conn.rows if r["memory_type"] is None and (ws is None or r["workspace_id"] == ws)),)]
        elif "from content_items ci" in s and "left join content_chunks" in s:
            limit = params[-1]
            ws = params[0] if len(params) > 1 else None
            selected = []
            for row in sorted(self.conn.rows, key=lambda r: r["created_at"]):
                if row["memory_type"] is not None:
                    continue
                if ws and row["workspace_id"] != ws:
                    continue
                chunks = self.conn.chunks.get(row["content_id"], [])
                text = "\n\n".join(t for _, t in sorted(chunks))
                selected.append({**row, "content_text": text})
                if len(selected) >= limit:
                    break
            self.last_rows = selected
        elif "select memory_type from content_items" in s:
            cid = params[0]
            row = next((r for r in self.conn.rows if r["content_id"] == cid), None)
            self.last_rows = [(row["memory_type"],)] if row else []
        elif "select 1 from cb_classification_history" in s:
            cid, mtype = params[0], params[1]
            found = any(h["content_id"] == cid and h["memory_type"] == mtype and h["active"] for h in self.conn.history)
            self.last_rows = [(1,)] if found else []
        elif "update content_items" in s and "set memory_type" in s:
            mtype, subtype, conf, cid = params[0], params[1], params[2], params[3]
            for row in self.conn.rows:
                if row["content_id"] == cid and row["memory_type"] is None:
                    row["memory_type"] = mtype
                    row["memory_sub_type"] = subtype
                    row["classify_confidence"] = conf
        elif "update cb_classification_history" in s:
            cid = params[0]
            for h in self.conn.history:
                if h["content_id"] == cid:
                    h["active"] = False
        elif "insert into cb_classification_history" in s:
            self.conn.history.append({"workspace_id": params[0], "content_id": params[1], "memory_type": params[2], "active": True})
        elif "insert into cb_discovered_domains" in s:
            self.conn.domains.add((params[0], params[1]))
        elif "set domain_id" in s:
            self.conn.domain_links.append(params)
        else:
            self.last_rows = []

    def fetchone(self):
        if not self.last_rows:
            return None
        return self.last_rows[0]

    def fetchall(self):
        return list(self.last_rows)


class FakeConn:
    def __init__(self):
        self.rows = []
        self.chunks = {}
        self.history = []
        self.domains = set()
        self.domain_links = []
        self.sql_calls = []
        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, *args, **kwargs):
        return FakeCursor(self, cursor_factory=kwargs.get("cursor_factory"))

    def commit(self):
        self.commit_count += 1


def _conn_with_rows():
    conn = FakeConn()
    conn.rows = [
        {"content_id": _C1, "workspace_id": _WS1, "tier": "long_term", "composite_score": 0.9, "created_at": 1, "memory_type": None},
        {"content_id": _C2, "workspace_id": _WS2, "tier": "long_term", "composite_score": 0.9, "created_at": 2, "memory_type": None},
    ]
    conn.chunks = {
        _C1: [(0, "current_state_scope: b10\nCurrent state canonical source of truth")],
        _C2: [(0, "unit test evidence test passed")],
    }
    return conn


def _high(**kwargs):
    return ClassificationResult(
        memory_type="anchor", memory_sub_type="current_state_anchor", confidence=0.85,
        signals=["current state"], project_topic="context_brain_memory_lab", domain_hint="governance",
    )


def _low(**kwargs):
    return ClassificationResult(memory_type="evidence", confidence=0.62, signals=["unit test"])


@dataclass
class Resolution:
    status: str = "active"
    reason: str = "resolved_current_state"


def test_dry_run_changes_no_rows_and_reports_would_resolve():
    from memory_lab.ingestion.classify_catchup import ClassifyCatchupJob

    conn = _conn_with_rows()
    resolver_calls = []
    job = ClassifyCatchupJob(conn_factory=lambda: conn, classifier=_high, resolver=lambda *a, **k: resolver_calls.append(k))
    summary = job.run(dry_run=True, limit=10, workspace_id=_WS1)

    assert summary.dry_run is True
    assert summary.selected_count == 1
    assert summary.rows[0].status == "dry_run"
    assert summary.rows[0].would_call_resolver is True
    assert conn.rows[0]["memory_type"] is None
    assert conn.commit_count == 0
    assert resolver_calls == []


def test_backfills_rows_with_memory_type_null_and_calls_resolver_for_high_confidence():
    from memory_lab.ingestion.classify_catchup import ClassifyCatchupJob

    conn = _conn_with_rows()
    resolver_calls = []
    def resolver(conn_arg, **kwargs):
        resolver_calls.append(kwargs)
        return Resolution()

    job = ClassifyCatchupJob(conn_factory=lambda: conn, classifier=_high, resolver=resolver)
    summary = job.run(dry_run=False, limit=10, workspace_id=_WS1)

    assert summary.classified_count == 1
    assert summary.resolver_called_count == 1
    assert conn.rows[0]["memory_type"] == "anchor"
    assert conn.history[-1]["content_id"] == _C1
    assert resolver_calls[0]["content_id"] == _C1
    assert resolver_calls[0]["classify_confidence"] == 0.85


def test_skips_already_classified_rows_and_second_run_noop():
    from memory_lab.ingestion.classify_catchup import ClassifyCatchupJob

    conn = _conn_with_rows()
    job = ClassifyCatchupJob(conn_factory=lambda: conn, classifier=_high, resolver=lambda *a, **k: Resolution())
    first = job.run(dry_run=False, limit=10, workspace_id=_WS1)
    second = job.run(dry_run=False, limit=10, workspace_id=_WS1)

    assert first.classified_count == 1
    assert second.selected_count == 0
    assert second.classified_count == 0
    assert len(conn.history) == 1


def test_does_not_call_resolver_for_low_confidence():
    from memory_lab.ingestion.classify_catchup import ClassifyCatchupJob

    conn = _conn_with_rows()
    resolver_calls = []
    job = ClassifyCatchupJob(conn_factory=lambda: conn, classifier=_low, resolver=lambda *a, **k: resolver_calls.append(k))
    summary = job.run(dry_run=False, limit=10, workspace_id=_WS1)

    assert summary.classified_count == 1
    assert summary.resolver_called_count == 0
    assert summary.resolver_skipped_low_confidence_count == 1
    assert resolver_calls == []


def test_workspace_filter_preserves_isolation():
    from memory_lab.ingestion.classify_catchup import ClassifyCatchupJob

    conn = _conn_with_rows()
    job = ClassifyCatchupJob(conn_factory=lambda: conn, classifier=_low, resolver=lambda *a, **k: Resolution())
    summary = job.run(dry_run=False, limit=10, workspace_id=_WS2)

    assert summary.selected_count == 1
    assert conn.rows[0]["memory_type"] is None
    assert conn.rows[1]["memory_type"] == "evidence"


def test_rows_with_no_usable_text_are_skipped_and_reported():
    from memory_lab.ingestion.classify_catchup import ClassifyCatchupJob

    conn = _conn_with_rows()
    conn.chunks[_C1] = []
    job = ClassifyCatchupJob(conn_factory=lambda: conn, classifier=_high)
    summary = job.run(dry_run=False, limit=10, workspace_id=_WS1)

    assert summary.skipped_no_usable_text_count == 1
    assert summary.rows[0].status == "skipped_no_usable_text"
    assert conn.rows[0]["memory_type"] is None


def test_non_dry_run_without_workspace_requires_explicit_all_workspaces():
    from memory_lab.ingestion.classify_catchup import ClassifyCatchupJob

    job = ClassifyCatchupJob(conn_factory=lambda: _conn_with_rows(), classifier=_low)
    with pytest.raises(ValueError, match="workspace_id or all_workspaces"):
        job.run(dry_run=False, limit=10)


def test_cli_defaults_to_dry_run():
    from memory_lab.ingestion.classify_catchup import build_arg_parser

    args = build_arg_parser().parse_args(["--database-url", "postgresql://example/db"])
    assert args.dry_run is True
    args2 = build_arg_parser().parse_args(["--database-url", "postgresql://example/db", "--apply", "--all-workspaces"])
    assert args2.dry_run is False


def test_catchup_source_does_not_directly_write_current_state_fields():
    import memory_lab.ingestion.classify_catchup as mod

    src = inspect.getsource(mod.ClassifyCatchupJob._write_classification)
    forbidden = ("is_current", "current_state_scope", "cs_supersedes_content_id")
    for field in forbidden:
        assert field not in src


def test_module_has_no_timed_runner_or_provider_calls():
    import memory_lab.ingestion.classify_catchup as mod

    src = inspect.getsource(mod)
    forbidden = ("cr" + "on", "sched" + "uler", "open" + "ai", "anth" + "ropic", "req" + "uests.", "ht" + "tpx.", "/opt/content" + "ingestor")
    for marker in forbidden:
        assert marker not in src.lower()
