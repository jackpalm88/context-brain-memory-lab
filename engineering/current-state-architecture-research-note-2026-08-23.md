# Current-state architecture research note — grouping vs. replacement identity

**Datums:** 2026-08-23
**Repo:** /opt/cbml (CBML / memory_lab), canonical workspace `69984891-9fd4-4a39-b3e8-c1f0459c9087`
**Escalated by:** decision `c6a4103f-5e46-4ec0-b61b-7bdcd69c923e` (bounded root-cause investigation,
closed: `engineering/current-state-resolver-false-supersession-root-cause-2026-08-23.md`).
**This spike:** content `fb0b8234-821f-4371-9392-3deec5ec101e`, "next logical step" hypothesis —
bounded architecture research/design spike, four candidates, real fixtures, **no resolver code
touched**.
**Precedent this follows:** decision `5b019127-6b33-4bcd-9b62-ac87fb6dd3fa` (search: measure before
choosing an architecture) — same discipline applied here.

## 1. The core tension, stated precisely

The root-cause report established the mechanism. This note is about the concept underneath it:

```text
topic similarity / grouping   ≠   replacement identity
```

`current_state_scope` is currently asked to do both jobs at once. Two of its resolution tiers
(`lineage`, `hub_alias` — `memory_lab/current_state/scope_pipeline.py`) are **deliberately** coarse
topic-clustering matchers (FV-FIX-2B design intent, confirmed from their own docstrings). But
`resolve_current_state_after_ingest` (`memory_lab/current_state/resolver.py`) treats *any* scope
value, regardless of which tier produced it, as if it named a single evolving fact whose latest
value replaces the previous one. That conflation is the whole bug.

## 2. Prior art

**External** (as supplied, not independently re-verified — bounded scope, not a literature review):
Datomic only replaces a prior value when a schema attribute is explicitly declared
`cardinality/one`; identity/uniqueness is *declared* schema semantics, never inferred from topical
similarity. SQL temporal tables version the state of *the same declared row identity* over time —
history is keyed to identity, not to "these two rows seem related." W3C PROV models revision,
invalidation, and specialization as explicit typed relationships between specific entities, not as
a side effect of shared classification. All three agree on the same principle this note's tension
statement already derived independently from this repo's own incident data.

**Internal — and this is the more load-bearing prior art, because it already runs in this exact
codebase**: `cb_decision_nodes` (`memory_lab/decisions/store.py`, `DecisionStore.create_decision`)
already implements an explicit-assertion replacement model correctly. `supersedes_decision_id` is a
**caller-declared** field at creation time; the store then atomically flips the old decision's
`decision_status` to `superseded` and sets `superseded_by_decision_id` — a real, specific,
declared edge between two specific decisions, never inferred from shared topic/scope. The 23 real
supersession chains pulled for this note's fixture set (below) show this working correctly, at
volume, including multi-step chains. **The bug under investigation exists only on the
`content_items`/`cb_current_state_anchors` side, which has no equivalent explicit-declaration
mechanism** — it infers replacement from scope co-membership instead.

Also relevant: `memory_lab/conflicts/escalation.py` already provides a non-destructive
quarantine-and-review pathway (`cb_escalations`, `tier=conflicted`, human-reviewed) — observed
firing correctly, twice, on plausibly-related content during this investigation's own saves. This
is existing infrastructure any "ambiguous → review candidate, not a destructive link" design can
extend rather than build from scratch.

## 3. Fixture set (16 real records, canonical workspace, no invented examples)

### 3.1 True supersession (explicit, unambiguous, already working correctly)

| # | Old | New | Notes |
|---|---|---|---|
| F1 | `62798537-...` "Current build priority leans to Finance Agent before Research Agent" | `1512cba4-...` "Finance Agent goes through Agent-Builder validation first..." | Clean 2-step decision chain |
| F2 | `16b75585-...` "Finance Agent migration is provisional until a clean acceptance rerun" | `8e8512a2-...` "Do not spend the next Agent-Builder acceptance cycle re-running Finance..." | Clean 2-step |
| F3 | `d3d0cd45-...` "FV-5 current_state scope collapse: ship explicit scope_hint (FV-FIX-2A), defer heuristic rework" | `4f965f59-...` "FV-5 CLOSED: scope resolver pipeline (FV-FIX-2B) replaces keyword-heuristic auto-scope" | The **prior decision about this exact resolver's own design history** — directly on-topic prior art |
| F4 | `c6738692-...` "DEFECT CONFIRMED: explain_decision serializes linked_hub_ids as a character array" | `424e5af4-...` → `a8b5167f-...` → `6fecb7bd-...` "RESOLVED: uuid[] array-serialization defect fixed... live 2026-07-22" | 4-hop chain, terminal `active` state — real lifecycle example |

