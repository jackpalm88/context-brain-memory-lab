import pytest

from memory_lab.context_packs.builder import build_context_pack
from memory_lab.context_packs.models import ContextPackBuildRequest
from memory_lab.providers.fake import FakeLLMBackend
from memory_lab.providers.llm_backend import LLMResponse

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000924"
SUBJECT = "00000000-0000-0000-0000-000000000925"


def _ev(content_id, *, rank=1, text="M4 endpoint evidence", role=None):
    row = {
        "evidence_id": f"ev_{content_id}",
        "rank": rank,
        "content_id": content_id,
        "snippet": text,
        "score": 0.9,
        "score_kind": "chunk_text_match",
        "memory_type": "decision",
    }
    if role:
        row["role"] = role
    return row


def _pack(*, query="m4 answer"):
    return build_context_pack(
        workspace_id=WS,
        request=ContextPackBuildRequest(query=query, scope="m4-answer"),
        supporting_evidence=[_ev("support", text="M4 endpoint provider synthesis may cite this public evidence", rank=1)],
        current_state_rows=[_ev("current", text="M4 current-state signal remains evidence only", rank=2) | {"is_current": True, "current_state_scope": "m4-answer"}],
        conflict_candidates=[],
    )


def _client(monkeypatch, backend=None):
    from fastapi.testclient import TestClient
    from memory_lab.api.auth_context import AuthContext
    from memory_lab.api.dependencies.auth import require_permission
    from memory_lab.api.main import create_app
    import memory_lab.reasoning.service as service

    app = create_app()

    def override():
        return AuthContext(
            auth_subject_id=SUBJECT,
            subject_type="user",
            workspace_id=WS,
            role="owner",
            auth_method="test",
        )

    def fake_build_context_pack_for_request(**kwargs):
        return _pack(query=kwargs["request"].query)

    app.dependency_overrides[require_permission("retrieval.search")] = override
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if not dependant:
            continue
        for dep in getattr(dependant, "dependencies", []):
            call = getattr(dep, "call", None)
            if getattr(call, "__name__", "") == "_dependency" and getattr(call, "__closure__", None):
                closure_values = [cell.cell_contents for cell in call.__closure__]
                if "retrieval.search" in closure_values:
                    app.dependency_overrides[call] = override

    monkeypatch.setattr(service, "build_context_pack_for_request", fake_build_context_pack_for_request)
    if backend is not None:
        monkeypatch.setattr(service, "get_reasoning_llm_backend", lambda: backend)
    return TestClient(app)


def test_answer_endpoint_empty_env_provider_disabled_deterministic_no_provider_call(monkeypatch):
    monkeypatch.delenv("MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED", raising=False)
    backend = FakeLLMBackend()
    r = _client(monkeypatch, backend=backend).post("/v1/reasoning/answer", json={"query": "m4 answer"})

    assert r.status_code == 200
    body = r.json()
    assert backend.summarize_calls == 0
    assert body["mode"] == "deterministic"
    assert body["provider_metadata"]["attempted"] is False
    assert body["provider_metadata"]["provider"] == "none"
    assert "fake_summary" not in body["answer_candidate"]
    assert body["evidence_refs"]


def test_answer_endpoint_env_gate_disabled_request_opt_in_still_fallback_no_provider_call(monkeypatch):
    monkeypatch.setenv("MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED", "0")
    backend = FakeLLMBackend()
    r = _client(monkeypatch, backend=backend).post(
        "/v1/reasoning/answer",
        json={"query": "m4 answer", "enable_provider_synthesis": True},
    )

    assert r.status_code == 200
    body = r.json()
    assert backend.summarize_calls == 0
    assert body["mode"] == "degraded"
    assert body["degraded_reason"] == "provider_disabled"
    assert body["provider_metadata"]["attempted"] is False
    assert body["provider_metadata"]["failure_reason"] == "provider_disabled"
    assert "fake_summary" not in body["answer_candidate"]
    assert body["evidence_refs"]


def test_answer_endpoint_env_gate_enabled_stub_provider_valid_citations(monkeypatch):
    monkeypatch.setenv("MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED", "1")
    backend = FakeLLMBackend(preset_response=LLMResponse(text="Provider wording cites ev_support", provider="fake"))
    r = _client(monkeypatch, backend=backend).post(
        "/v1/reasoning/answer",
        json={"query": "m4 answer", "enable_provider_synthesis": True},
    )

    assert r.status_code == 200
    body = r.json()
    assert backend.summarize_calls == 1
    assert body["mode"] == "provider_backed"
    assert body["provider_metadata"]["attempted"] is True
    assert body["provider_metadata"]["provider"] == "fake"
    assert body["provider_metadata"]["degraded"] is False
    assert body["answer_candidate"] == "Provider wording cites ev_support"
    assert {ref["evidence_id"] for ref in body["evidence_refs"]} >= {"ev_support"}


@pytest.mark.parametrize(
    "provider_text, rejected_fragment",
    [
        ("Provider cites ev_missing", "ev_missing"),
        ("The verdict is supported by ev_support", "verdict"),
    ],
)
def test_answer_endpoint_rejects_invented_citation_and_forbidden_terms_to_fallback(monkeypatch, provider_text, rejected_fragment):
    monkeypatch.setenv("MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED", "1")
    backend = FakeLLMBackend(preset_response=LLMResponse(text=provider_text, provider="fake"))
    r = _client(monkeypatch, backend=backend).post(
        "/v1/reasoning/answer",
        json={"query": "m4 answer", "enable_provider_synthesis": True},
    )

    assert r.status_code == 200
    body = r.json()
    assert backend.summarize_calls == 1
    assert body["mode"] == "degraded"
    assert body["degraded_reason"] == "provider_output_rejected"
    assert body["provider_metadata"]["failure_reason"] == "provider_output_rejected"
    assert rejected_fragment.lower() not in body["answer_candidate"].lower()
    assert "[ev_support]" in body["answer_candidate"]
    assert body["evidence_refs"]
