"""
Unit tests — ingestion scorer provider backend migration.
Tests that scorer.py uses _get_llm_backend() + backend.complete_json() instead
of direct Anthropic client. No live API calls. No DB ops.
"""
import json
import pytest
from unittest.mock import patch

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_backend(preset_json=None, preset_failure=None, configured=True):
    from memory_lab.providers.fake import FakeLLMBackend
    backend = FakeLLMBackend(preset_json=preset_json, preset_failure=preset_failure)
    if not configured:
        # Override is_configured property via subclass
        class UnconfiguredFake(FakeLLMBackend):
            @property
            def is_configured(self):
                return False
        return UnconfiguredFake()
    return backend


def _valid_scores_json():
    return {"quality": 0.8, "relevance": 0.7, "novelty": 0.6,
            "quality_reason": "good", "relevance_reason": "ok", "novelty_reason": "new"}


# ---------------------------------------------------------------------------
# _get_llm_backend resolution
# ---------------------------------------------------------------------------

def test_get_llm_backend_returns_noop_when_not_configured():
    """When AnthropicLLMBackend.is_configured=False, returns NoopLLMBackend."""
    from memory_lab.providers.noop import NoopLLMBackend
    from memory_lab.providers.anthropic import AnthropicLLMBackend

    class NotConfiguredBackend(AnthropicLLMBackend):
        @property
        def is_configured(self):
            return False

    with patch("memory_lab.providers.anthropic.AnthropicLLMBackend", NotConfiguredBackend):
        from memory_lab.ingestion import scorer
        backend = scorer._get_llm_backend()
    assert isinstance(backend, NoopLLMBackend)


def test_get_llm_backend_returns_noop_on_import_error():
    """If providers.anthropic import fails, _get_llm_backend returns NoopLLMBackend."""
    import importlib, sys
    from memory_lab.providers.noop import NoopLLMBackend
    from memory_lab.ingestion import scorer

    orig = sys.modules.get("memory_lab.providers.anthropic")
    sys.modules["memory_lab.providers.anthropic"] = None  # type: ignore
    try:
        backend = scorer._get_llm_backend()
    finally:
        if orig is None:
            sys.modules.pop("memory_lab.providers.anthropic", None)
        else:
            sys.modules["memory_lab.providers.anthropic"] = orig
    assert isinstance(backend, NoopLLMBackend)


# ---------------------------------------------------------------------------
# No-key fallback
# ---------------------------------------------------------------------------

def test_score_no_key_returns_fallback():
    """When backend not configured → fallback scores, fallback_reason=no_api_key."""
    from memory_lab.ingestion import scorer
    unconfigured = _make_fake_backend(configured=False)

    with patch.object(scorer, "_get_llm_backend", return_value=unconfigured), \
         patch.object(scorer, "_is_circuit_open", return_value=False):
        scores = scorer.score("Some content about databases.")

    assert scores.composite == pytest.approx(0.30, abs=0.01)
    assert "fallback:no_api_key" in scores.quality_reason


def test_score_content_no_key_fallback_reason():
    """score_content fallback_reason='no_api_key' when backend unconfigured."""
    from memory_lab.ingestion import scorer
    unconfigured = _make_fake_backend(configured=False)

    with patch.object(scorer, "_get_llm_backend", return_value=unconfigured), \
         patch.object(scorer, "_is_circuit_open", return_value=False):
        event = scorer.score_content("Some content.")

    assert event.fallback_reason == "no_api_key"
    assert event.scores.composite == pytest.approx(0.30, abs=0.01)


# ---------------------------------------------------------------------------
# Fake backend success
# ---------------------------------------------------------------------------

def test_score_fake_backend_success():
    """FakeLLMBackend with preset_json → correct scores, no fallback."""
    from memory_lab.ingestion import scorer
    fake = _make_fake_backend(preset_json=_valid_scores_json())

    with patch.object(scorer, "_get_llm_backend", return_value=fake), \
         patch.object(scorer, "_is_circuit_open", return_value=False):
        scores = scorer.score("PostgreSQL indexing strategies for JSONB columns.")

    expected_composite = 0.8 * 0.35 + 0.7 * 0.35 + 0.6 * 0.30
    assert abs(scores.composite - expected_composite) < 0.001
    assert scores.quality == pytest.approx(0.8, abs=0.001)
    assert scores.relevance == pytest.approx(0.7, abs=0.001)
    assert scores.novelty == pytest.approx(0.6, abs=0.001)
    assert not scores.quality_reason.startswith("fallback:")


def test_score_fake_backend_0_8_0_7_0_6_formula():
    """0.8/0.7/0.6 → 0.705 composite (receipt formula check)."""
    from memory_lab.ingestion import scorer
    fake = _make_fake_backend(preset_json={"quality": 0.8, "relevance": 0.7, "novelty": 0.6})

    with patch.object(scorer, "_get_llm_backend", return_value=fake), \
         patch.object(scorer, "_is_circuit_open", return_value=False):
        scores = scorer.score("content")

    assert abs(scores.composite - 0.705) < 0.001


