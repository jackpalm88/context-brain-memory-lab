# Context Brain Memory Lab (OpenCB)

**Different AI. Same brain.** OpenCB is a self-hosted, governed memory server
for AI agents: one client saves knowledge and records decisions with their
rationale; any other client — a custom GPT, Claude over MCP, a script over
REST — can later ask *what was decided and why* and get a grounded, cited
answer from the same memory.

OpenCB gives AI clients a shared memory for decisions, context and evidence —
with history, workspace isolation, and honest retrieval when the answer
isn't there. Full capability list: [docs/CAPABILITIES.md](docs/CAPABILITIES.md).

**Version** `1.0.0` · Python ≥ 3.12 · Apache-2.0 · self-hosted (Docker or pip)

## See it work (5 minutes, no API keys)

```bash
git clone https://github.com/jackpalm88/context-brain-memory-lab.git
cd context-brain-memory-lab
docker compose up --build
```

Save a decision from one "client":

```bash
curl -s -X POST http://127.0.0.1:8088/v1/content -H 'Content-Type: application/json' \
  -d '{"content": "Architecture decision: we chose PostgreSQL with pgvector for persistence because it keeps deterministic retrieval and vector KNN in one operational store. Alternatives considered: a dedicated vector DB was rejected for operational overhead."}'
```

Ask from any other client — a different terminal, a GPT Action, an MCP agent:

```bash
curl -s -X POST http://127.0.0.1:8088/v1/ask -H 'Content-Type: application/json' \
  -d '{"question": "What database did we choose and why?"}'
# → a grounded answer with citation ids, confidence, and honest
#   "insufficient_evidence" when the memory does not know.
```

Same flow as a script: `python examples/decision_recall_demo.py`.

Full walkthrough (demo corpus, decision records, teardown):
**[docs/INSTALL.md](docs/INSTALL.md)**.

## Connect your AI clients

- **MCP** (Claude Code, Claude Desktop, any MCP agent): 34 tools over stdio or
  streamable-http — **[docs/MCP.md](docs/MCP.md)**
- **Custom GPTs / GPT Actions**: two-part Action schema (A + B — split only
  because ChatGPT Actions caps schemas at 30 tools, not a conceptual split),
  with a ready-made system prompt —
  **[docs/GPT_ACTIONS.md](docs/GPT_ACTIONS.md)**,
  **[docs/GPT_SYSTEM_PROMPT.md](docs/GPT_SYSTEM_PROMPT.md)**
- **REST**: the full FastAPI surface, self-documented at `/docs` on a running
  instance; API keys for network-exposed deployments via
  `scripts/create_api_key.sh`

Architecture boundaries: [docs/ARCHITECTURE_BOUNDARIES.md](docs/ARCHITECTURE_BOUNDARIES.md).

## Project status

Public beta / release candidate `1.0.0`, feature-complete and tested
end-to-end including real provider and vector paths. This is a self-hosted
package and architecture reference — it is **not** a hosted service, not
production tenancy/billing, and not yet published to PyPI (install from
source). Known limitations and vNext items are tracked in
[docs/CAPABILITIES.md](docs/CAPABILITIES.md) and the
[CHANGELOG](CHANGELOG.md).

## Install for local development

```bash
git clone https://github.com/jackpalm88/context-brain-memory-lab.git
cd context-brain-memory-lab
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[test]"
```

Provider keys and database configuration are optional for the deterministic baseline.

```bash
export LLM_PROVIDER=none
export EMBEDDING_PROVIDER=none
```

Optional DB-backed runtime:

```bash
export DATABASE_URL="postgresql://<user>:<password>@<host>:5432/<database>"
for f in $(ls migrations/*.sql | sort); do psql "$DATABASE_URL" -f "$f"; done
```

Optional provider/vector runtime requires explicit configuration, runtime
secrets, and the relevant extras/dependencies. Do not commit provider keys or
DSNs.

```bash
export MEMORY_LAB_VECTOR_EMBEDDINGS_ENABLED=true
export MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED=true
export MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED=true
export EMBEDDING_PROVIDER=openai
export LLM_PROVIDER=anthropic
export OPENAI_API_KEY="...runtime only..."
export ANTHROPIC_API_KEY="...runtime only..."
```

## Tests and build

Deterministic source gate (fresh isolated venv, no keys, no DB):

```bash
bash scripts/hermetic_test.sh
```

Release artifacts (`dist/`, not tracked):

```bash
python -m build
```

The opt-in live smoke (`python scripts/m5_live_smoke.py`) proves the real
provider/vector path with runtime-only secrets and a throwaway pgvector DB; it
is not part of the default gate.

## Safety boundaries

- Provider-neutral by default: no OpenAI/Anthropic key required for baseline use.
- Database-neutral by default: the deterministic core runs without Postgres;
  Postgres/pgvector are opt-in runtime paths.
- Evidence-grounded outputs: reasoning endpoints return answer candidates and
  citations/evidence refs, not truth/verdict/resolution semantics.
- Private source material is not shipped as operational memory; public
  behavior is proven through committed code/tests/smokes.

## License

Apache-2.0. See [LICENSE](LICENSE).
