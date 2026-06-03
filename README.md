# Context Brain Memory Lab

**context-brain-memory-lab** is a provider-neutral, installable Python runtime for governed agent memory — structured around hub-linked knowledge, decision lineage, and retrieval discipline rather than raw vector storage.

- API surface: FastAPI (`memory_lab.api`)
- MCP surface: Model Context Protocol server (`memory_lab.mcp`)
- Graph layer: Hub-linked knowledge graph (`memory_lab.graph`)
- Bootstrap: Config, store init, smoke (`memory_lab.bootstrap`)
- Decision memory: Decision CRUD, lineage, conflict detection (`memory_lab.decisions`)
- Governance tier: Quality scoring, tier routing, override, cleanup (`memory_lab.governance`)
- Ingestion scoring: Provider-optional quality/relevance/novelty scorer (`memory_lab.ingestion`)
- Migrations: PostgreSQL schema `000..016`

**Version**: `0.1.0b2` · Python ≥ 3.12 · PostgreSQL required for runtime

---

## What makes this different

Context Brain Memory Lab is not a generic vector memory store. Its focus is **governed agent memory**: helping agents decide what to save, how to link it, how contradictions should be represented, and how future agents retrieve evidence without inheriting full chat history.

- Memory-write governance with quality/relevance/novelty scoring
- Hub-linked knowledge organization (navigation entry points, not just tags)
- Decision memory and lineage (what was decided and why)
- Retrieval discipline: graph-aware, hub-boosted, score-transparent
- API + MCP surfaces — works with any LLM client that speaks HTTP or MCP
- **Provider-neutral by default**: no OpenAI, Anthropic, or any LLM key required for the baseline runtime

---

## Quick Start

### Prerequisites

- Python ≥ 3.12
- PostgreSQL instance (local or remote)
- `pip`

### Install

```bash
git clone https://github.com/jackpalm88/context-brain-memory-lab.git
cd context-brain-memory-lab
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### Configure

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/memory_lab"
```

Provider keys are **not required** for the baseline runtime:

```bash
# Default — provider-neutral, deterministic retrieval only
export LLM_PROVIDER=none
export EMBEDDING_PROVIDER=none
```

Optional — enable provider-backed embeddings only if you have a key and want semantic search:

```bash
export EMBEDDING_PROVIDER=openai
export OPENAI_API_KEY=sk-...
```

### Run migrations

```bash
for f in migrations/00*.sql; do psql "$DATABASE_URL" -f "$f"; done
```

### Start the API runtime

```bash
uvicorn memory_lab.api.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### Start the MCP runtime

```bash
python -m memory_lab.mcp.server
```

---

## Package structure

```
memory_lab/
  bootstrap/    config, store init, smoke
  api/          FastAPI routers, services, policies
  graph/        hub store, edge store, hybrid search, expansion
  mcp/          MCP server, tools, client
  decisions/    decision CRUD, lineage, conflict detection
  governance/   tier router, ingestion policy, events, cleanup, override
  ingestion/    provider-optional scorer, models
migrations/
  000_base_schema.sql .. 016_add_governance_events.sql
pyproject.toml
```

### Import smoke

```python
from memory_lab.bootstrap import config, smoke, stores
from memory_lab.api import main
from memory_lab.graph import store, hub_store, hub_edge_store
from memory_lab.mcp import server, tools
from memory_lab.decisions import models as dm
from memory_lab.governance import tier_router, ingestion_policy
from memory_lab.ingestion import scorer
```

---

## What this does not claim

- **No production auth / multi-user access control** — single-tenant baseline only
- **No provider-backed embeddings by default** — deterministic retrieval path works without any key
- **No LLM generation by default** — retrieval and governance logic are independent of LLM calls
- **No hosted service** — self-hosted only; bring your own PostgreSQL
- **No full API stability guarantee** — `0.1.0b2` is a public beta; breaking changes may occur before `1.0`
- **No write tools for GPT Actions** — read-only API surface for external integrations at this stage

---

## Runtime proven

Package readiness verified in staging (`pr1a_staging`):

| Check | Result |
|---|---|
| `pip install -e .` | PASS |
| `py_compile` 34 modules | PASS |
| Import smoke (7 namespaces) | PASS |
| `python -m build` wheel + sdist | PASS |
| `twine check` | PASS |
| API runtime smoke | PASS |
| MCP runtime smoke | PASS |

Wheel: `context_brain_memory_lab-0.1.0b2-py3-none-any.whl`

---

## Scoring and Governance

### Provider-Neutral Fallback Scoring

Without `ANTHROPIC_API_KEY`: all scores default to `0.30` (composite=0.30), tier=`transient`,
`fallback_reason` exposed in response. No crash, no missing fields.

```json
{
  "mode": "governed_fallback",
  "scores": {"quality": 0.3, "relevance": 0.3, "novelty": 0.3, "composite": 0.3},
  "tier": "transient",
  "fallback_reason": "no_api_key",
  "governance_lines": [
    "score:fallback composite=0.3 reason=no_api_key",
    "tier:transient tier_reason:circuit_open:fallback_scores_used"
  ]
}
```

### Optional Anthropic Scoring

Set `ANTHROPIC_API_KEY` to enable live quality/relevance/novelty scoring via the Anthropic API.
Without it, fallback composite scores are used (see above).

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

When enabled, `mode` changes to `"governed"` and scores reflect actual content quality.

### Decision Memory Runtime

Decision memory (create, retrieve, supersede) is fully available without any provider key.
No `ANTHROPIC_API_KEY` required for decision memory operations.

```bash
curl -X POST http://localhost:8000/decisions/ \
  -H "Content-Type: application/json" \
  -d '{"title": "...", "decision_reason": "...", "decision_status": "active"}'
```

### Admin Endpoints Caveat

Admin endpoints (`/admin/cleanup/ttl`, `/admin/content/{id}/tier/override`,
`/admin/content/{id}/tier/rollback`) are unauthenticated in this release.
Intended for local and development use only.
Do not expose to untrusted networks without adding an auth layer.

### Excluded Modules

The following private modules are **not** included in this package:
`audit.py`, `conflict_detector.py`, `ask_v2.py`

---

## Related

- **Context Brain (Public Alpha)** — positioning, governance model, GPT Actions schema, MCP tool docs:  
  https://github.com/jackpalm88/context-brain-public-alpha

---

## License

See `LICENSE`.
