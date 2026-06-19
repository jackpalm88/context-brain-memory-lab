"""Static B24 sample schemas for bounded wrapper contracts."""
from __future__ import annotations
from typing import Any
from memory_lab.wrappers.metadata import TOOL_NAMES, capability_metadata

def capability_metadata_schema() -> dict[str, Any]:
    return {"type":"object","required":["capability","mode","input_scope","live_backend_used","requires_provider","requires_db","requires_private_context_brain","uses_embeddings","uses_vector_db","mutates_state","executes_llm","production_runtime","api_runtime","mcp_runtime","limitations","non_claims","degraded_reason"],"properties":{"capability":{"type":"string"},"mode":{"const":"deterministic_public_safe_supplied_input_only"},"input_scope":{"const":"caller_supplied_payload_only"},"live_backend_used":{"const":False},"requires_provider":{"const":False},"requires_db":{"const":False},"requires_private_context_brain":{"const":False},"uses_embeddings":{"const":False},"uses_vector_db":{"const":False},"mutates_state":{"const":False},"executes_llm":{"const":False},"production_runtime":{"const":False},"api_runtime":{"const":False},"mcp_runtime":{"const":False},"limitations":{"type":"array","items":{"type":"string"}},"non_claims":{"type":"array","items":{"type":"string"}},"degraded_reason":{"type":["string","null"]}}}

def wrapper_input_schemas() -> dict[str, dict[str, Any]]:
    candidate={"type":"object","required":["item_id"],"properties":{"item_id":{"type":"string"},"text":{"type":"string"},"snippet":{"type":"string"},"purpose_text":{"type":"string"},"domain":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}},"source_metadata":{"type":"object"},"extraction_confidence":{"type":"number"},"domain_confidence":{"type":"number"},"hub_signal":{"type":"number"},"tag_signal":{"type":"number"},"knn_score":{"type":"number"},"knn_ready":{"type":"boolean"},"ingestion_score":{"type":"number"},"tier":{"type":"string"},"circuit_state":{"type":"string"},"executor_limitations":{"type":"array","items":{"type":"string"}},"validator_limitations":{"type":"array","items":{"type":"string"}},"risk_level":{"type":"string"},"recency_rank":{"type":"number"}}}
    return {
      "validate_supplied_structured_response":{"type":"object","required":["response"],"properties":{"response":{"type":["object","string"]},"evidence_count":{"type":"integer"}}},
      "score_supplied_ingestion_signals":{"type":"object","properties":{"extraction_confidence":{"type":"number"},"domain_confidence":{"type":"number"},"hub_confidence":{"type":"number"},"tag_confidence":{"type":"number"},"chunk_quality":{"type":"number"},"chunk_composite":{"type":"number"},"embedding_admin_ready":{"type":"boolean"},"knn_ready":{"type":"boolean"},"risk_flags":{"type":"array","items":{"type":"string"}},"completeness_flags":{"type":"array","items":{"type":"string"}},"signal_metadata":{"type":"object"}}},
      "evaluate_supplied_circuit_state":{"type":"object","required":["events","now"],"properties":{"events":{"type":"array","items":{"type":"object"}},"now":{"type":"number"},"initial_state":{"type":"string"},"config":{"type":"object"}}},
      "rank_supplied_context_candidates":{"type":"object","required":["query","purpose","candidates"],"properties":{"query":{"type":"string"},"purpose":{"type":"string"},"candidates":{"type":"array","items":candidate},"limit":{"type":"integer"}}},
      "build_supplied_prompt_package":{"type":"object","required":["query","purpose","candidates"],"properties":{"query":{"type":"string"},"purpose":{"type":"string"},"candidates":{"type":"array","items":candidate},"limit":{"type":"integer"},"max_candidates":{"type":"integer"},"max_context_chars":{"type":"integer"},"snippet_chars":{"type":"integer"},"instructions":{"type":"string"}}},
      "build_supplied_text_prompt_package":_b30_prompt_flow_input_schema(),
      "build_supplied_text_prompt_request_shape":_b30_prompt_flow_input_schema(),
    }

def _b30_prompt_flow_input_schema() -> dict[str, Any]:
    return {"type":"object","required":["workspace_id","content_id","text"],"properties":{"workspace_id":{"type":"string"},"content_id":{"type":"string"},"text":{"type":"string"},"title":{"type":"string"},"source_ref":{"type":["string","null"]},"metadata":{"type":"object"},"hub_candidates":{"type":"array","items":{"type":"object"}},"tag_candidates":{"type":"array","items":{"type":"string"}},"circuit_events":{"type":"array","items":{"type":"object"}},"circuit_now":{"type":"number"},"query":{"type":"string"},"purpose":{"type":"string"},"instructions":{"type":"string"},"limit":{"type":"integer"},"max_candidates":{"type":"integer"},"max_context_chars":{"type":"integer"},"snippet_chars":{"type":"integer"},"max_tokens":{"type":"integer"},"temperature":{"type":"number"},"circuit_state":{"type":"string"}},"additionalProperties":False,"description":"B31 contract-only supplied text to B30 prompt flow wrapper; no backend object, provider call, DB, API runtime, MCP runtime, or deployment."}

def wrapper_output_schema(tool_name: str) -> dict[str, Any]:
    return {"type":"object","required":["tool_name","capability_metadata"],"properties":{"tool_name":{"const":tool_name},"capability_metadata":capability_metadata_schema()}}

def all_wrapper_schemas() -> dict[str, dict[str, Any]]:
    inputs=wrapper_input_schemas()
    return {name:{"input_schema":inputs[name],"output_schema":wrapper_output_schema(name),"capability_metadata":capability_metadata(name)} for name in TOOL_NAMES}
