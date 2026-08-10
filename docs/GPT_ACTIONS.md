# GPT Actions Setup — Context Brain Memory Lab

This guide covers how to connect a GPT Action (or any OpenAPI-compatible agent) to a
self-hosted OpenCB instance.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| OpenCB installed + migrated | See `docs/INSTALL.md` |
| Demo data seeded (optional) | `bash scripts/seed_demo.sh` |
| API service running | `uvicorn memory_lab.api.main:app --host 0.0.0.0 --port 8000` |
| Bearer token | Mint an API key on the server: `bash scripts/create_api_key.sh` (see §2) |
| Public HTTPS URL | GPT Actions require HTTPS. Use a reverse proxy (nginx/caddy) or ngrok for dev. |

---

## 1. Schema files

**The canonical CustomGPT integration is a matched pair — install both:**

```
openapi/customgpt-action-A-crud-decisions.openapi.yaml       (16 operations)
openapi/customgpt-action-B-discovery-curation.openapi.yaml   (19 operations)
```

**Why two files, not one:** ChatGPT Actions enforces a hard limit of under 30
tools per OpenAPI schema. OpenCB's public agent surface is 35 operations —
one schema cannot hold it. The split is a **platform constraint, not a
conceptual boundary** — A and B together are one integration, installed
together in the same CustomGPT, calling the same backend. `listHubs` and
`getHub` are deliberately present in *both* files so GPT can look up a hub
without switching actions (OpenCB decision `7c422dc5`).

- **Action A (CRUD + Decisions)** — the write-primary half: save content,
  link to hubs, create/update decisions, ask/retrieve, orientation reads.
  Covers workflows **A** (save a memory) and **D** (decision management).
- **Action B (Discovery + Graph Curation)** — the read-deep/curation half:
  hub and edge management, current-state anchors, graph inspection,
  decision lineage/conflicts. Covers workflows **B** (explore memory),
  **C** (manage hubs/edges), and **E** (deep graph inspection).

Both files' `servers` block must point to the **same host** (see §6).

For non-GPT OpenAPI clients without a tool-count limit, the full public REST
schema (29 operations, one file) remains available:

```
openapi/context-brain-actions.public.openapi.yaml
```

`scripts/deploy_openapi_dev.sh` can publish schemas to a stable URL, e.g.
`https://your-opencb-host/openapi/customgpt-action-A-crud-decisions.openapi.yaml`.

---

## 1b. GPT Instructions (system prompt)

Paste the instructions from `docs/GPT_SYSTEM_PROMPT.md` into the GPT
builder's **Instructions** field. It teaches the model to treat OpenCB as
persistent memory across conversations (not a tool to be asked permission
for), when to save vs. search, and which of the two actions has which
capability — using the real `operationId`s from A and B.

## 2. Authentication

OpenCB authenticates Bearer tokens against the `api_keys` table (SHA-256
hash match, plus subject and workspace-membership checks). There is no static
token env var on the server — a key must exist in the database.

**Server side** — enable API-key auth and mint a key:

```bash
# .env (or environment): switch off the local-dev bypass
MEMORY_LAB_AUTH_MODE=api_key

# Mint a key (prints the token ONCE — store it in a secrets manager):
bash scripts/create_api_key.sh --name "gpt-actions" --role writer
```

Action A performs writes (`createContent`, `createDecision`, etc.), so the
key needs at least `writer`. The script creates an auth subject, stores only
the key's hash, and grants membership in the default workspace (override
with `--workspace <uuid>`).

**GPT Action builder side** (set identically on both Action A and Action B):

- **Auth type:** `API Key`
- **Header name:** `Authorization`
- **Header value format:** `Bearer <your-token>`

Never use a database password or internal secret here — the Bearer token
is the only credential exposed to the action.

The Docker quickstart (`docker compose up`) runs in `local_dev_bypass` mode
and needs no token for local calls — but anything network-exposed (including
an ngrok tunnel for GPT Actions) should switch to `api_key` mode first.

---

## 3. What each action can do

**Action A — CRUD + Decisions** (16 operations):

| operationId | Use |
|---|---|
| `checkMemoryHealth` | Verify connectivity (no auth) |
| `listHubs`, `getHub` | Orientation — topic clusters (shared with B) |
| `getContentById` | Fetch one stored item incl. currency fields |
| `retrieveMemoryEvidence` | Raw ranked evidence with scores and currency |
| `answerFromMemory` | Ask questions against saved knowledge (cited answers) |
| `listDecisions`, `createDecision`, `explainDecision`, `getDecisionTimeline`, `updateDecisionStatus` | Decision CRUD and browsing |
| `getGraphSnapshot` | High-level hub/edge overview |
| `createContent`, `setQuickSummary`, `linkContentToHub` | Save new knowledge |
| `classifyContentNode` | Assign a semantic node type |

**Action B — Discovery + Graph Curation** (19 operations):

| operationId | Use |
|---|---|
| `listHubs`, `getHub` | Orientation — topic clusters (shared with A) |
| `createHub`, `updateHub` | Hub management |
| `listCurrentStateAnchors` | What is CURRENT for a scope right now |
| `listHubEdges`, `createHubEdge`, `memoryLabEdgeGet`, `updateHubEdge`, `archiveHubEdge` | Hub-to-hub edge CRUD |
| `approveInferredEdge`, `rejectInferredEdge` | Human gate for machine-proposed edges |
| `listGraphSnapshot`, `searchGraphPreview`, `loadGraphNodeFull` | Graph inspection |
| `updateNodeMetadata` | Read a content item's metadata (read-only despite the name) |
| `listDecisionsForContent`, `getDecisionLineage`, `listDecisionConflicts` | Decision relationships |

