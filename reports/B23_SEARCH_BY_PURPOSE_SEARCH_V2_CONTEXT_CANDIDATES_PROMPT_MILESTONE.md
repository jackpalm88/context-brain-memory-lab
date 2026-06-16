# B23 Search-by-Purpose / Search-v2 + Context Candidates/Prompt Milestone

## Milestone identity

- Milestone: B23
- Source: GSD gap-first plan
- Title: Search-by-Purpose / Search-v2 + Context Candidates/Prompt
- Classification: official GSD gap-first milestone, not ad-hoc cleanup
- Public repo: git@github.com:jackpalm88/context-brain-memory-lab.git
- Branch: main
- Public version: 0.1.0b17
- Public code commit: `0b40e2d55a242623ec0fd735a48be0068fb68749`
- Parent before B23: `c5e057b88af0c88ad798e8bf9b844fb399151f4c`

## Pushed B23 files

The B23 public code commit contains exactly these seven code/test files:

1. `memory_lab/reasoning/prompt_package.py`
2. `memory_lab/retrieval/context_candidates.py`
3. `memory_lab/retrieval/search_by_purpose.py`
4. `tests/unit/test_b23_context_candidates.py`
5. `tests/unit/test_b23_prompt_package.py`
6. `tests/unit/test_b23_public_safety.py`
7. `tests/unit/test_b23_search_by_purpose.py`

Protected paths were not changed by the B23 code commit: `README.md`, `pyproject.toml`, `memory_lab/context_packs/service.py`, `memory_lab/api`, `memory_lab/providers`, `memory_lab/ingestion/scorer.py`, and tracked `reports` files.

## Original gap

Before B23, the public repository lacked a public-safe search-by-purpose contract, a search-v2-like candidate record abstraction over supplied inputs, deterministic candidate ranking across B18-B22 supplied signals, context candidate packaging with stable evidence IDs, and provider-neutral prompt/context assembly for the B22 executor/validator boundary.

## Delivered implementation summary

### E1 — deterministic search-by-purpose ranking

B23 adds deterministic search-by-purpose ranking over caller-supplied records only. The implementation works from supplied candidate fields and public-safe metadata, combines purpose term matches with previously introduced deterministic signals, records rationale and limitations, and remains bounded to local deterministic computation.

### E2 — context candidate packaging

B23 adds deterministic context candidate packaging with stable evidence IDs, dedupe, budgeting, metadata, rationale, and limitations. This provides a public-safe evidence package shape that can be consumed by later layers without fetching private stored content or calling a provider.

### E3 — provider-neutral prompt/context package

B23 adds a provider-neutral prompt/context package compatible with the B22 `LLMExecutionRequest` and `StructuredValidator` direction. The package is an assembly contract and deterministic prompt/context carrier only. It does not run an LLM, call providers, copy private prompts, or wire an API/router/wrapper/MCP/GPT Actions surface.

## Validation summary

Post-push verification was performed from a fresh clean clone at `/tmp/context-brain-memory-lab_b23_post_push_verify`.

- Public HEAD via `git ls-remote`: `0b40e2d55a242623ec0fd735a48be0068fb68749`
- Fresh clone HEAD: `0b40e2d55a242623ec0fd735a48be0068fb68749`
- Fresh clone `origin/main`: `0b40e2d55a242623ec0fd735a48be0068fb68749`
- Parent: `c5e057b88af0c88ad798e8bf9b844fb399151f4c`
- Ahead/behind: `0/0`
- Fresh clone tracked diff: `0`
- Fresh clone staged files: `0`
- Fresh clone untracked files after cleanup: `0`
- Fresh clone pycache after cleanup: `0`

Validation results:

- Compile: PASS
- B23 targeted tests: `19 passed`
- B20 regression: `11 passed`
- B21 regression: `24 passed`
- B22 regression: `20 passed`
- Full unit suite: `635 passed, 9 skipped`

## Public-safety and private-prompt scans

Strict scoped scan over B23-added modules:

- `memory_lab/retrieval/search_by_purpose.py`
- `memory_lab/retrieval/context_candidates.py`
- `memory_lab/reasoning/prompt_package.py`

Results:

- Forbidden import hits: `0`
- Forbidden runtime call hits: `0`
- Private prompt fragment hits: `0`
- Strict public-safety scan: PASS
- Private prompt scan: PASS

Confirmed absent in B23 scope:

- DB/private Context Brain access
- Provider calls
- Embedding generation
- Vector DB integration or query
- Live LLM execution
- API/router/wrapper/MCP/GPT Actions wiring
- Stored content fetch
- Private prompt copy

## Gap burn-down before/after

Before B23, the public repo did not have a public-safe deterministic bridge from supplied candidate records into search-by-purpose ranking, evidence candidate packaging, and prompt/context assembly. After B23, E1/E2/E3 are closed for the public-safe deterministic supplied-record context/prompt scope.

Completion classification:

`full_gap_closed_public_safe_deterministic_context_candidate_prompt_scope_only`

## Prior milestone continuity retained

B23 retains the public-safe constraints and outputs from previous milestones:

- B18 A1/A2 public-safe deterministic extraction/domain signal.
- B19 A3/A4 public-safe deterministic hub/tag signals.
- B20 B1/B2 public-safe embedding admin planning and deterministic KNN core.
- B21 C1/C2/C3 public-safe scoring, tier routing plan, and provider-neutral circuit breaker.
- B22 D1/D2/D3 public-safe LLM executor contract, structured validator, and supplied circuit boundary.

## Caveats

- B23 public code commit author/committer identity is `root <root@vmi2728022.contaboserver.net>`. This was recorded after push and was not amended.
- The source worktree still has 50 local B17 report residue files. They are source-worktree-only, were not staged or pushed for B23, and are absent from the fresh public clone.

## Explicit non-claims

B23 is not live search capability.
B23 is not private search parity.
B23 is not provider-backed semantic search.
B23 is not production readiness.
B23 is not Full Context Brain readiness.
B23 does not claim DB/private Context Brain retrieval.
B23 does not claim embedding generation.
B23 does not claim vector DB/KNN mutation.
B23 does not claim live LLM execution.
B23 does not claim API/router/wrapper/MCP/GPT Actions wiring.
B23 does not claim private Context Brain parity.

## Next planned milestone

Recommended next gate: `GO_B24_GAP_CONTRACT_HONEST_MCP_TOOLS_GPT_ACTIONS_WRAPPERS`.
