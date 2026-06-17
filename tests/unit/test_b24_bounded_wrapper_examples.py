import json
from memory_lab.wrappers.examples import sample_payloads, sample_responses
from memory_lab.wrappers.metadata import TOOL_NAMES
NO_SECRET_MARKERS=("sk-","api_key","password","http://","https://","postgres://","conting.superagents","213.199.")

def test_examples_are_valid_and_deterministic():
    assert set(sample_payloads()) == set(TOOL_NAMES)
    first=sample_responses(); second=sample_responses()
    assert first == second
    assert set(first) == set(TOOL_NAMES)

def test_examples_have_no_credentials_private_urls_and_include_non_claims():
    text=json.dumps({"payloads":sample_payloads(),"responses":sample_responses()}).lower()
    for marker in NO_SECRET_MARKERS:
        assert marker.lower() not in text
    for response in sample_responses().values():
        meta=response["capability_metadata"]
        assert "not_full_context_brain_readiness" in meta["non_claims"]
        assert "no_provider_call" in meta["limitations"]
