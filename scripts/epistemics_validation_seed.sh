#!/usr/bin/env bash
# scripts/epistemics_validation_seed.sh — opencb-epistemics validation fixture
#
# Seeds the three-fragment scenario the opencb-epistemics skill's validation
# gate runs against (docs/EPISTEMICS_VALIDATION.md, scenarios E1-E4):
#   (a) a CURRENT item,
#   (b) its SUPERSEDED predecessor, linked via a current-state anchor,
#   (c) a weak, uncorroborated fragment adjacent to the topic
#       (no hub link, thin metadata -> low-trust retrieval).
#
# Design (mirrors scripts/seed_demo.sh):
#   - 100% synthetic content, deterministic UUIDs (e9e0...).
#   - Idempotent: ON CONFLICT DO UPDATE / DO NOTHING.
#   - Self-contained: only psql + CBML_DSN (or PG* vars). No migrations,
#     no provider calls, no embeddings.
#
# Usage:
#   CBML_DSN="postgresql://user:pass@host:port/db" bash scripts/epistemics_validation_seed.sh
#   SEED_WORKSPACE_ID=<uuid>  — target workspace (default: isolated validation workspace)
#
# Exits 0 on full pass, non-zero on any failure.

set -euo pipefail

GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo -e "${GREEN}  PASS${NC}  $*"; }
fail() { FAIL=$((FAIL+1)); echo -e "${RED}  FAIL${NC}  $*"; }
info() { echo -e "${CYAN}  INFO${NC}  $*"; }

echo "  opencb-epistemics validation fixture seed"
echo "  $(date -u '+%Y-%m-%d %H:%M UTC')"

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
fi
PSQL_CMD=(psql -v ON_ERROR_STOP=1 -q "${PSQL_ARGS[@]}")

if ! "${PSQL_CMD[@]}" -c "SELECT 1" >/dev/null 2>&1; then
    fail "Cannot connect to database. Set CBML_DSN or PG* vars."
    exit 1
fi
ok "DB connectivity"

VALIDATION_WS_ID="e9e00000-0000-0000-0000-0000000000f1"
SEED_WS_ID="${SEED_WORKSPACE_ID:-$VALIDATION_WS_ID}"
if [[ "${SEED_WS_ID}" == "${VALIDATION_WS_ID}" ]]; then
    "${PSQL_CMD[@]}" <<SQL
INSERT INTO cb_workspaces (workspace_id, slug, title, status, is_default, created_by_subject)
VALUES
    ('$VALIDATION_WS_ID', 'opencb-epistemics-validation',
     'OpenCB Epistemics Validation Fixture', 'active', FALSE,
     'opencb-epistemics-validation-seed')
ON CONFLICT (workspace_id) DO UPDATE
    SET slug = EXCLUDED.slug,
        title = EXCLUDED.title,
        status = 'active',
        is_default = FALSE,
        updated_at = NOW();

INSERT INTO workspace_memberships (workspace_id, auth_subject_id, role, status)
SELECT '$VALIDATION_WS_ID'::uuid, auth_subject_id, 'owner', 'active'
  FROM auth_subjects
 WHERE status = 'active'
ON CONFLICT (workspace_id, auth_subject_id) DO UPDATE
    SET role = EXCLUDED.role,
        status = 'active',
        updated_at = NOW();
SQL
    ok "Isolated validation workspace ready: $SEED_WS_ID"
fi
if [[ -z "$SEED_WS_ID" ]]; then
    fail "No workspace found. Set SEED_WORKSPACE_ID or run migrations first."
    exit 1
fi
ok "Workspace: $SEED_WS_ID"

SCOPE="epistemics-validation-notify-transport"

"${PSQL_CMD[@]}" <<SQL
-- (b) SUPERSEDED predecessor: the old notification transport choice.
INSERT INTO content_items (content_id, workspace_id, node_type, quick_summary, content_title,
                           content_metadata, is_current, current_state_scope)
VALUES
    ('e9e00001-0000-0000-0000-00000000000b', '$SEED_WS_ID', 'decision',
     'decision: use long-polling for the notification transport. Chosen for simplicity over WebSockets at launch; revisit when concurrent listeners exceed the polling budget.',
     'Notification transport: long-polling (superseded)',
     '{"domain":"engineering","word_count":240,"fixture":"opencb-epistemics-e1"}'::jsonb,
     FALSE, '$SCOPE')
ON CONFLICT (content_id) DO UPDATE
    SET workspace_id = '$SEED_WS_ID',
        node_type = EXCLUDED.node_type,
        quick_summary = EXCLUDED.quick_summary,
        content_title = EXCLUDED.content_title,
        content_metadata = EXCLUDED.content_metadata,
        is_current = FALSE,
        current_state_scope = '$SCOPE',
        updated_at = NOW();

-- (a) CURRENT item: the decision that replaced it.
INSERT INTO content_items (content_id, workspace_id, node_type, quick_summary, content_title,
                           content_metadata, is_current, current_state_scope, cs_supersedes_content_id)
VALUES
    ('e9e00002-0000-0000-0000-00000000000a', '$SEED_WS_ID', 'decision',
     'decision: switch the notification transport to WebSockets. Long-polling exceeded its budget at 500 concurrent listeners; WebSockets cut idle connection cost by an order of magnitude.',
     'Notification transport: WebSockets (current)',
     '{"domain":"engineering","word_count":260,"fixture":"opencb-epistemics-e1"}'::jsonb,
     TRUE, '$SCOPE', 'e9e00001-0000-0000-0000-00000000000b')
