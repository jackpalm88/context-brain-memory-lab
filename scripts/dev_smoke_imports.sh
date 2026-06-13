#!/usr/bin/env bash
# Import smoke for memory_lab package — no DB, no provider, no network required.

FAIL=0
PASS=0

MODULES=(
  "memory_lab.graph"
  "memory_lab.api"
  "memory_lab.mcp"
  "memory_lab.bootstrap"
  "memory_lab.decisions"
  "memory_lab.governance"
  "memory_lab.ingestion"
)

for mod in "${MODULES[@]}"; do
  if python3 -c "import ${mod}; print('OK: ${mod}')"; then
    PASS=$((PASS + 1))
  else
    echo "FAIL: ${mod}" >&2
    FAIL=$((FAIL + 1))
  fi
done

# Verify constitutionrules.yaml is readable via importlib.resources
if python3 - << 'PYEOF'
import importlib.resources as ir
data = ir.files("memory_lab.governance").joinpath("constitutionrules.yaml").read_bytes()
assert len(data) > 0, "constitutionrules.yaml is empty"
print("OK: constitutionrules.yaml asset readable via importlib.resources")
PYEOF
then
  PASS=$((PASS + 1))
else
  echo "FAIL: constitutionrules.yaml asset check" >&2
  FAIL=$((FAIL + 1))
fi

echo ""
echo "Import smoke: $PASS OK, $FAIL FAIL"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
