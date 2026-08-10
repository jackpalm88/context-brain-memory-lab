#!/usr/bin/env bash
# scripts/seed_demo.sh — DEMO-1 Public Demo Seed Corpus
#
# Populates a freshly-migrated OpenCB database with synthetic demo content so
# that a new agent or developer immediately has something to query instead of
# hitting an empty database.
#
# Design:
#   - All data is 100% synthetic — zero private or workspace-specific content.
#   - Idempotent: safe to run multiple times (ON CONFLICT DO NOTHING / DO UPDATE).
#   - Self-contained: only requires psql + CBML_DSN (or individual PG* vars).
#   - Post-seed: optional API smoke verify (if MEMORY_LAB_API_HOST is reachable).
#   - No migrations — assumes schema is already applied (000–035+).
#   - No provider calls — no embeddings, no AI enrichment.
#
# Usage:
#   CBML_DSN="postgresql://user:pass@host:port/db" bash scripts/seed_demo.sh
#   # or individual vars:
#   PGHOST=127.0.0.1 PGPORT=5432 PGUSER=cbml PGPASSWORD=cbml PGDATABASE=cbml \
#     bash scripts/seed_demo.sh
#
# Optional env:
#   SEED_WORKSPACE_ID   — target workspace UUID (default: auto-detect default)
#   MEMORY_LAB_API_HOST — if set, runs post-seed API smoke (default: skip)
#   MEMORY_LAB_API_PORT — port for API smoke (default: 8000)
#   SEED_VERIFY_ONLY    — if set, skips seed and only runs verify
#
# Exits 0 on full-pass, non-zero on any failure.

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo -e "${GREEN}  PASS${NC}  $*"; }
fail() { FAIL=$((FAIL+1)); echo -e "${RED}  FAIL${NC}  $*"; }
info() { echo -e "${CYAN}  INFO${NC}  $*"; }
hr()   { echo "────────────────────────────────────────────────────────"; }

hr
echo "  OpenCB Demo Seed (DEMO-1)"
echo "  $(date -u '+%Y-%m-%d %H:%M UTC')"
hr

# ── DSN resolution ─────────────────────────────────────────────────────────────
if [[ -n "${CBML_DSN:-}" ]]; then
    PSQL_ARGS=("$CBML_DSN")
    info "Using CBML_DSN"
else
    PSQL_ARGS=(
        -h "${PGHOST:-127.0.0.1}"
        -p "${PGPORT:-5432}"
        -U "${PGUSER:-cbml}"
        -d "${PGDATABASE:-cbml}"
    )
    [[ -n "${PGPASSWORD:-}" ]] && export PGPASSWORD
    info "Using PG* vars: host=${PGHOST:-127.0.0.1} port=${PGPORT:-5432} user=${PGUSER:-cbml} db=${PGDATABASE:-cbml}"
fi

PSQL_CMD=(psql -v ON_ERROR_STOP=1 -q "${PSQL_ARGS[@]}")

if ! "${PSQL_CMD[@]}" -c "SELECT 1" >/dev/null 2>&1; then
    fail "Cannot connect to database. Set CBML_DSN or PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE."
    exit 1
fi
ok "DB connectivity"

# ── Workspace resolution ───────────────────────────────────────────────────────
echo ""
echo "Stage 1 — Workspace"

SEED_WS_ID="${SEED_WORKSPACE_ID:-}"

if [[ -z "$SEED_WS_ID" ]]; then
    SEED_WS_ID="$("${PSQL_CMD[@]}" -t -c \
        "SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE LIMIT 1;" \
        2>/dev/null | tr -d '[:space:]')"
fi

if [[ -z "$SEED_WS_ID" ]]; then
    fail "No default workspace found. Run migrations first (migration 017 creates it)."
    exit 1
fi
ok "Workspace: $SEED_WS_ID"

if [[ -n "${SEED_VERIFY_ONLY:-}" ]]; then
    info "SEED_VERIFY_ONLY set — skipping seed, running verify only"
else

# ── Stage 2: Seed hubs ─────────────────────────────────────────────────────────
echo ""
echo "Stage 2 — Seed hubs"

