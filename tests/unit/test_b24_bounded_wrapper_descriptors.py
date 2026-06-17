import json
from memory_lab.wrappers.descriptors import all_descriptors, gpt_actions_openapi_style_descriptor, mcp_style_descriptors
from memory_lab.wrappers.metadata import TOOL_NAMES
FORBIDDEN_NAMES=("search_memory","ask_context_brain","retrieve_context","semantic_search","query_private_memory","live_context_search","mcp_search_private_cb","private_context_search","context_brain_search","memory_retrieval","provider_semantic_search")
FORBIDDEN_PHRASES=("production MCP ready","production GPT Actions ready","Full Context Brain ready","private Context Brain parity","live memory retrieval","live semantic search","queries your memory","searches Context Brain","provider-backed reasoning","real semantic extraction","DB-backed retrieval","vector search","embeddings generated","production DLP","auth-ready production deployment")

def test_descriptor_list_exactly_selected_five_and_has_schemas_metadata():
    descriptors=mcp_style_descriptors()
    assert [d["name"] for d in descriptors] == list(TOOL_NAMES)
    for d in descriptors:
        assert "input_schema" in d and "output_schema" in d and "capability_metadata" in d
        text=json.dumps(d)
        assert "not deployed" in text and "no live backend" in text and "caller-supplied input only" in text

def test_gpt_actions_descriptor_is_contract_only_no_server_or_auth():
    descriptor=gpt_actions_openapi_style_descriptor()
    assert "servers" not in descriptor
    text=json.dumps(descriptor).lower()
    assert "securityschemes" not in text and "authorization" not in text and "bearer" not in text
    assert "no_server_url_no_auth_block" in text
    assert all(name in text for name in TOOL_NAMES)

def test_descriptors_avoid_forbidden_operation_names_and_misleading_phrases():
    text=json.dumps(all_descriptors())
    lowered=text.lower()
    for name in FORBIDDEN_NAMES:
        assert (chr(34) + "operationid" + chr(34) + ": " + chr(34) + name.lower()) not in lowered
        assert (chr(34) + "name" + chr(34) + ": " + chr(34) + name.lower()) not in lowered
    for phrase in FORBIDDEN_PHRASES:
        assert phrase.lower() not in lowered
