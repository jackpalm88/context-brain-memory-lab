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

## 1. Schema URL

**Recommended for GPT Actions:** the MINIMAL curated schema — 10 well-described
read/answer operations. GPT tool selection is measurably better with a small
surface than with the full API:

```
openapi/gpt-actions.minimal.openapi.yaml
```

The full public REST schema (including write paths) remains available for
wider non-MCP integrations:

```
openapi/context-brain-actions.public.openapi.yaml
```

Host either at a stable HTTPS URL, e.g.:

```
https://your-opencb-host/openapi.yaml
```

(`scripts/deploy_openapi_dev.sh` publishes both to the api-dev host.)

---

## 1b. GPT Instructions (system prompt)

Paste the ready-made instructions from `docs/GPT_SYSTEM_PROMPT.md` into the
GPT builder's **Instructions** field — it encodes the OpenCB epistemics
(grounded answers only, currency discipline, lineage before finality, honest
empties) and the action-selection playbook for the 10 minimal operations.

## 2. Authentication

OpenCB authenticates Bearer tokens against the `api_keys` table (SHA-256
hash match, plus subject and workspace-membership checks). There is no static
token env var on the server — a key must exist in the database.

**Server side** — enable API-key auth and mint a key:

```bash
# .env (or environment): switch off the local-dev bypass
MEMORY_LAB_AUTH_MODE=api_key

# Mint a key (prints the token ONCE — store it in a secrets manager):
bash scripts/create_api_key.sh --name "gpt-actions" --role reader
```

Use `--role writer` for a knowledge-writing GPT. The script creates an auth
subject, stores only the key's hash, and grants membership in the default
workspace (override with `--workspace <uuid>`).

**GPT Action builder side:**

- **Auth type:** `API Key`
- **Header name:** `Authorization`
- **Header value format:** `Bearer <your-token>`

Never use a database password or internal secret here — the Bearer token
is the only credential exposed to the action.

The Docker quickstart (`docker compose up`) runs in `local_dev_bypass` mode
and needs no token for local calls — but anything network-exposed (including
an ngrok tunnel for GPT Actions) should switch to `api_key` mode first.

---

## 3. The minimal action set (what the recommended schema contains)

`gpt-actions.minimal.openapi.yaml` ships exactly these 10 read/answer
operations (camelCase operationIds; all marked `x-openai-isConsequential:
false` so GPT never interrupts for confirmation):

| operationId | Use |
|---|---|
| `checkMemoryHealth` | Verify connectivity (no auth) |
| `answerFromMemory` | Ask questions against saved knowledge (cited answers) |
| `retrieveMemoryEvidence` | Raw ranked evidence with scores and currency |
| `getContentById` | Fetch one stored item incl. currency fields |
| `listHubs` | Show available topic clusters |
| `listDecisions` | List tracked decisions |
| `explainDecision` | Full decision rationale |
| `getDecisionLineage` | What replaced what — the supersession chain |
| `listCurrentStateAnchors` | What is CURRENT for a scope right now (CF-003) |
| `listDecisionsForContent` | Which decisions rest on this content (CF-002) |

For a knowledge-WRITING GPT, import the full schema instead and additionally
enable:

| operationId | Use |
|---|---|
| `create_content` | Save new knowledge |
| `create_hub` | Create a new topic cluster |
| `link_content_to_hub` | Attach content to a hub |
| `create_decision_memory` | Record a decision with rationale |

Recording a decision (the "client A writes, client B recalls" demo) takes two
calls: `create_content` with the full context (saves are governed — substantive
content passes the quality floor, throwaway one-liners are discarded with
`persisted: false`), then `create_decision_memory` with `title`,
`decision_reason` (required), and the returned content id in
`source_content_ids`. Any other client — another GPT, an MCP agent, curl —
can then answer "what was decided and why" via `query_memory`/`answerFromMemory`
and `explain_decision`.

---

## 4. Quick smoke test