"${PSQL_CMD[@]}" <<HUBSQL
INSERT INTO cb_hubs (hub_id, workspace_id, workspace_uuid, title, type, description, aliases, related_terms, status, owner_defined)
VALUES
    ('a1a1a1a1-de00-0001-0000-000000000001', '$SEED_WS_ID', '$SEED_WS_ID',
     'Architecture & Decisions', 'concept_cluster',
     'Core architectural decisions and design rationale for OpenCB.',
     ARRAY['arch','decisions','design'],
     ARRAY['architecture','decision','rationale','ADR','design choice'],
     'active', TRUE),
    ('a1a1a1a1-de00-0002-0000-000000000002', '$SEED_WS_ID', '$SEED_WS_ID',
     'Retrieval & Embeddings', 'concept_cluster',
     'Semantic search, embedding pipelines, and KNN retrieval in OpenCB.',
     ARRAY['retrieval','embeddings','search','RAG'],
     ARRAY['semantic search','KNN','vector','pgvector','embedding','cosine similarity'],
     'active', TRUE),
    ('a1a1a1a1-de00-0003-0000-000000000003', '$SEED_WS_ID', '$SEED_WS_ID',
     'Agent Integration', 'topic',
     'How AI agents connect to and use OpenCB via MCP tools and HTTP transport.',
     ARRAY['agents','MCP','integration'],
     ARRAY['MCP tool','streamable-http','Claude','Codex','agentic workflow','tool call'],
     'active', TRUE),
    ('a1a1a1a1-de00-0004-0000-000000000004', '$SEED_WS_ID', '$SEED_WS_ID',
     'Getting Started', 'topic',
     'Quickstart guide: installation, first save, first query, first hub.',
     ARRAY['quickstart','onboarding','first steps'],
     ARRAY['install','setup','tutorial','hello world','first run'],
     'active', TRUE)
ON CONFLICT (hub_id) DO UPDATE
    SET title        = EXCLUDED.title,
        description  = EXCLUDED.description,
        aliases      = EXCLUDED.aliases,
        related_terms = EXCLUDED.related_terms,
        workspace_uuid = EXCLUDED.workspace_uuid,
        updated_at   = NOW();
HUBSQL
ok "4 demo hubs seeded"

# ── Stage 3: Seed content items ────────────────────────────────────────────────
echo ""
echo "Stage 3 — Seed content items"

"${PSQL_CMD[@]}" <<CONTENTSQL
INSERT INTO content_items (content_id, workspace_id, node_type, quick_summary, content_title, content_metadata)
VALUES
    ('c0de0001-0000-0000-0000-000000000001', '$SEED_WS_ID',
     'concept',
     'OpenCB is an open-source persistent semantic memory layer for AI agents, exposing a 34-tool MCP surface over stdio and HTTP.',
     'What is OpenCB?',
     '{"domain":"general","word_count":220}'::jsonb),
    ('c0de0002-0000-0000-0000-000000000002', '$SEED_WS_ID',
     'concept',
     'OpenCB chunks saved content, generates vector embeddings, and uses KNN (pgvector cosine) to rank chunks by query similarity.',
     'How semantic retrieval works in OpenCB',
     '{"domain":"general","word_count":310}'::jsonb),
    ('c0de0003-0000-0000-0000-000000000003', '$SEED_WS_ID',
     'fact',
     'OpenCB exposes 34 MCP tools: save_memory, query_memory, create_hub, link_content_to_hub, create_hub_edge, list_hubs, get_hub, search_raw_chunks, and more.',
     'OpenCB MCP tool surface (34 tools)',
     '{"domain":"general","word_count":180}'::jsonb),
    ('c0de0004-0000-0000-0000-000000000004', '$SEED_WS_ID',
     'playbook',
     'Four steps: (1) clone + pip install -e .[test], (2) run migrations, (3) bash scripts/seed_demo.sh, (4) connect any MCP-compatible agent.',
     'OpenCB Quickstart: install, migrate, seed, run',
     '{"domain":"general","word_count":260}'::jsonb),
    ('c0de0005-0000-0000-0000-000000000005', '$SEED_WS_ID',
     'decision',
     'Chose pgvector (in-Postgres extension) over a dedicated vector DB to minimize operational complexity and keep semantic search co-located with relational data.',
     'ADR-001: pgvector over external vector store',
     '{"domain":"general","word_count":290}'::jsonb),
    ('c0de0006-0000-0000-0000-000000000006', '$SEED_WS_ID',
     'concept',
     'Every saved item is routed to a tier (ephemeral / session / persistent) based on composite quality x relevance x novelty score. Persistent items survive across sessions.',
     'OpenCB governance tiers: ephemeral, session, persistent',
     '{"domain":"general","word_count":240}'::jsonb),
    ('c0de0007-0000-0000-0000-000000000007', '$SEED_WS_ID',
     'fact',
     'All content, hubs, edges, and decisions are scoped to a workspace_id UUID. Cross-workspace leakage is blocked at the DB query layer.',
     'Workspace isolation in OpenCB',
     '{"domain":"general","word_count":195}'::jsonb),
    ('c0de0008-0000-0000-0000-000000000008', '$SEED_WS_ID',
     'concept',
     'OpenCB exposes its 34 MCP tools over streamable-http (MCP spec 2025-11-05) via FastMCP. Bearer token auth resolves workspace from api_keys table.',
     'MCP streamable-http transport in OpenCB',
     '{"domain":"general","word_count":230}'::jsonb)
