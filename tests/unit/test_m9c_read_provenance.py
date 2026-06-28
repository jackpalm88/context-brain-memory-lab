"""M9C-1 — core read-model provenance exposure (read-only).

created_by_subject surfaced on content get/metadata, decision get (DecisionFull),
and hub list (HubResponse). NULL stays null = unknown / pre-provenance.
"""

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


# ---- content get ----

def test_content_get_exposes_created_by_subject():
    from memory_lab.api.services.api_adapter import ApiAdapter
    a = ApiAdapter.__new__(ApiAdapter)
    a.database_url = "x"
    cur = FakeCursor({"content_id": CONTENT, "workspace_id": WS, "created_by_subject": SUBJECT})
    a._conn = lambda: FakeConn(cur)
    out = a.get_content_minimal(CONTENT, workspace_id=WS)
    assert "created_by_subject" in _sql(cur)
    assert out["created_by_subject"] == SUBJECT


# ---- content metadata ----

def test_content_metadata_exposes_created_by_subject():
    from memory_lab.api.services.api_adapter import ApiAdapter
    a = ApiAdapter.__new__(ApiAdapter)
    a.database_url = "x"
    cur = FakeCursor({"content_id": CONTENT, "node_type": "fact", "quick_summary": None,
                      "memory_type": None, "domain": None, "word_count": 0,
                      "created_by_subject": SUBJECT, "created_at": NOW, "updated_at": NOW})
    a._conn = lambda: FakeConn(cur)
    out = a.get_content_metadata(CONTENT, workspace_id=WS)
    assert "created_by_subject" in _sql(cur)
    assert out["created_by_subject"] == SUBJECT


def test_content_metadata_null_provenance_accepted():
    from memory_lab.api.services.api_adapter import ApiAdapter
    a = ApiAdapter.__new__(ApiAdapter)
    a.database_url = "x"
    cur = FakeCursor({"content_id": CONTENT, "node_type": None, "quick_summary": None,
                      "memory_type": None, "domain": None, "word_count": 0,
                      "created_by_subject": None, "created_at": NOW, "updated_at": NOW})
    a._conn = lambda: FakeConn(cur)
    out = a.get_content_metadata(CONTENT, workspace_id=WS)
    assert out["created_by_subject"] is None


# ---- decision get (DecisionFull) ----

def test_decision_full_model_has_provenance_field():
    from memory_lab.decisions.models import DecisionFull
    assert "created_by_subject" in DecisionFull.model_fields


def test_decision_row_to_full_maps_created_by_subject():
    from memory_lab.decisions.store import DecisionStore
    row = {
        "decision_id": "d1", "content_id": None, "title": "T", "decision_reason": "r",
        "decision_status": "active", "reversible": True,
        "source_content_ids": [], "linked_hub_ids": [],
        "alternatives_considered": [], "decision_tags": [],
        "created_by_subject": SUBJECT, "created_at": NOW, "updated_at": NOW,
    }
    full = DecisionStore._row_to_full(row)
    assert full.created_by_subject == SUBJECT


# ---- hub list (HubResponse) ----

def test_hub_response_model_has_provenance_field():
    from memory_lab.api.routers.hubs import HubResponse
    assert "created_by_subject" in HubResponse.model_fields


def test_list_hubs_select_includes_created_by_subject():
    from memory_lab.graph.hub_store import HubStore
    s = HubStore.__new__(HubStore)
    cur = FakeCursor({"hub_id": "h1", "title": "T", "type": "topic", "description": None,
                      "aliases": [], "related_terms": [], "status": "active",
                      "owner_defined": True, "workspace_id": WS, "workspace_uuid": WS,
                      "created_by_subject": SUBJECT, "created_at": NOW, "updated_at": NOW})
    s._conn = lambda: FakeConn(cur)
    rows = s.list_hubs(workspace_id=WS, status="active")
    assert "created_by_subject" in _sql(cur)
    assert rows[0].get("created_by_subject") == SUBJECT
