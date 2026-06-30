from __future__ import annotations

import pytest

from memory_lab.api.config import get_settings

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


def test_ask_provider_synthesis_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MEMORY_LAB_ASK_PROVIDER_SYNTHESIS_ENABLED", raising=False)
    assert get_settings().ask_provider_synthesis_enabled is False


def test_ask_provider_synthesis_enabled_via_env(monkeypatch):
    monkeypatch.setenv("MEMORY_LAB_ASK_PROVIDER_SYNTHESIS_ENABLED", "true")
    assert get_settings().ask_provider_synthesis_enabled is True


def test_ask_provider_synthesis_independent_of_reasoning_gate(monkeypatch):
    monkeypatch.setenv("MEMORY_LAB_ASK_PROVIDER_SYNTHESIS_ENABLED", "true")
    monkeypatch.delenv("MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED", raising=False)
    settings = get_settings()
    assert settings.ask_provider_synthesis_enabled is True
    assert settings.reasoning_provider_synthesis_enabled is False
