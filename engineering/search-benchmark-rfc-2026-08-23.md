# OpenCB search architecture evaluation — RFC v0.1 (benchmark only, no implementation)

**Datums:** 2026-08-23 (v0 drafted) / updated same day (v0.1 hygiene pass)
**Repo:** /opt/cbml (CBML / memory_lab), canonical workspace `69984891-9fd4-4a39-b3e8-c1f0459c9087`
**Governs:** decision `5b019127-6b33-4bcd-9b62-ac87fb6dd3fa` — *"Do not implement tokenized-AND
search as a quick fix; run a formal OpenCB search architecture evaluation first"* (Ricardo:
*"query matching/retrieval [is] a core OpenCB design decision, not a convenience patch"*).
**v0.1 changelog** (review finding `e7f9b6a6-b001-4677-9766-9fac4e630782`, linked to
`OpenCB Bugs & Reliability`): fixed a real Q26 category/gate inconsistency; added an explicit
abstention/no-result policy requirement for any vector-involving candidate; specified the missing
FTS↔trgm fusion parameters that must be frozen before scoring; clarified `unaccent` as an optional
sub-variant rather than an assumed property of the FTS candidate; added workspace + hub isolation
hard gates (Q27/Q28); added a dev-set-vs-holdout-set requirement; added a corpus snapshot pin; added
an operations scorecard alongside retrieval-quality metrics. Reviewer's own framing, which this
revision agrees with: *"direction very good, corpus already serious enough to continue; but one more
RFC hygiene pass needed before scoring; nothing changes in production search yet."*
**Scope of this RFC:** define the gold corpus, metrics, and acceptance criteria. **No FTS, no
trigram index, no pgvector wiring, no query-type routing is implemented here.** That is
deliberate — see "Explicitly out of scope" below.

## 1. Why this exists

Two closed findings set up this RFC:

1. `a0a83b6`/`186be82` — the structural split-brain bug (`search_graph_preview` couldn't see
   `cb_decision_nodes` at all) is fixed and live.
2. `7c7454c0-...` / `268a11da-...` — with the corpus now visible, a second, separate defect
   surfaced: multi-word queries use whole-phrase `LIKE '%query%'`, which is brittle against word
   order, punctuation, typos, and paraphrase.

The obvious next move — swap `LIKE` for tokenized `AND`-matching — was deliberately blocked by
`5b019127`: that's a convenience patch, not an architecture decision, and Ricardo wants data before
picking a direction. This RFC is that data-gathering step.

## 2. What "done" looks like for this RFC

A gold query corpus (`engineering/search-benchmark-gold-corpus-2026-08-23.yaml`, **28 queries**,
v0.1) with per-query expected results, acceptable alternates, explicit false-positive traps, and —
where relevant — an explicit (possibly *deliberately undefined*) current-state/supersession policy.
This document defines how that corpus gets scored and what bar a candidate must clear before it's
allowed to replace the current whole-phrase `LIKE`. No candidate is scored yet — that's the next
phase, after this RFC is reviewed/ratified.

## 3. Candidate systems (comparison set, not commitments)

| Candidate | What it is | Role |
|---|---|---|
| **Baseline** | Current whole-phrase `LIKE '%query%'` (both `content_items` and `cb_decision_nodes` branches, as shipped in `a0a83b6`) | Control — everything is measured relative to this |
| **FTS(simple) + pg_trgm** | PostgreSQL `tsvector`/`tsquery` with the `simple` (non-stemming) config, fused with `pg_trgm` similarity for typo tolerance | Primary lexical candidate |
| **+ pgvector RRF** | The above, fused via Reciprocal Rank Fusion with `pgvector` semantic (embedding) similarity | Semantic layer — targets the paraphrase category (Q16/Q17) that lexical approaches structurally cannot solve |

Rejected/deferred, explicitly, per the earlier discussion this RFC formalizes:

- **Tokenized AND-matching** — the very thing `5b019127` blocked as a quick fix. It would fix
  Q04/Q10-class failures cheaply but does nothing for typos (Q12/Q13) or paraphrase (Q16/Q17), and
  locks in a design without measuring the alternatives first.
- **Query-type routing** (detect "this looks like an exact title" vs "this looks like a paraphrase"
  and route to different strategies) — real candidate for *later*, but adds a classifier of its own
  that needs its own evaluation. Deferred, not rejected.

