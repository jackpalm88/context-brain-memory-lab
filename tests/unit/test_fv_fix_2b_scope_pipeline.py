"""Unit tests — FV-FIX-2B scope resolver pipeline.

Tier order: scope_hint → marker → lineage → hub alias → classify metadata
→ keyword heuristic → global. Deterministic; ambiguous ties skip the tier;
DB errors skip the tier; the pipeline never raises.

Pure-Python; no DB; no provider calls.
"""

import pytest

from memory_lab.current_state.resolver import resolve_current_state_after_ingest
from memory_lab.current_state.scope_pipeline import ScopeResolution, resolve_scope

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000001"
CONTENT = "00000000-0000-0000-0000-000000000002"


class FakeCursor:
    """Routes fetchall by table named in the executed SQL; fetchone from a queue."""

    def __init__(self, anchor_scopes=None, hubs=None, fetchone_queue=None, fail_tables=()):
        self.anchor_scopes = anchor_scopes or []
        self.hubs = hubs or []
        self.fetchone_queue = list(fetchone_queue or [])
        self.fail_tables = fail_tables
        self.executed = []
        self._last_sql = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        for table in self.fail_tables:
            if table in sql:
                raise RuntimeError(f"simulated failure on {table}")
        self.executed.append((sql, params))
        self._last_sql = sql

    def fetchall(self):
        if "cb_current_state_anchors" in self._last_sql:
            return [(s,) for s in self.anchor_scopes]
        if "cb_hubs" in self._last_sql:
            return list(self.hubs)
        return []

    def fetchone(self):
        return self.fetchone_queue.pop(0) if self.fetchone_queue else None


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        pass


def _conn(**kwargs):
    return FakeConn(FakeCursor(**kwargs))


# ---------------------------------------------------------------------------
# Tier 1+2 — precedence: explicit scope_hint beats in-text marker
# ---------------------------------------------------------------------------

def test_scope_hint_beats_in_text_marker():
    result = resolve_scope(None, scope_hint="Api Choice", content_text="scope: other-thing\nbody")
    assert result == ScopeResolution(scope="api-choice", source="scope_hint")


def test_marker_wins_when_no_hint():
    result = resolve_scope(None, content_text="scope: db-migration-plan\nbody")
    assert result == ScopeResolution(scope="db-migration-plan", source="marker")


def test_scope_hint_skips_db_tiers_entirely():
    cur = FakeCursor()
    result = resolve_scope(FakeConn(cur), workspace_id=WS, content_text="text",
                           scope_hint="pinned")
    assert result.source == "scope_hint"
    assert cur.executed == []


# ---------------------------------------------------------------------------
# Tier 3 — lineage: reuse an existing active anchor scope
# ---------------------------------------------------------------------------

def test_lineage_reuses_existing_anchor_scope():
    conn = _conn(anchor_scopes=["db-choice", "frontend-framework"])
    result = resolve_scope(conn, workspace_id=WS,
                           content_text="We revisited the db choice for the storage layer today.")
    assert result == ScopeResolution(scope="db-choice", source="lineage")


def test_lineage_ambiguous_tie_skips_tier():
    conn = _conn(anchor_scopes=["db-choice", "db-plan"])
    result = resolve_scope(conn, workspace_id=WS,
                           content_text="The db choice and the db plan were both discussed.",
                           project_topic="fallback-topic")
    assert result.source == "classify_metadata"
    assert result.scope == "fallback-topic"


def test_lineage_requires_all_scope_tokens():
    conn = _conn(anchor_scopes=["frontend-framework"])
    result = resolve_scope(conn, workspace_id=WS,
                           content_text="Notes about the frontend only, framework not decided.",
                           domain_hint="api")
    # "frontend" and "framework" both appear as words → match
    assert result == ScopeResolution(scope="frontend-framework", source="lineage")
    conn2 = _conn(anchor_scopes=["frontend-framework"])
    result2 = resolve_scope(conn2, workspace_id=WS,
                            content_text="Notes about the frontend only.", domain_hint="api")
    assert result2.source == "keyword_heuristic"


# ---------------------------------------------------------------------------
# Tier 4 — hub alias match
# ---------------------------------------------------------------------------

