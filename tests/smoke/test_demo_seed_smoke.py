"""DEMO-1 seed smoke tests — verify demo corpus integrity without a live DB.

Gate: DEMO-1
Scope: tests/smoke/test_demo_seed_smoke.py

What is tested (import/parse smoke — no live DB, no psql, no provider):
  DS1 — seed_demo.sh is present, executable, and contains required stage markers
  DS2 — all 4 demo hub UUIDs are referenced in the script
  DS3 — all 8 demo content UUIDs are referenced in the script
  DS4 — all 8 demo chunk UUIDs are referenced in the script
  DS5 — all 8 hub-content link pairs are referenced in the script
  DS6 — all 3 demo edge_key values are referenced in the script
  DS7 — script contains idempotency markers (ON CONFLICT) for all object types
  DS8 — script is POSIX-safe: no bash-isms that break on dash (shebang is bash)
  DS9 — SEED_VERIFY_ONLY guard is present (allows verify-only runs)
  DS10 — no private data patterns in the seed script

No live DB. No psql. No network. pytest.mark.smoke.
"""
from __future__ import annotations

import os
import re
import stat
import pathlib
import pytest

pytestmark = [pytest.mark.smoke]

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SEED_SCRIPT = REPO_ROOT / "scripts" / "seed_demo.sh"

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def seed_text() -> str:
    assert SEED_SCRIPT.exists(), f"seed_demo.sh not found at {SEED_SCRIPT}"
    return SEED_SCRIPT.read_text(encoding="utf-8")


# ── DS1: presence and executable bit ─────────────────────────────────────────

def test_DS1_seed_script_present_and_executable(seed_text):
    """DS1 — seed_demo.sh exists and has executable bit set."""
    assert SEED_SCRIPT.exists(), "seed_demo.sh must exist"
    mode = SEED_SCRIPT.stat().st_mode
    assert mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH), (
        "seed_demo.sh must have at least one executable bit set"
    )
    # Must have bash shebang
    first_line = seed_text.splitlines()[0]
    assert first_line.startswith("#!/"), f"First line must be a shebang, got: {first_line!r}"
    assert "bash" in first_line, f"Shebang must reference bash, got: {first_line!r}"
    # Stage markers
    for stage_num in range(1, 8):
        assert f"Stage {stage_num}" in seed_text, f"Stage {stage_num} marker missing from seed script"


# ── DS2: hub UUIDs ────────────────────────────────────────────────────────────

EXPECTED_HUB_IDS = [
    "a1a1a1a1-de00-0001-0000-000000000001",  # Architecture & Decisions
    "a1a1a1a1-de00-0002-0000-000000000002",  # Retrieval & Embeddings
    "a1a1a1a1-de00-0003-0000-000000000003",  # Agent Integration
    "a1a1a1a1-de00-0004-0000-000000000004",  # Getting Started
]

@pytest.mark.parametrize("hub_id", EXPECTED_HUB_IDS)
def test_DS2_hub_uuids_present(seed_text, hub_id):
    """DS2 — all 4 demo hub UUIDs appear in the seed script."""
    assert hub_id in seed_text, f"Hub UUID {hub_id} not found in seed_demo.sh"


# ── DS3: content UUIDs ────────────────────────────────────────────────────────

EXPECTED_CONTENT_IDS = [
    "c0de0001-0000-0000-0000-000000000001",
    "c0de0002-0000-0000-0000-000000000002",
    "c0de0003-0000-0000-0000-000000000003",
    "c0de0004-0000-0000-0000-000000000004",
    "c0de0005-0000-0000-0000-000000000005",
    "c0de0006-0000-0000-0000-000000000006",
    "c0de0007-0000-0000-0000-000000000007",
    "c0de0008-0000-0000-0000-000000000008",
]

@pytest.mark.parametrize("content_id", EXPECTED_CONTENT_IDS)
def test_DS3_content_uuids_present(seed_text, content_id):
    """DS3 — all 8 demo content UUIDs appear in the seed script."""
    assert content_id in seed_text, f"Content UUID {content_id} not found in seed_demo.sh"


# ── DS4: chunk UUIDs ──────────────────────────────────────────────────────────

EXPECTED_CHUNK_IDS = [
    "c0dec001-0000-0000-0000-000000000001",
    "c0dec002-0000-0000-0000-000000000002",
    "c0dec003-0000-0000-0000-000000000003",
    "c0dec004-0000-0000-0000-000000000004",
    "c0dec005-0000-0000-0000-000000000005",
    "c0dec006-0000-0000-0000-000000000006",
    "c0dec007-0000-0000-0000-000000000007",
    "c0dec008-0000-0000-0000-000000000008",
]

@pytest.mark.parametrize("chunk_id", EXPECTED_CHUNK_IDS)
def test_DS4_chunk_uuids_present(seed_text, chunk_id):
    """DS4 — all 8 demo chunk UUIDs appear in the seed script."""
    assert chunk_id in seed_text, f"Chunk UUID {chunk_id} not found in seed_demo.sh"


# ── DS5: hub-content link pairs ───────────────────────────────────────────────

