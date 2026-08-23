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
nothing about it is guessed. No tier of `scope_pipeline.py` (marker, lineage, hub_alias,
classify_metadata, keyword_heuristic, global_fallback) may *derive* a `state_identity` — that would
just recreate today's bug in a new column with a different name, which is exactly the migration
mistake to avoid (§4).

**Revised per §9 (implementation-readiness pass, review `40961bea-...`): Phase A supports exactly
one input surface for `state_identity` — a dedicated, typed API/MCP request parameter supplied by
the calling application layer.** The v0 draft of this spec also allowed "an explicit in-text marker
analogous to `current_state_scope:`" — dropped. An in-text marker is text an LLM can emit inside
generated content on its own initiative; syntactically explicit, but not necessarily backed by any
real application-level authority, which reopens exactly the "inference in a trenchcoat" risk this
spec exists to close (§9.2). If a marker-based surface is wanted later, it belongs to Phase B
alongside the rest of the trust/authority model for inferred-but-declared input, not Phase A.

**Can governance/classification propose a candidate without committing it?** Not in Phase A. That
capability (a classifier suggesting "this might be the same identity as X, confirm?") is exactly the
shape of Phase B's escalation-routed ambiguity handling — deferred, not built now. In Phase A, no
`state_identity` means no supersession, full stop (§3).

**Uniqueness key:** `(workspace_id, memory_type, state_identity)` — same partitioning
`cb_current_state_anchors` already uses for scope today, with `state_identity` replacing `scope` as
the third column *only for the supersession lookup*. `memory_type` stays part of the identity: it's
already a natural, working partition (a `decision` and an `evidence` row are never treated as
candidates for the same identity today, and there's no reason to relax that in Phase A).

**Schema form, decided (per §9 readiness pass — the v0 draft left this open, picking one now):
`state_identity` is a nullable column added directly to both `cb_current_state_anchors` (the
supersession-lookup key, alongside `scope`) and `content_items` (denormalized for cheap reads, the
same pattern `cs_supersedes_content_id`/`is_current`/`current_state_scope` already use there today).
No new table.** A separate identity/supersession table was considered — cleaner separation, easier
to extend with `relationship_type` later — but rejected for Phase A specifically because it's a
heavier migration than the smallest-reversible-increment framing this spec is built on (§8 of the
research note). If Phase B's typed relationships need a dedicated table, that's Phase B's migration
to scope, not Phase A's.

**Revised per review `de24fac8-a7c5-435f-883a-b0350230a1f1`: no `relationship_type` column in Phase
A, not even nullable.** The v0 readiness-pass draft proposed adding it now as a forward-compat
placeholder. Reconsidered: Phase B hasn't ratified *where* typed relationships should live — same
two tables, a dedicated edge table, or a different assertion model entirely — so adding the column
now would freeze part of that undecided data model prematurely. "Leave room for typed relationships"
stays a spec/invariant note (§1, §6), not a physical column. A single nullable column is a cheap
migration to add later, once Phase B actually decides where it belongs — cheap enough that
pre-committing to it now buys nothing.

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
  `constrains`), no confidence-scored candidates, no escalation-queue wiring, and (per `de24fac8-...`)
  no `relationship_type` column of any kind yet — nothing beyond Phase A's single implicit `replaces`
  semantics is built or pre-allocated in schema.
- No automatic backfill of `state_identity` for existing data (§4) — explicit rule, not a deferred
  detail.

## 8. Implementation-readiness pass (review `40961bea-8765-4259-a1bb-d9f1f7016786`, decision `982606cd-f487-4983-ad71-c18959e708c0`)

The v0 spec (§1-§7 above, edited in place above where superseded) left three implementation-contract
gaps. This section closes them without reopening the Phase A architecture choice itself.

### 8.1 Read-model / cardinality contract — must change alongside the write path

Phase A's whole point is that multiple `state_identity` chains can legitimately coexist under one
`current_state_scope`. Three real, already-shipped surfaces currently assume the opposite —
confirmed in code, not hypothetical:

- `ApiAdapter.list_current_state_anchors` (`memory_lab/api/services/api_adapter.py:605`) docstring:
  *"The resolver keeps at most one active anchor per (workspace, memory_type, scope)."*
- `GET /v1/current-state/anchors` (`memory_lab/api/routers/current_state.py:1-9,25-40`) module
  docstring: *"return its active anchor(s) — **at most one per memory_type** by resolver invariant"*;
  the `memory_type` query param docstring repeats the same "one active anchor per memory type"
  framing.
- MCP `list_current_state_anchors` (`memory_lab/mcp/capability_manifest.yaml:152-158`): framed as
  answering *"What is **the** current item of scope X?"* — singular by design.
- `memory_lab/conflicts/detector.py:150-172` (`multiple_current_anchors_v1`): groups candidate rows
  **`by_scope` alone** (line 110-113, `by_scope.setdefault(row_scope, []).append(...)`), and raises a
  high-severity (`0.80` confidence) `stale_current_tension` conflict whenever more than one
  `is_current=True` row shares a scope. Under Phase A this would fire on every scope with ≥2
  legitimate, independent `state_identity` chains — a guaranteed flood of false conflict escalations
  on correct behavior, the opposite of what that detector exists for.

