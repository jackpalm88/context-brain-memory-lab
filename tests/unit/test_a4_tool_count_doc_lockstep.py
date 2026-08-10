"""Card A4 — doc/skill tool-count lockstep.

The code-level count was always gate-pinned (test_m7_mcp_expose_only and
siblings assert len(APPROVED_TOOLS)), but the DOCS drifted: CAPABILITIES.md,
the opencb-memory skill and install_smoke still said 32 fourteen days after
the surface became 34 (2026-07-08 CF additions). Doc drift is a defect
(doctrine reconstruction §17.17); these assertions make the drifted files
gate-visible so the next surface change fails here instead of rotting quietly.

Historical, dated documents (MCP_PARITY_TABLE.md, PARITY_AUDIT.md,
STATE_OF_MEMORY_LAB_M10_3.md) are deliberately NOT covered: their figures are
accurate at their stated dates and carry inline UPDATE notes instead.
"""
import re
from pathlib import Path

import pytest

from memory_lab.mcp.tools import APPROVED_TOOLS

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

REPO = Path(__file__).resolve().parents[2]

# (file, pattern, description) — every pattern must match at least once and
# every captured count must equal len(APPROVED_TOOLS).
CLAIMS = [
    ("docs/CAPABILITIES.md", r"— (\d+) MCP tools are registered", "MCP surface bullet"),
    ("docs/CAPABILITIES.md", r"all (\d+) MCP tools ship useful descriptions", "MCP ergonomics bullet"),
    (".claude/skills/opencb-memory/SKILL.md", r"memory_lab\.mcp\.server` — (\d+) tools", "skill connection line"),
    ("README.md", r"(\d+) tools over stdio or", "README feature line"),
    ("memory_lab/mcp/http_server.py", r"the same (\d+) tools \(APPROVED_TOOLS\)", "http_server docstring"),
    ("memory_lab/mcp/http_server.py", r"(\d+) tool registrations are identical", "http_server design note"),
    ("scripts/install_smoke_app.py", r"^EXPECTED_TOOL_COUNT = (\d+)$", "SM-8 expected count"),
    ("scripts/install_smoke_app.py", r"APPROVED_TOOLS has (\d+) entries", "SM-8 header comment"),
    ("scripts/install_smoke.sh", r"MCP tool registry \((\d+) tools, all callable\)", "SM-8 shell header"),
    ("scripts/seed_demo.sh", r"a (\d+)-tool MCP surface", "seed demo surface phrase"),
    ("scripts/seed_demo.sh", r"exposes (?:exactly |its |all )?(\d+) (?:MCP )?tools", "seed demo exposes phrases"),
    ("scripts/seed_demo.sh", r"MCP tool surface \((\d+) tools\)", "seed demo title phrase"),
]


@pytest.mark.parametrize("relpath,pattern,label", CLAIMS, ids=[c[2] for c in CLAIMS])
def test_documented_tool_count_matches_registry(relpath, pattern, label):
    expected = len(APPROVED_TOOLS)
    text = (REPO / relpath).read_text(encoding="utf-8")
    counts = [int(m) for m in re.findall(pattern, text, flags=re.MULTILINE)]
    assert counts, f"{relpath}: pattern for {label!r} matched nothing — claim text changed without updating the lockstep test"
    assert all(c == expected for c in counts), (
        f"{relpath}: {label} states tool count(s) {counts}, registry has {expected}"
    )


def test_no_stale_32_tool_claims_in_current_state_files():
    stale = re.compile(r"\b32\b(?=[^\n]{0,60}\bMCP tools?\b)|\b32/32\b|\b32-tool\b|\b32 approved tools\b")
    current_state_files = [
        "docs/CAPABILITIES.md",
        ".claude/skills/opencb-memory/SKILL.md",
        "README.md",
        "memory_lab/mcp/http_server.py",
        "scripts/install_smoke.sh",
        "scripts/install_smoke_app.py",
        "scripts/seed_demo.sh",
    ]
    offenders = {}
    for relpath in current_state_files:
        for i, line in enumerate((REPO / relpath).read_text(encoding="utf-8").splitlines(), 1):
            # "32 approved Context Brain-parity names" in the corrected
            # CAPABILITIES bullet is the honest parity breakdown, not a
            # surface-count claim — the bullet's own count is 34.
            if "32 approved Context Brain-parity names" in line:
                continue
            if stale.search(line):
                offenders.setdefault(relpath, []).append(f"{i}: {line.strip()}")
    assert not offenders, f"stale 32-tool claims remain: {offenders}"