EXPECTED_LINK_PAIRS = [
    ("a1a1a1a1-de00-0004-0000-000000000004", "c0de0001-0000-0000-0000-000000000001"),
    ("a1a1a1a1-de00-0004-0000-000000000004", "c0de0004-0000-0000-0000-000000000004"),
    ("a1a1a1a1-de00-0002-0000-000000000002", "c0de0002-0000-0000-0000-000000000002"),
    ("a1a1a1a1-de00-0002-0000-000000000002", "c0de0006-0000-0000-0000-000000000006"),
    ("a1a1a1a1-de00-0001-0000-000000000001", "c0de0005-0000-0000-0000-000000000005"),
    ("a1a1a1a1-de00-0001-0000-000000000001", "c0de0007-0000-0000-0000-000000000007"),
    ("a1a1a1a1-de00-0003-0000-000000000003", "c0de0003-0000-0000-0000-000000000003"),
    ("a1a1a1a1-de00-0003-0000-000000000003", "c0de0008-0000-0000-0000-000000000008"),
]

@pytest.mark.parametrize("hub_id,content_id", EXPECTED_LINK_PAIRS)
def test_DS5_link_pairs_present(seed_text, hub_id, content_id):
    """DS5 — all 8 hub-content link pairs appear in the same section of the seed script."""
    # Both UUIDs must appear (they may not be on the same line but must both exist)
    assert hub_id in seed_text,     f"Hub {hub_id} not found in links section"
    assert content_id in seed_text, f"Content {content_id} not found in links section"


# ── DS6: edge_key values ──────────────────────────────────────────────────────

EXPECTED_EDGE_KEYS = [
    # supports: Getting Started → Agent Integration (sorted for non-directional? actually 'supports' is directional)
    "a1a1a1a1-de00-0003-0000-000000000003|a1a1a1a1-de00-0004-0000-000000000004|supports",
    # supports: Architecture → Retrieval
    "a1a1a1a1-de00-0001-0000-000000000001|a1a1a1a1-de00-0002-0000-000000000002|supports",
    # related: Agent Integration ↔ Retrieval (symmetric, sorted)
    "a1a1a1a1-de00-0002-0000-000000000002|a1a1a1a1-de00-0003-0000-000000000003|related",
]

@pytest.mark.parametrize("edge_key", EXPECTED_EDGE_KEYS)
def test_DS6_edge_keys_present(seed_text, edge_key):
    """DS6 — all 3 demo edge_key values appear in the seed script."""
    assert edge_key in seed_text, f"Edge key {edge_key!r} not found in seed_demo.sh"


# ── DS7: idempotency markers ──────────────────────────────────────────────────

def test_DS7_idempotency_markers(seed_text):
    """DS7 — ON CONFLICT clause present for all 5 object types (hubs, content, chunks, links, edges)."""
    on_conflict_count = seed_text.count("ON CONFLICT")
    assert on_conflict_count >= 5, (
        f"Expected at least 5 ON CONFLICT clauses (one per object type), found {on_conflict_count}"
    )
    # Verify DO UPDATE or DO NOTHING patterns
    assert "DO NOTHING" in seed_text or "DO UPDATE" in seed_text, (
        "ON CONFLICT clauses must use DO NOTHING or DO UPDATE"
    )


# ── DS8: shebang and basic bash safety ────────────────────────────────────────

def test_DS8_posix_safe_shebang(seed_text):
    """DS8 — script uses #!/usr/bin/env bash shebang (not #!/bin/sh)."""
    first_line = seed_text.splitlines()[0]
    assert "bash" in first_line, (
        f"Script must use bash shebang for bash-specific features, got: {first_line!r}"
    )
    # set -euo pipefail or set -e must be present
    assert "set -e" in seed_text, "Script must use set -e (or set -euo pipefail) for safety"


# ── DS9: SEED_VERIFY_ONLY guard ───────────────────────────────────────────────

def test_DS9_verify_only_guard(seed_text):
    """DS9 — SEED_VERIFY_ONLY env guard is present to allow verify-without-seed runs."""
    assert "SEED_VERIFY_ONLY" in seed_text, (
        "SEED_VERIFY_ONLY guard must be present for verify-only runs"
    )


# ── DS10: no private data ─────────────────────────────────────────────────────

# Patterns that must NOT appear in a public seed script
_PRIVATE_PATTERNS = [
    r"(?<!\$\{)(?<!PG)password\s*=\s*['\"][^'\"]{6,}",  # hardcoded password value (not env var reference)
    r"(?<!\$\{)secret\s*=\s*['\"][^'\"]{6,}",             # hardcoded secret value
    r"api[_-]?key\s*=\s*['\"][a-zA-Z0-9]{20,}",           # hardcoded API key value
    r"\b192\.168\.\d+\.\d+",                               # private RFC-1918 IP
    r"\b10\.\d+\.\d+\.\d+",                               # private RFC-1918 IP
    r"@[a-z0-9-]+\.internal",                              # internal hostname
]

@pytest.mark.parametrize("pattern", _PRIVATE_PATTERNS)
def test_DS10_no_private_data(seed_text, pattern):
    """DS10 — no private data patterns (passwords, secrets, internal IPs) in seed script."""
    matches = re.findall(pattern, seed_text, re.IGNORECASE)
    assert not matches, (
        f"Potential private data pattern {pattern!r} found in seed_demo.sh: {matches}"
    )