### 3.1 Parameters that MUST be fixed and published before any scoring run (v0.1, was underspecified)

Naming a candidate is not the same as defining it. Before scoring:

- **FTS↔trgm fusion method**: how the `simple`-FTS channel and the `pg_trgm` similarity channel
  combine into one ranked list — e.g. normalized-score weighted sum, or trgm itself feeding a
  second RRF pass. Must be one fixed, documented method, not "whichever gets the best number on
  this corpus" (that would be tuning the corpus, not evaluating an architecture).
- **pg_trgm similarity threshold**: the minimum trigram similarity for a row to be eligible at all
  (Postgres `pg_trgm` has no default relevance cutoff of its own).
  candidates.
- **Per-channel pool size**: how many top-N candidates are pulled from the FTS channel and from the
  trgm channel before fusion (e.g. top-20 each, or top-50) — affects both quality and cost.
- **pgvector RRF `k`**: the standard RRF smoothing constant, fixed once, not tuned per query.
- **`unaccent` is an optional sub-variant, not an assumed property of "FTS(simple)"**: Q08/Q09 exist
  to *measure* LV diacritics handling, not to presuppose `unaccent()` is wired in. Score two
  FTS(simple)+trgm rows if `unaccent` is trialed: with and without. If it isn't trialed in this
  pass, v0.1 only establishes the baseline-without-unaccent number on Q06-Q09, and that must be
  stated plainly in the results, not silently implied as "the FTS candidate handles LV."
- **Abstention / no-result policy for any vector-involving candidate**: nearest-neighbor search
  structurally always returns *something* close by cosine distance — it has no native concept of
  "nothing is relevant enough." Without an explicit similarity/relevance threshold or eligibility
  gate on the vector channel, the `negative` category (Q20/Q21) is by construction stacked against
  any candidate that includes pgvector, punishing it for doing exactly what nearest-neighbor search
  does. This is not optional: **every candidate that includes a vector channel must define and
  publish its abstention threshold before scoring**, and the negative-category hard gate (§5.1)
  applies to that candidate's *final, post-abstention* output — not to raw pre-threshold distances.

## 4. Metrics

Per-query, per-candidate:

- **Hit@1** — is `expected_top` (or one of `acceptable_alternates`) the #1 result? (n/a for
  `multi_match`/`precision_stress` queries — see below.)
- **Recall@5** — fraction of `expected_top ∪ acceptable_alternates` present in the top 5.
- **False-positive flag** — did any id listed in `false_positives` appear in the top 5? This is a
  **hard fail** for that query regardless of Hit@1/Recall@5 — a candidate that "fixes" recall by
  also over-matching has made things worse, not better, per the `search_graph_preview` UX-confusion
  history this whole investigation started from.

Category-level rollups (not single-number aggregate — a candidate that's great at typos but breaks
exact-title matching is not simply "better"):

| Category | Primary metric | What a regression here means |
|---|---|---|
| `exact_title` (Q02/Q03 only) | Hit@1 must stay 100% | Any candidate that can't nail an exact-phrase match is disqualified outright |
| `boundary` (Q26) | Reported, not gated with exact_title | Hub-title-as-query is a scope-boundary check, not a title-retrieval guarantee — fixed in v0.1 after being miscategorized in v0 |
| `negative` (Q20/Q21) | False-positive rate must stay 0% **after abstention filtering** (§3.1) | Hard disqualifier — see false-positive flag above |
| `isolation` (Q27/Q28) | Zero cross-workspace / cross-hub leakage | Hard disqualifier, same severity as `negative` — added in v0.1 after the workspace-identity incident earlier in this investigation |
| `reordered_terms`/`punctuation_hyphen` (Q04/Q05/Q10/Q11) | Recall@5 | This is the known baseline failure class this RFC exists to fix |
| `typo` (Q12/Q13) | Recall@5 | Justifies (or fails to justify) pg_trgm specifically |
| `paraphrase` (Q16/Q17) | Recall@5 | Justifies (or fails to justify) the pgvector/RRF layer specifically — if lexical alone hits these, the semantic layer's cost isn't earned |
| `lv_morphology`/`diacritics_unaccent` (Q06-Q09) | Recall@5, reported, **not gated** | Measured honestly; if `simple` FTS (with or without `unaccent`) doesn't help, that's a real finding, not a failure to fix before shipping — a full LV stemmer is a separate, larger decision |
| `current_state_supersession` (Q18/Q19) | Policy statement, not a number | Whichever candidate ships MUST document its supersession-surfacing policy explicitly in its own decision record — "whatever the ranking happened to do" is not an acceptable answer |
| `precision_stress`/`multi_match`/`ranking_precision` (Q22/Q24/Q25) | Qualitative — top-5 diversity and ordering, reviewed by hand | These don't reduce to pass/fail; they're where RRF fusion quality actually shows up or doesn't |
| `cross_type` (Q23) | Hit@1 both filtered and unfiltered variants | `node_type` scoping must not regress while search quality improves |

