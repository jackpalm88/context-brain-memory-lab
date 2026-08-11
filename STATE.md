# STATE — Context Brain Memory Lab (single source of truth pointer)

canonical_working_tree: /opt/cbml
real_version: 1.0.0
release_state: v1.0.0 TAGGED (tag object 1c4293a → commit 4f6a100, 2026-07-05); post-1.0 consumer-driven evolution closed its first full cycle — CF-001..CF-005 all Stage 1 resolved, Stage 2 items evidence-gated; 2026-08-10 pre-marketing release-truth audit closed (mcp<2 pin, seed/quickstart fixes, auth/SECURITY.md truth, docs/MCP.md, README rewrite); GPT Actions consumer surface: minimal schema removed, real production Action A+B pair (35 ops, OpenCB decision df97aa73) published as canonical with restored epistemic discipline in the system prompt; 2026-08-11 repo archaeology + human-voice pass: 3 files with leaked private paths/name redacted in current tree, dead artifacts removed (requirements-pr1b-*.txt, old examples/ fixture replaced with a real decision-recall demo), reference_framework/ untracked (kept local), README trimmed (163→137 lines); full git-history scan found no credentials but found 154/194 commits (79%) under two identity-leaking author/committer strings — mitigated with .mailmap (display-layer remap, no history rewrite, by explicit decision); STATE refreshed at current HEAD a3dc360 after green hermetic gate on 2026-08-11
authoritative_boundaries: docs/ARCHITECTURE_BOUNDARIES.md (standing doctrines, graph authority model, Graph Navigation scope freeze, v1.0 exception policy)
last_green_gate: 1753 passed / 92 skipped / 0 failed (hermetic env -i via scripts/hermetic_test.sh, 2026-08-11, HEAD a3dc360)
state_refresh_trigger: STATE.md (at minimum last_green_gate and release_state) MUST be refreshed as part of every safe_push approval and every tag-prep — a push whose gate result is not reflected here is an incomplete push.
milestone_scheme: M-scheme and B-scheme FROZEN (historical); post-v1.0 work is governed by the scope-freeze contract and vNext triggers, not new M-numbers
historical_note: tag v0.2.0a1 predates the M6 privacy remediation; v1.0.0 is the first recommended checkout
release_gates: PyPI publish and public announcement require separate explicit human GO