**Required contract change, part of Phase A, not deferred:**

1. `list_current_state_anchors` (adapter + router + manifest text) must be re-documented and, where
   it filters, re-scoped: querying by `scope` (± `memory_type`) is a **grouping** query and may
   legitimately return multiple active anchors — one per distinct `state_identity` (plus at most one
   legacy `state_identity IS NULL` row per §4's transition rules). Callers who want "the one current
   item for a specific tracked fact" must supply `state_identity`, not `scope`, once it exists. This
   is a real, documented API behavior change, not just an implementation detail — it needs to ship
   with the same Phase A release, not follow it.
2. `multiple_current_anchors_v1` must group by `(workspace_id, memory_type, state_identity)` where
   `state_identity` is non-null, and keep today's `by_scope` grouping **only** for the
   `state_identity IS NULL` (legacy) subset. Two active anchors sharing a scope but holding different
   non-null `state_identity` values are not a conflict and must not generate one; two active anchors
   sharing a scope with `state_identity IS NULL` on both stay exactly as risky as they are today
   (correctly still flagged, since that's the untrusted-legacy case per §4).

### 8.2 Caller-explicit ≠ authoritative — the authority boundary

Valid distinction the v0 draft blurred: an LLM agent writing `state_identity="message-queue-choice"`
into a structured tool call is syntactically explicit but not necessarily *epistemically* explicit —
it can still be the model's own inference, just relocated from free text into a parameter, which
would smuggle destructive supersession back in through a technically-compliant side door.

**Phase A authority rule:** `state_identity` may only be supplied by a request whose caller
identity/route is on an explicit, pre-declared allowlist of trusted writers (e.g. a specific
application/workflow integration that has deliberately chosen to track a singleton fact this way —
analogous to how `cb_decision_nodes.supersedes_decision_id` is trusted because it's a deliberate,
reviewed API call from a workflow that decided to declare a replacement, not a model free-associating
inside a text field). A general-purpose content-ingestion path (e.g. `create_content_minimal` today)
must **not** accept a caller-supplied `state_identity` from arbitrary/untrusted callers by default —
this is the enforcement mechanism for §6's "inference alone never triggers destructive supersession,"
applied to the *provenance of the parameter itself*, not just to the classifier's confidence score.
Dropping the in-text marker surface (§2) is one part of this; the allowlist/trust-boundary on the
structured parameter path is the other, and both are required together.

### 8.3 Marker precision and schema form — resolved (edits made directly in §2 above)

Both folded into §2 in place rather than left as a separate note: (a) Phase A has exactly one
`state_identity` input surface (a typed request parameter from a trusted caller, per §8.2) —
the ambiguous "existing marker vs. new marker" question is moot because there is no marker in Phase
A at all; (b) schema form is decided as columns on `cb_current_state_anchors` + `content_items`, no
new table, smallest-reversible-increment rationale stated explicitly.

## 9. Acceptance matrix (ratified `de24fac8-a7c5-435f-883a-b0350230a1f1` — binding for implementation)

Every item below must hold for Phase A to be considered done. This is the test list, not aspiration:

1. No `state_identity` supplied → `current_state_scope` grouping still works, supersession **never**
   fires (`cb_current_state_anchors` untouched).
2. Trusted caller + `state_identity` → supersedes only an existing active anchor with an **identical**
   `(workspace_id, memory_type, state_identity)`.
3. Same `current_state_scope`, different `state_identity` values → both stay `active`, no false
   conflict raised (§8.1's `multiple_current_anchors_v1` re-grouping).
4. Untrusted / general-purpose caller attempts to supply `state_identity` → fails/rejects explicitly,
   never silently accepted or silently dropped (§8.2).
5. `multiple_current_anchors_v1` does not flag legitimate multi-identity coexistence under one scope.
6. Legacy `state_identity IS NULL` rows keep today's (stricter, `by_scope`) conflict-detection
   semantics — isolated from the new identity-based path, not silently upgraded or downgraded.
7. Re-ingesting the same `content_id` is idempotent — no duplicate anchors, no duplicate escalations.
8. Zero automatic backfill of `state_identity` from `current_state_scope`, anywhere in the write path.
9. The four false-supersession fixtures from this investigation
   (`914a75c9`/`10825d3a`, `bd3cd7e4`/`47f0499b`, `cdb6284a`/`4cb27e68`, `f2937127`/`69383060`) are no
   longer reproducible under the same conditions, **and** the known true-supersession fixture (F1,
   `62798537`→`1512cba4`, or an equivalent explicit-identity case) still resolves correctly through
   the new `state_identity` path.

## 10. Status

Spec complete through the implementation-readiness pass (§8) and the pre-implementation review
(`de24fac8-...`, §9's acceptance matrix, `relationship_type` column removed from Phase A). All gaps
closed: read-model/cardinality contract change specified (§8.1), authority boundary defined (§8.2),
marker/schema ambiguity resolved (§8.3, §2), schema minimized to `state_identity` only (§2).
Architecture itself (`4a11008b-...`, candidate #3 as Phase A) was not reopened at any point.
Implementation is authorized to begin against this spec and acceptance matrix.
