#!/usr/bin/env python3
"""Local script entrypoint for B15 graph health report generator.

Does not require pyproject.toml changes or console script registration.
Run from repo root: python scripts/b15_graph_health_report.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_lab.reports.graph_health_report import GraphHealthReportGenerator


def main() -> None:
    now = datetime.now(timezone.utc)
    scenarios = GraphHealthReportGenerator.generate_all_scenarios(now=now)

    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    # Write summary JSON
    summary_path = reports_dir / "b15_graph_health_report_generator_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "gate": "B15_GRAPH_HEALTH_REPORT_GENERATOR",
                "status": "generated",
                "scenario_count": len(scenarios),
                "generated_at": now.isoformat(),
                "scenarios": scenarios,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    # Write markdown report
    md_path = reports_dir / "B15_GRAPH_HEALTH_REPORT_GENERATOR.md"
    lines = [
        "# B15 Graph Health Report Generator",
        "",
        f"Generated: {now.isoformat()}Z",
        "",
        "## Validation",
        "",
        "- Report generator uses existing B15 service/models only",
        "- No API wiring, no database dependency, no provider calls",
        "- No graph mutation, no private CB access",
        "",
        "## Scenarios",
        "",
    ]
    for s in scenarios:
        lines.append(f"### {s['scenario']}")
        lines.append("")
        lines.append(f"- **status**: {s['status']}")
        lines.append(f"- **health_score**: {s['health_score']}")
        lines.append(f"- **component_scores**: {json.dumps(s['component_scores'])}")
        lines.append(f"- **warnings count**: {len(s['warnings'])}")
        lines.append(f"- **findings count**: {len(s['hub_recall_findings'])}")
        lines.append(f"- **alias candidates count**: {len(s['alias_candidates'])}")
        lines.append(f"- **limitations**: {s['limitations']}")
        lines.append("")
    lines.append("## Scope Guard")
    lines.append("")
    lines.append("- api_wiring: false")
    lines.append("- report_generator: true")
    lines.append("- pyproject_changes: false")
    lines.append("- build_export: false")
    lines.append("- provider_calls: false")
    lines.append("- private_cb_access: false")
    lines.append("- cb_write: false")
    lines.append("- git_ops: false")
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {summary_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
