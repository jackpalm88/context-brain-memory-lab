# Context Brain Memory Lab

**context-brain-memory-lab** is a provider-neutral, installable Python runtime for governed agent memory — structured around hub-linked knowledge, decision lineage, workspace-aware retrieval, and retrieval discipline rather than raw vector storage.

- API surface: FastAPI (`memory_lab.api`)
- MCP surface: Model Context Protocol server (`memory_lab.mcp`)
- Graph layer: Hub-linked knowledge graph (`memory_lab.graph`)
- Bootstrap: Config, store init, smoke (`memory_lab.bootstrap`)
- Decision memory: Decision CRUD, lineage, conflict detection (`memory_lab.decisions`)
- Governance tier: Quality scoring, tier routing, override, cleanup (`memory_lab.governance`)
- Ingestion scoring: Provider-optional quality/relevance/novelty scorer (`memory_lab.ingestion`)
- Workspace foundation: default workspace bootstrap, API/MCP workspace context propagation, and retrieval workspace isolation
- Migrations: PostgreSQL schema `000..021`

**Version**: `0.1.0b6` · Python ≥ 3.12 · PostgreSQL required for runtime

---

## What makes this different

Context Brain Memory Lab is not a generic vector memory store. Its focus is **governed agent memory**: helping agents decide what to save, how to link it, how contradictions should be represented, and how future agents retrieve evidence without inheriting full chat history.

- Memory-write governance with quality/relevance/novelty scoring
- Hub-linked knowledge organization (navigation entry points, not just tags)
- Decision memory and lineage (what was decided and why)
- Retrieval discipline: graph-aware, hub-boosted, score-transparent
- API + MCP surfaces — works with any LLM client that speaks HTTP or MCP
- Workspace-aware API/MCP context propagation for local-dev workspace separation
- Retrieval workspace isolation for API and MCP retrieval paths
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

For local setup, see [docs/INSTALL.md](docs/INSTALL.md).

### Configure

```bash
export DATABASE_URL="postgresql://user:***@localhost:5432/memory_lab"
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
export OPENAI_API_KEY=***
```

### Run migrations

```bash
for f in migrations/00*.sql; do psql "$DATABASE_URL" -f "$f"; done
```

The public beta schema includes migrations `000..021`, including the Prestage 3 workspace foundation migrations.

### Start the API runtime

```bash
uvicorn memory_lab.api.main:app --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### Workspace context: API

The API supports an optional `X-Workspace-ID` header for workspace-aware requests:

```bash
curl http://localhost:8000/retrieval/search   -H "X-Workspace-ID: <workspace-uuid>"
```

If no `X-Workspace-ID` header is provided, the runtime uses the default workspace for local-dev compatibility. Unknown or invalid workspace IDs should be treated as structured errors rather than silently crossing workspace boundaries.

This is **workspace foundation**, not tenant-safe production security. `X-Workspace-ID` is context propagation, not authentication or authorization.

### Start the MCP runtime

```bash
python -m memory_lab.mcp.server
```

MCP wrapper/tool calls can pass an optional `workspace_id` argument. If omitted, the MCP runtime follows the same local-dev default workspace behavior where configured. This proves MCP workspace context propagation at the wrapper/tool level; it does not claim separate protocol-level MCP transport proof unless a dedicated transport smoke is run.

---

## Package structure

```
memory_lab/
  bootstrap/    config, store init, smoke
  api/          FastAPI routers, workspace context, services, policies
  graph/        hub store, edge store, hybrid search, expansion, workspace-scoped retrieval helpers
  mcp/          MCP server, tools, client with workspace_id propagation
  decisions/    decision CRUD, lineage, conflict detection
  governance/   tier router, ingestion policy, events, cleanup, override
  ingestion/    provider-optional scorer, models
  providers/    LLM + embedding backend abstractions (base interfaces, Noop, Fake, optional Anthropic LLM + OpenAI Embedding adapters)
