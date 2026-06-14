# B15 Graph Health Service Only

Status: B15_GRAPH_HEALTH_SERVICE_ONLY_PASS_WITH_CAVEATS
Target: /opt/context-brain-memory-lab_pr1a_staging
Mode: source_changes_allowed / service_and_models_only / tests_allowed / no_api_wiring / no_git_ops / no_release_execution
Baseline observed: 0.1.0b14

## Scope executed

Implemented the deterministic B15 service/model layer for Graph Health and Retrieval Governance without API wiring, report generator, console script, pyproject changes, provider calls, private CB access, git commit/tag/push, build/export, or release operations.

## Files added

Core modules:

- `memory_lab/graph/health_models.py`
- `memory_lab/graph/health_service.py`
- `memory_lab/graph/hub_recall_health.py`
- `memory_lab/graph/alias_hygiene.py`

Unit tests:

- `tests/unit/test_graph_health_service.py`
- `tests/unit/test_hub_recall_health.py`
- `tests/unit/test_alias_hygiene_candidates.py`

## Files intentionally not changed

- `memory_lab/api/main.py`
- `memory_lab/api/routers/hubs.py`
- `memory_lab/api/routers/graph_health.py` was not added
- `pyproject.toml`
- no report generator module or console script was added

## Implemented models

`memory_lab/graph/health_models.py` defines:

- `IndexingStatus`
- `GraphHealthWarning`
- `GraphHealthComponentScores`
- `ContentHealthState`
- `TopologyMetrics`
- `IndexSearchabilityMetrics`
- `HubRecallFinding`
- `HubRecallMetrics`
- `HubRecallHealthReport`
- `AliasCandidate`
- `AliasCandidateReport`
- `GraphHealthReport`
- `DEFAULT_NON_CLAIMS`

Supported indexing statuses:

- `unknown`
- `pending`
- `indexing`
- `searchable`
- `blocked_empty`
- `blocked_quality`
- `blocked_reextract`
- `failed`
- `stale`

## Implemented Graph Health Score

`memory_lab/graph/health_service.py` implements pure in-memory deterministic scoring through `GraphHealthService.evaluate(...)`.

Component weights:

- `topology_score`: 25
- `index_searchability_score`: 30
- `hub_recall_score`: 25
- `alias_hygiene_score`: 10
- `consistency_score`: 10

Final score:

```text
health_score = topology_score
             + index_searchability_score
             + hub_recall_score
             + alias_hygiene_score
             + consistency_score
```

The total is clamped to `0–100`.

Topology calculation uses deterministic sorted BFS/DFS over a plain Python adjacency map. No NetworkX or new dependency was introduced.

## Implemented required states

The model/report layer represents:

- `saved`
- `searchable`
- `hub_linked`
- `graph_reachable`
- `retrieval_observed`

The hub recall tests explicitly assert these states stay distinct.

## Implemented warnings

Implemented warning codes:

- `MISSING_ITEM_EMBEDDING`
- `NULL_EMBEDDING_BACKLOG`
- `STALE_INDEX_NOT_SEARCHABLE`
- `HUB_LINKED_NOT_SEARCHABLE`
- `HUB_LINKED_NOT_RETRIEVED`
- `GRAPH_VECTOR_INDEX_MISMATCH`
- `ALIAS_CANDIDATE_REVIEW_REQUIRED`

## Implemented Hub Recall Health

`memory_lab/graph/hub_recall_health.py` implements `HubRecallHealthService.evaluate(...)` with:

- `linked_count`
- `searchable_linked_count`
- `retrieval_observed_count`
- `retrieval_observed_available`
- `hub_linked_not_searchable_count`
- `hub_linked_not_retrieved_count`
- `HubRecallFinding` records for saved/searchable/hub-linked/graph-reachable/retrieval-observed state gaps
- bounded recall score contribution out of 25

If retrieval observations are absent, the service emits a limitation instead of pretending recall was observed.

## Implemented Alias Hygiene candidates

`memory_lab/graph/alias_hygiene.py` implements report-only HITL alias candidate generation from provided labels:

- deterministic normalization via casefold, diacritic fold, punctuation trim, whitespace collapse
- duplicate/alias candidate grouping
- `requires_human_review=true`
- `mutation_allowed=false`
- `ALIAS_CANDIDATE_REVIEW_REQUIRED` warning when candidates are found

No graph mutation, alias write, canonical rewrite, or auto-merge is implemented.

## Validation run

Command executed on target:

```bash
python3 -m py_compile \
  memory_lab/graph/health_models.py \
  memory_lab/graph/health_service.py \
  memory_lab/graph/hub_recall_health.py \
  memory_lab/graph/alias_hygiene.py \
  tests/unit/test_graph_health_service.py \
  tests/unit/test_hub_recall_health.py \
  tests/unit/test_alias_hygiene_candidates.py

pytest -q \
  tests/unit/test_graph_health_service.py \
  tests/unit/test_hub_recall_health.py \
  tests/unit/test_alias_hygiene_candidates.py
```

Result:

```text
14 passed in 0.39s
```

## Boundary verification

Read-only boundary checks after implementation:

- API graph-health router added: no
- API main/router files recently changed: no
- `pyproject.toml` recently changed: no
- report generator added: no
- console script added: no
- provider calls: no
- private CB access: no
- build/export/release ops: no
- git commit/push/tag: no

Caveat: target directory does not contain a `.git` directory, so git status/commit verification is limited to confirming `.git` is absent and no git mutation command was used.

Recently touched source/test files were only:

- `memory_lab/graph/alias_hygiene.py`
- `memory_lab/graph/health_models.py`
- `memory_lab/graph/health_service.py`
- `memory_lab/graph/hub_recall_health.py`
- `tests/unit/test_alias_hygiene_candidates.py`
- `tests/unit/test_graph_health_service.py`
- `tests/unit/test_hub_recall_health.py`

## Fixture/test coverage

Unit tests cover:

- healthy connected graph
- isolated/low-degree graph
- hub-linked but retrieval-invisible content
- missing embedding / null searchable case
- duplicate alias candidates
- stale index warning
- empty graph / no graph data case
- score clamp
- no mutation of alias input labels
- non-claims presence

## Non-claims preserved

Implemented report non-claims include:

- graph health is an operational signal, not answer correctness
- saved-by-ID does not guarantee searchable
- hub link does not guarantee semantic recall
- alias candidates require human review
- no graph mutation or automatic merge
- no truth arbitration or conflict resolution
- no Full Context Brain claim
- no private CB or ask_v2 port

## Final status

**B15_GRAPH_HEALTH_SERVICE_ONLY_PASS_WITH_CAVEATS**

Caveats:

- This is in-memory deterministic service/model layer only; no repository/database read layer yet.
- API wiring and report generator are intentionally deferred.
- `indexing_status` and `searchable_after` are supported in models/derivation but not backed by schema migration in this gate.
- Git verification is limited because the staging target has no `.git` directory.

Recommended next gate:

`GO_B15_GRAPH_HEALTH_REPORT_GENERATOR`

Alternative next gate:

`GO_B15_GRAPH_HEALTH_API_WIRING`
