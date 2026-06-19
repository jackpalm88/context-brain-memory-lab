"""B24 bounded supplied-input wrapper functions.

Deterministic contract-wrapper surface over caller-supplied payloads only. No
live lookup, service call, API wiring, durable mutation, model call, embedding
work, or vector-store integration is performed.
"""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Sequence
from memory_lab.governance.circuit_breaker import CircuitBreakerConfig, CircuitBreakerEvent, evaluate_circuit_state
from memory_lab.ingestion.ingestion_scoring import IngestionSignalInput, score_ingestion_signals
from memory_lab.reasoning.ingestion_prompt_flow import SuppliedTextPromptFlowRequest, build_prompt_package_from_supplied_text, build_prompt_request_from_supplied_text
from memory_lab.reasoning.prompt_package import PromptPackageRequest, build_prompt_package
from memory_lab.reasoning.structured_validation import validate_structured_response
from memory_lab.retrieval.context_candidates import ContextCandidateBuildRequest, build_context_candidates
from memory_lab.retrieval.search_by_purpose import SearchByPurposeRequest, SuppliedSearchCandidate, rank_context_candidates_by_purpose
from memory_lab.wrappers.metadata import TOOL_NAMES, attach_metadata

def validate_supplied_structured_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    response = payload.get("response", {}) if isinstance(payload, Mapping) else {}
    evidence_count = _int(payload.get("evidence_count"), 0) if isinstance(payload, Mapping) else 0
    result = validate_structured_response(response=response, evidence_count=evidence_count)
    degraded_reason = None if result.valid else "supplied_response_failed_structural_validation"
    return attach_metadata({"tool_name":"validate_supplied_structured_response","valid":result.valid,"status":result.status,"flags":list(result.flags),"errors":list(result.errors),"warnings":list(result.warnings),"sanitized":dict(result.sanitized),"quality_score":result.quality_score,"mode":result.mode,"non_claims":list(result.non_claims),"quality":_to_plain(result.quality)}, "validate_supplied_structured_response", degraded_reason)

def score_supplied_ingestion_signals(payload: Mapping[str, Any]) -> dict[str, Any]:
    payload=dict(payload or {})
    signals=IngestionSignalInput(extraction_confidence=_maybe_float(payload.get("extraction_confidence")),domain_confidence=_maybe_float(payload.get("domain_confidence")),hub_confidence=_maybe_float(payload.get("hub_confidence")),tag_confidence=_maybe_float(payload.get("tag_confidence")),chunk_quality=_maybe_float(payload.get("chunk_quality")),chunk_composite=_maybe_float(payload.get("chunk_composite")),embedding_admin_ready=_maybe_bool(payload.get("embedding_admin_ready")),knn_ready=_maybe_bool(payload.get("knn_ready")),risk_flags=_tuple_str(payload.get("risk_flags")),completeness_flags=_tuple_str(payload.get("completeness_flags")),signal_metadata=_mapping(payload.get("signal_metadata")))
    result=score_ingestion_signals(signals); degraded_reason="missing_optional_supplied_signals" if result.degraded else None
    return attach_metadata({"tool_name":"score_supplied_ingestion_signals","score":_to_plain(result.score),"rationale":result.rationale,"rule_ids":list(result.rule_ids),"limitations":list(result.limitations),"mode":result.mode,"degraded":result.degraded}, "score_supplied_ingestion_signals", degraded_reason)

def evaluate_supplied_circuit_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    payload=dict(payload or {}); config_payload=_mapping(payload.get("config")); events=tuple(_event(item) for item in _list(payload.get("events")))
    config=CircuitBreakerConfig(failure_threshold=_int(config_payload.get("failure_threshold"),3),degraded_threshold=_int(config_payload.get("degraded_threshold"),2),unavailable_threshold=_int(config_payload.get("unavailable_threshold"),1),window_seconds=_float(config_payload.get("window_seconds"),60.0),open_duration_seconds=_float(config_payload.get("open_duration_seconds"),300.0),half_open_successes_to_close=_int(config_payload.get("half_open_successes_to_close"),1))
    result=evaluate_circuit_state(events=events, now=_float(payload.get("now"),0.0), config=config, initial_state=str(payload.get("initial_state") or "closed"))
    return attach_metadata({"tool_name":"evaluate_supplied_circuit_state","state":result.state,"allow_request_recommendation":result.allow_request_recommendation,"retry_after_seconds":result.retry_after_seconds,"cooldown_remaining_seconds":result.cooldown_remaining_seconds,"failure_reason_summary":result.failure_reason_summary,"rationale":result.rationale,"limitations":list(result.limitations),"mode":result.mode}, "evaluate_supplied_circuit_state", None)

