"""Smoke test for examples/decision_recall_demo.py — the public "different AI,
same brain" example (replaces the removed internal B31 wrapper-flow example,
2026-08-10 repo archaeology pass).

This example requires a live OpenCB API (`docker compose up`) to demonstrate
anything real, so the hermetic gate cannot exercise its actual save/recall
behavior. What the gate CAN and must verify: the script is valid, importable,
and fails gracefully (clear message, exit 1, no traceback) when no API is
reachable — a newcomer who runs it before starting the stack should get a
helpful message, not a stack trace.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.provider_optional, pytest.mark.public_safe]

EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "examples" / "decision_recall_demo.py"


def test_example_exists_and_is_valid_python():
    assert EXAMPLE_PATH.exists()
    compile(EXAMPLE_PATH.read_text(encoding="utf-8"), str(EXAMPLE_PATH), "exec")


def test_example_fails_gracefully_without_a_live_api():
    # Deliberately unreachable port — no compose stack listens here.
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib.util, sys; "
                "spec = importlib.util.spec_from_file_location('decision_recall_demo', "
                f"{str(EXAMPLE_PATH)!r}); "
                "mod = importlib.util.module_from_spec(spec); "
                "spec.loader.exec_module(mod); "
                "mod.API_URL = 'http://127.0.0.1:19999'; "
                "sys.exit(mod.main())"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 1, completed.stderr
    assert "not reachable" in completed.stdout
    assert "Traceback" not in completed.stderr


def test_example_targets_the_documented_quickstart_port():
    source = EXAMPLE_PATH.read_text(encoding="utf-8")
    assert "127.0.0.1:8088" in source, (
        "must match the README/INSTALL Docker quickstart port for copy-paste-ability"
    )