ON CONFLICT (content_id) DO UPDATE
    SET node_type     = EXCLUDED.node_type,
        quick_summary = EXCLUDED.quick_summary,
        content_title = EXCLUDED.content_title,
        updated_at    = NOW();
CONTENTSQL
ok "8 demo content items seeded"

# ── Stage 4: Seed content chunks ───────────────────────────────────────────────
echo ""
echo "Stage 4 — Seed content chunks"

"${PSQL_CMD[@]}" <<CHUNKSQL
INSERT INTO content_chunks (chunk_id, content_id, chunk_index, chunk_text, word_count)
VALUES
    ('c0dec001-0000-0000-0000-000000000001', 'c0de0001-0000-0000-0000-000000000001', 0,
     'OpenCB is an open-source persistent semantic memory layer for AI agents. It exposes a 34-tool MCP surface over stdio and streamable-http transport. Agents save content, create hubs, link content to hubs, and query by semantic similarity. OpenCB is designed for long-term agent memory across sessions and is accessible via the Model Context Protocol.',
     53),
    ('c0dec002-0000-0000-0000-000000000002', 'c0de0002-0000-0000-0000-000000000002', 0,
     'Semantic retrieval in OpenCB works by chunking saved content into paragraph-sized segments, generating vector embeddings per chunk, and using KNN search with pgvector cosine similarity to rank chunks by proximity to the query embedding. When EMBEDDING_PROVIDER is unset, a deterministic keyword fallback is used. Results include hub-match signals for navigation.',
     50),
    ('c0dec003-0000-0000-0000-000000000003', 'c0de0003-0000-0000-0000-000000000003', 0,
     'OpenCB exposes exactly 34 MCP tools. Key tools include: save_memory, query_memory, search_raw_chunks, search_graph_preview, load_graph_node_full, create_hub, list_hubs, get_hub, update_hub, link_content_to_hub, save_and_link_to_hub, create_hub_edge, list_hub_edges, get_graph_snapshot, create_decision_memory, list_decisions, explain_decision, health_check, and classify_content_node.',
     55),
    ('c0dec004-0000-0000-0000-000000000004', 'c0de0004-0000-0000-0000-000000000004', 0,
     'OpenCB quickstart in four steps: step one is clone the repo and run pip install -e with the test extra. Step two is start PostgreSQL with the pgvector extension enabled and run all migrations in order. Step three is run bash scripts/seed_demo.sh to populate this demo corpus. Step four is start the API server and connect any MCP-compatible agent via stdio or streamable-http transport.',
     60),
    ('c0dec005-0000-0000-0000-000000000005', 'c0de0005-0000-0000-0000-000000000005', 0,
     'Architecture decision ADR-001: OpenCB uses pgvector, a PostgreSQL extension, for vector similarity search rather than a dedicated external vector database. This keeps semantic search co-located with relational data, eliminates a separate operational component, and leverages ACID guarantees from PostgreSQL. The tradeoff accepted is reduced specialization for very-high-scale vector workloads versus purpose-built vector stores.',
     57),
    ('c0dec006-0000-0000-0000-000000000006', 'c0de0006-0000-0000-0000-000000000006', 0,
     'OpenCB uses a three-tier governance system for saved content. Ephemeral tier holds low-score items discarded after session. Session tier holds medium-score items surviving the session. Persistent tier holds high composite-score items surviving indefinitely and included in semantic retrieval. The composite score is computed from quality, relevance, and novelty sub-scores provided by the scoring pipeline.',
     57),
    ('c0dec007-0000-0000-0000-000000000007', 'c0de0007-0000-0000-0000-000000000007', 0,
     'All data in OpenCB is scoped to a workspace_id UUID. Content items, hubs, hub edges, hub-content links, and decisions all carry a workspace_id foreign key. The API enforces workspace boundaries at the query layer so a request for workspace A cannot return data from workspace B. The default workspace is created automatically by migration 017 during first setup.',
     57),
    ('c0dec008-0000-0000-0000-000000000008', 'c0de0008-0000-0000-0000-000000000008', 0,
     'The OpenCB MCP streamable-http transport exposes all 34 tools over HTTP using the MCP specification 2025-11-05 streamable-http profile. Authentication uses Bearer tokens resolved against the api_keys table. The workspace_id is injected by the MCPBearerAuthMiddleware from the resolved API key record. The stdio transport remains fully functional alongside HTTP with identical tool contracts.',
     55)
