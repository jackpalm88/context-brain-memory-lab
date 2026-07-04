#!/usr/bin/env bash
# DX-1 compose bootstrap: apply migrations + seed the local-dev auth subject.
#
# Runs as a one-shot compose service against the stack's Postgres. Idempotent —
# safe to re-run on every `docker compose up`.
#
# Dev-only posture: the fixed auth subject below exists so the API works out of
# the box with MEMORY_LAB_AUTH_MODE=local_dev_bypass. Never reuse this bootstrap
# for a network-exposed deployment; switch to api_key auth and real subjects.
set -euo pipefail

DSN="${CBML_DSN:?CBML_DSN is required}"
DEV_SUBJECT_ID="${CBML_DEV_SUBJECT_ID:-11111111-1111-1111-1111-111111111111}"

echo "[bootstrap] applying migrations..."
for f in $(ls /app/migrations/*.sql | sort); do
  echo "  -> $(basename "$f")"
  psql "$DSN" -v ON_ERROR_STOP=1 -q -f "$f"
done

echo "[bootstrap] seeding local-dev auth subject ${DEV_SUBJECT_ID}..."
psql "$DSN" -v ON_ERROR_STOP=1 -q <<SQL
INSERT INTO auth_subjects (auth_subject_id, subject_type, display_name, status)
VALUES ('${DEV_SUBJECT_ID}', 'human', 'compose-local-dev', 'active')
ON CONFLICT DO NOTHING;

INSERT INTO workspace_memberships (workspace_id, auth_subject_id, role, status)
SELECT workspace_id, '${DEV_SUBJECT_ID}', 'owner', 'active'
  FROM cb_workspaces WHERE is_default = TRUE
ON CONFLICT DO NOTHING;
SQL

echo "[bootstrap] done."
