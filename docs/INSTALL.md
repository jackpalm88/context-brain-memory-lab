# Local Developer Setup

This guide covers installing and running Context Brain Memory Lab locally for development.
It does **not** cover production deployment, Docker, or reverse-proxy setup.

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

This applies `migrations/000_base_schema.sql` through `016_add_governance_events.sql` in sorted order.

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

Latest B24 unit-suite evidence is approximately **644 passed, 9 skipped, 0 failed**.
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

Should output `OK:` for all 7 modules plus the `constitutionrules.yaml` asset check.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `psql: command not found` | psql not installed | Install PostgreSQL client tools |
| `DATABASE_URL not set` | `.env` missing or not sourced | `cp .env.example .env`, then re-run |
| `FATAL: password authentication failed` | Wrong PG credentials | Edit `DATABASE_URL` in `.env` |
| `Address already in use :8000` | Port taken | `PORT=8001 bash scripts/dev_run_api.sh` or kill conflicting process |
| `ANTHROPIC_API_KEY not set` warnings | Provider key absent | **Not an error.** No-key fallback scoring is active by default. |
