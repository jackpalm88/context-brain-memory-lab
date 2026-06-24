#!/usr/bin/env bash
# Hermetic test gate: prove the deterministic core passes with an empty environment.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"
# Re-exec under a scrubbed environment, keeping only PATH and the venv.
if [ "${HERMETIC_SCRUBBED:-0}" != "1" ]; then
  exec env -i HERMETIC_SCRUBBED=1 PATH="$PATH" HOME="$HOME" bash "$0" "$@"
fi
python -m pytest -q -p no:cacheprovider "$@"
