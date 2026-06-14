# Context Brain Memory Lab

**context-brain-memory-lab** is a provider-neutral, installable Python runtime for governed agent memory — structured around hub-linked knowledge, decision lineage, workspace-aware retrieval, and retrieval discipline rather than raw vector storage.

- API surface: FastAPI (`memory_lab.api`)
- MCP surface: Model Context Protocol server (`memory_lab.mcp`)
- Graph layer: Hub-linked knowledge graph (`memory_lab.graph`)
- Bootstrap: Config, store init, smoke (`memory_lab.bootstrap`)
- Decision memory: Decision CRUD, lineage, conflict detection (`memory_lab.decisions`)
- Governance tier: Quality scoring, tier routing, override, cleanup (`memory_lab.governance`)
- Ingestion scoring: Provider-optional quality/relevance/novelty scorer (`memory_lab.ingestion`)
- Classify pipeline: deterministic `heuristic_v1` memory classification wired into save/ingest flows
- Retrieval filters: `memory_type` / `memory_types` filtering for scoped retrieval use cases
- Current-state resolver: beta canonical-state supersession helper for high-confidence classified content
- Catchup helper: dry-run-first classify catchup CLI for persisted rows that still need `memory_type`
- Conflict discovery: public-beta `POST /v1/conflicts/search` for computed-only conflict/counterfinding candidates
- Context packs: public-beta `POST /v1/context-packs/build` for computed/read-only evidence object packaging
- Workspace foundation: default workspace bootstrap, API/MCP workspace context propagation, and retrieval workspace isolation
- Authentication and RBAC: API key auth, workspace membership enforcement, six-role RBAC model across all API and MCP surfaces
- Ask/reasoning beta: deterministic/noop-first `/v1/ask` over workspace-scoped retrieval, with evidence/citations and degraded insufficient-evidence behavior
- Retrieval evidence contract: normalized `EvidenceItem` with deterministic `evidence_id`, rank, `score_kind`, and `retrieval_path` across `/v1/retrieval/search` and `/v1/ask`
- Context pack API: deterministic `context_pack_id` values (`cp_<sha256_first_24>`) for transient, non-mutating context packages
- Reasoning over context packs: public-beta `POST /v1/reasoning/traverse`, `POST /v1/reasoning/explain`, and `POST /v1/reasoning/answer` for deterministic/read-only evidence traversal, explanation, and answer-candidate assembly over B12 context packs
- Graph health beta: read-only Graph Health Score, Hub Recall Health, and Alias Hygiene candidate reporting over deterministic/sample graph-health data
- Migrations: PostgreSQL schema `000..030`

**Version**: `0.1.0b15` · Python ≥ 3.12 · PostgreSQL required for runtime

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
- Retrieval evidence contract: normalized, deterministic evidence fields across retrieval and ask surfaces
- Classify ingest wiring for public beta memory typing, including discard-tier handling and discovered-domain hints
- `memory_type` / `memory_types` retrieval filters for focused search behavior
- Current-state resolver beta for high-confidence classified content, without claiming broader agent context packaging
- Dry-run-first classify catchup CLI/helper for existing persisted content
- Conflict discovery / counterfinding surfacing via `POST /v1/conflicts/search`, without truth arbitration or automatic resolution
- Context packaging / evidence object layer via `POST /v1/context-packs/build`, without answer synthesis, truth arbitration, or DB mutation
- Reasoning over B12 context packs via `POST /v1/reasoning/traverse`, `POST /v1/reasoning/explain`, and B14 `POST /v1/reasoning/answer`, returning `answer_candidate` rather than top-level `answer` and without private ask_v2 parity, truth arbitration, conflict resolution, graph mutation, or DB mutation
- B15 graph-health reporting via read-only API endpoints for Graph Health Score, Hub Recall Health, and Alias Hygiene candidates, using the existing `hubs.read` permission and deterministic/sample data in this beta
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
export DATABASE_URL="<postgresql-url-for-your-memory-lab-database>"
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

