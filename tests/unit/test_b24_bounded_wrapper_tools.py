from memory_lab.wrappers.bounded_tools import build_supplied_prompt_package, evaluate_supplied_circuit_state, rank_supplied_context_candidates, score_supplied_ingestion_signals, validate_supplied_structured_response
from memory_lab.wrappers.examples import sample_payloads

MANDATORY_FALSE_FIELDS=("live_backend_used","requires_provider","requires_db","requires_private_context_brain","uses_embeddings","uses_vector_db","mutates_state")
REQUIRED_LIMITATIONS=("caller_supplied_input_only","no_live_backend","no_db_access","no_private_context_brain_access","no_provider_call","no_embeddings_generated","no_vector_db_query","no_stored_content_fetch","not_a_production_deployment")
REQUIRED_NON_CLAIMS=("not_production_mcp_readiness","not_gpt_actions_production_readiness","not_full_context_brain_readiness","not_private_context_brain_parity","not_live_memory_retrieval","not_live_semantic_search","not_provider_backed_intelligence","not_semantic_truth_validation","not_production_dlp","not_auth_or_secrets_layer")
def assert_metadata(result, capability):
    meta=result["capability_metadata"]
    assert meta["capability"] == capability
    assert meta["mode"] == "deterministic_public_safe_supplied_input_only"
    assert meta["input_scope"] == "caller_supplied_payload_only"
    for field in MANDATORY_FALSE_FIELDS:
        assert meta[field] is False
    for value in REQUIRED_LIMITATIONS:
        assert value in meta["limitations"]
    for value in REQUIRED_NON_CLAIMS:
        assert value in meta["non_claims"]

def test_all_five_tools_execute_deterministically_with_metadata():
    payloads=sample_payloads()
    tools={"validate_supplied_structured_response":validate_supplied_structured_response,"score_supplied_ingestion_signals":score_supplied_ingestion_signals,"evaluate_supplied_circuit_state":evaluate_supplied_circuit_state,"rank_supplied_context_candidates":rank_supplied_context_candidates,"build_supplied_prompt_package":build_supplied_prompt_package}
    for name, tool in tools.items():
        first=tool(payloads[name]); second=tool(payloads[name])
        assert first == second
        assert first["tool_name"] == name
        assert_metadata(first, name)

def test_expected_shapes_and_degraded_honesty():
    assert validate_supplied_structured_response({"response":"not-json"})["capability_metadata"]["degraded_reason"]
    assert score_supplied_ingestion_signals({})["degraded"] is True
    assert rank_supplied_context_candidates({"query":"x","purpose":"answer","candidates":[]})["capability_metadata"]["degraded_reason"] == "no_supplied_candidates"
    prompt=build_supplied_prompt_package(sample_payloads()["build_supplied_prompt_package"])
    assert "prompt_package" in prompt and "context_package" in prompt
    assert prompt["prompt_package"]["evidence_ids"] == [1]
    circuit=evaluate_supplied_circuit_state({"events":[{"event_type":"failure","timestamp":1},{"event_type":"failure","timestamp":2},{"event_type":"failure","timestamp":3}],"now":4})
    assert circuit["state"] == "open"
