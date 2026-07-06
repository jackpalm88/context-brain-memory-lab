"""Execution Trace renderer — the small component that becomes gold in debug."""

from __future__ import annotations

from typing import Any, Dict

from reference_framework.executor import ExecutionState
from reference_framework.manifest import Manifest


def render_trace(state: ExecutionState, package: Dict[str, Any], manifest: Manifest) -> str:
    ep = package["evidence_package"]
    lines = [
        f"Intent:           {state.plan.intent}",
        f"Matched by:       {state.plan.matched_by}" + ("  (historical)" if state.plan.historical else ""),
        f"Manifest version: {manifest.manifest_version} (opencb {manifest.opencb_version})",
        "Calls:",
    ]
    for t in state.trace:
        marker = {"ok": "✓", "error": "✗", "empty": "∅", "skipped": "·"}.get(t.outcome, "?")
        condition = f" [{t.condition}={'fired' if t.condition_fired else 'not fired'}]" if t.condition else ""
        lines.append(f"  {t.step_id} {marker} {t.tool}{condition} — {t.args_digest}")
    lines.append(f"Package:          {len(ep['items'])} evidence items, "
                 f"{len(ep['conflicts'])} conflicts, {len(ep['lineage'])} lineage chains")
    if ep["degradations"]:
        lines.append(f"Degradations:     {', '.join(sorted({d['type'] for d in ep['degradations']}))}")
    if ep["gaps"]:
        lines.append("Gaps:")
        lines.extend(f"  - {g}" for g in ep["gaps"])
    lines.append("Reasoner:         ready (package is the only input)")
    return "\n".join(lines)