### 3.2 Coexistence mistaken for supersession (the bug, reproduced live)

| # | New (the one wrongly marked as replacing) | Falsely superseded | scope / scope_source |
|---|---|---|---|
| F5 | `914a75c9-...` (search RFC v0 finding) | `10825d3a-...` (Curator/Orchestrator/Reasoner doctrine) | `retrieval-embeddings` / `hub_alias` |
| F6 | `bd3cd7e4-...` (search RFC v0.1 update) | `47f0499b-...` (unrelated MCP list_hubs schema defect) | `retrieval-embeddings` / `lineage` |
| F7 | `cdb6284a-...` (finding about F5+F6) | `4cb27e68-...` (retrieval/memory architecture-layers doctrine, itself previously its own clean singleton anchor `2b41111f-...`) | `opencb-retrieval-vs-memory-architecture` / `lineage` |

### 3.3 Correction (narrower than full replacement — a distinct relationship the model conflates with plain supersession)

| # | Record | Relationship |
|---|---|---|
| F8 | `424e5af4-...` "**Correction**: GPT's short-UUID validation-error finding is complementary, not contradictory, to the linked_hub_ids serialization bug" | Explicitly declares itself a *complementary correction*, not an invalidation, yet uses the same `supersedes_decision_id` field as full replacements (F1-F4) — the decision model itself doesn't yet distinguish "corrects/refines" from "replaces/invalidates" |
| F9 | `af63d79f-...` "Crystallization: 95/5 model" → `6e21d9bc-...` "Crystallization: 97/3 model" | A parameter tweak, not a claim reversal — same relationship-type ambiguity as F8 |
| F10 | `04316997-...` "D1 v2 CustomGPT Actions split — no-action-100%-read invariant..." → `63b32b15-...` "**corrected** active doctrine" | Near-identical titles by design (genuine revision), contrast with F5-F7 where title/content similarity was coincidental, not intentional |

### 3.4 Ambiguity (genuinely unclear, and the existing data shows it — not hypothetical)

| # | Record | Why ambiguous |
|---|---|---|
| F11 | `cb15d757-...` "Two distinct OpenCB deployments clarified..." has `superseded_by_decision_id = 983516d7-...`, **but its own `decision_status` still reads `active`** | A real, pre-existing data inconsistency in this workspace: the edge says superseded, the status field disagrees. Exactly the kind of state a "fail closed to ambiguous, don't silently pick" design must handle gracefully rather than paper over |
| F12 | Finance Agent micro-step chain (e.g. `8a1f1def-...` → `4a968538-...` → ...) | Each link reads as "here's the next planned step," not "the previous belief was wrong." Sequencing and invalidation are being encoded through the same edge type |

### 3.5 Explicit/narrow scopes — safe by construction (contrast case, not a bug)

| # | Record | Why it didn't collide |
|---|---|---|
| F13 | `e7f9b6a6-...` (review finding), scope `opencb-search-benchmark-rfc-v0-review-gaps-2026-08-23`, `scope_source: scope_hint` | Effectively content-unique slug — no other row shares it, so the same buggy resolver logic produces a correct result here purely by accident of scope narrowness |
| F14 | `fb0b8234-...` (this spike's own hypothesis note), same pattern | Confirms the pattern holds even for today's own saves: `scope_hint`-tier scopes tend toward uniqueness, `lineage`/`hub_alias`-tier scopes tend toward collision |
| F15 | `a6bf094e-...` (root-cause finding itself), scope `opencb-current-state-false-supersession-retrieval-embeddings-2026-08-23`, `scope_source: lineage`, **`cs_supersedes_content_id: None`** | Even a `lineage`-tier scope is safe when the resolved slug happens to be specific enough — the risk is proportional to scope granularity, not the tier name itself |
| F16 | `a6bf094e-...`'s own conflict escalation against `7640cc15-...` (an independent duplicate write-up of the same finding) | A *plausible* flag from the **separate** conflict-escalation system — contrast case showing that system already does non-destructive, review-gated linking correctly, unlike the current-state resolver's destructive, ungated linking |

## 4. Four candidates

| # | Name | Mechanism |
|---|---|---|
| 1 | **Explicit-source gate** | Auto-supersede only when `scope_source` is `scope_hint` or `marker` (caller-declared, narrow by construction). `lineage`/`hub_alias`/`classify_metadata`/`keyword_heuristic`/`global_fallback` still set `current_state_scope` for grouping/retrieval, but never trigger `cs_supersedes_content_id`. |
| 2 | **Relatedness gate** | Keep scope-based candidate lookup, but require additional evidence (similarity threshold, or explicit caller-supplied `supersedes_content_id`) before committing the link. |
| 3 | **Split model** | Separate the two concepts outright: `current_state_scope` stays a broad grouping/retrieval tag; a new, narrower `state_identity` (or reuse of the `cb_decision_nodes` pattern for content) is the only thing `cb_current_state_anchors` keys supersession on. |
| 4 | **Assertion/projection model** | Broad memory records never supersede anything by themselves. "Current state" becomes a *projection* over explicit state assertions/revisions (a caller or governance step declares "this replaces that"); anything the projection can't resolve confidently becomes a conflict-escalation candidate (§2's existing `cb_escalations` pathway), not a destructive link. |