ON CONFLICT (chunk_id) DO UPDATE
    SET chunk_text  = EXCLUDED.chunk_text,
        word_count  = EXCLUDED.word_count,
        chunk_index = EXCLUDED.chunk_index;
CHUNKSQL
ok "8 demo chunks seeded"

# ── Stage 5: Hub-content links ─────────────────────────────────────────────────
echo ""
echo "Stage 5 — Hub-content links"

"${PSQL_CMD[@]}" <<LINKSQL
INSERT INTO cb_hub_content (hub_id, content_id)
VALUES
    ('a1a1a1a1-de00-0004-0000-000000000004', 'c0de0001-0000-0000-0000-000000000001'),
    ('a1a1a1a1-de00-0004-0000-000000000004', 'c0de0004-0000-0000-0000-000000000004'),
    ('a1a1a1a1-de00-0002-0000-000000000002', 'c0de0002-0000-0000-0000-000000000002'),
    ('a1a1a1a1-de00-0002-0000-000000000002', 'c0de0006-0000-0000-0000-000000000006'),
    ('a1a1a1a1-de00-0001-0000-000000000001', 'c0de0005-0000-0000-0000-000000000005'),
    ('a1a1a1a1-de00-0001-0000-000000000001', 'c0de0007-0000-0000-0000-000000000007'),
    ('a1a1a1a1-de00-0003-0000-000000000003', 'c0de0003-0000-0000-0000-000000000003'),
    ('a1a1a1a1-de00-0003-0000-000000000003', 'c0de0008-0000-0000-0000-000000000008')
ON CONFLICT DO NOTHING;
LINKSQL
ok "8 hub-content links seeded"

# ── Stage 6: Hub edges ─────────────────────────────────────────────────────────
echo ""
echo "Stage 6 — Hub edges"

# edge_key convention: sorted(src,tgt)|type for symmetric; src|tgt|type for directional
"${PSQL_CMD[@]}" <<EDGESQL
INSERT INTO cb_hub_edges (source_hub_id, target_hub_id, type, status, origin, edge_key)
VALUES
    ('a1a1a1a1-de00-0004-0000-000000000004',
     'a1a1a1a1-de00-0003-0000-000000000003',
     'supports', 'manual', 'manual',
     'a1a1a1a1-de00-0003-0000-000000000003|a1a1a1a1-de00-0004-0000-000000000004|supports'),
    ('a1a1a1a1-de00-0001-0000-000000000001',
     'a1a1a1a1-de00-0002-0000-000000000002',
     'supports', 'manual', 'manual',
     'a1a1a1a1-de00-0001-0000-000000000001|a1a1a1a1-de00-0002-0000-000000000002|supports'),
    ('a1a1a1a1-de00-0003-0000-000000000003',
     'a1a1a1a1-de00-0002-0000-000000000002',
     'related', 'manual', 'manual',
     'a1a1a1a1-de00-0002-0000-000000000002|a1a1a1a1-de00-0003-0000-000000000003|related')