The public beta schema includes migrations `000..030`. Earlier beta migrations cover workspace foundation, auth/RBAC, ask, and retrieval evidence. v0.1.0b10 adds the classify pipeline, discovered-domain metadata, retrieval memory-type filtering support, and current-state anchor schema used by the B10 beta helpers. v0.1.0b11 adds computed-only conflict/counterfinding discovery over existing public-beta memory signals; it adds no B11 migrations and no durable conflict table. v0.1.0b12 adds a computed/read-only context-pack API over existing B10/B11 signals; it adds no B12 migrations, no durable context-pack table, and no DB mutation path. v0.1.0b13 adds a deterministic/read-only reasoning layer over B12 context packs via `POST /v1/reasoning/traverse` and `POST /v1/reasoning/explain`; it adds no B13 migrations, no durable reasoning table, and no DB mutation path. v0.1.0b14 adds `POST /v1/reasoning/answer` as an evidence-grounded answer-candidate endpoint over the same public-beta reasoning/context-pack layer; it adds no B14 migrations, no durable answer trace table, and no DB mutation path. v0.1.0b15 adds read-only B15 graph-health reporting for Graph Health Score, Hub Recall Health, and Alias Hygiene candidates over deterministic/sample beta data; it adds no B15 migrations, no durable graph-health table, no live repository read requirement yet, and no graph mutation path.

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
  ingestion/    provider-optional scorer, classify pipeline, catchup helper, models
  providers/    LLM + embedding backend abstractions (base interfaces, Noop, Fake, optional Anthropic LLM + OpenAI Embedding adapters)
  reasoning/    deterministic/noop-first ask models, intent detection, policy generation, and answer synthesis
  current_state/ beta current-state resolver helpers
  conflicts/     public-beta computed conflict/counterfinding discovery helpers
  context_packs/  public-beta computed/read-only context packaging helpers
migrations/
  000_base_schema.sql .. 030_add_current_state_anchors.sql
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
from memory_lab.ingestion.classify import classify_content
from memory_lab.ingestion.classify_catchup import run_catchup
from memory_lab.current_state import resolve_current_state
from memory_lab.conflicts.detector import detect_conflict_candidates
from memory_lab.context_packs import build_context_pack_for_request
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

## Retrieval evidence contract in v0.1.0b9

v0.1.0b9 hardens the retrieval and ask surfaces with a normalized evidence contract. No new migrations are added — the public schema remains `000..026`.

### /v1/retrieval/search — normalized response

The `/v1/retrieval/search` response now returns normalized `EvidenceItem` objects. This is a **breaking change** relative to v0.1.0b8: the raw `RetrievalAdapter` row shape is no longer returned directly.

Response shape per result:

```json
{
  "evidence_id": "ev_<content_id>_<chunk_id>",
  "rank": 1,
  "content_id": "<uuid>",
  "chunk_id": "<uuid>",
  "snippet": "...",
  "score": 0.9,
  "score_kind": "chunk_text_match",
  "retrieval_path": "content_chunk_workspace_scoped",
  "source": null,
  "title": null,
  "metadata": null
}
```

**Breaking field changes vs v0.1.0b8:**

| Field | v0.1.0b8 | v0.1.0b9 |
|---|---|---|
| `id` | present | removed |
| `text` | present | removed (→ `snippet`) |
| `workspace_id` (in result items) | present | removed |
| `hub_match` (conditional) | present | removed |
| `evidence_id` | absent | added |
| `rank` | absent | added |
| `score_kind` | absent | added |
| `snippet` | absent | added (replaces `text`) |
| `source`, `title`, `metadata` | absent | added (nullable) |

Fields `content_id`, `chunk_id`, `score`, and `retrieval_path` are preserved.

### /v1/ask — evidence contract

`AskResponse.evidence[]` items now carry the full 11-field `EvidenceItem` shape (same as `/v1/retrieval/search` above). `AskResponse.citations[]` now include `rank` alongside `evidence_id`.

`evidence_id` format:
- Chunk-backed: `ev_{content_id}_{chunk_id}`
- No-chunk: `ev_{content_id}_{retrieval_path}_{rank}`

### Evidence contract rules

- Content-level deduplication before ranking: one `EvidenceItem` per `content_id`
- `rank` is 1-based, sequential, and post-deduplication
- `score_kind`: `chunk_text_match` unless `"hub"` is in `retrieval_path`, in which case `hub_link`
- `evidence_id` is deterministic: same content and chunk inputs produce the same ID across calls

---

