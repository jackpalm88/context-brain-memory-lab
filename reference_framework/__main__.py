"""CLI entry: python -m reference_framework "your question"

Runs the full reference pipeline against a live OpenCB
(MEMORY_LAB_API_HOST/PORT/TOKEN env, same as the MCP server) and prints the
execution trace plus the Evidence Package JSON.
"""

from __future__ import annotations

import json
import sys

from reference_framework.executor import execute
from reference_framework.manifest import load_manifest
from reference_framework.package_builder import build_package
from reference_framework.router import route
from reference_framework.trace import render_trace


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('usage: python -m reference_framework "your question"', file=sys.stderr)
        return 2
    question = " ".join(argv[1:])

    manifest = load_manifest()
    plan = route(question)
    for step in plan.steps:
        if step.tool not in manifest.tools:
            raise SystemExit(f"router plan names unknown tool {step.tool!r} — manifest drift")

    from memory_lab.mcp.tools import APPROVED_TOOLS  # the public MCP surface (HTTP underneath)

    state = execute(plan, APPROVED_TOOLS)
    package = build_package(state)
    print(render_trace(state, package, manifest))
    print()
    print(json.dumps(package, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
