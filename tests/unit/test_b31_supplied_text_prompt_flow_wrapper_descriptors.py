import json

from memory_lab.wrappers.descriptors import all_descriptors, gpt_actions_openapi_style_descriptor, mcp_style_descriptors


B31_TOOLS = {"build_supplied_text_prompt_package", "build_supplied_text_prompt_request_shape"}
FORBIDDEN_DESCRIPTOR_CLAIMS = (
    "server url",
    "authorization",
    "bearer",
    "production mcp ready",
    "production gpt actions ready",
    "private context brain parity",
    "full context brain ready",
    "live memory retrieval",
    "provider-backed reasoning",
    "db-backed retrieval",
    "deployed server",
)


def test_b31_mcp_descriptors_expose_b30_wrappers_as_static_contracts_only():
    descriptors = {item["name"]: item for item in mcp_style_descriptors()}

    assert B31_TOOLS.issubset(descriptors)
    for name in B31_TOOLS:
        descriptor = descriptors[name]
        text = json.dumps(descriptor).lower()
        assert "not deployed" in text
        assert "caller-supplied input only" in text
        assert "no live backend" in text
        assert descriptor["descriptor_scope"] == "static_contract_descriptor_only_not_deployed_no_live_backend"
        assert descriptor["capability_metadata"]["requires_provider"] is False
        assert descriptor["capability_metadata"]["requires_db"] is False
        assert descriptor["capability_metadata"]["mcp_runtime"] is False


def test_b31_openapi_style_descriptor_has_no_server_auth_or_runtime_claim():
    descriptor = gpt_actions_openapi_style_descriptor()
    text = json.dumps(descriptor).lower()

    assert "servers" not in descriptor
    assert all(name in text for name in B31_TOOLS)
    assert "no_server_url_no_auth_block" in text
    for claim in FORBIDDEN_DESCRIPTOR_CLAIMS:
        assert claim not in text


def test_b31_all_descriptors_serialize_without_private_runtime_claims():
    text = json.dumps(all_descriptors()).lower()

    for claim in FORBIDDEN_DESCRIPTOR_CLAIMS:
        assert claim not in text