ON CONFLICT (content_id) DO UPDATE
    SET workspace_id = '$SEED_WS_ID',
        node_type = EXCLUDED.node_type,
        quick_summary = EXCLUDED.quick_summary,
        content_title = EXCLUDED.content_title,
        content_metadata = EXCLUDED.content_metadata,
        is_current = TRUE,
        current_state_scope = '$SCOPE',
        cs_supersedes_content_id = 'e9e00001-0000-0000-0000-00000000000b', updated_at = NOW();

-- Anchor: names what IS current for the scope and what it superseded.
INSERT INTO cb_current_state_anchors (anchor_id, workspace_id, memory_type, scope,
                                      content_id, supersedes_content_id, state_status, set_by, state_reason)
VALUES
    ('e9e000aa-0000-0000-0000-0000000000aa', '$SEED_WS_ID', 'decision', '$SCOPE',
     'e9e00002-0000-0000-0000-00000000000a', 'e9e00001-0000-0000-0000-00000000000b',
     'active', 'api', 'opencb-epistemics validation fixture seed')
ON CONFLICT (anchor_id) DO UPDATE
    SET workspace_id = '$SEED_WS_ID',
        memory_type = 'decision',
        scope = '$SCOPE',
        content_id = 'e9e00002-0000-0000-0000-00000000000a',
        supersedes_content_id = 'e9e00001-0000-0000-0000-00000000000b',
        state_status = 'active';

-- (c) Weak fragment: topic-adjacent, uncorroborated, no hub link, no scope,
--     no current-state involvement — retrieval may surface it, trust stays low.
INSERT INTO content_items (content_id, workspace_id, node_type, quick_summary, content_title,
                           content_metadata, is_current, current_state_scope)
VALUES
    ('e9e00003-0000-0000-0000-00000000000c', '$SEED_WS_ID', 'raw_note',
     'someone mentioned server-sent events might also work for notifications, not sure',
     'note re notifications',
     '{"fixture":"opencb-epistemics-e2","word_count":14}'::jsonb,
     NULL, NULL)
ON CONFLICT (content_id) DO UPDATE
    SET workspace_id = '$SEED_WS_ID',
        node_type = EXCLUDED.node_type,
        quick_summary = EXCLUDED.quick_summary,
        content_title = EXCLUDED.content_title,
        content_metadata = EXCLUDED.content_metadata,
        is_current = NULL,
        current_state_scope = NULL,
        cs_supersedes_content_id = NULL,
        updated_at = NOW();

INSERT INTO content_chunks (chunk_id, content_id, workspace_id, chunk_index, chunk_text, word_count)
VALUES
    ('e9e000c1-0000-0000-0000-00000000000b',
     'e9e00001-0000-0000-0000-00000000000b', '$SEED_WS_ID', 0,
     'decision: use long-polling for the notification transport. Chosen for simplicity over WebSockets at launch; revisit when concurrent listeners exceed the polling budget.',
     21),
    ('e9e000c2-0000-0000-0000-00000000000a',
     'e9e00002-0000-0000-0000-00000000000a', '$SEED_WS_ID', 0,
     'decision: switch the notification transport to WebSockets. Long-polling exceeded its budget at 500 concurrent listeners; WebSockets cut idle connection cost by an order of magnitude.',
     22),
    ('e9e000c3-0000-0000-0000-00000000000c',
     'e9e00003-0000-0000-0000-00000000000c', '$SEED_WS_ID', 0,
     'someone mentioned server-sent events might also work for notifications, not sure',
     10)
ON CONFLICT (chunk_id) DO UPDATE
    SET workspace_id = EXCLUDED.workspace_id,
        chunk_text = EXCLUDED.chunk_text,
        word_count = EXCLUDED.word_count,
        chunk_index = EXCLUDED.chunk_index;
SQL
ok "Three-fragment fixture seeded with retrievable chunks (scope: $SCOPE)"

# Verify the fixture is actually in the shape the scenarios assume.
COUNT="$("${PSQL_CMD[@]}" -t -c "
    SELECT count(*) FROM content_items
     WHERE workspace_id = '$SEED_WS_ID'::uuid
       AND content_id IN ('e9e00001-0000-0000-0000-00000000000b',
                          'e9e00002-0000-0000-0000-00000000000a',
                          'e9e00003-0000-0000-0000-00000000000c');" | tr -d '[:space:]')"
ANCHOR_OK="$("${PSQL_CMD[@]}" -t -c "
    SELECT count(*) FROM cb_current_state_anchors
     WHERE anchor_id = 'e9e000aa-0000-0000-0000-0000000000aa'
       AND content_id = 'e9e00002-0000-0000-0000-00000000000a'
       AND supersedes_content_id = 'e9e00001-0000-0000-0000-00000000000b'
       AND state_status = 'active';" | tr -d '[:space:]')"
CHUNK_COUNT="$("${PSQL_CMD[@]}" -t -c "
    SELECT count(*) FROM content_chunks
     WHERE workspace_id = '$SEED_WS_ID'::uuid
       AND content_id IN ('e9e00001-0000-0000-0000-00000000000b',
                          'e9e00002-0000-0000-0000-00000000000a',
                          'e9e00003-0000-0000-0000-00000000000c');" | tr -d '[:space:]')"

[[ "$COUNT" == "3" ]] && ok "3 fixture content rows present" || fail "expected 3 fixture rows, got $COUNT"
[[ "$ANCHOR_OK" == "1" ]] && ok "anchor links current -> superseded" || fail "anchor row missing or mis-linked"
[[ "$CHUNK_COUNT" == "3" ]] && ok "3 fixture chunks present" || fail "expected 3 fixture chunks, got $CHUNK_COUNT"

echo ""
if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}Fixture ready${NC} — run the E1-E4 scenarios from docs/EPISTEMICS_VALIDATION.md against this workspace."
    exit 0
else
    echo -e "${RED}$FAIL check(s) failed${NC}"
    exit 1
fi
