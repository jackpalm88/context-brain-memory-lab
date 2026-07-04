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

Upload or reference the public schema file:

```
openapi/context-brain-actions.public.openapi.yaml
```

Or host it at a stable URL, e.g.:

```
https://your-opencb-host/openapi.yaml
```

---

## 2. Authentication

In the GPT Action builder:

- **Auth type:** `API Key`
- **Header name:** `Authorization`
- **Header value format:** `Bearer <your-token>`

The token is the same `MEMORY_LAB_API_TOKEN` configured on the server.
Never use a database password or internal secret here — the Bearer token
is the only credential exposed to the action.

---

## 3. Recommended actions for a first GPT

For a knowledge-retrieval GPT, enable these operations:

| operationId | Use |
|---|---|
| `health_check` | Verify connectivity |
| `query_memory` | Ask questions against saved knowledge |
| `search_raw_chunks` | Retrieve raw evidence with scores |
| `search_graph_preview` | Browse the knowledge graph cheaply |
| `list_hubs` | Show available topic clusters |
| `get_hub` | Inspect a specific hub |

For a knowledge-writing GPT, also enable:

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
→ calls list_hubs

Tell me about [topic from demo seed]
→ calls query_memory or search_raw_chunks

What do you know about embeddings?
→ calls query_memory with "embeddings"
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

All 32 MCP tools are available with identical semantics to the REST surface.
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
| HTTPS not available | Use ngrok for local dev: `ngrok http 8000` |
