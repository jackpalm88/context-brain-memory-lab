"""M9C-3 — provenance on decision conflicts read surface (read-only).

list_decision_conflicts builds ConflictPair from two LineageNodes; expose
created_by_subject on each so the conflicts surface matches the rest of the
provenance read surface (M9B writes, M9C-1 core reads, M9C-2 navigational/graph).
NULL stays null = unknown / pre-provenance. No write-path or migration changes.
"""

from datetime import datetime, timezone

SUBJECT_A = "00000000-0000-0000-0000-0000000000a1"
SUBJECT_B = "00000000-0000-0000-0000-0000000000b2"
WS = "00000000-0000-0000-0000-0000000000c3"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, row):
        self.executed = []
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return [self.row] if self.row else []


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, *a, **k):
        return self.cursor_obj

    def commit(self):
        pass


def _sql(cur):
    return " || ".join(s for s, _ in cur.executed)


def _row(a_by=SUBJECT_A, b_by=SUBJECT_B):
    return {
        "a_id": "d1", "a_title": "A", "a_status": "active", "a_created": NOW, "a_created_by": a_by,
        "b_id": "d2", "b_title": "B", "b_status": "active", "b_created": NOW, "b_created_by": b_by,
        "conflict_reason": "Same tag: x",
    }


def test_list_conflicts_select_includes_created_by_subject():
    from memory_lab.decisions.store import DecisionStore
    s = DecisionStore.__new__(DecisionStore)
    cur = FakeCursor(_row())
    s._conn = lambda: FakeConn(cur)
    s.list_conflicts(workspace_id=WS)
    assert "created_by_subject" in _sql(cur)


def test_list_conflicts_nodes_expose_created_by_subject():
    from memory_lab.decisions.store import DecisionStore
    s = DecisionStore.__new__(DecisionStore)
    cur = FakeCursor(_row())
    s._conn = lambda: FakeConn(cur)
    out = s.list_conflicts(workspace_id=WS)
    pair = out.conflicts[0]
    assert pair.decision_a.created_by_subject == SUBJECT_A
    assert pair.decision_b.created_by_subject == SUBJECT_B


def test_list_conflicts_null_provenance_accepted():
    from memory_lab.decisions.store import DecisionStore
    s = DecisionStore.__new__(DecisionStore)
    cur = FakeCursor(_row(a_by=None, b_by=None))
    s._conn = lambda: FakeConn(cur)
    out = s.list_conflicts(workspace_id=WS)
    pair = out.conflicts[0]
    assert pair.decision_a.created_by_subject is None
    assert pair.decision_b.created_by_subject is None
