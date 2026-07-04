"""Gap-5 — conflict detection wired into ingest + escalation human gate.

Behavioral contracts:
  G5-1  planner maps B11 candidate types/severities to cb_escalations values
  G5-2  informational (low) severity never escalates
  G5-3  only unresolved candidates involving the new content_id escalate; max 1
  G5-4  TTL is severity-based and env-overridable
  G5-5  persist: requires_review quarantines tier=conflicted + governance event
  G5-6  persist: warning links escalation without touching tier
  G5-7  save path: escalation meta lands in response; failure never blocks save
  G5-8  router: approve→persistent, reject→archived, 409 on resolved/expired
  G5-9  router: workspace isolation (foreign escalation is 404)
  G5-10 RBAC: escalations.read broad, escalations.resolve owner/admin + audited

All tests are hermetic — no real DB, no providers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.dependencies.auth import ADMIN_PERMISSIONS, ROLE_PERMISSIONS, require_permission
from memory_lab.api.main import create_app
from memory_lab.conflicts.escalation import (
    ESCALATION_CONFLICT_TYPE_MAP,
    EscalationPlan,
    evaluate_and_escalate_on_ingest,
    persist_escalation,
    plan_escalation_for_content,
)
from memory_lab.conflicts.models import ConflictCandidate
import memory_lab.api.routers.escalations as escalations_router

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-0000000000a1"
OTHER_WS = "00000000-0000-0000-0000-0000000000b2"
SUBJECT = "00000000-0000-0000-0000-0000000000c3"
NEW_CONTENT = "00000000-0000-0000-0000-0000000000d4"
OLD_CONTENT = "00000000-0000-0000-0000-0000000000e5"
ESC_ID = "00000000-0000-0000-0000-0000000000f6"
NOW = datetime(2026, 7, 4, tzinfo=timezone.utc)


def _candidate(
    conflict_type="explicit_contradiction",
    severity="high",
    status="unresolved",
    supporting=(OLD_CONTENT,),
    contradicting=(NEW_CONTENT,),
    confidence=0.85,
):
    return ConflictCandidate(
        candidate_id="cc_test",
        workspace_id=WS,
        conflict_type=conflict_type,
        scope="global",
        status=status,
        severity=severity,
        confidence=confidence,
        supporting_content_ids=list(supporting),
        contradicting_content_ids=list(contradicting),
        evidence=[],
        reason_codes=["explicit_contradiction_marker"],
        detection_rule="explicit_contradiction_marker_v1",
    )


# ---------------------------------------------------------------------------
# G5-1..G5-4 — pure planner
# ---------------------------------------------------------------------------

class TestPlanner:
    def test_g5_1_contradiction_high_maps_to_direct_contradiction_requires_review(self):
        plan = plan_escalation_for_content([_candidate()], workspace_id=WS, content_id=NEW_CONTENT)
        assert plan is not None
        assert plan.conflict_type == "direct_contradiction"
        assert plan.severity == "requires_review"
        assert plan.conflict_content_id == OLD_CONTENT
        assert plan.ttl_days == 30

    def test_g5_1_counterfinding_medium_maps_to_incompatible_assumption_warning(self):
        cand = _candidate(conflict_type="explicit_counterfinding", severity="medium")
        plan = plan_escalation_for_content([cand], workspace_id=WS, content_id=NEW_CONTENT)
        assert plan.conflict_type == "incompatible_assumption"
        assert plan.severity == "warning"
        assert plan.ttl_days == 7

    def test_g5_1_stale_current_tension_maps_to_outdated_assumption(self):
        cand = _candidate(conflict_type="stale_current_tension", severity="high")
        plan = plan_escalation_for_content([cand], workspace_id=WS, content_id=NEW_CONTENT)
        assert plan.conflict_type == "outdated_assumption"

    def test_g5_1_all_b11_types_map_into_migration_014_constraint(self):
        allowed = {
            "same_topic", "incompatible_assumption", "direct_contradiction",
            "confidence_disagreement", "outdated_assumption", "no_conflict",
        }
        assert set(ESCALATION_CONFLICT_TYPE_MAP.values()) <= allowed

    def test_g5_2_low_severity_never_escalates(self):
        cand = _candidate(severity="low")
        assert plan_escalation_for_content([cand], workspace_id=WS, content_id=NEW_CONTENT) is None

    def test_g5_3_resolved_candidates_skipped(self):
        cand = _candidate(status="resolved")
        assert plan_escalation_for_content([cand], workspace_id=WS, content_id=NEW_CONTENT) is None

    def test_g5_3_candidate_not_involving_content_skipped(self):
        cand = _candidate(supporting=(OLD_CONTENT,), contradicting=("00000000-0000-0000-0000-000000000099",))
        assert plan_escalation_for_content([cand], workspace_id=WS, content_id=NEW_CONTENT) is None

    def test_g5_3_max_one_escalation_first_candidate_wins(self):
        first = _candidate(conflict_type="explicit_contradiction", severity="high")
        second = _candidate(conflict_type="explicit_counterfinding", severity="medium")
        plan = plan_escalation_for_content([first, second], workspace_id=WS, content_id=NEW_CONTENT)
        assert plan.conflict_type == "direct_contradiction"

    def test_g5_4_ttl_env_override(self, monkeypatch):
        monkeypatch.setenv("CB_ESCALATION_TTL_REQUIRES_REVIEW_DAYS", "3")
        plan = plan_escalation_for_content([_candidate()], workspace_id=WS, content_id=NEW_CONTENT)
        assert plan.ttl_days == 3

    def test_summary_is_deterministic_and_bounded(self):
        plan = plan_escalation_for_content([_candidate()], workspace_id=WS, content_id=NEW_CONTENT)
        assert "cc_test" in plan.conflict_summary
        assert OLD_CONTENT in plan.conflict_summary
        assert len(plan.conflict_summary) <= 500


# ---------------------------------------------------------------------------
# G5-5 / G5-6 — persist_escalation against a fake connection
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, fetchone_queue):
        self.executed = []
        self._queue = list(fetchone_queue)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._queue.pop(0) if self._queue else None

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, *a, **k):
        return self.cursor_obj

    def commit(self):
        self.committed = True


def _plan(severity="requires_review", conflict_type="direct_contradiction", ttl_days=30):
    return EscalationPlan(
        workspace_id=WS,
        content_id=NEW_CONTENT,
        conflict_content_id=OLD_CONTENT,
        conflict_type=conflict_type,
        severity=severity,
        conflict_summary="candidate_id=cc_test",
        ttl_days=ttl_days,
        candidate_id="cc_test",
        detection_rule="explicit_contradiction_marker_v1",
    )


class TestPersist:
    def test_g5_5_requires_review_quarantines_and_emits_governance_event(self):
        cur = FakeCursor(fetchone_queue=[(ESC_ID,), ("probationary",)])
        conn = FakeConn(cur)

        meta = persist_escalation(conn, _plan())

        sql_all = " || ".join(s for s, _ in cur.executed)
        assert "INSERT INTO cb_escalations" in sql_all
        assert "tier = 'conflicted'::memory_tier" in sql_all
        assert "conflict_escalation_id" in sql_all
        assert "INSERT INTO cb_governance_events" in sql_all
        assert conn.committed
        assert meta == {
            "conflict_escalation_id": ESC_ID,
            "conflict_type": "direct_contradiction",
            "conflict_severity": "requires_review",
            "conflict_content_id": OLD_CONTENT,
            "conflict_status": "pending",
            "conflict_detection_rule": "explicit_contradiction_marker_v1",
        }
        insert_params = cur.executed[0][1]
        assert insert_params[0] == WS
        assert insert_params[1] == NEW_CONTENT
        assert insert_params[2] == OLD_CONTENT
        assert insert_params[3] == "direct_contradiction"
        assert insert_params[4] == "requires_review"
        assert insert_params[6] == 30

    def test_g5_6_warning_links_escalation_without_tier_change(self):
        cur = FakeCursor(fetchone_queue=[(ESC_ID,)])
        conn = FakeConn(cur)

        meta = persist_escalation(conn, _plan(severity="warning", conflict_type="incompatible_assumption", ttl_days=7))

        sql_all = " || ".join(s for s, _ in cur.executed)
        assert "INSERT INTO cb_escalations" in sql_all
        assert "conflict_escalation_id" in sql_all
        assert "'conflicted'::memory_tier" not in sql_all
        assert "cb_governance_events" not in sql_all
        assert meta["conflict_severity"] == "warning"
        assert conn.committed

    def test_evaluate_without_workspace_is_noop(self):
        conn = MagicMock()
        assert evaluate_and_escalate_on_ingest(conn, workspace_id=None, content_id=NEW_CONTENT) is None
        conn.cursor.assert_not_called()


# ---------------------------------------------------------------------------
# G5-7 — save path wiring (T6) is best-effort and reflected in the response
# ---------------------------------------------------------------------------

def _run_create_content(conflict_side_effect):
    """Drive create_content_minimal with everything but T6 stubbed out."""
    from memory_lab.api.services.api_adapter import ApiAdapter
    from memory_lab.governance.tier_router import TierDecision

    adapter = ApiAdapter.__new__(ApiAdapter)
    adapter.database_url = "stub://not-real"
    adapter.embedding_backend = None

    fake_event = MagicMock()
    fake_event.scores.composite = 0.8
    fake_event.scores.quality = 0.8
    fake_event.scores.relevance = 0.8
    fake_event.scores.novelty = 0.8
    fake_event.circuit_open = False
    fake_event.fallback_reason = ""
    fake_tier = TierDecision(tier="probationary", reason="test", rule_id="T", should_persist=True)

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = {
        "content_id": NEW_CONTENT
    }

    with patch.object(adapter, "_conn", return_value=mock_conn), \
         patch.object(adapter, "_find_duplicate_content_id", return_value=None), \
         patch.object(adapter, "_run_classify_and_write", return_value={"classify_confidence": None}), \
         patch("memory_lab.api.services.api_adapter.score_content", return_value=fake_event), \
         patch("memory_lab.api.services.api_adapter.tier_route", return_value=fake_tier), \
         patch("memory_lab.api.services.api_adapter.persist_multi_chunks", return_value=SimpleNamespace(warnings=[])), \
         patch("memory_lab.api.services.api_adapter.annotate", return_value=SimpleNamespace(topic_tags=[], meta_tags=[])), \
         patch("memory_lab.api.services.api_adapter.evaluate_and_escalate_on_ingest", side_effect=conflict_side_effect) as mock_eval:
        resp = adapter.create_content_minimal(content="x " * 200, workspace_id=WS)
    return resp, mock_eval


class TestSavePathWiring:
    def test_g5_7_escalation_meta_in_save_response_and_tier_reflected(self):
        meta = {
            "conflict_escalation_id": ESC_ID,
            "conflict_type": "direct_contradiction",
            "conflict_severity": "requires_review",
            "conflict_content_id": OLD_CONTENT,
            "conflict_status": "pending",
            "conflict_detection_rule": "explicit_contradiction_marker_v1",
        }
        resp, mock_eval = _run_create_content(lambda *a, **k: meta)

        assert mock_eval.call_count == 1
        assert mock_eval.call_args.kwargs["workspace_id"] == WS
        assert mock_eval.call_args.kwargs["content_id"] == NEW_CONTENT
        assert resp["conflict_escalation_id"] == ESC_ID
        assert resp["conflict_severity"] == "requires_review"
        assert resp["tier"] == "conflicted"
        assert resp["tier_reason"] == "conflict:requires_review"
        assert resp["persisted"] is True

    def test_g5_7_warning_meta_does_not_flip_tier(self):
        meta = {"conflict_escalation_id": ESC_ID, "conflict_severity": "warning", "conflict_status": "pending"}
        resp, _ = _run_create_content(lambda *a, **k: meta)
        assert resp["conflict_escalation_id"] == ESC_ID
        assert resp["tier"] == "probationary"

    def test_g5_7_conflict_failure_never_blocks_save(self):
        resp, _ = _run_create_content(RuntimeError("detector exploded"))
        assert resp["persisted"] is True
        assert resp["content_id"] == NEW_CONTENT
        assert "conflict_escalation_id" not in resp

    def test_g5_7_no_conflict_leaves_response_clean(self):
        resp, _ = _run_create_content(lambda *a, **k: None)
        assert resp["persisted"] is True
        assert "conflict_escalation_id" not in resp


# ---------------------------------------------------------------------------
# G5-8 / G5-9 — /v1/escalations router
# ---------------------------------------------------------------------------

def _esc_row(status="pending", expired=False, workspace_id=WS):
    return {
        "id": ESC_ID,
        "workspace_id": workspace_id,
        "content_id": NEW_CONTENT,
        "conflict_content_id": OLD_CONTENT,
        "conflict_type": "direct_contradiction",
        "severity": "requires_review",
        "conflict_summary": "candidate_id=cc_test",
        "status": status,
        "created_at": NOW - timedelta(hours=1),
        "expires_at": NOW + (timedelta(days=30) if not expired else timedelta(days=-1)),
        "resolved_at": None,
        "resolved_by": None,
        "expired_now": expired and status == "pending",
    }


class RouterFakeCursor(FakeCursor):
    def __init__(self, fetchone_queue=(), fetchall_rows=()):
        super().__init__(fetchone_queue)
        self._rows = list(fetchall_rows)

    def fetchall(self):
        return self._rows


def _client(monkeypatch, cursor, role="owner", workspace_id=WS):
    app = create_app()

    def override():
        return AuthContext(
            auth_subject_id=SUBJECT,
            subject_type="user",
            workspace_id=workspace_id,
            role=role,
            auth_method="test",
        )

    for perm in ("escalations.read", "escalations.resolve"):
        app.dependency_overrides[require_permission(perm)] = override
        for route in app.routes:
            dependant = getattr(route, "dependant", None)
            if not dependant:
                continue
            for dep in getattr(dependant, "dependencies", []):
                call = getattr(dep, "call", None)
                if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                    closure_values = [cell.cell_contents for cell in call.__closure__]
                    if perm in closure_values:
                        app.dependency_overrides[call] = override

    monkeypatch.setattr(escalations_router, "_conn", lambda: FakeConn(cursor))
    return TestClient(app)


class TestEscalationsRouter:
    def test_list_is_workspace_scoped(self, monkeypatch):
        cur = RouterFakeCursor(fetchall_rows=[_esc_row()])
        client = _client(monkeypatch, cur)

        resp = client.get("/v1/escalations")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["escalation_id"] == ESC_ID
        assert body[0]["status"] == "pending"
        sql, params = cur.executed[0]
        assert "workspace_id = %s::uuid" in sql
        assert params[0] == WS

    def test_list_synthesizes_expired_status(self, monkeypatch):
        cur = RouterFakeCursor(fetchall_rows=[_esc_row(expired=True)])
        client = _client(monkeypatch, cur)

        resp = client.get("/v1/escalations")

        assert resp.json()[0]["status"] == "expired"

    def test_get_foreign_workspace_escalation_is_404(self, monkeypatch):
        cur = RouterFakeCursor(fetchone_queue=[None])
        client = _client(monkeypatch, cur, workspace_id=OTHER_WS)

        resp = client.get(f"/v1/escalations/{ESC_ID}")

        assert resp.status_code == 404
        sql, params = cur.executed[0]
        assert "workspace_id = %s::uuid" in sql
        assert params == (ESC_ID, OTHER_WS)

    def test_g5_8_approve_promotes_content_to_persistent(self, monkeypatch):
        resolved = {**_esc_row(status="approved"), "resolved_at": NOW, "resolved_by": SUBJECT}
        cur = RouterFakeCursor(fetchone_queue=[_esc_row(), {"tier": "conflicted"}, resolved])
        client = _client(monkeypatch, cur)

        resp = client.post(f"/v1/escalations/{ESC_ID}/approve")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "approved"
        assert body["resolved_by"] == SUBJECT
        sql_all = " || ".join(s for s, _ in cur.executed)
        assert "tier = %s::memory_tier" in sql_all
        assert "INSERT INTO cb_governance_events" in sql_all
        tier_update = next(p for s, p in cur.executed if "UPDATE content_items" in s)
        assert tier_update[0] == "persistent"
        assert tier_update[1] == "escalation_approved"

    def test_g5_8_reject_archives_content(self, monkeypatch):
        resolved = {**_esc_row(status="rejected"), "resolved_at": NOW, "resolved_by": SUBJECT}
        cur = RouterFakeCursor(fetchone_queue=[_esc_row(), {"tier": "conflicted"}, resolved])
        client = _client(monkeypatch, cur)

        resp = client.post(f"/v1/escalations/{ESC_ID}/reject")

        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"
        tier_update = next(p for s, p in cur.executed if "UPDATE content_items" in s)
        assert tier_update[0] == "archived"
        assert tier_update[1] == "escalation_rejected"

    def test_g5_8_already_resolved_is_409(self, monkeypatch):
        cur = RouterFakeCursor(fetchone_queue=[_esc_row(status="approved")])
        client = _client(monkeypatch, cur)

        resp = client.post(f"/v1/escalations/{ESC_ID}/approve")

        assert resp.status_code == 409
        assert "approved" in resp.json()["detail"]

    def test_g5_8_expired_pending_refuses_resolution(self, monkeypatch):
        cur = RouterFakeCursor(fetchone_queue=[_esc_row(expired=True)])
        client = _client(monkeypatch, cur)

        resp = client.post(f"/v1/escalations/{ESC_ID}/approve")

        assert resp.status_code == 409
        assert resp.json()["detail"] == "escalation expired"

    def test_invalid_escalation_id_is_422(self, monkeypatch):
        cur = RouterFakeCursor()
        client = _client(monkeypatch, cur)

        resp = client.get("/v1/escalations/not-a-uuid")

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# G5-10 — RBAC surface
# ---------------------------------------------------------------------------

class TestRbac:
    def test_read_permission_is_broad(self):
        assert ROLE_PERMISSIONS["escalations.read"] == {
            "owner", "admin", "writer", "reader", "service_agent", "auditor",
        }

    def test_resolve_permission_is_owner_admin_only_and_audited(self):
        assert ROLE_PERMISSIONS["escalations.resolve"] == {"owner", "admin"}
        assert "escalations.resolve" in ADMIN_PERMISSIONS
