#!/usr/bin/env bash
# scripts/install_smoke.sh — INSTALL-1 Installation Smoke (Engineering Quality Asset)
#
# Proves OpenCB can be installed and smoke-tested reproducibly from a clean checkout.
# One command: bash scripts/install_smoke.sh
#
# Stages:
#   1  Environment check (Python ≥ 3.12, docker, psql, pip)
#   2  Dependency check (pip install -e . idempotent; check imports)
#   3  Hermetic application smoke (no DB, no live server, TestClient)
#       SM-1  Module imports
#       SM-2  App factory + routes
#       SM-3  /health
#       SM-4  Content create → governance envelope
#       SM-5  Content get
#       SM-6  query_memory → six signals
#       SM-7  retrieval_search → deterministic list
#       SM-8  MCP tool registry (32 tools, all callable)
#       SM-9  Cross-workspace isolation
#       SM-10 Governance tier routing
#       SM-11 save_and_link_to_hub
#   4  Migrations smoke (ephemeral pgvector Docker: schema applies cleanly)
#   5  Full hermetic gate (pytest tests/unit/)
#   6  Report
#
# Exits 0 on full-pass, non-zero on any failure.
# No DB credentials required for stages 1-3 and 5.
# Stage 4 requires docker (pgvector/pgvector:pg16 image must be pullable).
# Pass --skip-migrations to omit stage 4.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKIP_MIGRATIONS="${SKIP_MIGRATIONS:-}"
for arg in "$@"; do [[ "$arg" == "--skip-migrations" ]] && SKIP_MIGRATIONS=1; done

PASS=0; FAIL=0; STAGES_FAILED=()
GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'

ok()   { PASS=$((PASS+1)); echo -e "${GREEN}  PASS${NC}  $*"; }
fail() { FAIL=$((FAIL+1)); STAGES_FAILED+=("$*"); echo -e "${RED}  FAIL${NC}  $*"; }
hr()   { echo "────────────────────────────────────────────────────────"; }

hr
echo "  OpenCB Installation Smoke (INSTALL-1)"
echo "  Repo: $REPO_ROOT"
echo "  $(date -u '+%Y-%m-%d %H:%M UTC')"
hr

# ── Stage 1: Environment ──────────────────────────────────────────────────────
echo ""
echo "Stage 1 — Environment"

# Python ≥ 3.12
if command -v python3 >/dev/null 2>&1; then
    PYVER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    PYMAJ="$(python3 -c 'import sys; print(sys.version_info.major)')"
    PYMIN="$(python3 -c 'import sys; print(sys.version_info.minor)')"
    if [[ "$PYMAJ" -ge 3 && "$PYMIN" -ge 12 ]]; then
        ok "Python $PYVER (≥ 3.12)"
    else
        fail "Python $PYVER — need ≥ 3.12"
    fi
else
    fail "python3 not found"
fi

# pip
if python3 -m pip --version >/dev/null 2>&1; then
    ok "pip available"
else
    fail "pip not available"
fi

# docker (only required for stage 4)
if command -v docker >/dev/null 2>&1; then
    ok "docker available ($(docker --version | head -1))"
else
    if [[ -z "$SKIP_MIGRATIONS" ]]; then
        echo "  WARN  docker not found — stage 4 (migrations) will be skipped"
        SKIP_MIGRATIONS=1
    fi
fi

# psql (only required for stage 4)
if [[ -z "$SKIP_MIGRATIONS" ]]; then
    if ! command -v psql >/dev/null 2>&1; then
        echo "  WARN  psql not found — stage 4 (migrations) will be skipped"
        SKIP_MIGRATIONS=1
    fi
fi

# ── Stage 2: Dependency install ───────────────────────────────────────────────
echo ""
echo "Stage 2 — Dependencies"

cd "$REPO_ROOT"