ON CONFLICT (edge_key) WHERE archived_at IS NULL DO NOTHING;
EDGESQL
ok "3 hub edges seeded"

fi  # end SEED_VERIFY_ONLY

# ── Stage 7: Verify counts ─────────────────────────────────────────────────────
echo ""
echo "Stage 7 — Verify counts"

read -r HUBS CONTENT CHUNKS LINKS EDGES < <(
    "${PSQL_CMD[@]}" -tA -F" " <<VERIFYSQL
SELECT
    (SELECT COUNT(*) FROM cb_hubs        WHERE hub_id::text LIKE 'a1a1a1a1-de00-%')::int,
    (SELECT COUNT(*) FROM content_items  WHERE content_id::text LIKE 'c0de0%')::int,
    (SELECT COUNT(*) FROM content_chunks WHERE chunk_id::text   LIKE 'c0dec0%')::int,
    (SELECT COUNT(*) FROM cb_hub_content WHERE hub_id::text     LIKE 'a1a1a1a1-de00-%')::int,
    (SELECT COUNT(*) FROM cb_hub_edges   WHERE edge_key         LIKE '%a1a1a1a1-de00-%')::int;
VERIFYSQL
)

[[ "${HUBS}"    == "4" ]] && ok "Hubs: 4/4"    || fail "Hubs: expected 4, got '${HUBS}'"

# list_hubs filters on workspace_uuid — a NULL there makes seeded hubs invisible
# to GET /v1/hubs even though the rows exist (release-truth audit 2026-08-10, P0-3).
HUBS_NO_WS="$("${PSQL_CMD[@]}" -tA -c \
    "SELECT COUNT(*) FROM cb_hubs WHERE hub_id::text LIKE 'a1a1a1a1-de00-%' AND workspace_uuid IS NULL;")"
[[ "${HUBS_NO_WS}" == "0" ]] \
    && ok "Hubs visible to list_hubs (workspace_uuid set on all 4)" \
    || fail "Hubs invisible to GET /v1/hubs: ${HUBS_NO_WS} seeded hub(s) have NULL workspace_uuid"
[[ "${CONTENT}" == "8" ]] && ok "Content: 8/8" || fail "Content: expected 8, got '${CONTENT}'"
[[ "${CHUNKS}"  == "8" ]] && ok "Chunks: 8/8"  || fail "Chunks: expected 8, got '${CHUNKS}'"
[[ "${LINKS}"   == "8" ]] && ok "Links: 8/8"   || fail "Links: expected 8, got '${LINKS}'"
[[ "${EDGES}"   == "3" ]] && ok "Edges: 3/3"   || fail "Edges: expected 3, got '${EDGES}'"

# ── Stage 8: Optional API smoke ────────────────────────────────────────────────
if [[ -n "${MEMORY_LAB_API_HOST:-}" ]]; then
    echo ""
    echo "Stage 8 — API smoke (${MEMORY_LAB_API_HOST}:${MEMORY_LAB_API_PORT:-8000})"
    API_BASE="http://${MEMORY_LAB_API_HOST}:${MEMORY_LAB_API_PORT:-8000}"
    if command -v curl >/dev/null 2>&1; then
        HEALTH="$(curl -sf "$API_BASE/health" 2>/dev/null || echo '{}')"
        echo "$HEALTH" | grep -q '"status"' \
            && ok "API /health responds" \
            || fail "API /health did not return expected JSON"
        HUB_RESP="$(curl -sf "$API_BASE/v1/hubs?status=active" 2>/dev/null || echo '{}')"
        echo "$HUB_RESP" | grep -q 'Getting Started' \
            && ok "API /v1/hubs lists demo hub" \
            || fail "API /v1/hubs missing demo hub"
    else
        info "curl not available — skipping API smoke"
    fi
fi

# ── Report ─────────────────────────────────────────────────────────────────────
echo ""
hr
TOTAL=$((PASS + FAIL))
if [[ "$FAIL" -eq 0 ]]; then
    echo -e "${GREEN}  VERDICT: PASS ($PASS/$TOTAL)${NC}"
    echo "  4 hubs · 8 content · 8 chunks · 8 links · 3 edges"
else
    echo -e "${RED}  VERDICT: FAIL ($PASS/$TOTAL — $FAIL failures)${NC}"
fi
hr
echo ""

exit "$FAIL"
