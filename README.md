# Context Brain Memory Lab

**context-brain-memory-lab** is a provider-neutral, installable Python runtime for governed agent memory. It packages the public Memory Lab spine for hub-linked knowledge, decision lineage, workspace-aware retrieval, evidence-grounded asking, optional persistence, optional vector retrieval, and optional provider-backed reasoning.

**Version**: `0.2.0a1` · Python ≥ 3.12

## Current release truth

M1–M5 are closed for this release candidate:

- **Deterministic empty-env core**: the baseline runtime imports and deterministic tests run without provider keys, without a configured database, and without private Context Brain access.
- **Opt-in Postgres persistence**: DB-backed persistence is available when `DATABASE_URL` / `CB_TEST_DATABASE_URL` is explicitly configured; the in-memory fallback remains the no-DB path.
- **Opt-in pgvector retrieval**: pgvector KNN retrieval is gated behind explicit vector/pgvector configuration and migrations; deterministic retrieval remains the fallback.
- **Opt-in provider-backed reasoning**: provider synthesis is disabled by default and requires explicit flags plus runtime keys.
- **M5 live smoke proven**: `scripts/m5_live_smoke.py` proves real OpenAI embeddings + real Anthropic synthesis + throwaway pgvector KNN + grounded answer evidence when live secrets are supplied at runtime.

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

Expected `0.2.0a1` artifacts:

- `dist/context_brain_memory_lab-0.2.0a1-py3-none-any.whl`
- `dist/context_brain_memory_lab-0.2.0a1.tar.gz`

## Deterministic gates

Source hermetic gate:

```bash
bash scripts/hermetic_test.sh
```

Artifact proof should use a fresh venv outside the repo, install from the built wheel or sdist, import `memory_lab`, verify installed metadata version `0.2.0a1`, and run deterministic smoke without relying on editable install.

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