def rank_supplied_context_candidates(payload: Mapping[str, Any]) -> dict[str, Any]:
    response=_rank_response(payload); degraded_reason="no_supplied_candidates" if not response.results else None
    return attach_metadata(_rank_payload(response,"rank_supplied_context_candidates"), "rank_supplied_context_candidates", degraded_reason)

def build_supplied_prompt_package(payload: Mapping[str, Any]) -> dict[str, Any]:
    payload=dict(payload or {}); ranked_response=_rank_response(payload)
    context_package=build_context_candidates(ContextCandidateBuildRequest(query=str(payload.get("query") or ""), ranked_candidates=ranked_response.results, max_candidates=_int(payload.get("max_candidates"),8), max_context_chars=_int(payload.get("max_context_chars"),4000), snippet_chars=_int(payload.get("snippet_chars"),600)))
    prompt_package=build_prompt_package(PromptPackageRequest(query=str(payload.get("query") or ""), purpose=str(payload.get("purpose") or ranked_response.purpose), context_package=context_package, instructions=str(payload.get("instructions") or "Answer only from the supplied evidence. If evidence is insufficient, return no_context.")))
    degraded_reason="no_supplied_evidence" if not context_package.evidence else None
    return attach_metadata({"tool_name":"build_supplied_prompt_package","ranked_candidates":_rank_payload(ranked_response,"rank_supplied_context_candidates"),"context_package":{"query":context_package.query,"evidence":[_to_plain(ref) for ref in context_package.evidence],"context_text":context_package.context_text,"total_context_chars":context_package.total_context_chars,"truncated":context_package.truncated,"limitations":list(context_package.limitations),"non_claims":list(context_package.non_claims),"scope":context_package.scope},"prompt_package":{"prompt":prompt_package.prompt,"system":prompt_package.system,"expected_schema":dict(prompt_package.expected_schema),"evidence_ids":list(prompt_package.evidence_ids),"limitations":list(prompt_package.limitations),"non_claims":list(prompt_package.non_claims),"scope":prompt_package.scope}}, "build_supplied_prompt_package", degraded_reason)

def build_supplied_text_prompt_package(payload: Mapping[str, Any]) -> dict[str, Any]:
    request, error = _b30_request(payload, "build_supplied_text_prompt_package")
    if error is not None:
        return attach_metadata(error, "build_supplied_text_prompt_package", error["degraded_reason"])
    result = build_prompt_package_from_supplied_text(request)
    degraded_reason = None if result.ok else "b30_prompt_package_failed"
    return attach_metadata(_b30_payload(result, "build_supplied_text_prompt_package"), "build_supplied_text_prompt_package", degraded_reason)

def build_supplied_text_prompt_request_shape(payload: Mapping[str, Any]) -> dict[str, Any]:
    request, error = _b30_request(payload, "build_supplied_text_prompt_request_shape")
    if error is not None:
        return attach_metadata(error, "build_supplied_text_prompt_request_shape", error["degraded_reason"])
    result = build_prompt_request_from_supplied_text(request)
    degraded_reason = None if result.ok else "b30_prompt_request_shape_failed"
    return attach_metadata(_b30_payload(result, "build_supplied_text_prompt_request_shape"), "build_supplied_text_prompt_request_shape", degraded_reason)

def selected_tool_names() -> tuple[str, ...]: return TOOL_NAMES

