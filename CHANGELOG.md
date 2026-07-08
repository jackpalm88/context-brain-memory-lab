# Changelog

## Unreleased

### Added

- **CF-005 — Evidence Package v0.2: lookup items are marked, not mixed in.**
  The Intent Router now declares each plan step's epistemic role
  (`evidence` default | `lookup` for steps that resolve arguments or match
  candidates — the lexical decision lookup, the CF-002 by-content joins, the
  referential-entry retrieval, save-path hub term-matching). The role flows
  through the execution trace into the package: `package_version` 0.2, every
  item carries `role`, lookup trace steps are marked. Append-only doctrine
  preserved — lookup rows are kept and MARKED (ambiguity stays visible), the
  Reasoner can now down-weight locators without guessing. Framework-only
  change: no kernel, API, or MCP surface touched.

- **CF-001 + CF-004 Stage 1 — envelope truth.** The capability manifest is now
  v0.2: every tool carries a machine-readable `response_shape` (kind,
  rows_keys, count_key, bucket_keys, context_keys) describing where rows live
  in a successful response — including the warts (timeline's bucketed shape
  with legacy `total`, retrieval's `result_count` duplicate), drift-tested for
  coherence. `/decisions/timeline` additively gains a flat `decisions` view
  (newest first) and conventional `count` ALONGSIDE the status buckets —
  nothing renamed or removed. The envelope convention for NEW surfaces
  (`{"<plural>": rows, "count": n, ...context}`) is ratified as doctrine 6 in
  docs/ARCHITECTURE_BOUNDARIES.md, together with doctrine 5
  (read-before-semantics, the CF-evolution principle). The Reference Framework
  deletes its four hand-rolled shape-tolerance sites (including the CF-001
  bucket workaround) in favor of manifest-driven extraction. Bare-list REST
  surfaces (`/v1/hubs`, `/v1/escalations`) are documented, not reshaped —
  REST normalization belongs to a future API rev with its own GO. Design:
  engineering CF-001-004_DESIGN_PROPOSAL.

- **CF-002 Stage 1 — the content→decision join is now readable.** New
  `GET /decisions/by-content/{content_id}` returns the decision nodes that
  reference a content item, each with `link_role: canonical|source` — the
  derived reverse read over the two link columns the schema always had
  (`cb_decision_nodes.content_id`, never yet written by any writer, and
  caller-declared `source_content_ids`, previously write-only-in). Unknown ids
  return 200 with `count: 0` (never 404 — the read does not leak whether
  content exists). Migration 031 adds the GIN index that also serves the
  pre-existing internal cleanup guard. Exposed as MCP tool
  `list_decisions_for_content` (public surface 34 = 32 parity + two
  CF-minted public-only tools) with manifest entry and curated OpenAPI.
  The Reference Framework restores the §3.3 follow-up dropped in v0
  (ask evidence → decision → lineage) and gives `explain_decision` a
  referential entry (content→decision join) with lexical title matching as
  the declared fallback. Stage 2 (writing the canonical `content_id` at
  decision creation) is gated on live evidence that Stage 1 links are
  actively consumed. Design: engineering CF-002_DESIGN_PROPOSAL.

- **CF-003 — current-state anchors are now readable.** New
  `GET /v1/current-state/anchors?scope=…[&memory_type=…]` returns the ACTIVE
  anchor(s) of a scope from `cb_current_state_anchors` — the forward pointer
  of the supersession chain the resolver has always written but nothing public
  could read. The scope is normalized with the same slugifier as the write
  path. Exposed as MCP tool `list_current_state_anchors` (the first
  public-only tool: 33 vs production's 32; see MCP_PARITY_TABLE.md) with a
  capability-manifest entry, and added to the curated GPT Actions OpenAPI.
  The Reference Framework's `verify_current_state` intent now reads the
  successor of a superseded item from the anchor instead of the v0 bounded
  retrieval probe — it finds the successor even when retrieval does not
  surface it.

### Fixed

- Test hygiene (pre-existing, surfaced by the CF-003 gate run): the OpenAI
  adapter unit tests now restore `sys.modules` identity at teardown (leaving
  the adapter module popped split the `OpenAIEmbeddingBackend` class identity
  and failed unrelated tests order-dependently), and the classify-wiring
  low-confidence test asserts the EB-era explicit
  `current_state_status=noop/low_confidence` response instead of key absence.

## 1.0.0 — Feature-Complete, field-validated (2026-07-05)

First stable release. Covers everything since tag `v0.2.0a1` (73 commits):
gap closure, the full-provider field-validation cycle, the v1.0 Architecture
Review, and the epistemic-blocker fixes.

### Breaking / strictness changes (intentional)

- **Empty save now fails loudly (EB-2).** `POST /v1/content` with a missing,
  empty, or whitespace-only `content` returns **422** instead of silently
  answering `persisted: true` (previously it deduplicated onto a shared empty
  content item). `POST /v1/content/batch` marks such items as inline per-item
  failures without aborting the batch.

### Added

- **Gap closure (1–8b):** embeddings on the save path with deterministic
  multi-chunk persistence and a backfill CLI (EMB-1A/1B/1C); ingest-path
  conflict detection with human-gated escalations (`/v1/escalations`);
  deterministic, provider-free hub-edge inference with approve/reject
  (`ai_suggested` proposals are never auto-curated, rejections never
  resurrected); M12 composite ranking surface (per-result `confidence`,
  `result_trust`, `ranking_reason`, `score_components`, `ranking_signals`);
  streamable-http MCP transport; demo seeds; public GPT Actions OpenAPI
  schema; docker-compose onboarding; batch save, similar retrieval, feedback
  signal, ask metrics, and keyword-audit routes (DX-1..3).
- **Scope resolution (FV-FIX-2A/2B):** explicit `scope_hint` on
  `POST /v1/content` and the MCP save tools, plus a deterministic scope
  resolver pipeline (`scope_hint` → in-text marker → anchor lineage → hub
  alias match → classify metadata → keyword heuristic → `global` last
  resort). The winning tier is reported as `current_state_scope_source`.
  Fixes silent cross-topic supersession ("scope collapse").
- **Ask current-state awareness (FV-FIX-3):** `/v1/ask` evidence carries
  `is_current` / `current_state_scope` / `cs_supersedes_content_id`;
  superseded items are demoted below the current item of the same scope with
  an explicit `ranking_reason`; historical questions keep original order;
  provider prompts label snippet status.
- **MCP ergonomics (FV-FIX-4):** useful descriptions on all 32 approved MCP
  tools; `query_memory` gains an `enable_provider_synthesis` opt-in that
  reaches the provider-backed ask mode (and self-explains via
  `mode=degraded` / `failure_reason=provider_disabled` when the deployment
  gate is off).
- **Reasoning traverse depth (FV-FIX-5):** `/v1/reasoning/traverse` and
  `/explain` honor `max_hops`, and the hop-bounded BFS expansion consults the
  curated hub graph through read-only **hub-term graph adjacency** (reasoning
  surface only — raw retrieval and ask are byte-identical). Traversal steps
  expose `included_via_hub_link` / `included_via_graph_expansion` provenance.
- **Current-state on direct reads (EB-1):** `GET /v1/content/{id}` and
  `/metadata` (and the MCP content-get tool) expose `is_current`,
  `current_state_scope`, `cs_supersedes_content_id` via one canonical
  projection (`memory_lab/current_state/projection.py`).
- **Resolver-skip visibility (EB-3):** when classification confidence is
  below the 0.70 gate, the save response reports
  `current_state_status: "noop"` / `current_state_reason: "low_confidence"`
  instead of omitting the keys — a discarded `scope_hint` is now observable.
- **Architecture boundaries:** `docs/ARCHITECTURE_BOUNDARIES.md` — standing
  doctrines, the graph authority model (curated hub graph is the only edge
  authority; `cb_edges` is the non-authoritative legacy term layer), the
  Graph Navigation scope freeze with amendment procedure, and the v1.0
  exception policy.

### Accepted limitations (documented, not blockers)

- First save on a new topic with no hub and no prior anchor resolves to the
  `global` scope (mitigate with a hub or an explicit `scope_hint`).
- `/v1/reasoning/answer` retrieval stays at `max_hops=1` without hub-term
  adjacency (deliberate scoping; threading the parameter alone would be
  inert).
- The MCP raw-retrieval tool does not forward `memory_type` filters (stated
  in its description).
- Embedding backfill is CLI-only (no HTTP admin route).
- Ranked raw search does not expose current-state fields (physics-only by
  design; direct reads and ask do).

### Historical note

- Tag `v0.2.0a1` predates the M6 privacy remediation and was intentionally
  never re-tagged; `v1.0.0` is the first recommended checkout. Stale
  `0.2.0a1` build artifacts were removed from the repository (`dist/` is no
  longer tracked).

## 0.2.0a1 — M6 release readiness

- Privacy remediation (fix-forward): scrubbed private server paths from shipped source (`embedding_admin` denylist is now runtime/env-extensible), tests, and docs; removed internal B-phase reports and clone inventory from the public repo; rebuilt clean 0.2.0a1 wheel/sdist; repo + artifact privacy scan clean.

- Aligned README, capabilities, install, and state docs with M1-M5 release-candidate truth.
- Replaced stale pre-M artifacts with rebuilt `0.2.0a1` wheel/sdist during release-readiness proof.
- Added clean-install artifact proof expectation: import package from built artifact, verify installed metadata version, and run deterministic smoke without editable install.
- Release actions remain gated: no push, tag, PyPI publish, public announcement, or CB milestone completion without separate human GO.

## 0.2.0a1 — M5

- Added opt-in live end-to-end smoke `scripts/m5_live_smoke.py` proving the full real engine: real OpenAI embeddings + real Anthropic synthesis + pgvector KNN retrieval + grounded provider-backed answer over freshly-ingested content.
- Added `PARITY_AUDIT.md` mapping every original the private reference monolith capability to its memory_lab status (ported / opt-in / intentionally dropped / post-1.0) with no unknown rows.
- Live smoke is opt-in (requires a live DB + provider keys) and is not part of the hermetic deterministic gate.

## 0.2.0a1 — M4

- Hardened reasoning answer citation/provenance behavior for `/v1/reasoning/answer`.
- Stabilized public evidence-ID citations so answer candidates cite supplied evidence refs rather than ordinal placeholders.
- Added opt-in provider-backed `/v1/reasoning/answer` synthesis behind `MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED` and request-level `enable_provider_synthesis`.
- Kept provider-backed synthesis disabled by default with deterministic evidence-grounded fallback behavior.
- Preserved safe fallback on disabled, missing, degraded, or rejected provider output, including invented citations and forbidden truth/verdict/resolution language.
- Added endpoint-level stub verification for provider-disabled, request opt-in, fake-provider success, invented-citation rejection, and forbidden-term rejection paths.

## 0.2.0a1 — M3

- Added gated pgvector retrieval path for opt-in vector KNN search.
- Added embedding write seam to `PostgresPersistenceBackend` after chunk insert.
- Preserved deterministic retrieval fallback as the default and degraded/no-key path.
- Added migration `032_add_m3_pgvector_knn_index.sql` for the M3 pgvector KNN index and embedding metadata.
- Added live pgvector stub test coverage proving vector similarity ranking over recency ordering.

## 0.2.0a1 — M2

- Added `PostgresPersistenceBackend` for opt-in DB-backed content and governance persistence.
- Enabled explicit Postgres selection through `DATABASE_URL` / `CB_TEST_DATABASE_URL` while preserving deterministic empty-env behavior.
- Kept `InMemoryPersistenceBackend` as the empty-env fallback and explicit no-DB seam.
- Verified live throwaway Postgres round-trip coverage for content save→load, governance state save→load, and governance event append→list.
- Added migration `031_add_m2_persistence_roundtrip.sql` for the M2 persistence round-trip schema support.

## 0.2.0a1 — M1

- Froze the B-scheme milestone baseline for Context Brain Memory Lab.
- Established `/opt/cbml` as the canonical working tree and aligned project state pointers.
- Preserved deterministic, read-only graph-health API behavior without requiring `DATABASE_URL`.
- Kept DB-backed write/admin/provider paths fail-closed when database or key prerequisites are absent.
- Restored full hermetic test compatibility under the installed FastAPI route include behavior.
- Reconciled the package version to `0.2.0a1` for the M1 freeze candidate.