# ---------------------------------------------------------------------------
# Provider failure codes → fallback_reason mapping
# ---------------------------------------------------------------------------

def test_failure_code_to_reason_mapping():
    from memory_lab.providers.failure import FailureCode
    from memory_lab.ingestion.scorer import _failure_code_to_reason

    assert _failure_code_to_reason(FailureCode.MISSING_API_KEY) == "no_api_key"
    assert _failure_code_to_reason(FailureCode.PROVIDER_IMPORT_MISSING) == "no_api_key"
    assert _failure_code_to_reason(FailureCode.NOT_CONFIGURED) == "no_api_key"
    assert _failure_code_to_reason(FailureCode.CIRCUIT_OPEN) == "circuit_open"
    assert _failure_code_to_reason(FailureCode.INVALID_JSON) == "parse_error"
    assert _failure_code_to_reason(FailureCode.SCHEMA_VALIDATION_FAILED) == "parse_error"
    assert _failure_code_to_reason(FailureCode.PROVIDER_HTTP_ERROR) == "api_error"
    assert _failure_code_to_reason(FailureCode.RATE_LIMITED) == "api_error"
    assert _failure_code_to_reason(FailureCode.TIMEOUT) == "api_error"
    assert _failure_code_to_reason(FailureCode.UNKNOWN_ERROR) == "api_error"


def test_score_invalid_json_from_backend_returns_parse_error():
    """Backend returns INVALID_JSON → fallback_reason='parse_error'."""
    from memory_lab.ingestion import scorer
    from memory_lab.providers.failure import FailureCode
    fake = _make_fake_backend(preset_failure=FailureCode.INVALID_JSON)

    with patch.object(scorer, "_get_llm_backend", return_value=fake), \
         patch.object(scorer, "_is_circuit_open", return_value=False), \
         patch.object(scorer, "_record_failure"):
        scores = scorer.score("content")

    assert "fallback:parse_error" in scores.quality_reason


def test_score_schema_mismatch_returns_parse_error():
    """Backend returns SCHEMA_VALIDATION_FAILED → fallback_reason='parse_error'."""
    from memory_lab.ingestion import scorer
    from memory_lab.providers.failure import FailureCode
    fake = _make_fake_backend(preset_failure=FailureCode.SCHEMA_VALIDATION_FAILED)

    with patch.object(scorer, "_get_llm_backend", return_value=fake), \
         patch.object(scorer, "_is_circuit_open", return_value=False), \
         patch.object(scorer, "_record_failure"):
        scores = scorer.score("content")

    assert "fallback:parse_error" in scores.quality_reason


def test_score_rate_limited_returns_api_error():
    """Backend returns RATE_LIMITED → fallback_reason='api_error'."""
    from memory_lab.ingestion import scorer
    from memory_lab.providers.failure import FailureCode
    fake = _make_fake_backend(preset_failure=FailureCode.RATE_LIMITED)

    with patch.object(scorer, "_get_llm_backend", return_value=fake), \
         patch.object(scorer, "_is_circuit_open", return_value=False), \
         patch.object(scorer, "_record_failure"):
        scores = scorer.score("content")

    assert "fallback:api_error" in scores.quality_reason


# ---------------------------------------------------------------------------
# Circuit breaker bypasses backend
# ---------------------------------------------------------------------------

def test_circuit_open_skips_backend_call():
    """When circuit is open, _get_llm_backend must NOT be called."""
    from memory_lab.ingestion import scorer

    with patch.object(scorer, "_is_circuit_open", return_value=True), \
         patch.object(scorer, "_get_llm_backend") as mock_backend:
        scores = scorer.score("content")

    mock_backend.assert_not_called()
    assert "fallback:circuit_open" in scores.quality_reason


# ---------------------------------------------------------------------------
# Forbidden: no direct anthropic import in scorer.py
# ---------------------------------------------------------------------------

def test_scorer_has_no_direct_anthropic_import():
    """scorer.py must not import anthropic directly (only via providers layer)."""
    import ast, pathlib
    # tests/unit/ingestion/ → parent×3 = project root
    src = pathlib.Path(__file__).parent.parent.parent.parent / "memory_lab" / "ingestion" / "scorer.py"
    tree = ast.parse(src.read_text())
    direct_imports = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            (alias.name or "").startswith("anthropic")
            for alias in getattr(node, "names", [])
        )
        or (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("anthropic"))
    ]
    assert direct_imports == [], f"Direct anthropic import found: {direct_imports}"


def test_scorer_has_no_get_anthropic_client():
    """scorer.py must not define _get_anthropic_client (replaced by _get_llm_backend)."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent.parent.parent / "memory_lab" / "ingestion" / "scorer.py"
    assert "_get_anthropic_client" not in src.read_text()


def test_scorer_has_no_client_messages_create():
    """scorer.py must not use client.messages.create (replaced by backend.complete_json)."""
    import pathlib
    src = pathlib.Path(__file__).parent.parent.parent.parent / "memory_lab" / "ingestion" / "scorer.py"
    assert "client.messages.create" not in src.read_text()
