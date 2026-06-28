#!/usr/bin/env bash
# safe_push.sh — enforce AGENT_CONTRACT §10: a push GO is bound to an EXACT approved
# commit hash, never to a branch name. Aborts unless the working tree is clean AND
# HEAD == approved hash; verifies the remote after pushing.
#
# Usage: scripts/safe_push.sh <approved_commit_hash>
#
# Env overrides (optional): SAFE_PUSH_REMOTE (default origin), SAFE_PUSH_BRANCH (default main).
set -euo pipefail

REMOTE="${SAFE_PUSH_REMOTE:-origin}"
BRANCH="${SAFE_PUSH_BRANCH:-main}"

die() { echo "ABORT: $*" >&2; exit 1; }

[ "$#" -eq 1 ] || { echo "usage: scripts/safe_push.sh <approved_commit_hash>" >&2; exit 2; }
APPROVED_INPUT="$1"

# Approved hash must reference a real commit; normalize to a full SHA.
EXPECTED="$(git rev-parse --verify --quiet "${APPROVED_INPUT}^{commit}")" \
  || die "approved hash '${APPROVED_INPUT}' is not a valid commit"

# Pre-push: working tree must be clean.
[ -z "$(git status --short)" ] || die "working tree not clean — commit or stash first"

# Pre-push: HEAD must equal the approved hash.
ACTUAL="$(git rev-parse HEAD)"
[ "$EXPECTED" = "$ACTUAL" ] \
  || die "HEAD ($ACTUAL) != approved hash ($EXPECTED) — re-review and get fresh GO"

echo "[safe_push] HEAD == approved ${EXPECTED}; tree clean. Pushing ${REMOTE} ${BRANCH}..."
git push "$REMOTE" "$BRANCH"

# Post-push: remote branch must equal the approved hash, tree still clean.
PUSHED="$(git rev-parse "${REMOTE}/${BRANCH}")"
[ "$EXPECTED" = "$PUSHED" ] \
  || die "post-push ${REMOTE}/${BRANCH} ($PUSHED) != approved hash ($EXPECTED)"
[ -z "$(git status --short)" ] || die "post-push working tree not clean"

echo "[safe_push] OK — ${REMOTE}/${BRANCH} == ${EXPECTED}, tree clean."
