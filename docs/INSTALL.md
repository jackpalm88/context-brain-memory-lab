# Quick start (Docker Compose)

The fastest path to a working API — no Python install, no database setup, no provider keys.

## Prerequisites

- Docker ≥ 24 with Compose v2 plugin (`docker compose` — not `docker-compose`)
- Ports 5433 and 8088 free (override with `CBML_PG_PORT` / `CBML_API_PORT` in `.env`)

## 1. Clone

```bash
git clone https://github.com/jackpalm88/context-brain-memory-lab.git
cd context-brain-memory-lab
```

## 2. (Optional) copy env template

```bash
cp .env.example .env
# Edit .env if you need different ports or credentials.
```

## 3. Start the stack

```bash
docker compose up --build
```

On first run this builds the API image (~60s), starts Postgres, applies all
migrations, seeds the local-dev auth subject, and starts the API on :8088.
Subsequent runs use the cached image.

## 4. Verify

```bash
curl http://127.0.0.1:8088/health
# Expected: {"status":"ok","service":"memory-lab-api","version":"1.0.0"}
```

Or run the quickstart smoke script (requires curl + jq):

```bash
bash scripts/dx1_quickstart_smoke.sh
```

## 5. Save and query

OpenCB is a **governed** memory: every save is scored (quality, relevance,
novelty) and routed to a tier. Content below the quality floor is **discarded,
not stored** — the response says so explicitly (`"persisted": false,
"discarded": true, "tier": "discard"`). A one-line throwaway note will be
rejected; a substantive memory (a decision with its rationale, a fact with
context) passes. That is by design: the memory only keeps what is worth
retrieving later.

Save a realistic first memory:

```bash
curl -s -X POST http://127.0.0.1:8088/v1/content \
  -H 'Content-Type: application/json' \
  -d '{"content": "Architecture decision: we chose PostgreSQL with pgvector for OpenCB persistence because it keeps deterministic fallback retrieval and vector KNN in one operational store. Rationale: single backup path, mature tooling, and the deterministic core must work without embeddings. Alternatives considered: a dedicated vector DB was rejected for operational overhead in self-hosted setups."}' | jq .
```

Expected response (abridged) — check for `"created": true` and
`"persisted": true`:

```json
{
  "created": true,
  "persisted": true,
  "discarded": false,
  "scores": {"quality": 0.72, "relevance": 0.5, "novelty": 0.65, "composite": 0.622},
  "tier": "probationary",
  "content_id": "…",
  "memory_type": "decision",
  "workspace_id": "…"
}
```

Note that OpenCB classified the save as a `decision` on its own, and every
response names the workspace it wrote to.

Query it back:

```bash
curl -s -X POST http://127.0.0.1:8088/v1/retrieval/search \
  -H 'Content-Type: application/json' \
  -d '{"query": "which database did we choose and why"}' | jq '.results[0].snippet, .count'
```

Or ask a question and get a grounded, cited answer (no provider keys needed —
this is the deterministic path):

```bash
curl -s -X POST http://127.0.0.1:8088/v1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "What database did we choose for persistence and why?"}' | jq '{answer, citations, status}'
```

Asking about something the memory does not contain returns an honest empty
(`"status": "insufficient_evidence"`), never an invented answer.

## 6. (Optional) seed demo corpus

```bash
docker compose --profile demo up seed
```

Loads the DEMO-1 synthetic corpus (~10 documents) so `/v1/retrieval/search` has
something to retrieve out of the box.

## 6b. Connect an AI client

- **MCP** (Claude Code, Claude Desktop, any MCP-capable agent): see
  [docs/MCP.md](MCP.md) — all 34 tools over stdio or streamable-http.
- **GPT Actions / OpenAPI clients**: see [docs/GPT_ACTIONS.md](GPT_ACTIONS.md)
  — curated read/answer schema plus the full REST schema.
- **API keys** for network-exposed deployments: `bash scripts/create_api_key.sh`
  (the compose quickstart needs no key — it runs in local-dev bypass mode).

## 7. Tear down

```bash
docker compose down          # stop, keep data volume
docker compose down -v       # stop + wipe data volume
```

---

# Local developer setup