### B10 beta classify, retrieval filters, current-state resolver, and catchup helper in v0.1.0b10

v0.1.0b10 adds the next public-beta memory governance layer. It is still a bounded Memory Lab beta, not the complete private Context Brain product.

What B10 adds:

- **Classify ingest wiring** — saved content can be classified with deterministic `heuristic_v1` memory typing during the ingest/save path. The public path is designed to remain provider-neutral by default.
- **Discard-tier fix** — discard decisions use the public schema enum correctly so low-value content can be rejected without schema mismatch errors.
- **Retrieval memory filters** — retrieval supports `memory_type` and `memory_types` filtering so callers can narrow search by classified memory category.
- **Public-style live DB proof** — B10 integration evidence uses a disposable public-style test database, not a private or production database.
- **Current-state resolver beta** — high-confidence classified content can participate in deterministic current-state supersession handling through the resolver helper.
- **Classify catchup CLI/helper** — existing persisted content with missing `memory_type` can be classified by a dry-run-first helper.

Catchup helper example:

```bash
python -m memory_lab.ingestion.classify_catchup   --dry-run   --limit 100   --workspace-id <workspace-uuid>
```

Safety notes:

- `--dry-run` is the default behavior.
- Writes require explicit `--apply`.
- Non-dry-run usage requires either `--workspace-id <uuid>` or explicit `--all-workspaces`.
- The helper reconstructs text from persisted content chunks and skips rows without usable text.
- The helper writes classify-owned fields only; current-state changes go through the resolver path.
- Provider calls are not required by default.

Test/dev database environment:

- `CB_TEST_ADMIN_DSN` is for creating and dropping disposable test databases only.
- `CB_TEST_DATABASE_URL` is for the disposable database under test.
- Use isolated local/test PostgreSQL credentials and throwaway database names.
- Do not point these variables at hosted production, private operational databases, or unrelated service databases.
- Do not paste secrets into docs, reports, tickets, or screenshots.

B10 remains a candidate-public capability set. It does not claim production tenancy/billing, provider-backed reasoning by default, contradiction escalation workflows, agent context packaging APIs, or client libraries.

---

### B11 beta conflict discovery and counterfinding surfacing in v0.1.0b11

v0.1.0b11 adds a public-beta conflict discovery surface for finding potential counterfindings and contradictions in already persisted, workspace-scoped memory. It is a discovery layer, not a final reasoning or truth-resolution layer.

New API endpoint:

```text
POST /v1/conflicts/search
```

What B11 adds:

- **Computed-only candidates** — conflict and counterfinding results are calculated at request time from existing persisted memory signals.
- **Deterministic `candidate_id`** — candidate IDs are deterministic for stable inputs, enabling repeatable review and downstream audit references.
- **Explicit counterfinding detection** — the detector can surface evidence that pushes against another same-scope memory item without declaring a winner.
- **Explicit contradiction detection** — the detector can surface direct opposing claims as candidate conflicts.
- **Stale/current same-scope tension detection** — current-state and stale-state signals in the same scope can be surfaced as tension candidates.
- **Support-only evidence is not a conflict** — evidence that merely supports the same claim is excluded from conflict creation.
- **Workspace isolation** — searches are scoped by workspace context and do not cross workspace boundaries.
- **Discard/no-persist content ignored** — discarded or non-persisted content is not used to create conflict candidates.

B11 safety and boundary rules:

- No durable conflict table in B11.
- No B11 migrations.
- No provider or LLM reasoning is required or performed by default.
- No truth arbitration: candidates indicate tension, not which side is correct.
- No destructive resolution: B11 does not overwrite, delete, or resolve source memories.
- No automatic contradiction resolution or escalation workflow is included.

Example request shape:

```json
{
  "workspace_id": "<workspace-uuid>",
  "scope": "same_hub_or_domain",
  "limit": 20
}
```

The exact candidate scoring and fields remain public-beta and may change before `1.0`. Treat results as review prompts for humans or governed agents, not as authoritative judgments.

---

### B12 beta context packaging / evidence object layer in v0.1.0b12

v0.1.0b12 adds a public-beta context-pack API for packaging already persisted, workspace-scoped memory evidence into a deterministic context object. It is a context packaging / evidence object layer, not a final reasoning or answer synthesis layer.