# Check installed version; attempt install only if version mismatch.
# On Debian/Ubuntu externally-managed environments pip install may be blocked —
# if imports succeed anyway (editable install or site-packages), treat as OK.
INSTALLED_VER="$(python3 -m pip show context-brain-memory-lab 2>/dev/null | grep ^Version | awk '{print $2}')"
PYPROJECT_VER="$(grep '^version' pyproject.toml | head -1 | grep -oP '"\K[^"]+')"
if [[ "$INSTALLED_VER" == "$PYPROJECT_VER" ]]; then
    ok "context-brain-memory-lab $INSTALLED_VER already installed"
else
    echo "  INFO  version mismatch: installed=${INSTALLED_VER:-none} pyproject=$PYPROJECT_VER — verifying imports"
    if python3 -c "import memory_lab.api, memory_lab.mcp, memory_lab.governance" 2>/dev/null; then
        ok "Imports OK (installed=$INSTALLED_VER — editable/site-packages path active)"
    else
        echo "  INFO  attempting pip install -e .[test] with --break-system-packages"
        if python3 -m pip install -q --break-system-packages -e ".[test]" 2>&1; then
            ok "pip install -e .[test] succeeded"
        else
            fail "Imports failed and pip install failed — check PYTHONPATH or venv"
        fi
    fi
fi

# Core imports
if python3 - <<'PYEOF' 2>/dev/null
import memory_lab.graph, memory_lab.api, memory_lab.mcp, memory_lab.bootstrap
import memory_lab.decisions, memory_lab.governance, memory_lab.ingestion
from memory_lab.governance.tier_router import route as tier_route
from memory_lab.mcp.tools import APPROVED_TOOLS
print("imports_ok")
PYEOF
then
    ok "All memory_lab subpackage imports"
else
    fail "One or more memory_lab imports failed"
fi

# ── Stage 3: Hermetic application smoke ───────────────────────────────────────
echo ""
echo "Stage 3 — Hermetic Application Smoke (no DB, no live server)"

SMOKE_OUT="$(PYTHONPATH="$REPO_ROOT" python3 "$SCRIPT_DIR/install_smoke_app.py" 2>&1)"
SMOKE_RC=$?

echo "$SMOKE_OUT"
if [[ "$SMOKE_RC" -eq 0 ]]; then
    ok "Hermetic app smoke (SM-1..SM-11) all passed"
else
    fail "Hermetic app smoke: one or more checks failed (exit=$SMOKE_RC)"
fi

# ── Stage 4: Migrations smoke ─────────────────────────────────────────────────
echo ""
echo "Stage 4 — Migrations (ephemeral pgvector)"

if [[ -n "$SKIP_MIGRATIONS" ]]; then
    echo "  SKIP  Stage 4 skipped (--skip-migrations or docker/psql unavailable)"
else
    MIG_NAME="cbml_install_smoke_$$"
    MIG_PORT=55932
    MIG_IMG="pgvector/pgvector:pg16"

    cleanup_mig() { docker rm -f "$MIG_NAME" >/dev/null 2>&1 || true; }
    trap cleanup_mig EXIT INT TERM

    docker rm -f "$MIG_NAME" >/dev/null 2>&1 || true
    echo "  INFO  spinning $MIG_IMG as $MIG_NAME on 127.0.0.1:$MIG_PORT"
    if ! docker run -d --name "$MIG_NAME" \
        -e POSTGRES_USER=cbml -e POSTGRES_PASSWORD=cbml_smoke -e POSTGRES_DB=cbml_smoke \
        -p "127.0.0.1:${MIG_PORT}:5432" "$MIG_IMG" >/dev/null 2>&1; then
        fail "docker run failed for $MIG_IMG"
    else
        # Wait ready
        READY=0
        for i in $(seq 1 30); do
            if docker exec "$MIG_NAME" pg_isready -U cbml -d cbml_smoke >/dev/null 2>&1; then
                READY=1; echo "  INFO  postgres ready after ${i}s"; break
            fi
            sleep 1
        done

        if [[ "$READY" -eq 0 ]]; then
            fail "postgres did not become ready within 30s"
        else
            MIG_FAIL=0
            for f in $(ls "$REPO_ROOT"/migrations/*.sql | sort); do
                if ! PGPASSWORD=cbml_smoke psql -q -v ON_ERROR_STOP=1 \
                    -h 127.0.0.1 -p "$MIG_PORT" -U cbml -d cbml_smoke -f "$f" >/dev/null 2>&1; then
                    echo "  FAIL  migration: $f" >&2
                    MIG_FAIL=1
                fi
            done
            if [[ "$MIG_FAIL" -eq 0 ]]; then
                MIG_COUNT="$(ls "$REPO_ROOT"/migrations/*.sql | wc -l | tr -d ' ')"
                ok "All $MIG_COUNT migrations applied cleanly"
            else
                fail "One or more migrations failed"
            fi
        fi
        docker rm -f "$MIG_NAME" >/dev/null 2>&1 || true
        trap - EXIT INT TERM
    fi
fi

# ── Stage 5: Full hermetic gate ───────────────────────────────────────────────
echo ""
echo "Stage 5 — Full Hermetic Gate (pytest tests/unit/)"

GATE_OUT="$(cd "$REPO_ROOT" && python3 -m pytest -q tests/unit/ 2>&1 | tail -3)"
GATE_RC=$?
echo "  $GATE_OUT"
if [[ "$GATE_RC" -eq 0 ]]; then
    ok "Hermetic gate: all unit tests passed"
else
    fail "Hermetic gate: tests failed (exit=$GATE_RC)"
fi

# ── Stage 6: Report ───────────────────────────────────────────────────────────
echo ""
hr
TOTAL=$((PASS + FAIL))
if [[ "$FAIL" -eq 0 ]]; then
    echo -e "${GREEN}  VERDICT: PASS ($PASS/$TOTAL)${NC}"
else
    echo -e "${RED}  VERDICT: FAIL ($PASS/$TOTAL — $FAIL failures)${NC}"
    for s in "${STAGES_FAILED[@]}"; do echo "    ✗  $s"; done
fi
hr

exit "$FAIL"