This guide covers installing and running Context Brain Memory Lab `1.0.0` locally. It does not cover hosted production deployment, private Context Brain parity, push/tag/PyPI publication, or public release announcements.

## Prerequisites

Required for deterministic baseline:

- Python >= 3.12
- pip

Optional runtime paths:

- PostgreSQL client/server for DB-backed persistence
- pgvector-enabled PostgreSQL for vector KNN retrieval
- Docker for the opt-in M5 live smoke throwaway pgvector DB
- runtime provider keys for opt-in OpenAI/Anthropic paths

## 1. Clone and install for development

```bash
git clone https://github.com/jackpalm88/context-brain-memory-lab.git
cd context-brain-memory-lab
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[test]"
```

Developer/build tooling:

```bash
python -m pip install -e ".[dev]"
```

## 2. Deterministic empty-env defaults

No provider key and no database are required for the deterministic baseline.

```bash
export LLM_PROVIDER=none
export EMBEDDING_PROVIDER=none
unset OPENAI_API_KEY
unset ANTHROPIC_API_KEY
unset DATABASE_URL
```

## 3. Optional Postgres runtime

```bash
export DATABASE_URL="postgresql://<user>:<password>@<host>:5432/<database>"
for f in $(ls migrations/*.sql | sort); do
  echo "Applying $f..."
  psql "$DATABASE_URL" -f "$f"
done
```

The current migration range includes `000` through `032`, covering the base public schema plus M2 Postgres persistence and M3 pgvector KNN support.

## 4. Optional provider/vector runtime

Provider-backed embeddings, pgvector retrieval, and provider-backed answer synthesis are opt-in only.

```bash
python -m pip install -e ".[openai,anthropic,pgvector]"
export MEMORY_LAB_VECTOR_EMBEDDINGS_ENABLED=true
export MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED=true
export MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED=true
export EMBEDDING_PROVIDER=openai
export LLM_PROVIDER=anthropic
export OPENAI_API_KEY="...runtime only..."
export ANTHROPIC_API_KEY="...runtime only..."
```

Do not commit `.env` files, provider keys, database passwords, or DSNs.

## 5. Start the API

```bash
python -m uvicorn memory_lab.api.main:app --host 127.0.0.1 --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
# Expected: {"status":"ok","service":"memory-lab-api","version":"1.0.0"}
```

## 6. Run tests

Source hermetic gate:

```bash
bash scripts/hermetic_test.sh
```

This gate creates a fresh isolated venv and runs deterministic tests from the source tree. It is separate from release artifact proof.

## 7. Build release artifacts

```bash
rm -rf dist
python -m build
```

Expected artifacts for `1.0.0` (dist/ is not tracked in git):

- `dist/context_brain_memory_lab-1.0.0-py3-none-any.whl`
- `dist/context_brain_memory_lab-1.0.0.tar.gz`

## 8. Clean install from built artifact

```bash
tmpvenv="$(mktemp -d /tmp/cbml-artifact-venv.XXXXXX)"
python -m venv "$tmpvenv"
"$tmpvenv/bin/python" -m pip install --upgrade pip
"$tmpvenv/bin/python" -m pip install "dist/context_brain_memory_lab-1.0.0-py3-none-any.whl[test]"
"$tmpvenv/bin/python" - <<'PY'
import importlib.metadata as metadata
import memory_lab
from memory_lab.api.main import app
assert metadata.version("context-brain-memory-lab") == "1.0.0"
assert app is not None
print("artifact import smoke PASS", metadata.version("context-brain-memory-lab"))
PY
```

## 9. Opt-in M5 live smoke

```bash
python scripts/m5_live_smoke.py
```

The live smoke uses a throwaway pgvector DB and runtime-only provider keys. It proves the real provider/vector path but is not part of the default deterministic gate.

## Troubleshooting

- Missing provider key: expected for baseline; provider paths degrade or remain disabled.
- Missing `DATABASE_URL`: expected for empty-env core; DB-backed runtime paths require explicit configuration.
- `psql` missing: install PostgreSQL client tools before applying migrations manually.
- Build backend missing: install `build`/`hatchling` or run `python -m pip install -e ".[dev]"`.
