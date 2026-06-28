"""Smoke test for scripts/safe_push.sh — AGENT_CONTRACT §10 approved-hash guard.

Uses a local bare repo as origin so the real push path is exercised hermetically
(no network).
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "safe_push.sh"


def _env(home: Path) -> dict:
    return {
        **os.environ,
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _git(cwd, *args, env):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _run(cwd, env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, env=env, capture_output=True, text=True)


def _remote_has_main(remote, env) -> bool:
    return subprocess.run(["git", "rev-parse", "main"], cwd=remote, env=env,
                          capture_output=True, text=True).returncode == 0


@pytest.fixture
def repo(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = _env(home)
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "--bare", str(remote)],
                   env=env, check=True, capture_output=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", str(work)],
                   env=env, check=True, capture_output=True)
    _git(work, "config", "user.email", "t@example.com", env=env)
    _git(work, "config", "user.name", "Test", env=env)
    _git(work, "remote", "add", "origin", str(remote), env=env)
    (work / "f.txt").write_text("hello\n")
    _git(work, "add", ".", env=env)
    _git(work, "commit", "-m", "init", env=env)
    head = _git(work, "rev-parse", "HEAD", env=env).stdout.strip()
    return work, env, head, remote


def test_pushes_when_head_matches_approved(repo):
    work, env, head, remote = repo
    result = _run(work, env, head)
    assert result.returncode == 0, result.stderr
    assert _git(remote, "rev-parse", "main", env=env).stdout.strip() == head


def test_aborts_on_dirty_tree_without_pushing(repo):
    work, env, head, remote = repo
    (work / "f.txt").write_text("dirty\n")
    result = _run(work, env, head)
    assert result.returncode != 0
    assert "clean" in result.stderr.lower()
    assert not _remote_has_main(remote, env)


def test_aborts_when_head_differs_from_approved(repo):
    work, env, head, remote = repo
    (work / "f.txt").write_text("v2\n")
    _git(work, "add", ".", env=env)
    _git(work, "commit", "-m", "second", env=env)
    result = _run(work, env, head)  # approved = stale head
    assert result.returncode != 0
    assert "approved" in result.stderr.lower()
    assert not _remote_has_main(remote, env)


def test_aborts_on_invalid_approved_hash(repo):
    work, env, head, remote = repo
    result = _run(work, env, "deadbeefdeadbeef")
    assert result.returncode != 0
    assert "valid commit" in result.stderr.lower()


def test_usage_error_without_argument(repo):
    work, env, head, remote = repo
    result = _run(work, env)
    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