New API endpoint:

```text
POST /v1/context-packs/build
```

What B12 adds:

- **Computed/read-only context pack** — the endpoint builds a transient response from existing persisted rows and does not write context-pack state.
- **Deterministic `context_pack_id`** — IDs use the `cp_<sha256_first_24>` format for stable inputs.
- **Supporting evidence packaging** — results include `supporting_evidence` from the retrieval path.
- **Current-state signal packaging** — B10 current-state signals are included where present.
- **Stale/superseded item packaging** — stale or superseded memory items can be surfaced separately from current-state signals.
- **Conflict candidate packaging** — B11 conflict/counterfinding candidates can be included without declaring a winner.
- **Counterfinding packaging** — `counterfindings` are represented as evidence objects, not final judgments.
- **Warnings and `non_claims`** — responses explicitly document what the context pack does and does not claim.
- **Stable output field names** — B12 responses include `supporting_evidence`, `current_state_signals`, `stale_or_superseded_items`, `conflict_candidates`, `counterfindings`, `warnings`, and `non_claims`.

B12 safety and boundary rules:

- Not an ask endpoint.
- Not a hidden reasoning endpoint.
- No provider/LLM reasoning is required or performed by default.
- No truth arbitration: the context pack organizes evidence and signals, but does not decide what is true.
- No automatic conflict resolution: conflicts remain candidates for review.
- No answer, verdict, resolution, or truth-decision output fields.
- No durable context-pack table.
- No B12 migrations.
- No DB mutation in the B12 runtime path.

Example request shape:

```json
{
  "query": "What is current for this topic?",
  "workspace_id": "<workspace-uuid>",
  "scope": "same_hub_or_domain",
  "memory_types": ["fact", "decision"],
  "limit": 10
}
```

The exact context-pack scoring and field details remain public-beta and may change before `1.0`. Treat B12 output as structured context for downstream review or reasoning, not as an authoritative answer.

---

### B13 beta reasoning over context packs in v0.1.0b13

v0.1.0b13 adds a public-beta reasoning layer over B12 context packs. It structures deterministic traversal and explanation of existing evidence objects; it is not Full Context Brain, not a private ask_v2 port, not truth arbitration, not conflict resolution, and not a standalone answer-generation API.

New API endpoints:

```text
POST /v1/reasoning/traverse
POST /v1/reasoning/explain
```

What B13 adds:

- **Reasoning over B12 context packs** — B13 consumes the B12 context-pack evidence object and returns traversal/explanation metadata.
- **Deterministic/read-only default** — the runtime path is computed from existing evidence and does not mutate graph or database state.
- **Evidence refs preserved** — supporting evidence, current-state signals, stale/superseded signals, conflict candidates, and counterfindings remain inspectable as evidence references.
- **Conflict warnings surfaced** — unresolved conflict/counterfinding/stale signals are surfaced for human review without declaring a winner.
- **Provider synthesis opt-in only** — `enable_provider_synthesis=false` by default; provider-backed synthesis is not attempted unless explicitly requested and configured.
- **`LLM_PROVIDER=none` default preserved** — no provider key is required for the baseline B13 reasoning path.
- **Limitations surfaced** — responses include non-claims and limitations rather than final judgments.

B13 safety and boundary rules:

- No private ask_v2 source-code port.
- No private prompt copy.
- No Full Context Brain claim.
- No truth arbitration.
- No automatic conflict resolution.
- No standalone `/v1/reasoning/answer` endpoint; that remains deferred and is not part of the B13 public API.
- No `answer`, `verdict`, `truth_decision`, or `resolution` response fields in the B13 reasoning response contract.
- No B13 migrations.
- No durable reasoning table.
- No DB mutation in the B13 reasoning runtime path.

Example request shape:

```json
{
  "query": "Explain the evidence path for this topic",
  "scope": "same_hub_or_domain",
  "memory_types": ["fact", "decision"],
  "include_conflicts": true,
  "max_hops": 3,
  "enable_provider_synthesis": false
}
```

The exact reasoning traversal/explanation fields remain public-beta and may change before `1.0`. Treat B13 output as structured review assistance over evidence, not as an authoritative answer, verdict, truth decision, or conflict resolution.

---

