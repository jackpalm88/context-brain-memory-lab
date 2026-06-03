"""
Unit tests for AnthropicLLMBackend adapter.

All tests are no-key, no-live-calls. Anthropic client is mocked via unittest.mock.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from memory_lab.providers.anthropic import AnthropicLLMBackend
from memory_lab.providers.failure import FailureCode
from memory_lab.providers.llm_backend import LLMRequest, LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(prompt="hello", system=None, max_tokens=128, expected_schema=None):
    return LLMRequest(
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        expected_schema=expected_schema,
    )


def _mock_anthropic_response(text: str):
    """Build a fake anthropic messages.create() return value."""
    content_block = SimpleNamespace(text=text)
    return SimpleNamespace(content=[content_block])


def _make_backend_with_key():
    """Return a backend with ANTHROPIC_API_KEY set in env (patched)."""
    return AnthropicLLMBackend()


# ---------------------------------------------------------------------------
# 1. Identity
# ---------------------------------------------------------------------------

def test_provider_name():
    b = AnthropicLLMBackend()
    assert b.provider_name == "anthropic"


# ---------------------------------------------------------------------------
# 2. is_configured — no-key paths
# ---------------------------------------------------------------------------

def test_not_configured_no_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch.dict("sys.modules", {"anthropic": MagicMock()}):
        b = AnthropicLLMBackend()
        assert b.is_configured is False


def test_not_configured_import_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with patch("builtins.__import__", side_effect=_import_fail_for_anthropic):
        b = AnthropicLLMBackend()
        assert b.is_configured is False


def _import_fail_for_anthropic(name, *args, **kwargs):
    if name == "anthropic":
        raise ImportError("anthropic not installed")
    import builtins
    return builtins.__import__(name, *args, **kwargs)


def test_is_configured_true_when_key_and_package(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    fake_anthropic = MagicMock()
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        assert b.is_configured is True


# ---------------------------------------------------------------------------
# 3. No-key: all methods return degraded without network call
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,kwargs", [
    ("complete_text", {}),
    ("complete_json", {}),
    ("summarize", {}),
    ("classify", {"labels": ["a", "b"]}),
])
def test_all_methods_degraded_no_key(monkeypatch, method, kwargs):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with patch.dict("sys.modules", {"anthropic": MagicMock()}):
        b = AnthropicLLMBackend()
        resp: LLMResponse = getattr(b, method)(_req(), **kwargs)
        assert resp.degraded is True
        assert resp.failure_reason == FailureCode.MISSING_API_KEY


def test_no_network_call_when_not_configured(monkeypatch):
    """Ensure _get_client returns before making any network call."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.side_effect = (
        AssertionError("network call made!")
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_text(_req())
        assert resp.degraded is True
        fake_anthropic.Anthropic.return_value.messages.create.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Import missing path
# ---------------------------------------------------------------------------

def test_complete_text_import_missing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    # Remove anthropic from sys.modules to simulate missing package
    with patch.dict("sys.modules", {"anthropic": None}):
        b = AnthropicLLMBackend()
        resp = b.complete_text(_req())
        assert resp.degraded is True
        assert resp.failure_reason == FailureCode.PROVIDER_IMPORT_MISSING


# ---------------------------------------------------------------------------
# 5. Mocked success: complete_text
# ---------------------------------------------------------------------------

def test_complete_text_success(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.return_value = (
        _mock_anthropic_response("hello world")
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_text(_req("say hello"))
        assert resp.degraded is False
        assert resp.text == "hello world"
        assert resp.provider == "anthropic"


# ---------------------------------------------------------------------------
# 6. Mocked success: complete_json
# ---------------------------------------------------------------------------

def test_complete_json_success(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    payload = {"quality": 0.8, "relevance": 0.7, "novelty": 0.6}
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.return_value = (
        _mock_anthropic_response(json.dumps(payload))
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_json(_req())
        assert resp.degraded is False
        assert resp.json_data == payload


def test_complete_json_strips_markdown_fences(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    payload = {"x": 1}
    raw = f"```json\n{json.dumps(payload)}\n```"
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.return_value = (
        _mock_anthropic_response(raw)
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_json(_req())
        assert resp.degraded is False
        assert resp.json_data == payload


# ---------------------------------------------------------------------------
# 7. complete_json — failure paths
# ---------------------------------------------------------------------------

def test_complete_json_invalid_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.return_value = (
        _mock_anthropic_response("not json {{{")
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_json(_req())
        assert resp.degraded is True
        assert resp.failure_reason == FailureCode.INVALID_JSON


def test_complete_json_schema_mismatch(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    payload = {"quality": 0.5}  # missing "relevance" and "novelty"
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.return_value = (
        _mock_anthropic_response(json.dumps(payload))
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        schema = {"quality": None, "relevance": None, "novelty": None}
        resp = b.complete_json(_req(expected_schema=schema))
        assert resp.degraded is True
        assert resp.failure_reason == FailureCode.SCHEMA_VALIDATION_FAILED


# ---------------------------------------------------------------------------
# 8. Exception → FailureCode mapping (via _call_messages)
# ---------------------------------------------------------------------------

def _make_exc(cls_name: str, module: str = "anthropic"):
    """Create a fake exception with the given class name and module."""
    exc_cls = type(cls_name, (Exception,), {"__module__": module})
    return exc_cls(f"simulated {cls_name}")


def test_rate_limited(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.side_effect = (
        _make_exc("RateLimitError")
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_text(_req())
        assert resp.degraded is True
        assert resp.failure_reason == FailureCode.RATE_LIMITED


def test_timeout(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.side_effect = (
        _make_exc("APITimeoutError")
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_text(_req())
        assert resp.degraded is True
        assert resp.failure_reason == FailureCode.TIMEOUT


def test_http_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.side_effect = (
        _make_exc("APIStatusError")
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_text(_req())
        assert resp.degraded is True
        assert resp.failure_reason == FailureCode.PROVIDER_HTTP_ERROR


def test_unknown_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.side_effect = RuntimeError("oops")
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.complete_text(_req())
        assert resp.degraded is True
        assert resp.failure_reason == FailureCode.UNKNOWN_ERROR


# ---------------------------------------------------------------------------
# 9. classify / summarize shape
# ---------------------------------------------------------------------------

def test_classify_returns_llm_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.return_value = (
        _mock_anthropic_response("label_a")
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.classify(_req(), labels=["label_a", "label_b"])
        assert isinstance(resp, LLMResponse)
        assert resp.text == "label_a"


def test_summarize_returns_llm_response(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic.return_value.messages.create.return_value = (
        _mock_anthropic_response("short summary")
    )
    with patch.dict("sys.modules", {"anthropic": fake_anthropic}):
        b = AnthropicLLMBackend()
        resp = b.summarize(_req("long text here"))
        assert isinstance(resp, LLMResponse)
        assert resp.degraded is False
