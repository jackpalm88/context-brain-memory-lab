from memory_lab.providers.fake import FakeLLMBackend
from memory_lab.providers.noop import NoopLLMBackend
from memory_lab.reasoning.llm_executor import (
    LLMExecutionRequest,
    execute_llm_request,
    make_public_safe_llm_executor,
    plan_llm_execution,
)


def test_default_live_disabled_no_backend_call():
    result = execute_llm_request(LLMExecutionRequest(prompt="hello"), backend=FakeLLMBackend())
    assert result.degraded is True
    assert result.failure_reason == "live_mode_disabled"
    assert result.plan.should_execute is False
    assert result.plan.uses_live_provider is False
    assert "no_live_provider_call_by_default" in result.non_claims


def test_fake_backend_only_when_explicitly_enabled_with_closed_circuit():
    backend = FakeLLMBackend(preset_json={"status": "ok"})
    req = LLMExecutionRequest(
        prompt="hello",
        expected_schema={"type": "object"},
        live_mode_enabled=True,
        allow_fake_backend=True,
        backend_name="fake",
        circuit_state="closed",
    )
    result = execute_llm_request(req, backend=backend)
    assert result.status == "ok"
    assert result.json_data == {"status": "ok"}
    assert result.provider == "fake"
    assert result.plan.should_execute is True
    assert result.plan.uses_live_provider is False
    assert result.mode == "fake_or_noop_only"


def test_noop_backend_is_explicit_provider_not_configured():
    req = LLMExecutionRequest(
        prompt="hello",
        live_mode_enabled=True,
        allow_fake_backend=True,
        backend_name="none",
        circuit_state="closed",
    )
    result = execute_llm_request(req, backend=NoopLLMBackend())
    assert result.degraded is True
    assert result.failure_reason == "provider_not_configured"
    assert result.plan.blocked_reason == "provider_not_configured"


def test_circuit_open_blocks_before_fake_backend():
    req = LLMExecutionRequest(
        prompt="hello",
        live_mode_enabled=True,
        allow_fake_backend=True,
        backend_name="fake",
        circuit_state="open",
    )
    result = execute_llm_request(req, backend=FakeLLMBackend())
    assert result.status == "blocked"
    assert result.failure_reason == "circuit_open"
    assert result.plan.should_execute is False
    assert result.plan.circuit_state == "open"
    assert "caller_supplied_circuit_state_only" in result.plan.limitations


def test_half_open_produces_cautious_degraded_plan_without_fake_permission():
    req = LLMExecutionRequest(
        prompt="hello",
        live_mode_enabled=True,
        allow_fake_backend=False,
        backend_name="fake",
        circuit_state="half-open",
    )
    plan = plan_llm_execution(req, backend=FakeLLMBackend())
    assert plan.should_execute is False
    assert plan.circuit_state == "half_open"
    assert plan.blocked_reason == "provider_not_allowed_public_safe_scope"
    assert "cautious_half_open_plan" in plan.limitations


def test_provider_capability_status_and_no_runtime_mutation_shape():
    executor = make_public_safe_llm_executor()
    req = LLMExecutionRequest(prompt="hello", live_mode_enabled=True, allow_fake_backend=True, backend_name="fake")
    status = executor.capability_status(req, FakeLLMBackend())
    assert status.provider == "fake"
    assert status.configured is True
    assert status.failure_reason is None
    first = executor.plan(req, FakeLLMBackend())
    second = executor.plan(req, FakeLLMBackend())
    assert first == second
