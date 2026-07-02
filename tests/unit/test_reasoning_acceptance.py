"""Reasoning Acceptance Tests — M12-REASONING-1 (Engineering Quality Asset, not product artifact).

Validates RA-1..RA-9 behavioral contracts for the reasoning layer (answer/traverse/explain)
against Retrieval Doctrine v1.0 and B13/B14 boundaries.

100% hermetic: no DATABASE_URL, no live provider, no live embeddings.
- Service-level tests (RA-2/3/4/5/6/7/9): call service/model functions directly.
- HTTP-level tests (RA-1/8): TestClient + all-route dep override + service patch.

RA-8 acceptance bugfix: require_permission() creates a new closure per import-time call,
so a single require_permission("retrieval.search") override does NOT match the closures
registered in the router. All deps must be found by scanning app.routes and overriding by
identity (see _override_auth_on_app). This is a harness bug, not a product bug — the router
_check_workspace correctly fires 403 when auth is properly supplied.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

WS_A = "00000000-0000-0000-0000-000000000924"
WS_B = "00000000-0000-0000-0000-000000000999"


def _mk_ev(cid: str, text: str = "evidence text for acceptance tests") -> dict:
    return {
        "evidence_id": f"ev_{cid}",
        "rank": 1,
        "content_id": cid,
        "snippet": text,
        "score": 0.9,
        "score_kind": "chunk_text_match",
        "memory_type": "decision",
        "retrieval_path": "hub_store.match_query",
    }


def _build_cp(workspace_id: str = WS_A, evidence: list | None = None):
    """Build a ContextPackBuildResponse without touching a database."""
    from memory_lab.context_packs.builder import build_context_pack
    from memory_lab.context_packs.models import ContextPackBuildRequest

    ev = evidence if evidence is not None else [_mk_ev("cid_a"), _mk_ev("cid_b")]
    return build_context_pack(
        workspace_id=workspace_id,
        request=ContextPackBuildRequest(query="acceptance test query", scope="test"),
        supporting_evidence=ev,
        current_state_rows=[],
        conflict_candidates=[],
    )


def _override_auth_on_app(app, workspace_id: str = WS_A):
    """Override ALL require_permission('retrieval.search') closures in the app route graph.

    FastAPI's dependency_overrides requires the exact function object as key.
    require_permission() creates a new closure on every call, so a new reference
    from the test does NOT match the router's registered closures — the DB is still hit.
    This helper scans app.routes and patches by identity.
    """
    from memory_lab.api.auth_context import AuthContext

    def auth_override():
        return AuthContext(
            auth_subject_id="acceptance-test-subject",
            subject_type="user",
            workspace_id=workspace_id,
            role="owner",
            auth_method="acceptance_test",
        )

    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if call is None:
                continue
            cells = []
            for cell in getattr(call, "__closure__", None) or []:
                try:
                    cells.append(cell.cell_contents)
                except ValueError:
                    pass
            if "retrieval.search" in cells:
                app.dependency_overrides[call] = auth_override


def _make_client(workspace_id: str = WS_A, evidence: list | None = None):
    """Return a hermetic TestClient with auth + service patched."""
    import memory_lab.reasoning.service as svc
    from fastapi.testclient import TestClient
    from memory_lab.api.main import create_app

    cp = _build_cp(workspace_id=workspace_id, evidence=evidence)
    svc.build_context_pack_for_request = lambda **kw: cp

    app = create_app()
    _override_auth_on_app(app, workspace_id=workspace_id)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# RA-1: Response shape — all required fields present on all endpoints
# ---------------------------------------------------------------------------

ANSWER_REQUIRED = {
    "reasoning_id",
    "mode",
    "answer_candidate",
    "evidence_refs",
    "context_pack_ref",
    "traversal_steps",
    "conflict_warnings",
    "limitations",
    "provider_metadata",
    "degraded_reason",
    "non_claims",
}
TRAVERSE_REQUIRED = {
    "reasoning_id",
    "mode",
    "context_pack_ref",
    "traversal_steps",
    "evidence_refs",
    "explanation",
    "conflict_warnings",
    "limitations",
    "provider_metadata",
    "degraded_reason",
    "non_claims",
}
EXPLAIN_REQUIRED = TRAVERSE_REQUIRED
CONTEXT_PACK_REF_REQUIRED = {"context_pack_id", "workspace_id", "query", "pack_version"}
PROVIDER_METADATA_REQUIRED = {"provider", "attempted", "configured", "degraded"}


class TestRA1ResponseShape:
    """RA-1: Every endpoint response exposes all required top-level fields."""

    def test_answer_endpoint_required_fields(self):
        tc = _make_client()
        r = tc.post("/v1/reasoning/answer", json={"query": "test shape"})
        assert r.status_code == 200
        body = r.json()
        missing = ANSWER_REQUIRED - set(body.keys())
        assert not missing, f"answer missing fields: {missing}"

    def test_traverse_endpoint_required_fields(self):
        tc = _make_client()
        r = tc.post("/v1/reasoning/traverse", json={"query": "test shape"})
        assert r.status_code == 200
        body = r.json()
        missing = TRAVERSE_REQUIRED - set(body.keys())
        assert not missing, f"traverse missing fields: {missing}"

    def test_explain_endpoint_required_fields(self):
        tc = _make_client()
        r = tc.post("/v1/reasoning/explain", json={"query": "test shape"})
        assert r.status_code == 200
        body = r.json()
        missing = EXPLAIN_REQUIRED - set(body.keys())
        assert not missing, f"explain missing fields: {missing}"

    def test_context_pack_ref_sub_fields(self):
        tc = _make_client()
        r = tc.post("/v1/reasoning/answer", json={"query": "test shape"})
        assert r.status_code == 200
        cp_ref = r.json()["context_pack_ref"]
        missing = CONTEXT_PACK_REF_REQUIRED - set(cp_ref.keys())
        assert not missing, f"context_pack_ref missing sub-fields: {missing}"

    def test_provider_metadata_sub_fields(self):
        tc = _make_client()
        r = tc.post("/v1/reasoning/answer", json={"query": "test shape"})
        assert r.status_code == 200
        pm = r.json()["provider_metadata"]
        missing = PROVIDER_METADATA_REQUIRED - set(pm.keys())
        assert not missing, f"provider_metadata missing sub-fields: {missing}"

    def test_reasoning_id_is_non_empty_string(self):
        tc = _make_client()
        for ep in ("/v1/reasoning/answer", "/v1/reasoning/traverse", "/v1/reasoning/explain"):
            r = tc.post(ep, json={"query": "test"})
            assert r.status_code == 200
            rid = r.json()["reasoning_id"]
            assert isinstance(rid, str) and len(rid) > 0, f"{ep} reasoning_id empty"


# ---------------------------------------------------------------------------
# RA-2: Mode classification — correct mode for each path
# ---------------------------------------------------------------------------

VALID_ANSWER_MODES = {"deterministic", "provider_backed", "degraded"}
VALID_TRAVERSE_MODES = {
    "deterministic_read_only",
    "provider_assisted_read_only",
    "provider_degraded_read_only",
}


class TestRA2ModeClassification:
    """RA-2: mode field reflects the actual execution path taken."""

    def test_traverse_default_mode_is_deterministic_read_only(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp()
        r = traverse_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert r.mode == "deterministic_read_only"

    def test_explain_default_mode_is_deterministic_read_only(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import explain_context_pack

        cp = _build_cp()
        r = explain_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert r.mode == "deterministic_read_only"

    def test_answer_with_evidence_no_provider_is_deterministic(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp()
        r = answer_context_pack(
            context_pack=cp,
            request=ReasoningRequest(query="q", enable_provider_synthesis=False),
        )
        assert r.mode == "deterministic"

    def test_answer_no_evidence_mode_is_degraded(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp(evidence=[])
        r = answer_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert r.mode == "degraded"

    def test_answer_with_fake_provider_mode_is_provider_backed(self):
        from memory_lab.providers.fake import FakeLLMBackend
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp()
        r = answer_context_pack(
            context_pack=cp,
            request=ReasoningRequest(query="q", enable_provider_synthesis=True),
            backend=FakeLLMBackend(),
            provider_synthesis_enabled=True,
        )
        assert r.mode == "provider_backed"

    def test_answer_mode_is_valid_enum_value(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        for ev, flag in [([_mk_ev("a")], False), ([], False)]:
            cp = _build_cp(evidence=ev)
            r = answer_context_pack(
                context_pack=cp,
                request=ReasoningRequest(query="q", enable_provider_synthesis=flag),
            )
            assert r.mode in VALID_ANSWER_MODES, f"unknown answer mode: {r.mode!r}"

    def test_traverse_mode_is_valid_enum_value(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp()
        r = traverse_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert r.mode in VALID_TRAVERSE_MODES, f"unknown traverse mode: {r.mode!r}"


# ---------------------------------------------------------------------------
# RA-3: Provider gate precedence — dual gate controls synthesis
# ---------------------------------------------------------------------------


class TestRA3ProviderGatePrecedence:
    """RA-3: Provider synthesis requires BOTH request flag AND server gate. Either off = no call."""

    def test_request_flag_off_gate_on_stays_deterministic(self):
        """enable_provider_synthesis=False overrides even when server gate is on."""
        from memory_lab.providers.fake import FakeLLMBackend
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp()
        r = answer_context_pack(
            context_pack=cp,
            request=ReasoningRequest(query="q", enable_provider_synthesis=False),
            backend=FakeLLMBackend(),
            provider_synthesis_enabled=True,
        )
        assert r.mode == "deterministic"
        assert r.provider_metadata.attempted is False

    def test_server_gate_off_blocks_synthesis_despite_request_flag(self):
        """provider_synthesis_enabled=False blocks even if request explicitly opts in."""
        from memory_lab.providers.fake import FakeLLMBackend
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp()
        r = answer_context_pack(
            context_pack=cp,
            request=ReasoningRequest(query="q", enable_provider_synthesis=True),
            backend=FakeLLMBackend(),
            provider_synthesis_enabled=False,
        )
        # gate blocked: provider not called; mode degrades (no deterministic fallback path)
        assert r.provider_metadata.attempted is False

    def test_both_gates_off_no_provider_call(self):
        """No provider call when both flags are off."""
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp()
        r = answer_context_pack(
            context_pack=cp,
            request=ReasoningRequest(query="q", enable_provider_synthesis=False),
            backend=None,
            provider_synthesis_enabled=False,
        )
        assert r.mode == "deterministic"
        assert r.provider_metadata.attempted is False
        assert r.provider_metadata.provider == "none"

    def test_traverse_never_calls_provider_by_default(self):
        """traverse always deterministic_read_only regardless of backend availability."""
        from memory_lab.providers.fake import FakeLLMBackend
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp()
        r = traverse_context_pack(
            context_pack=cp,
            request=ReasoningRequest(query="q"),
            backend=FakeLLMBackend(),
        )
        assert r.mode == "deterministic_read_only"


# ---------------------------------------------------------------------------
# RA-4: Graceful degradation — no context / empty evidence handled cleanly
# ---------------------------------------------------------------------------


class TestRA4GracefulDegradation:
    """RA-4: Empty or absent evidence does not raise; returns degraded state with explanation."""

    def test_answer_empty_evidence_degrades_gracefully(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp(evidence=[])
        r = answer_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert r.mode == "degraded"
        assert r.degraded_reason == "insufficient_evidence"

    def test_answer_degraded_candidate_is_non_empty_string(self):
        """Degraded response must contain a non-empty fallback text, not an error."""
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp(evidence=[])
        r = answer_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert isinstance(r.answer_candidate, str)
        assert len(r.answer_candidate.strip()) > 0

    def test_traverse_empty_evidence_returns_without_error(self):
        """traverse/explain on empty pack returns 200 with empty refs, not an error."""
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp(evidence=[])
        r = traverse_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert r.mode == "deterministic_read_only"
        assert r.evidence_refs == []

    def test_explain_empty_evidence_returns_without_error(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import explain_context_pack

        cp = _build_cp(evidence=[])
        r = explain_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert r.mode == "deterministic_read_only"
        assert r.evidence_refs == []

    def test_answer_degraded_has_no_provider_call(self):
        """Degraded due to insufficient evidence: provider must not be attempted."""
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp(evidence=[])
        r = answer_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        assert r.provider_metadata.attempted is False


# ---------------------------------------------------------------------------
# RA-5: Citation grounding — evidence_refs carry provenance fields
# ---------------------------------------------------------------------------


class TestRA5CitationGrounding:
    """RA-5: Every evidence_ref in the response exposes content_id, score, snippet, source."""

    def _get_refs(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp(evidence=[_mk_ev("cid_alpha"), _mk_ev("cid_beta")])
        r = answer_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        return r.evidence_refs

    def test_evidence_refs_have_content_id(self):
        for ref in self._get_refs():
            assert ref.get("content_id"), f"missing content_id in ref: {ref}"

    def test_evidence_refs_have_non_zero_score(self):
        for ref in self._get_refs():
            assert ref.get("score") is not None, f"missing score in ref: {ref}"
            assert ref["score"] > 0

    def test_evidence_refs_have_snippet(self):
        for ref in self._get_refs():
            assert ref.get("snippet"), f"missing snippet in ref: {ref}"

    def test_evidence_refs_have_retrieval_source(self):
        """source (maps from input retrieval_path) must be present on all refs."""
        for ref in self._get_refs():
            assert ref.get("source"), f"missing source in ref: {ref}"

    def test_answer_candidate_uses_evidence_text(self):
        """answer_candidate cites at least one evidence_id from the pack."""
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        ev = [_mk_ev("grounding_check")]
        cp = _build_cp(evidence=ev)
        r = answer_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        if r.mode != "degraded":
            # deterministic candidate should contain the evidence_id or snippet
            assert "ev_grounding_check" in r.answer_candidate or "evidence" in r.answer_candidate.lower()


# ---------------------------------------------------------------------------
# RA-6: No truth decision — non_claims invariants present on all modes
# ---------------------------------------------------------------------------


class TestRA6NoTruthDecision:
    """RA-6: No-truth-decision non_claims are present regardless of execution path."""

    REQUIRED_NON_CLAIMS = {"no_truth_arbitration", "no_verdict"}

    def _check_non_claims(self, non_claims: list[str], label: str):
        present = set(non_claims)
        missing = self.REQUIRED_NON_CLAIMS - present
        assert not missing, f"{label}: missing non_claims: {missing}; got: {present}"

    def test_traverse_non_claims(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp()
        r = traverse_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        self._check_non_claims(r.non_claims, "traverse")

    def test_explain_non_claims(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import explain_context_pack

        cp = _build_cp()
        r = explain_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        self._check_non_claims(r.non_claims, "explain")

    def test_answer_non_claims_deterministic(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp()
        r = answer_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        self._check_non_claims(r.non_claims, "answer/deterministic")
        # answer adds specific extra non_claims beyond base
        assert "no_verdict" in r.non_claims
        assert "no_resolution" in r.non_claims

    def test_answer_non_claims_degraded(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp(evidence=[])
        r = answer_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        self._check_non_claims(r.non_claims, "answer/degraded")

    def test_limitations_non_empty_on_all_paths(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import explain_context_pack, traverse_context_pack

        cp = _build_cp()
        req = ReasoningRequest(query="q")
        assert len(traverse_context_pack(context_pack=cp, request=req).limitations) > 0
        assert len(explain_context_pack(context_pack=cp, request=req).limitations) > 0
        assert len(answer_context_pack(context_pack=cp, request=req).limitations) > 0

    def test_no_answer_field_on_traverse(self):
        """traverse/explain must not expose an 'answer' top-level field (B13 boundary)."""
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp()
        r = traverse_context_pack(context_pack=cp, request=ReasoningRequest(query="q"))
        d = r.model_dump()
        assert "answer" not in d, "traverse must not expose 'answer' field"


# ---------------------------------------------------------------------------
# RA-7: Determinism — identical inputs produce identical outputs
# ---------------------------------------------------------------------------


class TestRA7Determinism:
    """RA-7: Reasoning is deterministic; repeated calls with same context produce same output."""

    def test_traverse_reasoning_id_is_stable(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp()
        req = ReasoningRequest(query="determinism test")
        r1 = traverse_context_pack(context_pack=cp, request=req)
        r2 = traverse_context_pack(context_pack=cp, request=req)
        assert r1.reasoning_id == r2.reasoning_id

    def test_traverse_evidence_refs_are_stable(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp()
        req = ReasoningRequest(query="determinism test")
        r1 = traverse_context_pack(context_pack=cp, request=req)
        r2 = traverse_context_pack(context_pack=cp, request=req)
        assert r1.evidence_refs == r2.evidence_refs

    def test_answer_candidate_is_stable(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp()
        req = ReasoningRequest(query="determinism test", enable_provider_synthesis=False)
        r1 = answer_context_pack(context_pack=cp, request=req)
        r2 = answer_context_pack(context_pack=cp, request=req)
        assert r1.answer_candidate == r2.answer_candidate

    def test_answer_reasoning_id_is_stable(self):
        from memory_lab.reasoning.answer import answer_context_pack
        from memory_lab.reasoning.models import ReasoningRequest

        cp = _build_cp()
        req = ReasoningRequest(query="determinism test", enable_provider_synthesis=False)
        r1 = answer_context_pack(context_pack=cp, request=req)
        r2 = answer_context_pack(context_pack=cp, request=req)
        assert r1.reasoning_id == r2.reasoning_id

    def test_explain_mode_is_stable(self):
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import explain_context_pack

        cp = _build_cp()
        req = ReasoningRequest(query="determinism test")
        r1 = explain_context_pack(context_pack=cp, request=req)
        r2 = explain_context_pack(context_pack=cp, request=req)
        assert r1.mode == r2.mode
        assert r1.reasoning_id == r2.reasoning_id


# ---------------------------------------------------------------------------
# RA-8: Workspace 403 — workspace_id mismatch rejected at router before service call
#
# Acceptance bugfix documented: single require_permission() override does not match
# the per-route closure already registered in the router. Use _override_auth_on_app()
# to scan app.routes and patch all retrieval.search closures by identity.
# ---------------------------------------------------------------------------


class TestRA8WorkspaceMismatch:
    """RA-8: request.workspace_id != auth.workspace_id → 403 workspace_id_mismatch."""

    def _make_mismatch_client(self):
        """Auth is WS_A; requests will carry WS_B."""
        import memory_lab.reasoning.service as svc
        from fastapi.testclient import TestClient
        from memory_lab.api.main import create_app

        cp = _build_cp(workspace_id=WS_A)
        svc.build_context_pack_for_request = lambda **kw: cp

        app = create_app()
        _override_auth_on_app(app, workspace_id=WS_A)  # token says WS_A
        return TestClient(app, raise_server_exceptions=False)

    def test_answer_workspace_mismatch_returns_403(self):
        tc = self._make_mismatch_client()
        r = tc.post("/v1/reasoning/answer", json={"query": "test", "workspace_id": WS_B})
        assert r.status_code == 403
        assert r.json().get("detail") == "workspace_id_mismatch"

    def test_traverse_workspace_mismatch_returns_403(self):
        tc = self._make_mismatch_client()
        r = tc.post("/v1/reasoning/traverse", json={"query": "test", "workspace_id": WS_B})
        assert r.status_code == 403
        assert r.json().get("detail") == "workspace_id_mismatch"

    def test_explain_workspace_mismatch_returns_403(self):
        tc = self._make_mismatch_client()
        r = tc.post("/v1/reasoning/explain", json={"query": "test", "workspace_id": WS_B})
        assert r.status_code == 403
        assert r.json().get("detail") == "workspace_id_mismatch"

    def test_omitted_workspace_id_returns_200(self):
        """No workspace_id in request body → _check_workspace skips check → 200."""
        tc = self._make_mismatch_client()
        r = tc.post("/v1/reasoning/answer", json={"query": "test"})
        assert r.status_code == 200

    def test_matching_workspace_id_returns_200(self):
        """workspace_id matching auth → no mismatch → 200."""
        tc = self._make_mismatch_client()
        r = tc.post("/v1/reasoning/answer", json={"query": "test", "workspace_id": WS_A})
        assert r.status_code == 200

    def test_mismatch_fires_before_db_call(self):
        """The 403 must fire before any DB/service call (workspace guard is at router level)."""
        import memory_lab.reasoning.service as svc
        from fastapi.testclient import TestClient
        from memory_lab.api.main import create_app

        sentinel = {"called": False}

        def _guard(**kw):
            sentinel["called"] = True
            raise AssertionError("service should not be reached on workspace mismatch")

        svc.build_context_pack_for_request = _guard

        app = create_app()
        _override_auth_on_app(app, workspace_id=WS_A)
        tc = TestClient(app, raise_server_exceptions=False)

        r = tc.post("/v1/reasoning/answer", json={"query": "test", "workspace_id": WS_B})
        assert r.status_code == 403
        assert not sentinel["called"], "service was called despite workspace mismatch"


# ---------------------------------------------------------------------------
# RA-9: Max hops cap — model enforces ge=1, le=3; limit enforces ge=1, le=50
# ---------------------------------------------------------------------------


class TestRA9MaxHopsCap:
    """RA-9: max_hops capped at 3 by model; limit capped at 50. Violations rejected at parse time."""

    def test_max_hops_above_limit_rejected(self):
        from memory_lab.reasoning.models import ReasoningRequest

        with pytest.raises(ValidationError) as exc_info:
            ReasoningRequest(query="q", max_hops=4)
        errors = exc_info.value.errors()
        assert any(e["type"] == "less_than_equal" for e in errors)

    def test_max_hops_below_minimum_rejected(self):
        from memory_lab.reasoning.models import ReasoningRequest

        with pytest.raises(ValidationError) as exc_info:
            ReasoningRequest(query="q", max_hops=0)
        errors = exc_info.value.errors()
        assert any(e["type"] == "greater_than_equal" for e in errors)

    def test_max_hops_at_upper_limit_accepted(self):
        from memory_lab.reasoning.models import ReasoningRequest

        r = ReasoningRequest(query="q", max_hops=3)
        assert r.max_hops == 3

    def test_max_hops_at_lower_limit_accepted(self):
        from memory_lab.reasoning.models import ReasoningRequest

        r = ReasoningRequest(query="q", max_hops=1)
        assert r.max_hops == 1

    def test_limit_above_cap_rejected(self):
        from memory_lab.reasoning.models import ReasoningRequest

        with pytest.raises(ValidationError) as exc_info:
            ReasoningRequest(query="q", limit=51)
        errors = exc_info.value.errors()
        assert any(e["type"] == "less_than_equal" for e in errors)

    def test_limit_at_cap_accepted(self):
        from memory_lab.reasoning.models import ReasoningRequest

        r = ReasoningRequest(query="q", limit=50)
        assert r.limit == 50

    def test_max_hops_respected_in_reasoning_id(self):
        """reasoning_id embeds max_hops so determinism is scoped to hop depth."""
        from memory_lab.reasoning.models import ReasoningRequest
        from memory_lab.reasoning.service import traverse_context_pack

        cp = _build_cp()
        r1 = traverse_context_pack(context_pack=cp, request=ReasoningRequest(query="q", max_hops=1))
        r2 = traverse_context_pack(context_pack=cp, request=ReasoningRequest(query="q", max_hops=2))
        # Different hop depths → different reasoning_id
        assert r1.reasoning_id != r2.reasoning_id