### 4.1 Comparison against the fixture set

| Candidate | F1-F4 (true supersession) | F5-F7 (coexistence bug) | F8-F10 (correction) | F11-F12 (ambiguity) | F13-F16 (narrow/safe) |
|---|---|---|---|---|---|
| **1. Explicit-source gate** | Preserved — decisions already use explicit declaration; content_items would need callers to start passing `scope_hint`/markers for anything meant to be a singleton fact | **Fixed** — `lineage`/`hub_alias` scopes stop triggering supersession entirely | Not addressed — correction vs. full replacement still conflated wherever explicit declaration IS used | Not addressed — F11/F12 already came from decision-level explicit declarations and are still ambiguous | Unaffected, still safe |
| **2. Relatedness gate** | Preserved, if threshold tuned correctly | Fixed *if* threshold is well-calibrated — but F7's `4cb27e68`/`cdb6284a` pair and F5/F6 pairs are all genuinely topically adjacent (both about retrieval architecture), so a similarity threshold has to be uncomfortably strict to not still false-positive on these | Not addressed | Partially — a low-confidence match could route to escalation instead of auto-link, if the "gate" includes that fallback | Unaffected |
| **3. Split model** | Preserved, and gives content_items the same clean mechanism decisions already have | **Fixed structurally** — grouping and identity can never collide because they're different fields entirely | Not addressed directly, but a clean identity key makes it easier to add a correction/full-replacement distinction later without further conflating concepts | Not addressed by itself | Unaffected; scope stays useful for retrieval even where it's broad |
| **4. Assertion/projection** | Preserved; extends the already-working `cb_decision_nodes` pattern to content generally | **Fixed structurally**, same as #3 | **Best fit** — assertions can carry their own relationship type (replace/correct/complement), unlike a single boolean-ish supersedes edge | **Best fit** — anything not a confident explicit assertion routes to the existing conflict-escalation queue (§2) instead of picking a side silently; F11's real inconsistency would have been caught at write time, not left in the data | Unaffected |

## 5. Invariants (any accepted design must satisfy all of these)

1. **A broad, inferred scope match alone may never set `cs_supersedes_content_id` / mark an anchor superseded.** (Directly falsified by F5-F7 today.)
2. **Supersession is always between two specific identified records, never between "the new thing" and "whatever else is currently in this bucket."**
3. **Grouping (retrieval/browsing) and replacement (current-state truth) must be independently queryable** — losing the ability to browse "everything about retrieval-embeddings" is not an acceptable cost of fixing supersession.
4. **When confidence is insufficient to assert replacement, the system fails to a non-destructive, reviewable state** (conflict escalation), never to a silent pick.
5. **Correction/refinement and full replacement are observably different relationship types**, even if today's schema only has one edge — a design should not make this distinction harder to add later (F8-F10).
6. **The existing, working `cb_decision_nodes` explicit-declaration pattern is not duplicated with different, weaker semantics** — whatever content_items gets should be consistent with what decisions already do correctly.
7. **Backward compatibility**: existing `is_current` / `cb_current_state_anchors` consumers must keep working during any migration — no silent behavior change for the 144 existing anchors and 23 existing `cs_supersedes_content_id` links in this workspace (some of which, per F1-F4, are correct and must not be disturbed).
8. **Idempotency is preserved** — re-ingesting the same content_id must not create duplicate anchors or duplicate escalations (already a resolver.py invariant today, must not regress).
9. **No candidate should make `current_state_scope` itself less useful for retrieval** — the classification quality that produces reasonable grouping is not the thing being blamed here; only the destructive-link side effect is.

