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
- Authentication and RBAC: API key auth, workspace membership enforcement, six-role RBAC model across all API and MCP surfaces
- Ask/reasoning beta: deterministic/noop-first `/v1/ask` over workspace-scoped retrieval, with evidence/citations and degraded insufficient-evidence behavior
- Migrations: PostgreSQL schema `000..026`

**Version**: `0.1.0b8` · Python ≥ 3.12 · PostgreSQL required for runtime

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
- Deterministic, evidence-grounded ask surface for workspace-scoped retrieval (`POST /v1/ask`)
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

The public beta schema includes migrations `000..026`, covering the Prestage 3 workspace foundation and the v0.1.0b7 auth/RBAC migrations. v0.1.0b8 adds the public beta ask endpoint without adding 027+ migrations.

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
  reasoning/    deterministic/noop-first ask models, intent detection, policy generation, and answer synthesis
migrations/
  000_base_schema.sql .. 026_add_auth_indexes_constraints.sql
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
from memory_lab.reasoning import synthesize_answer
from memory_lab.reasoning.models import AskRequest
```

---

## Workspace foundation in v0.1.0b6

v0.1.0b6 added the Prestage 3 workspace foundation:

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

## Authentication and RBAC in v0.1.0b7

v0.1.0b7 adds API key authentication and workspace role-based access control (RBAC) across all API and MCP surfaces. Migrations `022..026` add the auth/RBAC schema layer.

### API key authentication

All API and MCP requests require a Bearer token:

```bash
curl http://localhost:8000/v1/hubs \
  -H "Authorization: Bearer ***" \
  -H "X-Workspace-ID: <workspace-uuid>"
```

API keys are stored as SHA-256 hashes only — the plain-text token is never stored and cannot be recovered if lost.

### Service-agent tokens

```bash
export MEMORY_LAB_API_TOKEN=<token>       # direct API use
export MEMORY_LAB_MCP_API_TOKEN=<token>   # MCP client use
```

Both accept the same token format. The MCP client passes `Authorization: Bearer ***` to the API automatically.

### Workspace membership and X-Workspace-ID

All API and MCP operations require active workspace membership. Callers without membership receive `403 workspace_membership_required`.

`X-Workspace-ID` remains a workspace **selector**, not auth. It selects the workspace context but does not authenticate the caller. Authentication is always via the Bearer token; membership and role determine access.

### RBAC role model

Six roles are enforced at every endpoint via `require_permission()`:

| Role | Description |
|---|---|
| `owner` | Full access including admin endpoints |
| `admin` | Full access including admin endpoints |
| `writer` | Read and write; no admin |
| `reader` | Read-only |
| `service_agent` | Automated service access; read and write; no admin |
| `auditor` | Read-only; audit event access |

### Admin endpoint protection

Admin endpoints (`/admin/cleanup/ttl`, `/admin/content/{id}/tier/override`, `/admin/content/{id}/tier/rollback`) require `owner` or `admin` role. All other roles receive `403 role_forbidden`.

Admin MCP tools are not exposed. The 32 public MCP tools cover content, hub, edge, decision, and retrieval surfaces only.

### Audit events

- `auth.deny` events are written to `cb_audit_events` on every rejected request. No plain-text token is stored in audit metadata.
- `admin.action` events are written on every successful admin operation.

### Local-dev bypass caveat

`MEMORY_LAB_AUTH_ALLOW_LOCAL_DEV_BYPASS=true` is available for local development only. It still requires a valid auth subject and active workspace membership. **Do not enable in any deployed environment** — it is explicitly unsafe for production.

---

## Ask reasoning beta in v0.1.0b8

v0.1.0b8 adds a public beta ask surface:

```http
POST /v1/ask
```

The endpoint is intentionally minimal and deterministic. It is a **noop-first reasoning layer** over workspace-scoped retrieval: it does not call a provider by default, does not require an LLM key, and does not attempt private ask_v2 parity.

What it provides now:

- deterministic/noop-first reasoning;
- evidence-grounded answer synthesis from retrieved public Memory Lab evidence;
- returned citations/evidence list;
- insufficient-evidence response with degraded-mode wording instead of unsupported confidence;
- workspace-scoped ask behavior;
- RBAC-protected access via the existing `retrieval.search` permission;
- no provider key required by default;
- no provider calls by default.

Example shape:

```bash
curl -X POST http://localhost:8000/v1/ask \
  -H "Authorization: Bearer ***" \
  -H "X-Workspace-ID: <workspace-uuid>" \
  -H "Content-Type: application/json" \
  -d '{"question":"What evidence do we have about this decision?"}'
