from memory_lab.wrappers.metadata import TOOL_NAMES, capability_metadata
from memory_lab.wrappers.schemas import all_wrapper_schemas, wrapper_input_schemas


B31_TOOLS = ("build_supplied_text_prompt_package", "build_supplied_text_prompt_request_shape")
FALSE_SCHEMA_FIELDS = (
    "live_backend_used",
    "requires_provider",
    "requires_db",
    "requires_private_context_brain",
    "uses_embeddings",
    "uses_vector_db",
    "mutates_state",
    "executes_llm",
    "production_runtime",
    "api_runtime",
    "mcp_runtime",
)


def test_b31_tool_names_include_prompt_flow_wrappers():
    for name in B31_TOOLS:
        assert name in TOOL_NAMES


def test_b31_input_schemas_require_only_supplied_text_boundary_fields():
    schemas = wrapper_input_schemas()
    for name in B31_TOOLS:
        schema = schemas[name]
        assert schema["required"] == ["workspace_id", "content_id", "text"]
        assert schema["additionalProperties"] is False
        assert "backend" not in schema["properties"]
        assert "provider" not in schema["properties"]
        assert "workspace_id" in schema["properties"]
        assert "content_id" in schema["properties"]
        assert "text" in schema["properties"]


def test_b31_output_schema_and_metadata_false_fields():
    schemas = all_wrapper_schemas()
    for name in B31_TOOLS:
        assert schemas[name]["input_schema"]["required"] == ["workspace_id", "content_id", "text"]
        meta = capability_metadata(name)
        for field in FALSE_SCHEMA_FIELDS:
            assert meta[field] is False
        output_meta_schema = schemas[name]["output_schema"]["properties"]["capability_metadata"]
        for field in FALSE_SCHEMA_FIELDS:
            assert output_meta_schema["properties"][field]["const"] is False
