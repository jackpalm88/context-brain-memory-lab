# Context Brain Memory Lab

**context-brain-memory-lab** is a provider-neutral, installable Python runtime for governed agent memory. It packages the public Memory Lab spine for hub-linked knowledge, decision lineage, workspace-aware retrieval, evidence-grounded asking, optional persistence, optional vector retrieval, and optional provider-backed reasoning.

**Version**: `1.0.0` · Python ≥ 3.12

## Current release truth

v1.0.0 is feature-complete and field-validated:

- **Deterministic empty-env core**: the baseline runtime imports and deterministic tests run without provider keys, without a configured database, and without private Context Brain access.
- **Feature-complete developer surface**: governed save (scoring, tiering, dedup, classification, current-state resolution with explicit `scope_hint`), hub graph with deterministic edge inference and a human approve/reject gate, conflict escalations, decision memory with lineage, composite-ranked retrieval with per-result trust/provenance, evidence-grounded ask with current-state awareness, context packs, reasoning traverse/explain honoring `max_hops` with hub-term graph adjacency, 34 described MCP tools, batch/similar/feedback/metrics DX routes, docker-compose onboarding.
- **Full-provider field validation done**: the FV-1..FV-9 validation cycle (grounded answering, memory loop, retrieval precision, MCP ergonomics, cross-session coherence, traverse depth, graceful failure, parity, explainability) is closed with live evidence; the three epistemic blockers it surfaced are fixed.
- **Opt-in Postgres/pgvector/providers**: persistence, vector retrieval, and provider-backed synthesis remain explicit opt-ins with deterministic fallbacks.
- **Architecture boundaries ratified**: see [docs/ARCHITECTURE_BOUNDARIES.md](docs/ARCHITECTURE_BOUNDARIES.md) for the standing doctrines, the graph authority model, the Graph Navigation scope freeze, and the v1.0 exception policy. Accepted limitations and vNext items are documented there and in the CHANGELOG — they are separated from blockers by design.

This package is **not** Full/private Context Brain parity, not private `ask_v2` parity, not a hosted service, not production tenancy/billing, and not a public release announcement. Push, tag, PyPI publish, and public announcement require separate human approval.

## Capability summary

- FastAPI API surface in `memory_lab.api`
- MCP server/library surface in `memory_lab.mcp`
- hub graph and graph-health helpers in `memory_lab.graph`
- decision memory and lineage in `memory_lab.decisions`
- governance state, tier routing, and ingestion scoring helpers
- retrieval evidence contract across retrieval/ask paths
- context-pack and reasoning answer-candidate endpoints
- optional OpenAI embedding adapter and optional Anthropic LLM adapter with deferred imports and no-key degraded behavior
- optional Postgres/pgvector persistence and retrieval seams

For a compact capability/non-claim map, see [docs/CAPABILITIES.md](docs/CAPABILITIES.md).

## Install for local development

```bash
git clone https://github.com/jackpalm88/context-brain-memory-lab.git
cd context-brain-memory-lab
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[test]"
```

Provider keys and database configuration are optional for the deterministic baseline.

```bash
export LLM_PROVIDER=none
export EMBEDDING_PROVIDER=none
```

Optional DB-backed runtime:

```bash
export DATABASE_URL="postgresql://<user>:<password>@<host>:5432/<database>"
for f in $(ls migrations/*.sql | sort); do psql "$DATABASE_URL" -f "$f"; done
```

Optional provider/vector runtime requires explicit configuration, runtime secrets, and the relevant extras/dependencies. Do not commit provider keys or DSNs.

```bash
export MEMORY_LAB_VECTOR_EMBEDDINGS_ENABLED=true
export MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED=true
export MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED=true
export EMBEDDING_PROVIDER=openai
export LLM_PROVIDER=anthropic
export OPENAI_API_KEY="...runtime only..."
export ANTHROPIC_API_KEY="...runtime only..."
```

## Build artifacts

Release-readiness builds use the package metadata in `pyproject.toml`:

```bash
python -m build
```

Built artifacts land in `dist/` (not tracked in git) as
`context_brain_memory_lab-<version>-py3-none-any.whl` and the matching sdist.

## Deterministic gates

Source hermetic gate:

```bash
bash scripts/hermetic_test.sh
```

Artifact proof should use a fresh venv outside the repo, install from the built wheel or sdist, import `memory_lab`, verify the installed metadata version matches `pyproject.toml`, and run deterministic smoke without relying on editable install.

## M5 live smoke

The committed live smoke is opt-in and requires Docker, live provider keys, and runtime-only secrets:

```bash
python scripts/m5_live_smoke.py
```

It uses a throwaway pgvector database and masks evidence. It is not part of the default hermetic gate.

## Safety boundaries

- Provider-neutral by default: no OpenAI, Anthropic, or LLM key required for baseline use.
- Database-neutral by default: deterministic core can run without Postgres; Postgres/pgvector are opt-in runtime paths.
- Evidence-grounded outputs: reasoning endpoints return answer candidates and citations/evidence refs, not truth/verdict/resolution semantics.
- Private source material is not shipped as private operational memory; public behavior must be proven through committed code/tests/smokes.
- Release actions (`push`, `tag`, PyPI publish, public announcement) require separate human GO.

## License

Apache-2.0. See [LICENSE](LICENSE).