## 5. Acceptance criteria for a future candidate (not evaluated yet)

### 5.1 Hard gates (any failure disqualifies the candidate outright)

1. Does not regress **any** `exact_title` (Q02/Q03) query.
2. Zero false positives on `negative` (Q20/Q21), evaluated after the candidate's own published
   abstention policy is applied (§3.1) — not evaluated on raw nearest-neighbor output.
3. Zero cross-workspace or cross-hub leakage on `isolation` (Q27/Q28).
4. Does not silently change `node_type` filtering semantics (`cross_type`, Q23).

### 5.2 Required improvements (the actual point of doing this)

5. Improves Recall@5 on `reordered_terms` + `punctuation_hyphen` (the originally-reported defect
   class) without tripping any §5.1 gate.

### 5.3 Required documentation (not numeric, but blocking before ratification)

6. Reports (not necessarily "wins") on `lv_morphology`/`diacritics_unaccent`, stating plainly
   whether `unaccent` was trialed and what it changed.
7. Ships with an explicit, written policy for `current_state_supersession` handling — reviewed and
   ratified as its own decision, not inferred from behavior.
8. Publishes its fixed fusion/threshold/pool-size parameters (§3.1) so the scored numbers are
   reproducible, not an artifact of undisclosed tuning.
9. Fills in the operations scorecard (§6).

