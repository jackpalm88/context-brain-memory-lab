# Local Developer Setup

This guide covers installing and running the public Context Brain Memory Lab package locally for development.
It does **not** cover production deployment, Docker, reverse-proxy setup, private Context Brain parity, or production MCP/GPT Actions deployment.

---

## Prerequisites

- **Python >= 3.12**
- **PostgreSQL** (local instance running)
- **psql** client (for DB creation and verification)
- **pip**

---

## 1. Clone and install

```bash
git clone https://github.com/jackpalm88/context-brain-memory-lab.git
cd context-brain-memory-lab
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
# Install runtime plus test dependencies
python -m pip install -e ".[test]"

# Or install runtime plus developer tooling
python -m pip install -e ".[dev]"
```

---

## 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` if your PostgreSQL credentials differ from the defaults.
`LLM_PROVIDER=none` and `EMBEDDING_PROVIDER=none` are safe defaults — provider keys are optional.

---

## 3. Create local database

```bash
psql -U postgres -c "CREATE DATABASE memory_lab;"
```

Adjust the PostgreSQL user and password to match your local setup.

---

## 4. Run migrations

```bash
bash scripts/dev_migrate.sh
```

This applies the available public beta migrations in sorted order. The current public schema range is `000..030`; later B18-B31 helper/contract gates do not add production/private-CB deployment requirements.

Alternatively, apply manually:

```bash
for f in $(ls migrations/*.sql | sort); do
  echo "Applying $f..."
  psql "$DATABASE_URL" -f "$f"
done
```

---

## 5. Start the API

```bash
bash scripts/dev_run_api.sh
```

Or directly:

```bash
uvicorn memory_lab.api.main:app --host 127.0.0.1 --port 8000
```

---

## 6. Health check

```bash
curl http://127.0.0.1:8000/health
# Expected: {"status":"ok"}
```

---

## 7. Create content (no provider key required)

```bash
curl -X POST http://127.0.0.1:8000/content \
  -H "Content-Type: application/json" \
  -d '{"content":"Test content for onboarding smoke.","save_purpose":"onboarding test"}'
```

With no API key set, the response will include fallback scoring fields:

- `fallback_reason`: `no_api_key`
- `scores.composite`: `0.30`
- `tier`: `transient`

This is expected behaviour — not an error.

---

## 8. Run tests

```bash
python -m pytest tests/unit -q
```

Historical B24 unit-suite evidence was approximately **644 passed, 9 skipped, 0 failed**. Later B25-B31 evidence in the milestone reports is targeted public-safe contract evidence, not a new release/build claim from this install guide.
Exact counts may change as public-beta tests are added; failures should be investigated before packaging or release gates.

Skips are expected when database-backed or provider-backed checks are not configured. This is normal for local public-beta development.

---

## 9. Start MCP server

```bash
python -m memory_lab.mcp.server
```

---

## 10. Import smoke (no DB, no provider needed)

```bash
bash scripts/dev_smoke_imports.sh
```

Should output `OK:` for the configured import-smoke modules plus the `constitutionrules.yaml` asset check. Treat any exact module count as version-specific; B25-B31 added public-safe contract/helper surfaces without changing the package version, production status, or provider/DB requirements.

---

## 11. Run the public-safe B30/B31 wrapper example

```bash
python examples/b31_supplied_text_prompt_flow_smoke.py
```

This B34 example is a public-safe, caller-supplied-text, bounded B30/B31 wrapper flow smoke. It does not perform live LLM execution, provider-backed answer generation, DB/private Context Brain access, live memory retrieval by default, API/MCP/GPT Actions runtime deployment, or build/export/release/PyPI work.

---

## B25-B31 public-safe docs note

The package version remains `0.1.0b24`, but the public docs now recognize the completed B25-B31 contract milestones:

- B25 governance state model + workspace boundary contract.
- B26 in-memory persistence backend contract.
- B27 public-safe ingestion pipeline contract.
- B28 persistence-to-retrieval handoff contract.
- B29 persisted-record-to-prompt-package handoff contract.
- B30 supplied-text-to-prompt-request flow contract.
- B31 bounded wrapper exposure for supplied-text prompt flow, including `build_supplied_text_prompt_package` and `build_supplied_text_prompt_request_shape`.

These are public-safe contract/helper layers. They do not claim runtime API/MCP/GPT Actions deployment, production readiness, live LLM execution, provider-backed answer generation, DB/private Context Brain access, live memory retrieval by default, embeddings/vector DB execution, Full/private Context Brain parity, or any release/tag/PyPI/build/export completion.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `psql: command not found` | psql not installed | Install PostgreSQL client tools |
| `DATABASE_URL not set` | `.env` missing or not sourced | `cp .env.example .env`, then re-run |
| `FATAL: password authentication failed` | Wrong PG credentials | Edit `DATABASE_URL` in `.env` |
| `Address already in use :8000` | Port taken | `PORT=8001 bash scripts/dev_run_api.sh` or kill conflicting process |
| `ANTHROPIC_API_KEY not set` warnings | Provider key absent | **Not an error.** No-key fallback scoring is active by default. |