def _b30_request(payload: Mapping[str, Any], tool_name: str) -> tuple[SuppliedTextPromptFlowRequest | None, dict[str, Any] | None]:
    data=dict(payload or {})
    missing=tuple(name for name in ("workspace_id","content_id","text") if not str(data.get(name) or "").strip())
    if missing:
        return None, {"tool_name":tool_name,"ok":False,"status":"missing_required_fields","errors":[{"code":"missing_required_field","field":name,"message":f"{name} is required for the B30 supplied-text prompt flow wrapper"} for name in missing],"warnings":[],"limitations":["caller_supplied_text_only","contract_wrapper_only","no_backend_object_accepted","no_llm_execution","no_api_or_mcp_runtime"],"non_claims":["not_llm_execution","not_provider_backed_reasoning","not_db_backed_retrieval","not_private_context_brain_parity","not_full_context_brain_parity","not_mcp_or_gpt_actions_production_ready"],"degraded_reason":"missing_required_fields"}
    request=SuppliedTextPromptFlowRequest(workspace_id=str(data.get("workspace_id") or ""),content_id=str(data.get("content_id") or ""),text=str(data.get("text") or ""),title=str(data.get("title") or ""),source_ref=str(data["source_ref"]) if data.get("source_ref") is not None else None,metadata=_mapping(data.get("metadata")),hub_candidates=tuple(_mapping(item) for item in _list(data.get("hub_candidates"))),tag_candidates=_tuple_str(data.get("tag_candidates")),circuit_events=tuple(_mapping(item) for item in _list(data.get("circuit_events"))),circuit_now=_float(data.get("circuit_now"),0.0),backend=None,use_supplied_backend=False,persist_to_supplied_backend=False,query=str(data.get("query") or ""),purpose=str(data.get("purpose") or "answer"),instructions=str(data.get("instructions") or "Answer only from the supplied evidence. If evidence is insufficient, return no_context."),limit=_int(data.get("limit"),10),max_candidates=_int(data.get("max_candidates"),8),max_context_chars=_int(data.get("max_context_chars"),4000),snippet_chars=_int(data.get("snippet_chars"),600),max_tokens=_int(data.get("max_tokens"),512),temperature=_float(data.get("temperature"),0.0),circuit_state=str(data.get("circuit_state") or "unknown"))
    return request, None

def _b30_payload(result: Any, tool_name: str) -> dict[str, Any]:
    return {"tool_name":tool_name,"ok":bool(result.ok),"status":result.status,"request_id":result.request_id,"workspace_id":result.workspace_id,"content_id":result.content_id,"mode":result.mode,"prompt_package":_prompt_package_plain(result.prompt_package),"llm_request":_llm_request_plain(result.llm_request),"ingestion_result":{"present":result.ingestion_result is not None,"mode":getattr(result.ingestion_result,"mode",None),"ok":getattr(result.ingestion_result,"ok",None),"status":getattr(result.ingestion_result,"status",None)} if result.ingestion_result is not None else None,"persistence_record":_to_plain(result.persistence_record),"prompt_handoff":{"present":result.prompt_handoff is not None,"mode":getattr(result.prompt_handoff,"mode",None),"ok":getattr(result.prompt_handoff,"ok",None),"status":getattr(result.prompt_handoff,"status",None)} if result.prompt_handoff is not None else None,"errors":[_to_plain(error) for error in result.errors],"warnings":list(result.warnings),"limitations":list(result.limitations),"non_claims":list(result.non_claims)}

def _prompt_package_plain(package: Any) -> dict[str, Any] | None:
    if package is None: return None
    return {"prompt":package.prompt,"system":package.system,"expected_schema":dict(package.expected_schema),"evidence_ids":list(package.evidence_ids),"limitations":list(package.limitations),"non_claims":list(package.non_claims),"scope":package.scope}

def _llm_request_plain(request: Any) -> dict[str, Any] | None:
    if request is None: return None
    metadata=_mapping(getattr(request,"metadata",{}))
    return {"prompt":request.prompt,"system":request.system,"expected_schema":dict(request.expected_schema or {}),"evidence_count":request.evidence_count,"max_tokens":request.max_tokens,"temperature":request.temperature,"circuit_state":request.circuit_state,"live_mode_enabled":request.live_mode_enabled,"backend_name":request.backend_name,"allow_fake_backend":request.allow_fake_backend,"limitations":list(metadata.get("limitations", ())),"non_claims":list(metadata.get("non_claims", ())),"mode":metadata.get("mode")}