None of §5 is scored yet. The next phase (separately scoped, separately approved) is: implement
each candidate in a disposable branch/schema with its parameters and abstention policy fixed and
published *before* running the corpus, score against both the dev set and the later holdout set
(§7), and bring the results back for a real architecture decision — at which point `5b019127`'s bar
("clean architecture, maximum retrieval benefit, low operational risk, minimal technical debt,
professional quality") gets checked against actual numbers instead of vibes.

## 6. Operations scorecard (required alongside retrieval quality, v0.1 addition)

Retrieval-quality metrics alone can hide the real cost of a candidate — a 3% recall win that needs
4x the indexing cost or an unauditable ranking pipeline is not obviously a win. Every scored
candidate must report:

- **Latency**: p50/p95, warm and cold, for a representative query mix (not just the 28-query gold
  set, which is too small to be a latency signal on its own).
- **Index size / write amplification**: extra storage and per-write cost added on top of the
  existing `content_items`/`cb_decision_nodes` tables (FTS `tsvector` column, trigram GIN index,
  pgvector embedding column + index).
- **Backfill/migration complexity**: what it takes to populate the new index(es) for existing rows,
  and whether that's a one-time job or an ongoing per-write cost.
- **Rollback complexity**: how cleanly the candidate can be turned back off if it underperforms in
  production — schema-additive and reversible, or a one-way door.
- **Match provenance / explainability**: can a caller (or a debugging human) see *why* a result
  ranked where it did — which channel(s) contributed, what score each gave? Relevant given this
  whole investigation started from a search result being silently wrong with no diagnostic surface.
- **Failure isolation**: if the vector/FTS/trgm subsystem degrades or is unavailable, does search
  fail closed to a working (if lower-quality) fallback, or fail the whole endpoint?
- **Dedupe semantics across `content_item`/`decision_node`**: with a fused/scored ranking instead of
  today's simple concatenate-then-sort (`a0a83b6`), how are near-duplicate or genuinely-both-relevant
  results from the two sources ordered relative to each other?

## 7. Dev set vs. holdout set (v0.1 addition)

These 28 queries are now visible to anyone implementing a candidate — they are, practically, a
**development/tuning set**, not a blind test. A candidate can be made to score well against a known
set of 28 queries without that generalizing. Before any candidate is ratified for production:

- Collect a **holdout set** of real queries from actual future agent/user searches (logged
  separately, not authored for this RFC), of comparable size and category spread where possible.
- The person/session implementing a candidate's parameters (§3.1) must not have seen the holdout set
  before those parameters are frozen.
- Run the frozen candidate against the holdout set once. Holdout results are the ones that actually
  inform the ratification decision; dev-set (this file's) results inform iteration during
  implementation, not final acceptance.

## 8. Corpus snapshot pin (v0.1 addition)

OpenCB keeps growing; a query's "correct" top-5 can drift over time purely because new, unrelated,
but lexically-similar content gets added later. The gold corpus YAML now carries
`snapshot_at: 2026-08-23T13:00:00Z` and `source_workspace_id`. A scoring run must use a frozen
read-only export of at least the referenced records (title/reason/context/tags/status/supersession
columns) taken at or after that timestamp — not a live query against a database that has since
grown. If live state has diverged when scoring happens, re-validate `expected_top` against the
pinned snapshot's actual content, not current live state.

## 9. Explicitly out of scope (this RFC)

- No FTS/trgm/pgvector index or query code.
- No query-type routing/classifier.
- No assumption that Latvian morphology or `unaccent` "just works" with any of these — it's
  measured, not presumed (Q06-Q09), and `unaccent` is an explicit optional sub-variant (§3.1), not
  a default.
- No decision on `current_state_supersession` policy — Q18/Q19 exist to force that decision to be
  made explicitly, later, not to make it here by default.
- No holdout-set collection yet (§7 defines the requirement; the set itself doesn't exist yet).
- No changes to `memory_lab/api/services/api_adapter.py`, `memory_lab/decisions/store.py`, or any
  other production code.

## 10. Files

- `engineering/search-benchmark-gold-corpus-2026-08-23.yaml` — 28 gold queries (machine-readable),
  v0.1, snapshot-pinned.
- This file — methodology, metrics, acceptance criteria, operations scorecard.

## 11. Side note: governance auto-classification false positive (fixed, not this RFC's scope)

Saving this RFC's finding note (`content_id=914a75c9-4c93-4218-8de1-66d2dd8e63f6`) into the
canonical workspace triggered the heuristic current-state resolver to mark it as **superseding**
an unrelated prior anchor (`10825d3a-...`, the Curator/Orchestrator/Reasoner architecture doctrine
note) — purely because both got tagged `current_state_scope="retrieval-embeddings"` by the
classifier, with no actual topical relationship. Corrected by clearing
`content_items.cs_supersedes_content_id` on `914a75c9`; `10825d3a`'s own legitimate prior
supersession chain was untouched. Noted here because it's a real governance-pipeline behavior
worth being aware of on future saves into this scope, not because it's in scope for this RFC.

## 11.1 Follow-up: the false-supersession pattern reproduced twice more while logging this RFC

Logging the v0.1 update itself (`bd3cd7e4-...`) triggered the *same* false `cs_supersedes_content_id`
bug again — this time pointing at an unrelated MCP schema defect note (`47f0499b-...`), via a
different resolver path (`scope_source: "lineage"` vs. §11's `"hub_alias"`). Logging *a finding about
that bug* (`cdb6284a-...`) then triggered it a third time, pointing at an unrelated architecture note
(`4cb27e68-...`), again via `lineage`, under yet another scope
(`opencb-retrieval-vs-memory-architecture`). Three independent reproductions across two different
resolver paths in one session is enough to call this a real, repeatable resolver defect rather than
a one-off — logged as its own finding (content `cdb6284a-...`, linked to `OpenCB Bugs & Reliability`)
and explicitly NOT fixed at the resolver level here, same bounded-scope discipline as the original
query-matching finding. All three false links were cleared via the same targeted, reversible
`cs_supersedes_content_id = NULL` correction. The separate conflict-escalation on `bd3cd7e4-...`
(§11, `conflict_content_id=914a75c9-...`) was left alone for proper governance review — it looks
plausibly legitimate, unlike the three `cs_supersedes` false positives.

## 12. Status

v0.1 hygiene pass complete, addressing all points from review finding `e7f9b6a6-...`. Still NOT
ratified as a decision. Recommend logging as a new decision in the canonical workspace (linked to
`5b019127`) once reviewed, so the next phase (implementing and scoring candidates against dev +
holdout sets) has a ratified reference point rather than just a file on disk. No production search
code has been touched at any point in this RFC's lifecycle.
