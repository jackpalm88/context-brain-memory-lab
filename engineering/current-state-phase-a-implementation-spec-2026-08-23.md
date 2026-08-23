# Current-state Phase A implementation spec — split grouping from replacement identity

**Datums:** 2026-08-23
**Repo:** /opt/cbml (CBML / memory_lab), canonical workspace `69984891-9fd4-4a39-b3e8-c1f0459c9087`
**Ratifies:** decision `4a11008b-9ea8-4468-a305-328075349c9b` (candidate #3 as Phase A; candidate #4
deferred as Phase B, explicitly not part of this spec or its implementation).
**Governs prior work:** `fb0b8234-...` (architecture research note),
`c6a4103f-...` (root-cause investigation), `5b019127-...` (measure-before-architecture precedent).
**Status: spec only. No code written. Implementation is a separate next step, not started here.**

## 1. Scope of Phase A

Exactly candidate #3, nothing from #4:

- `current_state_scope` stays a grouping/retrieval concept — unchanged behavior for callers who
  only want topical clustering.
- A new, narrow **`state_identity`** concept is introduced. Supersession is keyed on it, never on
  `scope` alone.
- No typed relationships (`replaces`/`corrects`/`refines`/...), no confidence-based inference, no
  escalation-queue integration. Those are Phase B (#4) and are explicitly out of scope here — this
  spec only has to leave room for them, not build them.

## 2. `state_identity` semantics

**Who generates it: caller-explicit only, never inferred.** Same rule `cb_decision_nodes` already
follows for `supersedes_decision_id` — the thing that makes that mechanism trustworthy is that
nothing about it is guessed. Concretely: `state_identity` is only ever set when the caller (API
request, MCP tool argument, or an explicit in-text marker analogous to today's `current_state_scope:`
marker syntax) supplies it directly. No tier of `scope_pipeline.py` (marker, lineage, hub_alias,
classify_metadata, keyword_heuristic, global_fallback) may *derive* a `state_identity` — that would
just recreate today's bug in a new column with a different name, which is exactly the migration
mistake to avoid (§4).

**Can governance/classification propose a candidate without committing it?** Not in Phase A. That
capability (a classifier suggesting "this might be the same identity as X, confirm?") is exactly the
shape of Phase B's escalation-routed ambiguity handling — deferred, not built now. In Phase A, no
`state_identity` means no supersession, full stop (§3).

**Uniqueness key:** `(workspace_id, memory_type, state_identity)` — same partitioning
`cb_current_state_anchors` already uses for scope today, with `state_identity` replacing `scope` as
the third column *only for the supersession lookup*. `memory_type` stays part of the identity: it's
already a natural, working partition (a `decision` and an `evidence` row are never treated as
candidates for the same identity today, and there's no reason to relax that in Phase A).

**Forward-compat note (not implemented now):** add the identity/supersession table with an
`relationship_type` column, nullable or defaulted to a single value (e.g. `'replaces'`), so Phase B
can later introduce `corrects`/`refines`/etc. without a breaking schema change. This is schema
design discipline, not Phase B functionality — nothing branches on `relationship_type` yet.

## 3. Write path

```text
ingest content, resolve current_state_scope as today (unchanged, always runs)

if caller supplied an explicit state_identity:
    look up existing active anchor for (workspace_id, memory_type, state_identity)
    if found: mark it superseded, link cs_supersedes_content_id -> it
    if not found: this is the first anchor for this identity
    write the anchor, same as today's mechanism, keyed on state_identity instead of scope

if no state_identity supplied:
    still set current_state_scope for grouping/retrieval (unchanged)
    do NOT touch cb_current_state_anchors
    do NOT set cs_supersedes_content_id
    this is the entire fix — no state_identity means group-only, never destructive
```

This is a strict narrowing of *when* the destructive branch runs, not a new inference mechanism —
which is why it's safe to ship as a self-contained Phase A without any escalation-queue integration.
"No guess" doesn't need new machinery in Phase A; it needs the *absence* of the old machinery's
trigger condition.

**Consequence to state plainly, not bury:** most auto-classified saves today (via `hub_alias`,
`lineage`, `classify_metadata`, `keyword_heuristic` scope tiers — the overwhelming majority of
saves, per the 144 existing anchors vs. the much smaller number that came from explicit
`scope_hint`/`marker`) will **stop generating anchors/supersession entirely** once Phase A ships,
unless their callers start passing `state_identity` explicitly. This is the intended tradeoff:
current-state *tracking coverage* shrinks to only the things that actually declare themselves as
singleton facts, while current-state *correctness* for whatever remains goes to zero false positives.
Broader coverage is a Phase B (or later) concern, achieved by making explicit declaration easy/
common, not by inferring identity from topic.

## 4. Migration plan for existing data (144 anchors, 23 `cs_supersedes_content_id` links)

**Explicit rule: no automatic `state_identity` backfill from `current_state_scope`.** Generating a
narrow identity from a broad scope value is exactly the mistake this spec exists to not repeat in a
new field.

```text
existing historical data (144 anchors, 23 links)
    -> preserved as-is, untouched by Phase A deployment
    -> a separate, explicit audit pass classifies each of the 23 links as:
         known_good   (e.g. F1-F4 in the research note: real cb_decision_nodes-backed chains,
                        or otherwise manually verified as a real replacement)
         known_bad    (e.g. F5-F7 + the 4th live reproduction: already manually cleared this
                        session)
         unaudited    (the remainder — left exactly as-is, flagged, not silently trusted or cleared)
    -> narrow, genuinely-explicit historical cases MAY be backfilled with state_identity under a
       strict rule (e.g. originally resolved via scope_hint/marker AND manually confirmed unique)
       or manual classification -- never as a bulk/automatic operation

new writes (post-Phase-A deployment)
    -> new semantics only: state_identity-driven or group-only, per §3
    -> legacy scope-keyed anchors are not retroactively reinterpreted
```

**Read path: legacy vs. v2.** A reader needs to know whether an anchor's supersession (if any) came
from the old scope-keyed mechanism (untrustworthy, per the root-cause finding) or the new
state_identity-keyed one (trustworthy by construction). Simplest option: anchors written under Phase
A always populate a `state_identity` column; legacy anchors have it `NULL`. Any consumer that cares
about supersession correctness should treat `state_identity IS NULL` rows' `cs_supersedes_content_id`
as **unaudited, not authoritative** until the audit pass (above) has classified them, while still
trusting `current_state_scope` on those same rows for grouping (which was never the broken part).

## 5. Ambiguity handling in Phase A

No new mechanism needed — see §3's "no state_identity → group-only" rule. There is no "maybe
supersedes" state in Phase A; a write either carries an explicit identity or it doesn't. The
optional-escalation idea belongs to Phase B, where inferred *candidates* (not just binary
present/absent) become meaningful and need somewhere non-destructive to land
(`memory_lab/conflicts/escalation.py`'s existing `cb_escalations` pathway, per the research note).

## 6. Confidence-based inference — explicitly rejected, now and later

Recording this because it's a design rail, not just a Phase A detail: **inference confidence alone
must never trigger destructive supersession, in Phase A or Phase B.** The model is, and should
remain:

```text
explicit assertion  -> authoritative relationship (Phase A: state_identity match; Phase B: typed assertion)
inferred candidate   -> review/escalation candidate only (Phase B), never auto-committed
inference alone      -> never a destructive supersession, at any confidence level
```

This mirrors `cb_decision_nodes`' existing, working model exactly, and rules out a specific failure
mode ("the classifier was 92% confident, so it replaced the record") before it can be proposed later
as a Phase B shortcut.

## 7. Explicitly out of scope (this spec)

- No implementation — `resolver.py`/`scope_pipeline.py` are unchanged by this document.
- No Phase B: no typed relationships (`corrects`/`refines`/`extends`/`clarifies`/`decomposes`/
  `constrains`), no confidence-scored candidates, no escalation-queue wiring. The schema leaves room
  (`relationship_type` column, §2) but nothing beyond Phase A's single implicit `replaces` semantics
  is built.
- No automatic backfill of `state_identity` for existing data (§4) — explicit rule, not a deferred
  detail.
- No decision yet on the exact caller-facing surface for supplying `state_identity` (new API/MCP
  parameter name, marker syntax, or both) — small enough to resolve during implementation, not
  blocking this spec's ratification.

## 8. Status

Spec complete, answers the open questions the Phase A decision (`4a11008b-...`) needed closed before
code could start. Implementation itself has not begun and needs its own explicit go-ahead — this
document is the handoff artifact for that next step, not the step itself.