## 6. Migration / backward-compat analysis

Current real state in this workspace: 144 `cb_current_state_anchors` rows, 23 `content_items` rows
with non-null `cs_supersedes_content_id`. F1-F4 confirm a meaningful fraction of those 23 are
**correct** (real decision-chain-driven supersessions) — any fix must not blanket-clear existing
links, only stop *creating new* incorrect ones going forward, plus provide a way to audit/correct
the ones already wrong (three of which, F5-F7, are already manually corrected as of this
investigation).

- **Candidates 1 and 2** are additive gates on the *write path* only — no schema change, existing
  rows untouched, smallest migration footprint.
- **Candidate 3** needs a new column/table (`state_identity` or equivalent) and a backfill decision
  for the 144 existing anchors: do they get a generated identity retroactively, or does the new
  identity concept only apply going forward with `scope` continuing to serve its dual role for
  historical rows? That backfill question is itself non-trivial and should be scoped explicitly if
  #3 is chosen.
- **Candidate 4** is the largest change conceptually (introduces assertions as first-class,
  extends/reuses `cb_escalations`) but could be implemented incrementally: keep today's
  `cb_current_state_anchors` table as the read-side projection, change only how it gets *written*
  (via assertions + escalation fallback instead of direct scope-triggered writes). Existing readers
  of `cb_current_state_anchors` would see no schema change at all.

## 7. Fail-safe behavior (required regardless of which candidate is chosen)

When the resolver cannot establish supersession with high confidence:

- **Never** silently mark an existing anchor superseded.
- **Never** silently skip setting `current_state_scope` either — grouping should still work even when
  identity/replacement can't be resolved (invariant 3).
- **Do** create a conflict-escalation candidate (reusing `memory_lab/conflicts/escalation.py`'s
  existing `cb_escalations` pathway, per §2/F16) so a human or a later, more confident pass can
  decide, rather than the system guessing once and moving on.

## 8. Recommendation

**Candidates 3 and 4, combined**, in that order of implementation priority: split grouping from
identity first (3), then move identity assertion onto the explicit/projection model (4) — because
(4) without (3) still has nowhere clean to put "this is just a broad topic tag," and (3) without (4)
still leaves supersession-worthiness as an unexplained yes/no instead of a typed, reviewable
assertion.

This is not a novel design for this codebase — it's **applying the pattern `cb_decision_nodes`
already runs correctly** (explicit, caller-declared, specifically-identified replacement) to
`content_items`/`cb_current_state_anchors`, and routing anything short of that confidence through
the conflict-escalation queue that already exists and was observed working correctly twice during
this very investigation (F16). Candidates 1 and 2 were seriously considered — (1) is the cheapest
fix and stops the bleeding fastest, (2) adds calibration risk without solving the correction-vs-
replacement conflation — but neither closes invariant 5 or fully satisfies invariant 6, and this
repo already has working prior art for the more complete answer sitting one module away.

**This recommendation is not a decision.** Per the `5b019127` precedent, implementation needs its
own scoped decision, sized by whichever of (3)/(4) is chosen to go first — likely (3) alone as a
first bounded increment, since it's schema-additive and reversible per §6, with (4) as a follow-up
once (3) is live and its migration questions are answered in practice rather than in the abstract.

## 8.1 Additional corroborating prior art (found while saving this note — 4th live reproduction)

Saving this note triggered the same false-supersession bug a fourth time (`f2937127-...`, scope
`architecture-decisions`, `lineage` tier), against `69383060-...`. That record's content, unprompted:
*"Current-state supersession is intentionally binary in v1.0; future decision lineage may need
richer relationship types like refines, decomposes, extends, clarifies, or constrains."* — someone
had already anticipated invariant 5 (§5) independently, before this investigation. Cleared the false
link the same way as F5-F7; not written up as a separate finding since it's the same documented bug
class, but it's strong independent corroboration for the recommendation in §8.

## 9. Explicitly out of scope (this note)

- No changes to `memory_lab/current_state/resolver.py` or `scope_pipeline.py`.
- No schema migration written or applied.
- No choice made between (3) and (4) as a final, ratified architecture — only a reasoned
  recommendation for the next scoped decision to evaluate.
- No further external literature research beyond what was supplied for this spike.

## 10. Status

Research/design spike complete. Recommendation given, not ratified. Resolves the "what's the
bounded next step" question from `fb0b8234-...`. Next step (separately scoped): ratify a design
decision (likely starting with candidate 3 alone) before any resolver code changes.
