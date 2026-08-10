#!/usr/bin/env bash
# Mint an API key for MEMORY_LAB_AUTH_MODE=api_key deployments.
#
# Creates an auth subject, stores the key's SHA-256 hash in api_keys (the raw
# token is printed ONCE and never stored), and grants the subject a membership
# in the target workspace. Idempotence: every run mints a NEW subject + key.
#
# Usage:
#   bash scripts/create_api_key.sh [--name <label>] [--role <role>]
#                                  [--workspace <uuid>] [--subject-type <type>]
#                                  [--expires-days <n>] [--dsn <postgres-dsn>]
#
# Defaults: --role reader, --subject-type service_agent, workspace = the
# is_default workspace, no expiry.
#
# Database connection resolution order:
#   1. --dsn argument
#   2. DATABASE_URL env
#   3. CBML_DSN env
#   4. docker exec into the compose quickstart's cbml-db container
#
# Roles (workspace_memberships CHECK): owner admin writer reader service_agent auditor
set -euo pipefail

NAME="api-key"
ROLE="reader"
WORKSPACE=""
SUBJECT_TYPE="service_agent"
EXPIRES_DAYS=""
DSN="${DATABASE_URL:-${CBML_DSN:-}}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)          NAME="$2"; shift 2 ;;
    --role)          ROLE="$2"; shift 2 ;;
    --workspace)     WORKSPACE="$2"; shift 2 ;;
    --subject-type)  SUBJECT_TYPE="$2"; shift 2 ;;
    --expires-days)  EXPIRES_DAYS="$2"; shift 2 ;;
    --dsn)           DSN="$2"; shift 2 ;;
    -h|--help)       sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

case "$ROLE" in
  owner|admin|writer|reader|service_agent|auditor) ;;
  *) echo "invalid --role '$ROLE' (owner|admin|writer|reader|service_agent|auditor)" >&2; exit 1 ;;
esac
case "$SUBJECT_TYPE" in
  human|service_agent) ;;
  *) echo "invalid --subject-type '$SUBJECT_TYPE' (human|service_agent)" >&2; exit 1 ;;
esac

if [[ -n "$DSN" ]]; then
  PSQL=(psql "$DSN")
elif docker inspect cbml-db >/dev/null 2>&1; then
  echo "[create_api_key] no DSN — using docker exec into cbml-db (compose quickstart)" >&2
  PSQL=(docker exec -i cbml-db psql -U "${CBML_PG_USER:-cbml}" -d "${CBML_PG_DB:-cbml}")
else
  echo "No database reachable: pass --dsn, set DATABASE_URL, or start the compose stack." >&2
  exit 1
fi

# Token: 160 random bits, hex. Only its SHA-256 lands in the database.
if command -v openssl >/dev/null 2>&1; then
  RAW="$(openssl rand -hex 20)"
else
  RAW="$(od -An -N20 -tx1 /dev/urandom | tr -d ' \n')"
fi
TOKEN="cbml_${RAW}"
TOKEN_HASH="$(printf '%s' "$TOKEN" | sha256sum | cut -d' ' -f1)"
KEY_PREFIX="${TOKEN:0:12}"

EXPIRES_SQL="NULL"
if [[ -n "$EXPIRES_DAYS" ]]; then
  EXPIRES_SQL="NOW() + INTERVAL '${EXPIRES_DAYS} days'"
fi

WORKSPACE_SQL="(SELECT workspace_id FROM cb_workspaces WHERE is_default = TRUE AND status = 'active' ORDER BY created_at ASC LIMIT 1)"
if [[ -n "$WORKSPACE" ]]; then
  WORKSPACE_SQL="'${WORKSPACE}'::uuid"
fi

RESULT="$("${PSQL[@]}" -v ON_ERROR_STOP=1 -tA <<SQL
WITH new_subject AS (
    INSERT INTO auth_subjects (subject_type, display_name, status)
    VALUES ('${SUBJECT_TYPE}', '${NAME}', 'active')
    RETURNING auth_subject_id
), target_ws AS (
    SELECT ${WORKSPACE_SQL} AS workspace_id
), new_key AS (
    INSERT INTO api_keys (auth_subject_id, key_hash, key_prefix, name, status, expires_at)
    SELECT auth_subject_id, 'sha256:${TOKEN_HASH}', '${KEY_PREFIX}', '${NAME}', 'active', ${EXPIRES_SQL}
      FROM new_subject
    RETURNING key_id
), new_membership AS (
    INSERT INTO workspace_memberships (workspace_id, auth_subject_id, role, status)
    SELECT t.workspace_id, s.auth_subject_id, '${ROLE}', 'active'
      FROM new_subject s, target_ws t
    RETURNING workspace_id
)
SELECT s.auth_subject_id || '|' || k.key_id || '|' || m.workspace_id
  FROM new_subject s, new_key k, new_membership m;
SQL
)"

if [[ -z "$RESULT" ]]; then
  echo "key creation failed (is the workspace UUID valid and active?)" >&2
  exit 1
fi

SUBJECT_ID="${RESULT%%|*}"
REST="${RESULT#*|}"
KEY_ID="${REST%%|*}"
WS_ID="${REST#*|}"

cat <<OUT

API key created.

  name          : ${NAME}
  role          : ${ROLE}
  subject_id    : ${SUBJECT_ID}
  key_id        : ${KEY_ID}
  key_prefix    : ${KEY_PREFIX}
  workspace_id  : ${WS_ID}
  expires       : ${EXPIRES_DAYS:+in ${EXPIRES_DAYS} days}${EXPIRES_DAYS:-never}

  TOKEN (shown once — only its hash is stored):

    ${TOKEN}

Verify (against a server running with MEMORY_LAB_AUTH_MODE=api_key):

  curl -s -X POST http://127.0.0.1:8088/v1/retrieval/search \\
    -H "Authorization: Bearer ${TOKEN}" \\
    -H 'Content-Type: application/json' -d '{"query": "test"}'

Revoke later:

  UPDATE api_keys SET status = 'revoked', revoked_at = NOW() WHERE key_id = '${KEY_ID}';
OUT
