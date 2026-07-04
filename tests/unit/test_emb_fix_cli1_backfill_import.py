"""EMB-FIX-CLI-1 — regression test for scripts/embedding_backfill.py's backend builder.

Bug found live during FV-EMB-0: _make_backend() imported
memory_lab.providers.openai_embedding_backend (module does not exist) and called
OpenAIEmbeddingBackend(api_key=...) (the real class takes no constructor args —
it reads OPENAI_API_KEY from the process environment). Both bugs made the live
execution path permanently unreachable, even with a valid key and env pre-check
that reported success.

These tests import scripts/embedding_backfill.py directly (it is a standalone
script, not a package module) via importlib and exercise _make_backend() —
the exact function the CLI dry-run/live paths call — so a hermetic test
actually walks the code path that broke, not just the library module.
"""
from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.provider_optional, pytest.mark.public_safe]

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "embedding_backfill.py"


def _load_backfill_module():
    spec = importlib.util.spec_from_file_location("embedding_backfill_cli", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def backfill_cli():
    return _load_backfill_module()


def _args(**overrides):
    base = dict(dry_run=False, api_key=None)
    base.update(overrides)
    return Namespace(**base)


class _FakeOpenAIModule:
    """Minimal stand-in for the `openai` package — only needs to be importable."""


def test_dry_run_returns_none_no_import_attempted(backfill_cli, monkeypatch):
    """Dry-run must never touch the backend import at all."""
    result = backfill_cli._make_backend(_args(dry_run=True))
    assert result is None


def test_live_missing_api_key_exits_cleanly(backfill_cli, monkeypatch):
    monkeypatch.delenv("BACKFILL_OPENAI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        backfill_cli._make_backend(_args(dry_run=False, api_key=None))
    assert exc.value.code == 1


def test_live_correct_module_path_no_import_error(backfill_cli, monkeypatch):
    """The historical bug: importing memory_lab.providers.openai_embedding_backend
    (wrong module) always raised ImportError. This must no longer happen."""
    monkeypatch.setitem(sys.modules, "openai", _FakeOpenAIModule())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    backend = backfill_cli._make_backend(_args(dry_run=False, api_key="sk-test-fake-key"))

    from memory_lab.providers.openai_embedding import OpenAIEmbeddingBackend
    assert isinstance(backend, OpenAIEmbeddingBackend)


def test_live_constructor_call_does_not_raise_typeerror(backfill_cli, monkeypatch):
    """The second historical bug: OpenAIEmbeddingBackend(api_key=...) raised
    TypeError because the real class takes no constructor arguments."""
    monkeypatch.setitem(sys.modules, "openai", _FakeOpenAIModule())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # Must not raise TypeError — previously this line crashed even after
    # fixing only the import path.
    backfill_cli._make_backend(_args(dry_run=False, api_key="sk-test-fake-key"))


def test_live_cli_api_key_is_threaded_to_backend_env(backfill_cli, monkeypatch):
    """--api-key must actually take effect, not silently rely on a pre-existing
    OPENAI_API_KEY the operator forgot to export."""
    monkeypatch.setitem(sys.modules, "openai", _FakeOpenAIModule())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    backend = backfill_cli._make_backend(_args(dry_run=False, api_key="sk-explicit-cli-key"))

    assert backend.is_configured is True
    import os
    assert os.environ.get("OPENAI_API_KEY") == "sk-explicit-cli-key"


def test_live_backfill_openai_env_var_fallback(backfill_cli, monkeypatch):
    """BACKFILL_OPENAI_API_KEY (not --api-key) must still work end-to-end."""
    monkeypatch.setitem(sys.modules, "openai", _FakeOpenAIModule())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("BACKFILL_OPENAI_API_KEY", "sk-from-env-fallback")

    backend = backfill_cli._make_backend(_args(dry_run=False, api_key=None))

    assert backend.is_configured is True


def test_live_openai_package_missing_exits_cleanly_not_uncaught(backfill_cli, monkeypatch):
    """If the openai package genuinely isn't installed, is_configured is False
    and the CLI must exit(1) cleanly — not raise an uncaught exception."""
    monkeypatch.delitem(sys.modules, "openai", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import builtins
    real_import = builtins.__import__

    def _blocked_import(name, *a, **kw):
        if name == "openai":
            raise ImportError("No module named 'openai'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    with pytest.raises(SystemExit) as exc:
        backfill_cli._make_backend(_args(dry_run=False, api_key="sk-test-fake-key"))
    assert exc.value.code == 1
