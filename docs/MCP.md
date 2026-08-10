# MCP Setup — Context Brain Memory Lab

OpenCB exposes **34 MCP tools** (save, retrieval, grounded ask, hubs, graph,
decisions, current-state anchors) with the same semantics as the REST API.
Two transports are available:

| Transport | Entrypoint | For |
|---|---|---|
| streamable-http | `python -m memory_lab.mcp.http_server` | Network clients (Claude Code/Desktop remote MCP, agents) |
| stdio | `python -m memory_lab.mcp.server` | Clients that spawn a local process |

The MCP server is a **separate process** — it is not part of the
docker-compose stack and is not mounted on the REST API port. MCP tools do not
talk to the database directly for most operations; they call the REST API, so
a running API is required.

---

## Quick start (against the Docker quickstart stack)

Prerequisite: the compose stack from [INSTALL.md](INSTALL.md) is up
(API on `:8088`, Postgres on `:5433`), and the package is installed locally
(`pip install -e .` — the `mcp` dependency ships in the base install).

```bash
DATABASE_URL="postgresql://cbml:cbml-local-dev@127.0.0.1:5433/cbml" \
MEMORY_LAB_ENV=development \
MEMORY_LAB_HTTP_MCP_AUTH=none \
MEMORY_LAB_API_PORT=8088 \
LLM_PROVIDER=none EMBEDDING_PROVIDER=none \
python -m memory_lab.mcp.http_server
```

The server listens on `http://127.0.0.1:8765/mcp` (streamable-http,
MCP spec 2025-11-05).

`MEMORY_LAB_API_PORT=8088` matters: MCP tools proxy the REST API, which
defaults to `127.0.0.1:8000` — the Docker quickstart publishes it on `8088`.
If tools return connection errors while `tools/list` works, this wiring is
the first thing to check.

### Connect a client

Claude Code:

```bash
claude mcp add --transport http opencb http://127.0.0.1:8765/mcp
```

Any MCP-capable client: point it at `http://127.0.0.1:8765/mcp`
(add `Authorization: Bearer <token>` in `api_key` mode, see below).

### First calls

- Orientation: `list_hubs`, `memory_lab_health`.
- Ask the memory: `query_memory` — the argument is **`query`** (not
  `question`): `{"query": "What database did we choose and why?"}`. Returns a
  grounded answer with citations; deterministic, no provider keys needed.
- Save: `save_and_link_to_hub` or `memory_lab_content_create_id` (saves are
  governed — substantive content passes the quality floor, one-line throwaway
  notes are discarded with `persisted: false`).
- Decisions: `create_decision_memory` (requires `title` + `decision_reason`),
  `explain_decision`, `get_decision_lineage`, `list_decisions_for_content`.

---

## Configuration reference

| Env var | Default | Meaning |
|---|---|---|
| `MEMORY_LAB_MCP_HTTP_HOST` | `127.0.0.1` | Bind host for the HTTP transport |
| `MEMORY_LAB_MCP_HTTP_PORT` | `8765` | Bind port |
| `MEMORY_LAB_HTTP_MCP_AUTH` | `api_key` | `api_key` or `none` |
| `MEMORY_LAB_ENV` | `production` | `none` auth is refused unless this is `development` **and** the host is loopback |
| `MEMORY_LAB_MCP_DEFAULT_WORKSPACE_ID` | zero-UUID | Workspace injected in `none` mode (`CB_WORKSPACE_ID` also honored) |
| `DATABASE_URL` | — | Required in `api_key` mode (key lookup) |
| `MEMORY_LAB_API_HOST` / `MEMORY_LAB_API_PORT` / `MEMORY_LAB_API_SCHEME` | `127.0.0.1` / `8000` / `http` | Where MCP tools reach the REST API (loopback only, by design) |
| `MEMORY_LAB_API_TOKEN` (or `MEMORY_LAB_MCP_API_TOKEN`) | — | **Outbound** Bearer token the MCP tools attach when calling a REST API that runs in `api_key` mode. This is a client-side variable — the REST server itself has no static token env var |

## Authentication modes

**`none` (development only).** No token required; every request is scoped to
the default workspace. Hard-refused at startup unless
`MEMORY_LAB_ENV=development` and the bind host is loopback — this mode cannot
be exposed to a network by accident.

**`api_key` (anything network-exposed).** Requests need
`Authorization: Bearer <token>`; the token's SHA-256 is matched against the
`api_keys` table and the **workspace is resolved from the key's membership** —
any client-supplied `X-Workspace-ID` header is stripped and replaced. Mint a
key with:

```bash
bash scripts/create_api_key.sh --name "my-agent" --role writer
```

## Production notes

- Run under a supervisor (systemd unit executing
  `python -m memory_lab.mcp.http_server` with env from a protected file).
- TLS terminates at your reverse proxy; a common pattern is routing
  `https://your-host/mcp` → `127.0.0.1:8765/mcp`, which is what the
  "same host `/mcp`" URL in the OpenAPI descriptions refers to.
- Keep `MEMORY_LAB_HTTP_MCP_AUTH=api_key` for anything reachable beyond
  loopback; the server enforces this for the `none` mode on its own.