### B14 beta answer candidate endpoint in v0.1.0b14

v0.1.0b14 adds `POST /v1/reasoning/answer` as an evidence-grounded answer-candidate endpoint over the existing B12/B13 context-pack and reasoning layer. It returns `answer_candidate`; it does not return a top-level `answer`. The endpoint is deterministic/read-only by default, remains compatible with `LLM_PROVIDER=none`, and only attempts provider-backed synthesis when `enable_provider_synthesis=true` is explicitly requested and a provider is configured.

New API endpoint:

```text
POST /v1/reasoning/answer
```

What B14 preserves in the response contract:

- Evidence refs from the underlying context pack and reasoning path.
- Traversal steps for inspectable evidence movement.
- Conflict warnings for unresolved counterfinding/stale/conflict signals.
- Limitations and `non_claims` to keep the response bounded.
- Provider failure degradation that retains deterministic evidence references instead of hiding support context.

B14 safety and boundary rules:

- Not a private ask_v2 port.
- Not a `/v1/ask` rewrite.
- Not truth arbitration.
- Not conflict resolution.
- Not a production reasoning quality claim.
- Not a Full Context Brain claim.
- No top-level `answer` response field; use `answer_candidate` only.
- No public response semantics named `verdict`, `truth_decision`, `resolution`, `winner`, or `canonical_truth`.
- No B14 migrations.
- No durable answer trace or provider trace persistence.
- No graph or DB mutation in the default reasoning answer path.

Example request shape:

```json
{
  "query": "What does the evidence support about this topic?",
  "scope": "same_hub_or_domain",
  "memory_types": ["fact", "decision"],
  "include_conflicts": true,
  "max_hops": 3,
  "enable_provider_synthesis": false
}
```

The exact answer-candidate wording and reasoning fields remain public-beta and may change before `1.0`. Treat B14 output as structured review assistance grounded in evidence, not as an authoritative answer, verdict, truth decision, canonical truth, winner, or conflict resolution.

---

### B15 beta graph health endpoints in v0.1.0b15

v0.1.0b15 adds read-only graph-health reporting for public-beta review of graph retrieval readiness. The B15 layer exposes Graph Health Score, Hub Recall Health, and Alias Hygiene candidate outputs using existing B15 service/models and the existing `hubs.read` permission. In this beta, the API endpoints use deterministic/static sample data; live repository reads are deferred to a later gate.

New read-only API endpoints:

```text
GET /v1/graph/health
GET /v1/hubs/{hub_id}/recall-health
GET /v1/graph/alias-candidates
```

B15 report/API output documents:

- `health_score` and component scores.
- warnings for embedding/index/searchability consistency states.
- indexing/searchability states, including missing/null embeddings and searchable/not-searchable cases.
- hub recall findings for hub-linked content that is not searchable or not retrieved.
- alias candidates that require human review.
- limitations and `non_claims` to keep the beta boundary explicit.

B15 safety and boundary rules:

- Requires the existing `hubs.read` permission.
- Deterministic/sample-data beta output; no live repository reads yet.
- Report generator is available from Python tests via `memory_lab.reports.graph_health_report`.
- Not a Full Context Brain claim.
- Not a production graph quality claim.
- Not a production reasoning quality claim.
- Not automatic graph repair.
- No graph mutation.
- No automatic entity or alias merge.
- No truth arbitration.
- No conflict resolution.
- No private CB port.
- No ask_v2 parity.
- No provider dependency or provider call requirement.
- No B15 migrations and no durable graph-health table.

Treat B15 output as deterministic review assistance for graph-health diagnostics, not as a production quality verdict, canonical truth decision, graph repair engine, or conflict-resolution system.

---

## Public beta boundaries and roadmap

This is a public beta of Context Brain Memory Lab. It includes the memory/runtime foundation, workspace isolation, API/MCP auth/RBAC, governance, graph/hub/decision primitives, deterministic retrieval paths, a minimal/noop public ask layer, B10 classify ingest wiring, retrieval memory filters, current-state resolver beta helpers, a dry-run-first classify catchup helper, B11 conflict discovery / counterfinding surfacing, B12 context packaging / evidence object layering, B13 deterministic reasoning traversal/explanation over B12 context packs, B14 evidence-grounded answer-candidate assembly via `POST /v1/reasoning/answer`, and B15 read-only graph-health diagnostics for Graph Health Score, Hub Recall Health, and Alias Hygiene candidates.

