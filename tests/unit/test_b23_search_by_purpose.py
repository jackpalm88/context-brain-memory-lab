from memory_lab.retrieval.search_by_purpose import SearchByPurposeRequest, SearchPurpose, SuppliedSearchCandidate, rank_context_candidates_by_purpose

def candidate(item_id, **kw):
    defaults = dict(text="risk management context", snippet="risk management evidence snippet", purpose_text="answer risk", extraction_confidence=0.8, domain_confidence=0.7, ingestion_score=0.8)
    defaults.update(kw)
    return SuppliedSearchCandidate(item_id=item_id, **defaults)

def test_deterministic_candidate_ranking_and_input_order_stability():
    strong = candidate("a", knn_score=0.9, tags=("risk",), source_metadata={"url": "public"})
    weak = candidate("b", snippet="", text="", extraction_confidence=0.1, ingestion_score=0.1)
    assert [r.item_id for r in rank_context_candidates_by_purpose(SearchByPurposeRequest("risk management", SearchPurpose.ANSWER, (weak, strong))).results] == ["a", "b"]
    assert [r.item_id for r in rank_context_candidates_by_purpose(SearchByPurposeRequest("risk management", SearchPurpose.ANSWER, (strong, weak))).results] == ["a", "b"]

def test_purpose_specific_weighting_differs():
    meta = candidate("cite", source_metadata={"url": "https://example.test"}, knn_score=0.2, ingestion_score=0.2)
    semantic = candidate("answer", source_metadata={}, knn_score=1.0, ingestion_score=1.0)
    assert rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", "answer", (meta, semantic))).results[0].item_id == "answer"
    assert rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", "cite", (meta, semantic))).results[0].item_id == "cite"

def test_all_allowed_purposes_return_results_and_reasons():
    for purpose in ["answer", "cite", "summarize", "compare", "recall", "decide"]:
        response = rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", purpose, (candidate("x", tags=("risk",), hub_signal=0.6, tag_signal=0.7),)))
        assert response.results and f"purpose={purpose}" in response.results[0].reason

def test_unknown_purpose_degrades_with_warning():
    response = rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", "teach", (candidate("x"),)))
    assert response.warnings == ("unknown_purpose_degraded:teach",)

def test_missing_signals_and_missing_text_degrade_safely():
    result = rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", "answer", (SuppliedSearchCandidate(item_id="empty"),))).results[0]
    assert result.score >= 0 and "missing_snippet_or_text" in result.limitations

def test_knn_score_influences_only_when_present_and_ready():
    response = rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", "answer", (candidate("not_ready", knn_score=1.0, knn_ready=False), candidate("ready", knn_score=1.0, knn_ready=True))))
    assert response.results[0].item_id == "ready"
    assert "knn_not_ready" in response.results[1].limitations

def test_open_circuit_lowers_score_and_adds_limitation():
    response = rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", "decide", (candidate("open", circuit_state="open"), candidate("closed", circuit_state="closed"))))
    assert response.results[0].item_id == "closed"
    assert "circuit_state_open" in response.results[1].limitations

def test_no_live_or_private_parity_claim():
    response = rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", "answer", (candidate("x"),)))
    assert "no_live_search" in response.non_claims
    assert "no_private_context_brain_parity" in response.non_claims
