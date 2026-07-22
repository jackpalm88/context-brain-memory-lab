"""Card B2 — opencb-epistemics Stage 1 artifacts under the gate.

Pins the three Stage 1 deliverables (skill text, validation doc, seed script)
to the GO'd proposal's own constraints (OpenCB decision 9e7cf8dd, hash-bound):

- §6 truth-sync: the skill must carry NO version-coupled tool counts and must
  cite the capability manifest by reference, with the inline sync rule.
- §7 harness: the validation doc must carry scenarios E1-E4, each with
  explicit PASS and FAIL criteria, including the three FAIL conditions named
  by the proposal verbatim in spirit (superseded raised to current; weak
  cited as proof; evidence/inference not separated).
- The seed script must be syntactically valid bash and reference the same
  fixture ids/scope the validation doc describes.
"""
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / ".claude/skills/opencb-epistemics/SKILL.md"
VALIDATION = REPO / "docs/EPISTEMICS_VALIDATION.md"
SEED = REPO / "scripts/epistemics_validation_seed.sh"


def test_stage1_artifacts_exist():
    for path in (SKILL, VALIDATION, SEED):
        assert path.is_file(), f"Stage 1 artifact missing: {path}"


def test_skill_contains_the_contract_core():
    text = SKILL.read_text(encoding="utf-8")
    for required in (
        "Known (recorded)",
        "Suggested by evidence",
        "Insufficient evidence",
        "two-check",
        "Superseded is never current",
        "Lineage before finality",
        "Tool-output vs inference",
        "Ambiguity is reported",
        "consumer-habit skill over existing kernel capabilities",
    ):
        assert required in text, f"skill text lost its contract element: {required!r}"


def test_skill_truth_sync_no_version_coupled_counts():
    # §6: no literal tool counts anywhere in the skill's normative text.
    text = SKILL.read_text(encoding="utf-8")
    stale = re.findall(r"\b\d+\s*(?:-tool|\s?(?:approved\s)?(?:MCP\s)?tools)\b", text)
    assert not stale, f"skill text carries version-coupled tool counts: {stale}"
    assert "capability_manifest.yaml" in text, "skill must cite the manifest by reference"
    assert "the manifest is right" in text, "skill must state its inline truth-sync rule"


def test_validation_doc_has_all_four_scenarios_with_pass_fail():
    text = VALIDATION.read_text(encoding="utf-8")
    for scenario, fail_marker in (
        ("E1", "superseded raised to current"),
        ("E2", "weak cited as proof"),
        ("E3", "evidence/inference not separated"),
        ("E4", '"nothing" after a single call'),
    ):
        block = re.search(rf"### {scenario} — .+?(?=### |## |\Z)", text, flags=re.S)
        assert block, f"scenario {scenario} missing from validation doc"
        assert "**PASS:**" in block.group(0), f"{scenario} lacks an explicit PASS criterion"
        assert "**FAIL:**" in block.group(0), f"{scenario} lacks an explicit FAIL criterion"
        assert fail_marker in block.group(0), f"{scenario} lost its proposal-mandated FAIL condition"


def test_seed_script_is_valid_bash_and_matches_the_doc():
    subprocess.run(["bash", "-n", str(SEED)], check=True)
    seed_text = SEED.read_text(encoding="utf-8")
    doc_text = VALIDATION.read_text(encoding="utf-8")
    scope = "epistemics-validation-notify-transport"
    assert scope in seed_text and scope in doc_text, "fixture scope must match between seed and doc"
    for fixture_id in (
        "e9e00001-0000-0000-0000-00000000000b",
        "e9e00002-0000-0000-0000-00000000000a",
        "e9e00003-0000-0000-0000-00000000000c",
    ):
        assert fixture_id in seed_text, f"seed script lost fixture id {fixture_id}"