def test_hub_title_or_alias_match_wins():
    conn = _conn(hubs=[("Payments Platform", ["payments"], [])])
    result = resolve_scope(conn, workspace_id=WS,
                           content_text="Decision about payments retry policy.")
    assert result == ScopeResolution(scope="payments-platform", source="hub_alias")


def test_hub_related_terms_need_two_hits():
    hubs = [("Billing", [], ["stripe", "invoice"])]
    one_hit = resolve_scope(_conn(hubs=hubs), workspace_id=WS,
                            content_text="We integrated stripe yesterday.",
                            project_topic="fallback-topic")
    assert one_hit.source == "classify_metadata"
    two_hits = resolve_scope(_conn(hubs=hubs), workspace_id=WS,
                             content_text="The stripe invoice flow is now live.")
    assert two_hits == ScopeResolution(scope="billing", source="hub_alias")


def test_hub_tie_between_two_hubs_skips_tier():
    hubs = [("Alpha Service", ["alpha"], []), ("Beta Service", ["beta"], [])]
    result = resolve_scope(_conn(hubs=hubs), workspace_id=WS,
                           content_text="Comparing alpha and beta before deciding.")
    assert result.source == "global_fallback"


def test_hub_short_terms_are_ignored():
    conn = _conn(hubs=[("DB", ["db"], [])])  # < 3 chars — too noisy to match
    result = resolve_scope(conn, workspace_id=WS, content_text="the db is fine")
    assert result.source == "global_fallback"


# ---------------------------------------------------------------------------
# Tier isolation — DB errors skip the tier, never raise
# ---------------------------------------------------------------------------

def test_db_error_skips_tier_and_falls_through():
    cur = FakeCursor(hubs=[("Payments Platform", ["payments"], [])],
                     fail_tables=("cb_current_state_anchors",))
    result = resolve_scope(FakeConn(cur), workspace_id=WS,
                           content_text="Decision about payments retry policy.")
    assert result == ScopeResolution(scope="payments-platform", source="hub_alias")


def test_all_db_tiers_failing_falls_to_metadata():
    cur = FakeCursor(fail_tables=("cb_current_state_anchors", "cb_hubs"))
    result = resolve_scope(FakeConn(cur), workspace_id=WS, content_text="anything",
                           project_topic="Context Brain")
    assert result == ScopeResolution(scope="context-brain", source="classify_metadata")


def test_no_conn_skips_db_tiers():
    result = resolve_scope(None, workspace_id=WS, content_text="anything",
                           domain_hint="governance")
    assert result == ScopeResolution(scope="governance", source="keyword_heuristic")


# ---------------------------------------------------------------------------
# End-to-end — resolve_current_state_after_ingest threads scope_hint + source
# ---------------------------------------------------------------------------

def test_resolver_accepts_scope_hint_and_reports_scope_source():
    cur = FakeCursor(fetchone_queue=[None, None, ("anchor-1",)])
    resolution = resolve_current_state_after_ingest(
        FakeConn(cur), workspace_id=WS, content_id=CONTENT, memory_type="decision",
        classify_confidence=0.9, scope_hint="Payment Provider",
        content_text="scope: should-lose\nDecision: switch provider.",
    )
    assert resolution.status == "active"
    assert resolution.current_state_scope == "payment-provider"
    assert resolution.scope_source == "scope_hint"
    assert resolution.to_dict()["scope_source"] == "scope_hint"
    insert_sql, insert_params = next(
        (sql, params) for sql, params in cur.executed
        if "INSERT INTO cb_current_state_anchors" in sql
    )
    assert any("scope_source=scope_hint" in str(p) for p in insert_params)


def test_resolver_lineage_source_end_to_end():
    cur = FakeCursor(anchor_scopes=["db-choice"], fetchone_queue=[None, None, ("anchor-2",)])
    resolution = resolve_current_state_after_ingest(
        FakeConn(cur), workspace_id=WS, content_id=CONTENT, memory_type="decision",
        classify_confidence=0.9, content_text="Decision: revisit the db choice.",
    )
    assert resolution.current_state_scope == "db-choice"
    assert resolution.scope_source == "lineage"
