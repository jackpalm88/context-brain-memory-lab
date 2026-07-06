"""OpenCB Reference Framework v0 — the canonical consumer.

NOT an agent framework and NOT part of the OpenCB kernel. This package is the
executable reference for how OpenCB is meant to be consumed:

    Capability Manifest -> Intent Router -> Tool Executor -> Evidence Package -> Reasoner

Exactly five components (manifest loader, router, executor, package builder,
execution trace) and nothing else: no memory, no planner, no task
decomposition, no multi-agent, no workflow engine, no retries beyond the
ratified single-reroute rule, no scheduler.

It doubles as a validation instrument for the kernel: whenever this consumer
needs a capability OpenCB does not expose, that is a real architecture signal
with a live consumer behind it — record it, do not work around it silently.

Contracts implemented (design docs in engineering/):
- OPENCB_CAPABILITY_MANIFEST_V0 (ratified) — vocabulary
- OPENCB_EVIDENCE_PACKAGE_V0 (ratified) — output contract
- OPENCB_REFERENCE_INTENT_ROUTER_V0 (ratified) — routing policy
"""

from reference_framework.manifest import load_manifest
from reference_framework.router import route
from reference_framework.executor import execute
from reference_framework.package_builder import build_package

__all__ = ["load_manifest", "route", "execute", "build_package"]
