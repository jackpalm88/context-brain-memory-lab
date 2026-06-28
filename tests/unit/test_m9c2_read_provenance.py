"""M9C-2 — navigational/graph read-model provenance exposure (read-only).

Extends M9C-1: created_by_subject on decision list/timeline items
(DecisionSummary), decision lineage items (LineageNode), and load_graph_node_full;
created_by on graph snapshot edge records (HubEdgeRecord). NULL stays null =
unknown / pre-provenance. No write-path or migration changes.
"""

from dataclasses import asdict
from datetime import datetime, timezone

SUBJECT = "00000000-0000-0000-0000-0000000000c3"
WS = "00000000-0000-0000-0000-0000000000a1"
CONTENT = "00000000-0000-0000-0000-0000000000d4"
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


# ---- decision list / timeline items (DecisionSummary) ----

def test_decision_summary_model_has_provenance_field():
    from memory_lab.decisions.models import DecisionSummary
    assert "created_by_subject" in DecisionSummary.model_fields


def test_row_to_summary_maps_created_by_subject():
    from memory_lab.decisions.store import DecisionStore
    row = {
        "decision_id": "d1", "title": "T", "decision_status": "active",
        "reversible": True, "confidence_level": "medium", "decision_tags": [],
        "created_by_subject": SUBJECT, "created_at": NOW,
    }
    summary = DecisionStore._row_to_summary(row)
    assert summary.created_by_subject == SUBJECT


def test_list_decisions_select_and_summary_expose_created_by_subject():
    from memory_lab.decisions.store import DecisionStore
    s = DecisionStore.__new__(DecisionStore)
    cur = FakeCursor({
        "decision_id": "d1", "title": "T", "decision_status": "active",
        "reversible": True, "confidence_level": "medium", "decision_tags": [],
        "created_by_subject": SUBJECT, "created_at": NOW,
    })
    s._conn = lambda: FakeConn(cur)
    out = s.list_decisions(status=None, hub_id=None, limit=20, workspace_id=WS)
    assert "created_by_subject" in _sql(cur)
    assert out.decisions[0].created_by_subject == SUBJECT


def test_get_timeline_select_and_summary_expose_created_by_subject():
    from memory_lab.decisions.store import DecisionStore
    s = DecisionStore.__new__(DecisionStore)
    cur = FakeCursor({
        "decision_id": "d1", "title": "T", "decision_status": "active",
        "reversible": True, "confidence_level": "medium", "decision_tags": [],
        "created_by_subject": SUBJECT, "created_at": NOW,
    })
    s._conn = lambda: FakeConn(cur)
    out = s.get_timeline(hub_id=None, tags=None, limit=50, workspace_id=WS)
    assert "created_by_subject" in _sql(cur)
    assert out.active[0].created_by_subject == SUBJECT


def test_timeline_null_provenance_accepted():
    from memory_lab.decisions.store import DecisionStore
    s = DecisionStore.__new__(DecisionStore)
    cur = FakeCursor({
        "decision_id": "d1", "title": "T", "decision_status": "active",
        "reversible": True, "confidence_level": "medium", "decision_tags": [],
        "created_by_subject": None, "created_at": NOW,
    })
    s._conn = lambda: FakeConn(cur)
    out = s.get_timeline(hub_id=None, tags=None, limit=50, workspace_id=WS)
    assert out.active[0].created_by_subject is None


# ---- decision lineage items (LineageNode) ----

def test_lineage_node_model_has_provenance_field():
    from memory_lab.decisions.models import LineageNode
    assert "created_by_subject" in LineageNode.model_fields


def test_get_lineage_select_and_nodes_expose_created_by_subject():
    from memory_lab.decisions.store import DecisionStore
    s = DecisionStore.__new__(DecisionStore)
    cur = FakeCursor({
        "role": "ancestor", "decision_id": "d1", "title": "T",
        "decision_status": "active", "created_at": NOW, "depth": 1,
        "created_by_subject": SUBJECT,
    })
    s._conn = lambda: FakeConn(cur)
    out = s.get_lineage("d0", workspace_id=WS)
    assert "created_by_subject" in _sql(cur)
    assert out.ancestors[0].created_by_subject == SUBJECT


# ---- graph snapshot edges (HubEdgeRecord) ----

def test_hub_edge_record_has_created_by_field():
    from memory_lab.graph.repository_reader import HubEdgeRecord
    rec = HubEdgeRecord(id="e1", source_hub_id="h1", target_hub_id="h2", type="relates_to")
    assert hasattr(rec, "created_by")
    assert rec.created_by is None


def test_reader_hub_edges_populate_created_by():
    from memory_lab.graph.repository_reader import RepositoryGraphHealthReader
    reader = RepositoryGraphHealthReader(row_sets={
        "cb_hub_edges": [{
            "id": "e1", "source_hub_id": "h1", "target_hub_id": "h2",
            "type": "relates_to", "status": "active", "created_by": SUBJECT,
        }],
    })
    snap = reader.read_snapshot()
    assert snap.hub_edges[0].created_by == SUBJECT


def test_snapshot_edge_dict_carries_created_by_through_filter():
    from memory_lab.graph.repository_reader import HubEdgeRecord
    from memory_lab.api.services.api_adapter import filter_snapshot_edges
    rec = HubEdgeRecord(id="e1", source_hub_id="h1", target_hub_id="h2",
                        type="relates_to", origin="manual", created_by=SUBJECT)
    edges = filter_snapshot_edges([asdict(rec)])
    assert edges[0]["created_by"] == SUBJECT


# ---- load_graph_node_full ----

def test_load_graph_node_full_exposes_created_by_subject():
    from memory_lab.api.services.api_adapter import ApiAdapter
    a = ApiAdapter.__new__(ApiAdapter)
    a.database_url = "x"
    cur = FakeCursor({
        "content_id": CONTENT, "workspace_id": WS, "node_type": "fact",
        "quick_summary": None, "memory_type": None, "full_text": "", "word_count": 0,
        "created_by_subject": SUBJECT, "created_at": NOW, "updated_at": NOW,
    })
    a._conn = lambda: FakeConn(cur)
    out = a.load_graph_node_full(CONTENT, workspace_id=WS)
    assert "created_by_subject" in _sql(cur)
    assert out["created_by_subject"] == SUBJECT


def test_load_graph_node_full_null_provenance_accepted():
    from memory_lab.api.services.api_adapter import ApiAdapter
    a = ApiAdapter.__new__(ApiAdapter)
    a.database_url = "x"
    cur = FakeCursor({
        "content_id": CONTENT, "workspace_id": WS, "node_type": "fact",
        "quick_summary": None, "memory_type": None, "full_text": "", "word_count": 0,
        "created_by_subject": None, "created_at": NOW, "updated_at": NOW,
    })
    a._conn = lambda: FakeConn(cur)
    out = a.load_graph_node_full(CONTENT, workspace_id=WS)
    assert out["created_by_subject"] is None