After adding the action, try these prompts:

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

The prompts above each validate a single action. The prompts below only pass
if the GPT executes a **chain** — they are the consumer-behavior regression
check (run them after every schema or Instructions change):

```
Why did we decide [decision from demo seed], and is that still the final word?
→ retrieveMemoryEvidence → listDecisionsForContent on the top content_id
  → explainDecision + getDecisionLineage
  PASS: the answer contains the rationale AND states whether descendants
  exist. FAIL: a title-only answer, or lineage never checked.

We used to have [superseded item from demo seed] — what do we use now?
→ retrieveMemoryEvidence → getContentById (is_current=false)
  → listCurrentStateAnchors on its current_state_scope → getContentById
  PASS: old item labeled SUPERSEDED and the successor named as CURRENT.
  FAIL: the superseded item presented as the answer.

What do we know about [topic that is NOT in the knowledge base]?
→ answerFromMemory (status "insufficient_evidence") → retrieveMemoryEvidence with
  reworded query (no relevant results)
  PASS: "the memory has nothing on X" only after BOTH checks, with both
  named. FAIL: a fabricated answer, or "nothing" after a single call.
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
connect to the MCP server instead of this REST API. All 34 MCP tools are
available with identical semantics to the REST surface.

The MCP server is a **separate process** (`python -m memory_lab.mcp.http_server`,
default `127.0.0.1:8765`) — it is not part of the docker-compose stack and not
mounted on the REST API port. A same-origin `https://your-opencb-host/mcp` URL
only exists if your reverse proxy routes it there.

Setup, env vars, auth modes, and client configuration: see
[docs/MCP.md](MCP.md).

---

## 6. Base URL

The `servers` block in both schemas uses a placeholder:

```yaml
servers:
  - url: "https://your-opencb-host"
```

Override this in the GPT Action builder with your actual deployment URL.
If your reverse proxy serves the API under a prefix (e.g. `/api`), include it.

---

## 7. Excluded endpoints

The following endpoint categories are intentionally excluded from the public schema:

| Category | Reason |
|---|---|
| `/admin/*` | Destructive ops (tier override, DB cleanup) — internal use only |
| `/v1/reasoning/*` | Experimental internal traversal |
| `/v1/conflicts/*` | Internal dedup tooling |
| `/v1/context-packs/*` | Internal batch packing |
| `/v1/content/batch` | Bulk ingestion — scripted use, not agent-facing |
| `/v1/retrieval/similar`, `/v1/retrieval/feedback` | DX/experimental retrieval routes |
| `/v1/escalations*` | Conflict-escalation review — human governance gate |
| `/v1/edges/inferred/approve`, `/v1/edges/inferred/reject` | Edge-inference review — human governance gate |
| `PATCH /v1/edges/{id}` | Graph curation — operator use |
| `/v1/graph/health` | Operator observability, not agent-facing |
| `/v1/graph/alias-candidates` | Internal graph curation |
| `/v1/hubs/{id}/recall-health` | Operator observability |
| `/v1/audit/keywords` | Operator observability |

If you need any of these for an internal agent, add them separately from the public schema.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 invalid_api_key` / `unauthenticated` | The Bearer token does not match any active key in `api_keys` — mint one with `scripts/create_api_key.sh` and check `MEMORY_LAB_AUTH_MODE=api_key` |
| `403 workspace_membership_required` | The key's subject has no membership in the target workspace — re-run `create_api_key.sh` with `--workspace <uuid>` or add a membership row |
| `{"status":"unavailable","reason":"database_url_not_configured"}` | `DATABASE_URL` not set on server |
| Empty results from `query_memory` | Seed demo data: `bash scripts/seed_demo.sh` |
| `422` on `create_content` | Ensure request body is valid JSON with `content` field |
| HTTPS not available | Use ngrok for local dev: `ngrok http 8000` (or `ngrok http 8088` for the Docker quickstart port) |