It is intentionally scoped: the public package exposes the foundation now, while the broader Context Brain layers continue to move through explicit public boundary and extraction gates.

### Safety boundaries

- **Not production multi-user tenancy yet** — auth/RBAC is implemented for local and public beta use, but hosted production tenancy still requires additional hardening, deployment guidance, and operational proof.
- **Not a hosted service** — this is a self-hosted package; bring your own PostgreSQL.
- **Public beta API** — `0.1.0b15` may still introduce breaking changes before `1.0`.
- **No OIDC/SSO or password login yet** — current authentication uses hashed API keys. External identity adapters are a future track.
- **Bounded public Memory Lab beta** — this package is not the complete private Context Brain product. Provider-backed reasoning by default, production tenancy/billing, automatic contradiction resolution, human resolution workflow, wrapper SDK/client libraries, private ask_v2 parity, and `1.0` API stability remain outside this B15 public-beta package. B14 includes `POST /v1/reasoning/answer` only as a deterministic/read-only, evidence-grounded `answer_candidate` endpoint; B15 adds deterministic/read-only graph-health diagnostics only. These are not a private ask_v2 port, truth arbiter, conflict resolver, production reasoning quality claim, production graph quality claim, graph repair engine, automatic entity merge, provider dependency, or Full Context Brain claim.

### Coming next / planned Context Brain layers

- **Reasoning over context packs** — B13 adds `POST /v1/reasoning/traverse` and `POST /v1/reasoning/explain` over B12 context packs. B14 adds `POST /v1/reasoning/answer`, which returns `answer_candidate` (not top-level `answer`) while preserving evidence refs, traversal steps, conflict warnings, limitations, and `non_claims`. The default path is deterministic/read-only, `LLM_PROVIDER=none` remains valid/default, provider-backed synthesis is opt-in only via `enable_provider_synthesis=true`, private ask_v2 parity is not claimed, and B14 does not perform truth arbitration or conflict resolution. The existing minimal/noop public ask layer via `POST /v1/ask` remains separate and is not rewritten.
- **Graph health diagnostics** — B15 adds read-only Graph Health Score, Hub Recall Health, and Alias Hygiene candidate endpoints using `hubs.read`. The B15 API uses deterministic/static sample data in this beta; live repository reads are deferred. It does not mutate the graph, merge aliases/entities, perform graph repair, claim production graph quality, call providers, arbitrate truth, resolve conflicts, or port private CB/ask_v2 behavior.
- **Classify / embed / store pipeline** — B10 includes deterministic classify ingest wiring and catchup support. Provider-backed embeddings remain optional and are not required by default.
- **Conflict discovery vs resolution** — B11 surfaces computed counterfinding and contradiction candidates, but contradiction escalation workflows, truth arbitration, automatic contradiction resolution, and human resolution loops remain outside this public beta.
- **Context packaging vs reasoning** — B12 exposes a context packaging / evidence object layer via `POST /v1/context-packs/build`; B13 adds reasoning traversal/explanation over those B12 context packs; B14 adds evidence-grounded answer-candidate assembly. These are not Full Context Brain, not a private ask_v2 port, not truth arbitration, not production reasoning quality claims, and not automatic conflict resolution.
- **Current-state and agent packaging** — B10 includes resolver helpers for current-state anchors; B12 can package current-state signals and stale/superseded items, but the package is still not Full Context Brain and does not claim production agent-context orchestration.
- **Chunk search v2** — not included in this beta.
- **Additional public schema** — B10 public migration chain is `000..030`, including classify pipeline metadata, discovered-domain support, and current-state anchors. B11 adds no migrations and no durable conflict table. B12 adds no migrations and no durable context-pack table. B13 adds no migrations and no durable reasoning table. B14 adds no migrations and no durable answer trace table. B15 adds no migrations and no durable graph-health table.

### Current integration limits

- **Provider-backed embeddings and LLM calls are optional** — deterministic/no-key paths work by default; provider-backed behavior requires explicit configuration.
- **MCP proof level** — current public proof covers MCP wrapper/tool-level auth and workspace propagation. Protocol-level MCP transport proof can be published separately.
- **External integrations are conservative** — GPT Actions and similar external integrations should be treated as read-oriented unless a write surface is explicitly documented and authorized.

