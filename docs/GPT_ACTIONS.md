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
| Bearer token | Set `MEMORY_LAB_API_TOKEN` on the server; copy it for GPT Actions |
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

In the GPT Action builder:

- **Auth type:** `API Key`
- **Header name:** `Authorization`
- **Header value format:** `Bearer <your-token>`

The token is the same `MEMORY_LAB_API_TOKEN` configured on the server.
Never use a database password or internal secret here — the Bearer token
is the only credential exposed to the action.

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
→ answerFromMemory (status "no_context") → retrieveMemoryEvidence with
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

If your client supports the MCP streamable-http transport (Claude, Hermes Agent, etc.),
connect directly to the MCP endpoint instead of this REST API:

```
POST https://your-opencb-host/mcp
Authorization: Bearer <your-token>
```

All 34 MCP tools are available with identical semantics to the REST surface.
See `docs/INSTALL.md` → *MCP HTTP Transport* section.

---

## 6. Base URL

The `servers` block in the schema uses a placeholder:

```yaml
servers:
  - url: "https://your-opencb-host/api"
```

Override this in the GPT Action builder with your actual deployment URL.
The API prefix (`/api`) depends on your reverse proxy configuration — adjust as needed.

---

## 7. Excluded endpoints

The following endpoint categories are intentionally excluded from the public schema:

| Category | Reason |
|---|---|
| `/admin/*` | Destructive ops (tier override, DB cleanup) — internal use only |
| `/v1/reasoning/*` | Experimental internal traversal |
| `/v1/conflicts/*` | Internal dedup tooling |
| `/v1/context-packs/*` | Internal batch packing |
| `/v1/graph/health` | Operator observability, not agent-facing |
| `/v1/graph/alias-candidates` | Internal graph curation |
| `/v1/hubs/{id}/recall-health` | Operator observability |

If you need any of these for an internal agent, add them separately from the public schema.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `401 Unauthorized` | Check Bearer token matches `MEMORY_LAB_API_TOKEN` |
| `{"status":"unavailable","reason":"database_url_not_configured"}` | `DATABASE_URL` not set on server |
| Empty results from `query_memory` | Seed demo data: `bash scripts/seed_demo.sh` |
| `422` on `create_content` | Ensure request body is valid JSON with `content` field |
| HTTPS not available | Use ngrok for local dev: `ngrok http 8000` (or `ngrok http 8088` for the Docker quickstart port) |
