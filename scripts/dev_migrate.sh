#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source .env if present
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$REPO_ROOT/.env"
  set +a
fi

# Require DATABASE_URL
if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERROR: DATABASE_URL is not set. Copy .env.example to .env and set DATABASE_URL." >&2
  exit 1
fi

MIGRATIONS_DIR="$REPO_ROOT/migrations"

echo "Applying migrations from $MIGRATIONS_DIR ..."
for f in $(ls "$MIGRATIONS_DIR"/*.sql | sort); do
  echo "  -> $f"
  psql "$DATABASE_URL" -f "$f"
done

echo "All migrations applied."