---

## Runtime proven

Package readiness and workspace foundation behavior were verified in staging (`pr1a_staging`) before public release preparation:

| Check | Result |
|---|---|
| `pip install -e .` | PASS in prior public package gates; rerun required for v0.1.0b15 final proof |
| `py_compile` / import smoke | Required in final package proof |
| `python -m build` wheel + sdist | Required after version alignment |
| `twine check` | Required after build |
| API workspace context propagation smoke | PASS in Prestage 3 evidence |
| MCP workspace context propagation smoke | PASS at wrapper/tool level in Prestage 3 evidence |
| Retrieval workspace isolation smoke | PASS in Prestage 3 evidence |
| `POST /v1/ask` minimal/noop API smoke | PASS in staging with workspace/RBAC/evidence checks; rerun required for public package proof |
| `/v1/retrieval/search` + `/v1/ask` evidence contract live smoke | PASS in B9_API_LIVE_SMOKE (disposable DB, all 11 EvidenceItem fields, deterministic evidence_id, citations with rank) |
| B10 classify ingest integration | PASS in release-readiness review with disposable public-style DB |
| B10 retrieval `memory_type` / `memory_types` filter tests | PASS in release-readiness review |
| B10 current-state resolver tests | PASS in release-readiness review |
| B10 classify catchup helper tests | PASS in release-readiness review |
| B11 conflict/counterfinding API integration tests | PASS in release-readiness review with disposable public-style DB |
| B11 conflict detector and marker unit tests | PASS in release-readiness review |
| B11 migrations required | NO |
| B11 durable conflict table | NO |
| B12 context-pack API unit tests | PASS in release-readiness review (`7 passed`) |
| B12 context-pack API integration tests | PASS in release-readiness review (`11 passed`) |
| B12 migrations required | NO |
| B12 durable context-pack table | NO |
| B12 provider/LLM reasoning required | NO |
| B12 truth arbitration or automatic conflict resolution | NO |
| B13 reasoning unit/non-DB validation | PASS in release-readiness review with caveat (`11 passed`, `22 skipped` because `CB_TEST_DATABASE_URL` unset) |
| B13 prior DB-backed implementation/review evidence | PRIOR evidence only (`33 passed`), not fresh post-fix DB-backed coverage |
| B13 migrations required | NO |
| B13 durable reasoning table | NO |
| B13 provider-backed synthesis required | NO; opt-in only |
| B13 truth arbitration or automatic conflict resolution | NO |
| B13 standalone `/v1/reasoning/answer` endpoint | NO |
| B14 `POST /v1/reasoning/answer` endpoint | PASS in implementation and DB-backed review (`tests/integration/test_reasoning_answer_api.py`: 4 passed) |
| B14 DB-backed regression coverage | PASS in review (`27 passed`, `0 skipped`, `0 failed` across answer, reasoning, context-pack, conflicts integration tests) |
| B14 response field | `answer_candidate`; no top-level `answer` claim |
| B14 provider-backed synthesis required | NO; `LLM_PROVIDER=none` compatible and provider synthesis opt-in only via `enable_provider_synthesis=true` |
| B14 truth arbitration or automatic conflict resolution | NO |
| B15 Graph Health Score API endpoint | PASS in pass review (`GET /v1/graph/health`) |
| B15 Hub Recall Health API endpoint | PASS in pass review (`GET /v1/hubs/{hub_id}/recall-health`) |
| B15 Alias Hygiene candidate API endpoint | PASS in pass review (`GET /v1/graph/alias-candidates`) |
| B15 permission | `hubs.read` |
| B15 data source caveat | deterministic/static sample data in beta; no live repository reads yet |
| B15 graph mutation / automatic alias merge | NO |
| B15 truth arbitration or conflict resolution | NO |
| B15 provider calls required | NO |
| Ask provider calls required | NO |
| Provider calls required | NO |
| Disposable teardown | PASS in B9/B10 public-style evidence |

Wheel target after version alignment: `context_brain_memory_lab-0.1.0b15-py3-none-any.whl`

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
