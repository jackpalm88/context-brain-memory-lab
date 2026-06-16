from memory_lab.reasoning.llm_executor import LLMExecutionRequest
from memory_lab.reasoning.prompt_package import PromptPackageRequest, build_prompt_package
from memory_lab.reasoning.structured_validation import validate_structured_response
from memory_lab.retrieval.context_candidates import ContextCandidateBuildRequest, build_context_candidates
from memory_lab.retrieval.search_by_purpose import SearchByPurposeRequest, SuppliedSearchCandidate, rank_context_candidates_by_purpose

def package():
    supplied = SuppliedSearchCandidate(item_id="a", snippet="public supplied evidence for risk", source_metadata={"url": "public"}, ingestion_score=0.9)
    ranked = rank_context_candidates_by_purpose(SearchByPurposeRequest("risk", "answer", (supplied,))).results
    context = build_context_candidates(ContextCandidateBuildRequest("risk", ranked))
    return build_prompt_package(PromptPackageRequest("risk", "answer", context))

def test_prompt_package_contains_only_supplied_records():
    pkg = package()
    assert "public supplied evidence for risk" in pkg.prompt
    assert "content_items" not in pkg.prompt
    assert "private prompt" not in pkg.prompt.lower()

def test_compatible_with_b22_llm_execution_request_fields():
    pkg = package()
    req = LLMExecutionRequest(prompt=pkg.prompt, system=pkg.system, expected_schema=pkg.expected_schema)
    assert req.prompt == pkg.prompt and req.system == pkg.system and req.expected_schema == pkg.expected_schema

def test_expected_schema_is_accepted_by_b22_structural_validator_shape():
    pkg = package()
    result = validate_structured_response({"status": "ok", "answer": "Uses supplied evidence.", "confidence": 0.8, "claims": [{"claim": "Risk evidence exists.", "evidence_ids": [1]}]}, evidence_count=len(pkg.evidence_ids))
    assert result.valid is True
    assert "claims" in pkg.expected_schema["required"]

def test_includes_non_claims_limitations_and_no_live_execution():
    pkg = package()
    assert "no_live_llm_execution" in pkg.non_claims
    assert "no_provider_call" in pkg.non_claims
    assert "supplied_context_only" in pkg.limitations
    assert "Do not claim private Context Brain parity" in pkg.system
