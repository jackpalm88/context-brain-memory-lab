# Local developer setup

This guide covers installing and running Context Brain Memory Lab `0.2.0a1` locally. It does not cover hosted production deployment, private Context Brain parity, push/tag/PyPI publication, or public release announcements.

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
# Expected: {"status":"ok"}
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

Expected artifacts for `0.2.0a1`:

- `dist/context_brain_memory_lab-0.2.0a1-py3-none-any.whl`
- `dist/context_brain_memory_lab-0.2.0a1.tar.gz`

## 8. Clean install from built artifact

```bash
tmpvenv="$(mktemp -d /tmp/cbml-artifact-venv.XXXXXX)"
python -m venv "$tmpvenv"
"$tmpvenv/bin/python" -m pip install --upgrade pip
"$tmpvenv/bin/python" -m pip install "dist/context_brain_memory_lab-0.2.0a1-py3-none-any.whl[test]"
"$tmpvenv/bin/python" - <<'PY'
import importlib.metadata as metadata
import memory_lab
from memory_lab.api.main import app
assert metadata.version("context-brain-memory-lab") == "0.2.0a1"
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