migrations/
  000_base_schema.sql .. 021_add_workspace_fk_constraints_not_valid.sql
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
from memory_lab.providers import LLMBackend, NoopLLMBackend, FailureCode
```

---

## Workspace foundation in v0.1.0b6

This public beta adds the Prestage 3 workspace foundation:

- Workspace schema foundation with `cb_workspaces` and default workspace bootstrap
- API workspace context propagation across content, hubs, hub links, edges, decisions, and retrieval surfaces
- MCP workspace context propagation through wrapper/tool `workspace_id` handling
- Retrieval workspace isolation for API and MCP retrieval paths
- Hub-linked retrieval scoping
- Graph traversal / neighbor / edge expansion scoping
- Decision list/timeline/conflict regression scoping
- Default workspace behavior for local-dev compatibility

This is an app/schema-level workspace foundation. It is useful for local development, public beta evaluation, and future auth/RBAC design, but it is not production multi-user security.

---

## What this does not claim

- **No auth/RBAC** — there is no production authentication or role-based authorization boundary in this beta
- **Not production tenancy** — workspace isolation is app/schema-level context scoping, not tenant-safe production isolation
- **Not Full Context Brain** — this package is a bounded Memory Lab public beta, not the full private Context Brain system
- **No production multi-user security** — do not treat `X-Workspace-ID` or MCP `workspace_id` as a trusted identity boundary
- **No provider-backed embeddings by default** — deterministic retrieval path works without any key
- **No LLM generation by default** — retrieval and governance logic are independent of LLM calls
- **No hosted service** — self-hosted only; bring your own PostgreSQL
- **No protocol-level MCP transport proof by default** — MCP workspace propagation is wrapper/tool-level unless a separate transport smoke is published
- **No full API stability guarantee** — `0.1.0b6` is a public beta; breaking changes may occur before `1.0`
- **No write tools for GPT Actions** — read-only API surface for external integrations at this stage

---

## Runtime proven

Package readiness and workspace foundation behavior were verified in staging (`pr1a_staging`) before public release preparation:

| Check | Result |
|---|---|
| `pip install -e .` | PASS in prior public package gates; rerun required for v0.1.0b6 final proof |
| `py_compile` / import smoke | Required in final package proof |
| `python -m build` wheel + sdist | Required after version alignment |
| `twine check` | Required after build |
| API workspace context propagation smoke | PASS in Prestage 3 evidence |
| MCP workspace context propagation smoke | PASS at wrapper/tool level in Prestage 3 evidence |
| Retrieval workspace isolation smoke | PASS in Prestage 3 evidence |
| Provider calls required | NO |
| Disposable teardown | PASS in Prestage 3 evidence |

Wheel target after version alignment: `context_brain_memory_lab-0.1.0b6-py3-none-any.whl`

---

## Scoring and Governance

### Provider Abstraction Layer

`memory_lab.providers` ships a provider-optional LLM backend abstraction:

- `LLMBackend` ABC — single `complete_text()` contract; no streaming, no tool-calls in base
- `NoopLLMBackend` — default; `degraded=True`, no external calls, no key required
- `FakeLLMBackend` — test fixture; 4 modes (fixed, empty, error, timeout)
- `AnthropicLLMBackend` — optional adapter; deferred import, no top-level `import anthropic`
- `FailureCode` enum — typed failure reasons across all backends
- `ProviderConfig` — reads `LLM_PROVIDER` env var; `none` is valid and default

`LLM_PROVIDER=none` (the default) is always valid — no external calls, no crash.

**Live Anthropic smoke note:** live end-to-end scoring via `AnthropicLLMBackend` was not exercised in the public baseline because provider keys are not required. The optional Anthropic path is implemented and tested via mocks. Live smoke is deferred to a future provider-specific gate with key injection.

### Embedding Backends

`memory_lab.providers` also ships a provider-optional embedding backend abstraction:

- `EmbeddingBackend` ABC — single `embed_text()` / `embed_batch()` contract
- `NoopEmbeddingBackend` — default; `degraded=True`, no external calls, no key required
- `FakeEmbeddingBackend` — test fixture; returns deterministic synthetic vectors
- `OpenAIEmbeddingBackend` — optional adapter; deferred import, no top-level `import openai`
  - Requires `OPENAI_API_KEY` and `pip install "context-brain-memory-lab[openai]"`
  - Default model: `text-embedding-3-small`, default dims: 1536
  - No-key / missing-package path: returns `degraded=True`, empty vector, no crash

`EMBEDDING_PROVIDER=none` (the default) is always valid — no external calls, no crash.

**Live OpenAI embedding smoke note:** live end-to-end embedding via `OpenAIEmbeddingBackend` was not exercised in the public baseline. All tests use mocked responses. Live smoke is deferred to a future provider-specific gate with key injection.

### Provider-Neutral Fallback Scoring

Without `ANTHROPIC_API_KEY`: all scores default to `0.30` (composite=0.30), tier=`transient`, and `fallback_reason` is exposed in response. No crash, no missing fields.

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

Set `ANTHROPIC_API_KEY` to enable live quality/relevance/novelty scoring via the Anthropic API. Without it, fallback composite scores are used (see above).

```bash
export ANTHROPIC_API_KEY=***
```

When enabled, `mode` changes to `"governed"` and scores reflect actual content quality.

### Decision Memory Runtime

Decision memory (create, retrieve, supersede) is fully available without any provider key. No `ANTHROPIC_API_KEY` is required for decision memory operations.

```bash
curl -X POST http://localhost:8000/decisions/   -H "Content-Type: application/json"   -d '{"title": "...", "decision_reason": "...", "decision_status": "active"}'
```

### Admin Endpoints Caveat

Admin endpoints (`/admin/cleanup/ttl`, `/admin/content/{id}/tier/override`, `/admin/content/{id}/tier/rollback`) are unauthenticated in this release. They are intended for local and development use only.

Do not expose admin endpoints to untrusted networks without adding an auth layer. Admin endpoint caveats remain separate from workspace foundation; workspace IDs do not make admin endpoints production-safe.

### Excluded Modules

The following private modules are **not** included in this package:
`audit.py`, `conflict_detector.py`, `ask_v2.py`

---

## Security & Privacy

See [SECURITY.md](SECURITY.md) for vulnerability reporting, admin endpoint caveats, and secrets guidance. See [PRIVACY.md](PRIVACY.md) for data handling and telemetry policy.

---

## Related

- **Context Brain (Public Alpha)** — positioning, governance model, GPT Actions schema, MCP tool docs:  
  https://github.com/jackpalm88/context-brain-public-alpha

---

## License

See `LICENSE`.
