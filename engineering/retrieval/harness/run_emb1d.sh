#!/usr/bin/env bash
# EMB-1D Semantic Loop Acceptance Harness runner.
# Spins an ephemeral pgvector DB, applies repo migrations, runs E1-E5 properties,
# writes the report, tears down.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VALDIR="$(cd "$HERE/.." && pwd)/validation"
REPORT="$VALDIR/EMB-1D_semantic_loop_report.md"
REPO="/opt/cbml"
NAME="cbml_emb1d_accept_$$"
PORT=55988
IMG="pgvector/pgvector:pg16"
DSN="host=127.0.0.1 port=${PORT} dbname=cbml_e1d user=cbml password=cbml_e1d"

mkdir -p "$VALDIR"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

docker rm -f "$NAME" >/dev/null 2>&1 || true
echo "[emb1d] spinning ephemeral $IMG as $NAME on 127.0.0.1:${PORT}"
docker run -d --name "$NAME" \
  -e POSTGRES_USER=cbml -e POSTGRES_PASSWORD=cbml_e1d -e POSTGRES_DB=cbml_e1d \
  -p 127.0.0.1:${PORT}:5432 "$IMG" >/dev/null

echo "[emb1d] waiting for postgres..."
for i in $(seq 1 40); do
  docker exec "$NAME" pg_isready -U cbml -d cbml_e1d >/dev/null 2>&1 && { echo "[emb1d] ready after ${i}s"; break; }
  sleep 1
done

echo "[emb1d] applying repo migrations"
for f in $(ls "$REPO"/migrations/*.sql | sort); do
  if ! PGPASSWORD=cbml_e1d psql -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p ${PORT} -U cbml -d cbml_e1d -f "$f" >/dev/null 2>&1; then
    echo "[emb1d] MIGRATION FAILED: $f" >&2
    exit 2
  fi
done
echo "[emb1d] migrations applied"

echo "[emb1d] running E1-E5 semantic loop properties"
RC=0
PYTHONPATH="$REPO" MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED=false \
  python3 "$HERE/emb1d_semantic_loop_harness.py" "$DSN" "$REPORT" || RC=$?

echo "[emb1d] report: $REPORT (exit=$RC)"
exit $RC