def _rank_response(payload: Mapping[str, Any]):
    payload=dict(payload or {}); candidates=tuple(_candidate(item) for item in _list(payload.get("candidates")))
    return rank_context_candidates_by_purpose(SearchByPurposeRequest(query=str(payload.get("query") or ""), purpose=str(payload.get("purpose") or "answer"), candidates=candidates, limit=_int(payload.get("limit"),10)))
def _rank_payload(response: Any, tool_name: str) -> dict[str, Any]:
    return {"tool_name":tool_name,"query":response.query,"purpose":response.purpose,"results":[_ranked_plain(item) for item in response.results],"warnings":list(response.warnings),"non_claims":list(response.non_claims),"scope":response.scope}
def _ranked_plain(item: Any) -> dict[str, Any]:
    return {"item_id":item.item_id,"rank":item.rank,"score":item.score,"score_components":dict(item.score_components),"reason":item.reason,"limitations":list(item.limitations),"matched_terms":list(item.matched_terms),"purpose":item.purpose,"candidate":_to_plain(item.candidate)}
def _candidate(item: Any) -> SuppliedSearchCandidate:
    data=_mapping(item)
    return SuppliedSearchCandidate(item_id=str(data.get("item_id") or "supplied-item"),text=str(data.get("text") or ""),snippet=str(data.get("snippet") or ""),purpose_text=str(data.get("purpose_text") or ""),domain=str(data["domain"]) if data.get("domain") is not None else None,tags=_tuple_str(data.get("tags")),source_metadata=_mapping(data.get("source_metadata")),extraction_confidence=_maybe_float(data.get("extraction_confidence")),domain_confidence=_maybe_float(data.get("domain_confidence")),hub_signal=_maybe_float(data.get("hub_signal")),tag_signal=_maybe_float(data.get("tag_signal")),knn_score=_maybe_float(data.get("knn_score")),knn_ready=_maybe_bool(data.get("knn_ready")),ingestion_score=_maybe_float(data.get("ingestion_score")),tier=str(data["tier"]) if data.get("tier") is not None else None,circuit_state=str(data["circuit_state"]) if data.get("circuit_state") is not None else None,executor_limitations=_tuple_str(data.get("executor_limitations")),validator_limitations=_tuple_str(data.get("validator_limitations")),risk_level=str(data["risk_level"]) if data.get("risk_level") is not None else None,recency_rank=_maybe_float(data.get("recency_rank")))
def _event(item: Any) -> CircuitBreakerEvent:
    data=_mapping(item); return CircuitBreakerEvent(event_type=str(data.get("event_type") or "success"), timestamp=_float(data.get("timestamp"),0.0), reason=str(data.get("reason") or ""))
def _to_plain(value: Any) -> Any:
    if value is None: return None
    if is_dataclass(value): return _to_plain(asdict(value))
    if isinstance(value, Mapping): return {str(k):_to_plain(v) for k,v in value.items()}
    if isinstance(value, tuple): return [_to_plain(v) for v in value]
    if isinstance(value, list): return [_to_plain(v) for v in value]
    return value
def _mapping(value: Any) -> dict[str, Any]: return dict(value) if isinstance(value, Mapping) else {}
def _list(value: Any) -> list[Any]: return list(value) if isinstance(value, Sequence) and not isinstance(value,(str,bytes,bytearray)) else []
def _tuple_str(value: Any) -> tuple[str, ...]: return tuple(str(item) for item in _list(value) if str(item).strip())
def _maybe_float(value: Any) -> float | None:
    if value is None: return None
    try: return float(value)
    except (TypeError, ValueError): return None
def _float(value: Any, default: float) -> float:
    parsed=_maybe_float(value); return default if parsed is None else parsed
def _int(value: Any, default: int) -> int:
    try: return int(value)
    except (TypeError, ValueError): return default
def _maybe_bool(value: Any) -> bool | None:
    if value is None: return None
    if isinstance(value,bool): return value
    if isinstance(value,str):
        lowered=value.strip().lower()
        if lowered in {"true","1","yes"}: return True
        if lowered in {"false","0","no"}: return False
    return None
