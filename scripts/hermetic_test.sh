#!/usr/bin/env bash
# Hermetic test gate: prove the deterministic core passes from a fresh isolated venv.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

# Re-exec under a scrubbed environment after creating an isolated venv outside the repo.
if [ "${HERMETIC_SCRUBBED:-0}" != "1" ]; then
  PYTHON_BOOTSTRAP=""
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BOOTSTRAP="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BOOTSTRAP="$(command -v python)"
  else
    echo "hermetic gate requires python3 or python on PATH" >&2
    exit 127
  fi

  TMP_PARENT="${TMPDIR:-/tmp}"
  VENV_DIR="$(mktemp -d "$TMP_PARENT/cbml-hermetic-venv.XXXXXX")"
  cleanup() {
    rm -rf "$VENV_DIR"
  }
  trap cleanup EXIT INT TERM

  "$PYTHON_BOOTSTRAP" -m venv "$VENV_DIR"

  env -i \
    HERMETIC_SCRUBBED=1 \
    CBML_HERMETIC_VENV="$VENV_DIR" \
    PATH="$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    HOME="${HOME:-/tmp}" \
    TMPDIR="$TMP_PARENT" \
    PYTHONDONTWRITEBYTECODE=1 \
    bash "$0" "$@"
  exit $?
fi

if [ -z "${CBML_HERMETIC_VENV:-}" ]; then
  echo "CBML_HERMETIC_VENV is required in scrubbed hermetic mode" >&2
  exit 2
fi

PYTHON="$CBML_HERMETIC_VENV/bin/python"
"$PYTHON" -m pip install -e ".[dev]"

"$PYTHON" - <<'PY_ASSERT'
from pathlib import Path
import memory_lab

expected = (Path.cwd() / "memory_lab").resolve()
locations = [Path(location).resolve() for location in (memory_lab.__spec__.submodule_search_locations or [])]
unique_locations = sorted(set(locations), key=str)
if unique_locations != [expected]:
    raise SystemExit(f"memory_lab import path mismatch: expected only {expected}, got {locations}")
actual = unique_locations[0]
print(f"memory_lab import path: {actual}")
PY_ASSERT

"$PYTHON" -m pytest -q -p no:cacheprovider "$@"