```

If retrieval cannot support an answer, the response is expected to mark the result as insufficient/degraded rather than inventing unsupported conclusions.

Provider-backed generation remains future/optional roadmap work. The public beta ask endpoint is deterministic and provider-free by default.

---

## Public beta boundaries and roadmap

This is a public beta of Context Brain Memory Lab. It includes the memory/runtime foundation, workspace isolation, API/MCP auth/RBAC, governance, graph/hub/decision primitives, deterministic retrieval paths, and a minimal/noop public ask layer.

It is intentionally scoped: the public package exposes the foundation now, while the broader Context Brain layers continue to move through explicit public boundary and extraction gates.

### Safety boundaries

- **Not production multi-user tenancy yet** — auth/RBAC is implemented for local and public beta use, but hosted production tenancy still requires additional hardening, deployment guidance, and operational proof.
- **Not a hosted service** — this is a self-hosted package; bring your own PostgreSQL.
- **Public beta API** — `0.1.0b8` may still introduce breaking changes before `1.0`.
- **No OIDC/SSO or password login yet** — current authentication uses hashed API keys. External identity adapters are a future track.
- **Not the full Context Brain yet** — this release is a bounded public Memory Lab beta. It includes a first deterministic/noop ask layer, but the broader private Context Brain goal also includes provider-backed reasoning, conflict resolution, current-state discipline, and wider governance workflows.

### Coming next / planned Context Brain layers

- **Reasoning / ask_v2** — partially implemented as a minimal/noop public ask layer via `POST /v1/ask`, with evidence-grounded synthesis, citations, and insufficient-evidence degraded behavior. Private ask_v2 parity and provider-backed generation are not claimed.
- **Classify / embed / store pipeline** — still a planned extraction track for the full ingestion pipeline; not included in this beta.
- **Conflict detection and escalation workflow** — still a planned extraction track for contradiction detection, counterfindings, and human resolution loops; not included in this beta.
- **Current-state / context-pack layer** — still a planned track for canonical current-state anchors and agent context packaging; not included in this beta.
- **Chunk search v2** — not included in this beta.
- **Additional public schema** — future migrations are expected for capability tables such as `classification_history`, `discovered_domains`, and related ingestion/search metadata. The v0.1.0b8 public migration chain remains `000..026`; 027+ migrations are not present in this beta.

### Current integration limits

- **Provider-backed embeddings and LLM calls are optional** — deterministic/no-key paths work by default; provider-backed behavior requires explicit configuration.
- **MCP proof level** — current public proof covers MCP wrapper/tool-level auth and workspace propagation. Protocol-level MCP transport proof can be published separately.
- **External integrations are conservative** — GPT Actions and similar external integrations should be treated as read-oriented unless a write surface is explicitly documented and authorized.

---

## Runtime proven

Package readiness and workspace foundation behavior were verified in staging (`pr1a_staging`) before public release preparation:

| Check | Result |
|---|---|
| `pip install -e .` | PASS in prior public package gates; rerun required for v0.1.0b8 final proof |
| `py_compile` / import smoke | Required in final package proof |
| `python -m build` wheel + sdist | Required after version alignment |
| `twine check` | Required after build |
| API workspace context propagation smoke | PASS in Prestage 3 evidence |
| MCP workspace context propagation smoke | PASS at wrapper/tool level in Prestage 3 evidence |
| Retrieval workspace isolation smoke | PASS in Prestage 3 evidence |
| `POST /v1/ask` minimal/noop API smoke | PASS in staging with workspace/RBAC/evidence checks; rerun required for public package proof |
| Ask provider calls required | NO |
| Provider calls required | NO |
| Disposable teardown | PASS in Prestage 3 evidence |

Wheel target after version alignment: `context_brain_memory_lab-0.1.0b8-py3-none-any.whl`

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

### Admin Endpoints

Admin endpoints (`/admin/cleanup/ttl`, `/admin/content/{id}/tier/override`, `/admin/content/{id}/tier/rollback`) require `owner` or `admin` role. All other roles receive `403 role_forbidden`. There is no unauthenticated admin success path — the local-dev bypass still enforces workspace membership and role.

Admin MCP tools are not exposed via MCP. Admin operations are available through the API only, with RBAC enforced.

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
