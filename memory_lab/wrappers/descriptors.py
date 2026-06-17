"""Static B24 descriptor contracts for bounded wrappers.

Descriptors are contract metadata and sample schema only: not deployed, no
server URL, no auth block, caller-supplied input only, no live backend.
"""
from __future__ import annotations
from typing import Any
from memory_lab.wrappers.metadata import TOOL_NAMES, capability_metadata
from memory_lab.wrappers.schemas import all_wrapper_schemas
_DESCRIPTION_BY_TOOL={
"validate_supplied_structured_response":"contract descriptor; sample schema; not deployed; caller-supplied input only; no live backend; structural validation adapter",
"score_supplied_ingestion_signals":"contract descriptor; sample schema; not deployed; caller-supplied input only; no live backend; deterministic ingestion signal scoring adapter",
"evaluate_supplied_circuit_state":"contract descriptor; sample schema; not deployed; caller-supplied input only; no live backend; source-neutral circuit evaluation adapter",
"rank_supplied_context_candidates":"contract descriptor; sample schema; not deployed; caller-supplied input only; no live backend; deterministic ranking adapter over supplied candidates",
"build_supplied_prompt_package":"contract descriptor; sample schema; not deployed; caller-supplied input only; no live backend; provider-neutral prompt package adapter over supplied candidates",
}
def mcp_style_descriptors() -> list[dict[str, Any]]:
    schemas=all_wrapper_schemas()
    return [{"name":name,"description":_DESCRIPTION_BY_TOOL[name],"input_schema":schemas[name]["input_schema"],"output_schema":schemas[name]["output_schema"],"capability_metadata":capability_metadata(name),"descriptor_scope":"static_contract_descriptor_only_not_deployed_no_live_backend"} for name in TOOL_NAMES]
def gpt_actions_openapi_style_descriptor() -> dict[str, Any]:
    schemas=all_wrapper_schemas()
    return {"openapi":"3.1.0","info":{"title":"B24 bounded wrapper contract descriptors","version":"0.1.0b24-contract-only","description":"contract descriptor; sample schema; not deployed; caller-supplied input only; no live backend"},"paths":{f"/contract-only/{name}":{"post":{"operationId":name,"summary":_DESCRIPTION_BY_TOOL[name],"description":_DESCRIPTION_BY_TOOL[name],"requestBody":{"required":True,"content":{"application/json":{"schema":schemas[name]["input_schema"]}}},"responses":{"200":{"description":"sample schema only","content":{"application/json":{"schema":schemas[name]["output_schema"]}}}},"x-capability-metadata":capability_metadata(name)}} for name in TOOL_NAMES},"x-descriptor-scope":"static_contract_descriptor_only_not_deployed_no_live_backend_no_server_url_no_auth_block"}
def all_descriptors() -> dict[str, Any]:
    return {"mcp_style_descriptors":mcp_style_descriptors(),"gpt_actions_openapi_style_descriptor":gpt_actions_openapi_style_descriptor()}
