"""Public-safe LLM execution contracts for B22.

This module is intentionally provider-neutral. It plans and executes only
caller-supplied fake/noop-style backends, keeps live mode disabled by default,
and treats circuit state as caller-supplied input. It does not resolve
credentials, read environment, mutate circuit state, or perform retries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

PUBLIC_SAFE_NON_CLAIMS: tuple[str, ...] = (
    "no_live_provider_call_by_default",
    "no_provider_sdk_resolution",
    "no_private_context_brain_access",
    "no_runtime_circuit_mutation",
    "no_retry_or_fallback_orchestration",
    "no_semantic_truth_judging",
)
_ALLOWED_CIRCUIT_STATES = {"closed", "open", "half_open", "unknown"}
_FAKE_BACKEND_NAMES = {"fake", "test_fake"}
_NOOP_BACKEND_NAMES = {"none", "noop", "no_provider"}

class _BackendLike(Protocol):
    provider_name: str
    is_configured: bool

@dataclass(frozen=True)
class LLMExecutionRequest:
    prompt: str
    system: str | None = None
    expected_schema: Mapping[str, Any] | None = None
    max_tokens: int = 512
    temperature: float = 0.0
    live_mode_enabled: bool = False
    allow_fake_backend: bool = False
    backend_name: str = "none"
    circuit_state: str = "unknown"
    evidence_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ProviderCapabilityStatus:
    provider: str
    configured: bool
    supports_json: bool
    supports_text: bool
    live_mode_enabled: bool
    failure_reason: str | None = None

@dataclass(frozen=True)
class LLMExecutionPlan:
    should_execute: bool
    backend_name: str
    mode: str
    blocked_reason: str | None
    rationale: str
    limitations: tuple[str, ...]
    uses_live_provider: bool
    requires_provider_config: bool
    circuit_state: str

@dataclass(frozen=True)
class LLMExecutionResult:
    status: str
    text: str
    json_data: Mapping[str, Any] | None
    provider: str
    model: str | None
    degraded: bool
    failure_reason: str | None
    plan: LLMExecutionPlan
    validation_flags: tuple[str, ...]
    mode: str
    non_claims: tuple[str, ...] = PUBLIC_SAFE_NON_CLAIMS

@dataclass(frozen=True)
class _BackendRequest:
    prompt: str
    system: str | None = None
    max_tokens: int = 512
    temperature: float = 0.0
    timeout_s: float = 30.0
    expected_schema: Mapping[str, Any] | None = None

class PublicSafeLLMExecutor:
    """Contract-only executor for supplied fake/noop-compatible backends."""
    def capability_status(self, request: LLMExecutionRequest, backend: _BackendLike | None = None) -> ProviderCapabilityStatus:
        provider = _backend_provider_name(backend) or request.backend_name or "none"
        configured = bool(_backend_configured(backend)) if backend is not None else False
        if not request.live_mode_enabled:
            return ProviderCapabilityStatus(provider, configured, backend is not None, backend is not None, False, "live_mode_disabled")
        if provider in _NOOP_BACKEND_NAMES or not configured:
            return ProviderCapabilityStatus(provider, configured, backend is not None, backend is not None, True, "provider_not_configured")
        if provider in _FAKE_BACKEND_NAMES and request.allow_fake_backend:
            return ProviderCapabilityStatus(provider, configured, True, True, True, None)
        return ProviderCapabilityStatus(provider, configured, False, False, True, "provider_not_allowed_public_safe_scope")

    def plan(self, request: LLMExecutionRequest, backend: _BackendLike | None = None) -> LLMExecutionPlan:
        circuit_state = _normalize_circuit_state(request.circuit_state)
        backend_name = _backend_provider_name(backend) or request.backend_name or "none"
        limitations = list(PUBLIC_SAFE_NON_CLAIMS)
        if circuit_state == "open":
            return LLMExecutionPlan(False, backend_name, "blocked_circuit_open", "circuit_open", "Caller-supplied circuit state is open; public-safe execution is blocked before backend use.", tuple(limitations + ["caller_supplied_circuit_state_only"]), False, False, circuit_state)
        if not request.live_mode_enabled:
            return LLMExecutionPlan(False, backend_name, "live_mode_disabled", "live_mode_disabled", "Live mode is disabled by default; no backend call is attempted.", tuple(limitations), False, False, circuit_state)
        if circuit_state == "half_open":
            limitations.append("cautious_half_open_plan")
        capability = self.capability_status(request, backend)
        if capability.failure_reason:
            return LLMExecutionPlan(False, backend_name, "degraded", capability.failure_reason, "Backend is unavailable or outside the public-safe fake/noop execution boundary.", tuple(limitations), False, True, circuit_state)
        return LLMExecutionPlan(True, backend_name, "fake_or_noop_only", None, "Caller explicitly enabled a supplied fake backend inside public-safe test scope.", tuple(limitations), False, True, circuit_state)

    def run(self, request: LLMExecutionRequest, backend: Any | None = None) -> LLMExecutionResult:
        plan = self.plan(request, backend)
        if not plan.should_execute:
            return _blocked_result(plan)
        backend_request = _BackendRequest(request.prompt, request.system, request.max_tokens, request.temperature, 30.0, request.expected_schema)
        method_name = "complete_" + ("json" if request.expected_schema is not None else "text")
        method = getattr(backend, method_name, None)
        if method is None:
            return _blocked_result(LLMExecutionPlan(False, plan.backend_name, "degraded", "backend_method_missing", "Supplied backend does not expose the requested fake/noop-compatible method.", plan.limitations, False, True, plan.circuit_state))
        response = method(backend_request)
        failure = _failure_to_text(getattr(response, "failure_reason", None))
        degraded = bool(getattr(response, "degraded", False) or failure)
        json_data = getattr(response, "json_data", None)
        text = getattr(response, "text", "") or ""
        provider = getattr(response, "provider", None) or plan.backend_name
        status = "degraded" if degraded else "ok"
        flags = (failure,) if failure else ("complete",)
        return LLMExecutionResult(status, text, json_data, provider, getattr(response, "model", None), degraded, failure, plan, tuple(flag for flag in flags if flag), plan.mode)

def make_public_safe_llm_executor() -> PublicSafeLLMExecutor:
    return PublicSafeLLMExecutor()

def plan_llm_execution(request: LLMExecutionRequest, backend: Any | None = None) -> LLMExecutionPlan:
    return make_public_safe_llm_executor().plan(request, backend)

def execute_llm_request(request: LLMExecutionRequest, backend: Any | None = None) -> LLMExecutionResult:
    return make_public_safe_llm_executor().run(request, backend)

def _blocked_result(plan: LLMExecutionPlan) -> LLMExecutionResult:
    reason = plan.blocked_reason or "blocked"
    return LLMExecutionResult("blocked" if reason == "circuit_open" else "degraded", "", None, plan.backend_name, None, True, reason, plan, (reason,), plan.mode)

def _normalize_circuit_state(value: str | None) -> str:
    state = (value or "unknown").strip().lower().replace("-", "_")
    return state if state in _ALLOWED_CIRCUIT_STATES else "unknown"

def _backend_provider_name(backend: Any | None) -> str | None:
    if backend is None:
        return None
    value = getattr(backend, "provider_name", None)
    return str(value() if callable(value) else value) if value is not None else None

def _backend_configured(backend: Any | None) -> bool:
    if backend is None:
        return False
    value = getattr(backend, "is_configured", False)
    return bool(value() if callable(value) else value)

def _failure_to_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))
