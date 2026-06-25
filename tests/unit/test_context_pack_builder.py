import pytest

from memory_lab.context_packs.builder import build_context_pack
from memory_lab.context_packs.models import ContextPackBuildRequest
from memory_lab.reasoning.models import EvidenceItem

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

WS = "00000000-0000-0000-0000-000000000901"


def _req(**kwargs):
    base = {"query": "b12 context pack", "limit": 10}
    base.update(kwargs)
    return ContextPackBuildRequest(**base)


def _evidence(content_id, *, chunk_id=None, rank=1, score=0.9, text="support text", memory_type="decision"):
    return {
        "evidence_id": f"ev_{content_id}_{chunk_id or 'c'}",
        "rank": rank,
        "content_id": content_id,
        "chunk_id": chunk_id,
        "snippet": text,
        "score": score,
        "score_kind": "chunk_text_match",
        "memory_type": memory_type,
    }


def test_support_only_pack():
    pack = build_context_pack(workspace_id=WS, request=_req(), supporting_evidence=[_evidence("c2")])
    assert pack.workspace_id == WS
    assert len(pack.supporting_evidence) == 1
    assert pack.current_state_signals == []
    assert pack.conflict_candidates == []
    assert pack.summary_metadata.truth_arbitration is False
    assert pack.summary_metadata.provider_backed_reasoning is False
    assert "context_pack_is_not_answer" in pack.warnings
    assert "no_truth_arbitration" in pack.non_claims


def test_pack_with_current_state_signal():
    rows = [
        _evidence("current", text="new", rank=2) | {"is_current": True, "current_state_scope": "b12"},
        _evidence("stale", text="old", rank=1) | {"is_current": False, "current_state_scope": "b12", "cs_supersedes_content_id": "current"},
    ]
    pack = build_context_pack(workspace_id=WS, request=_req(scope="b12"), current_state_rows=rows)
    assert [e.content_id for e in pack.current_state_signals] == ["current"]
    assert [e.content_id for e in pack.stale_or_superseded_items] == ["stale"]


def test_pack_with_counterfinding_conflict_candidate():
    conflict = {
        "candidate_id": "cc_1",
        "workspace_id": WS,
        "conflict_type": "explicit_counterfinding",
        "scope": "b12",
        "status": "unresolved",
        "severity": "high",
        "confidence": 0.9,
        "evidence": [
            _evidence("finding", text="finding") | {"role": "finding"},
            _evidence("counter", text="counterfinding") | {"role": "counterfinding", "classify_confidence": 0.8},
        ],
        "detection_rule": "explicit_marker",
    }
    pack = build_context_pack(workspace_id=WS, request=_req(scope="b12"), conflict_candidates=[conflict])
    assert pack.conflict_candidates[0]["conflict_type"] == "explicit_counterfinding"
    assert pack.conflict_candidates[0]["conflict_id"] == "cc_1"
    assert [e.content_id for e in pack.counterfindings] == ["counter"]


def test_deterministic_context_pack_id():
    req = _req(memory_types=["decision", "evidence"])
    a = [_evidence("a", rank=2), _evidence("b", rank=1)]
    b = list(reversed(a))
    pack_a = build_context_pack(workspace_id=WS, request=req, supporting_evidence=a)
    pack_b = build_context_pack(workspace_id=WS, request=req, supporting_evidence=b)
    assert pack_a.context_pack_id == pack_b.context_pack_id


def test_deterministic_ordering():
    pack = build_context_pack(
        workspace_id=WS,
        request=_req(),
        supporting_evidence=[
            _evidence("b", chunk_id="2", rank=2, score=0.7),
            _evidence("a", chunk_id="1", rank=1, score=0.6),
            _evidence("c", chunk_id="3", rank=1, score=0.9),
        ],
        conflict_candidates=[
            {"candidate_id": "low", "severity": "low", "confidence": 0.9, "conflict_type": "explicit_contradiction", "evidence": []},
            {"candidate_id": "high", "severity": "high", "confidence": 0.5, "conflict_type": "explicit_counterfinding", "evidence": []},
        ],
    )
    assert [e.content_id for e in pack.supporting_evidence] == ["c", "a", "b"]
    assert [c["conflict_id"] for c in pack.conflict_candidates] == ["high", "low"]


def test_warning_and_non_claim_constants():
    pack1 = build_context_pack(workspace_id=WS, request=_req())
    pack2 = build_context_pack(workspace_id=WS, request=_req(query="other"))
    assert pack1.warnings == pack2.warnings
    assert pack1.non_claims == pack2.non_claims


def test_no_truth_arbitration_fields():
    payload = build_context_pack(workspace_id=WS, request=_req()).model_dump()
    forbidden = {"answer", "verdict", "resolution", "truth", "winner", "resolved_answer"}
    assert forbidden.isdisjoint(payload.keys())


def test_supporting_evidence_preserves_retrieval_provenance_metadata():
    evidence = EvidenceItem(
        evidence_id="ev_prov_chunk",
        rank=1,
        content_id="prov",
        chunk_id="chunk",
        snippet="provenance support text",
        score=0.88,
        score_kind="vector_similarity",
        retrieval_path="pgvector_knn",
        metadata={
            "retrieval_mode": "pgvector_knn",
            "embedding_status": "ok",
            "distance": 0.42,
        },
    )

    pack = build_context_pack(workspace_id=WS, request=_req(), supporting_evidence=[evidence])
    ref = pack.supporting_evidence[0]

    assert ref.source == "pgvector_knn"
    assert ref.metadata["retrieval_mode"] == "pgvector_knn"
    assert ref.metadata["retrieval_path"] == "pgvector_knn"
    assert ref.metadata["embedding_status"] == "ok"
    assert ref.metadata["distance"] == 0.42
    assert ref.metadata["score_kind"] == "vector_similarity"