Recording a decision (the "client A writes, client B recalls" demo) takes
two Action-A calls: `createContent` with the full context (saves are
governed — substantive content passes the quality floor, throwaway
one-liners are discarded with `persisted: false`), then `createDecision`
with `title`, `decision_reason` (required), and the returned content id in
`source_content_ids`. Any other client — another GPT, an MCP agent, curl —
can then answer "what was decided and why" via `answerFromMemory` and
`explainDecision`.

---

## 4. Quick smoke test

After adding both actions, try these prompts:

```
What topics are covered in this knowledge base?
→ calls listHubs

Tell me about [topic from demo seed]
→ calls answerFromMemory or retrieveMemoryEvidence

What do you know about embeddings?
→ calls answerFromMemory with "embeddings"

Is [decision from demo seed] still current?
→ calls getContentById, then listCurrentStateAnchors on its scope
```

The prompts above each validate a single action call. The prompts below only
pass if the GPT executes a **chain across both actions** — they are the
consumer-behavior regression check (run them after every schema or
Instructions change):

```
Why did we decide [decision from demo seed], and is that still the final word?
→ retrieveMemoryEvidence (A) → listDecisionsForContent (B) on the top content_id
  → explainDecision (A) + getDecisionLineage (B)
  PASS: the answer contains the rationale AND states whether descendants
  exist. FAIL: a title-only answer, or lineage never checked.

We used to have [superseded item from demo seed] — what do we use now?
→ retrieveMemoryEvidence (A) → getContentById (A) (is_current=false)
  → listCurrentStateAnchors (B) on its current_state_scope → getContentById (A)
  PASS: old item labeled SUPERSEDED and the successor named as CURRENT.
  FAIL: the superseded item presented as the answer.

What do we know about [topic that is NOT in the knowledge base]?
→ answerFromMemory (A) (status "insufficient_evidence") → retrieveMemoryEvidence (A)
  with reworded query (no relevant results)
  PASS: "the memory has nothing on X" only after BOTH checks, with both
  named. FAIL: a fabricated answer, or "nothing" after a single call.

Save this idea and tell me how it relates to what we already have.
→ createContent (A) → loadGraphNodeFull or searchGraphPreview (B) on the new content_id
  PASS: the new item's hub memberships / neighboring nodes are reported.
```

With demo data seeded (`bash scripts/seed_demo.sh`), the knowledge base
contains content about:

- **Architecture & Decisions** — design decisions, system architecture
- **Retrieval & Embeddings** — semantic search, pgvector, KNN
- **Agent Integration** — MCP tools, HTTP transport, GPT Actions
- **Getting Started** — installation, first steps, quick start

---

## 5. MCP alternative

If your client supports MCP (Claude Code, Claude Desktop, Hermes Agent, etc.),
connect to the MCP server instead of these REST actions. All 34 MCP tools are
available with identical semantics to the REST surface, in one connection —
no 30-tool split needed, since MCP has no such platform limit.

The MCP server is a **separate process** (`python -m memory_lab.mcp.http_server`,
default `127.0.0.1:8765`) — it is not part of the docker-compose stack and not
mounted on the REST API port. A same-origin `https://your-opencb-host/mcp` URL
only exists if your reverse proxy routes it there.

Setup, env vars, auth modes, and client configuration: see
[docs/MCP.md](MCP.md).

---

## 6. Base URL

The `servers` block in both A and B uses a placeholder:

```yaml
servers:
  - url: "https://your-opencb-host"
```

Override this in the GPT Action builder with your actual deployment URL —
**set it identically on both actions**, since they call the same backend.
If your reverse proxy serves the API under a prefix (e.g. `/api`), include it.

---

## 7. Excluded endpoints

Combined, Action A and Action B cover 32 of the API's 51 non-meta routes
(some routes are reachable by more than one operationId — e.g. both
`getGraphSnapshot` in A and `listGraphSnapshot` in B read `GET
/v1/graph/snapshot`). The following remain intentionally excluded from the
GPT-facing surface:

| Category | Reason |
|---|---|
| `/admin/*` | Destructive ops (tier override, DB cleanup) — internal use only |
| `/v1/reasoning/*` | Experimental internal traversal |
| `/v1/conflicts/search` | Internal dedup tooling |
| `/v1/context-packs/build` | Internal batch packing |
| `/v1/content/batch` | Bulk ingestion — scripted use, not agent-facing |
| `/v1/retrieval/similar`, `/v1/retrieval/feedback` | DX/experimental retrieval routes |
| `/v1/escalations*` | Conflict-escalation review — human governance gate |
| `/v1/graph/health` | Operator observability, not agent-facing |
| `/v1/graph/alias-candidates` | Internal graph curation |
| `/v1/hubs/{id}/recall-health` | Operator observability |
| `/v1/audit/keywords` | Operator observability |

If you need any of these for an internal agent, add them separately from
the GPT-facing schemas.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 invalid_api_key` / `unauthenticated` | The Bearer token does not match any active key in `api_keys` — mint one with `scripts/create_api_key.sh` and check `MEMORY_LAB_AUTH_MODE=api_key` |
| `403 workspace_membership_required` | The key's subject has no membership in the target workspace — re-run `create_api_key.sh` with `--workspace <uuid>` or add a membership row |
| `{"status":"unavailable","reason":"database_url_not_configured"}` | `DATABASE_URL` not set on server |
| Empty results from `answerFromMemory` | Seed demo data: `bash scripts/seed_demo.sh` |
| `422` on `createContent` | Ensure request body is valid JSON with `content` field |
| GPT can't find a tool it expects | Check which action (A or B) has it — see §3 — both must be installed in the same CustomGPT |
| HTTPS not available | Use ngrok for local dev: `ngrok http 8000` (or `ngrok http 8088` for the Docker quickstart port) |
