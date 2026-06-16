from memory_lab.retrieval.context_candidates import ContextCandidateBuildRequest, build_context_candidates
from memory_lab.retrieval.search_by_purpose import SearchByPurposeRequest, SuppliedSearchCandidate, rank_context_candidates_by_purpose

def ranked():
    c1 = SuppliedSearchCandidate(item_id="a", snippet="alpha supplied text", source_metadata={"url": "public-a"}, ingestion_score=0.9)
    c2 = SuppliedSearchCandidate(item_id="a", snippet="duplicate lower", ingestion_score=0.1)
    c3 = SuppliedSearchCandidate(item_id="b", snippet="bravo supplied text" * 50, source_metadata={"url": "public-b"}, ingestion_score=0.8)
    return rank_context_candidates_by_purpose(SearchByPurposeRequest("alpha bravo", "answer", (c2, c3, c1))).results

def test_stable_evidence_ids_and_dedupe():
    p1 = build_context_candidates(ContextCandidateBuildRequest("alpha bravo", ranked()))
    p2 = build_context_candidates(ContextCandidateBuildRequest("alpha bravo", ranked()))
    assert [r.item_id for r in p1.evidence] == ["a", "b"]
    assert [r.evidence_key for r in p1.evidence] == [r.evidence_key for r in p2.evidence]
    assert [r.evidence_id for r in p1.evidence] == [1, 2]

def test_source_metadata_preserved_from_supplied_records_only():
    p = build_context_candidates(ContextCandidateBuildRequest("alpha bravo", ranked()))
    assert p.evidence[0].source_metadata == {"url": "public-a"}
    assert p.evidence[1].source_metadata == {"url": "public-b"}

def test_budget_and_truncation_are_deterministic():
    p = build_context_candidates(ContextCandidateBuildRequest("alpha bravo", ranked(), max_context_chars=120, snippet_chars=40))
    assert p.total_context_chars <= 120 and p.truncated is True
    assert any("context_budget" in item for item in p.limitations)

def test_output_contains_only_supplied_candidate_content():
    p = build_context_candidates(ContextCandidateBuildRequest("alpha bravo", ranked(), snippet_chars=30))
    assert "alpha supplied text" in p.context_text
    assert "content_items" not in p.context_text
    assert "private" not in p.context_text.lower()

def test_limitations_and_non_claims_included():
    results = rank_context_candidates_by_purpose(SearchByPurposeRequest("none", "answer", (SuppliedSearchCandidate(item_id="empty"),))).results
    p = build_context_candidates(ContextCandidateBuildRequest("none", results))
    assert "missing_snippet_or_text" in p.limitations
    assert "no_private_memory_retrieval" in p.non_claims
