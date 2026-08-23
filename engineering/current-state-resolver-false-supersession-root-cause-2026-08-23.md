# current-state resolver false supersession — root cause investigation

**Datums:** 2026-08-23
**Repo:** /opt/cbml (CBML / memory_lab), canonical workspace `69984891-9fd4-4a39-b3e8-c1f0459c9087`
**Escalated by:** decision `c6a4103f-5e46-4ec0-b61b-7bdcd69c923e` — *"Escalate repeated false
current-state supersession to a bounded root-cause investigation"* (after 3 reproductions in one
session while saving [[opencb-search-benchmark-rfc]] work — see `OpenCB Bugs & Reliability` hub,
findings `cdb6284a-...` and the RFC v0.1 file's §11.1).
**Status: root cause identified. No fix implemented — this is investigation only, per the same
bounded-scope discipline used for the search-matching finding.**

## Root cause

`memory_lab/current_state/resolver.py`, function `resolve_current_state_after_ingest`
(lines 139–188), does this on every ingest with `classify_confidence >= 0.70`:

1. Look up the most recent **active** row in `cb_current_state_anchors` matching the exact triple
   `(workspace_id, memory_type, scope)`.
2. If one exists, mark it `superseded` and set the **new** content's
   `cs_supersedes_content_id` to point at it — unconditionally.

This treats `(workspace_id, memory_type, scope)` as if it were a **singleton-fact identity key** —
like a KV store where writing a new value for the same key naturally replaces the old one. That
model is correct for narrow, deliberately-declared scopes (e.g. an explicit `scope_hint` or an
in-text `current_state_scope:` marker naming one specific tracked fact, like "which message queue
do we use now?").

It is **wrong** for scope, `memory_type`, or scope for broad topic-cluster scopes — which is exactly
what most of `current_state_scope` actually is in practice. `memory_lab/current_state/scope_pipeline.py`
(FV-FIX-2B, a deliberate prior design) resolves scope through a tiered pipeline, and two of its
tiers are **explicitly, by design, coarse topical clustering**, not fact identity:

- `_match_lineage_scope` (tier 3, `source: "lineage"`) — docstring: *"Reuse an existing active
  anchor scope whose slug tokens all appear in the content."* Any new content sharing enough
  keyword tokens with an existing scope's slug gets bucketed into that same scope.
- `_match_hub_scope` (tier 4, `source: "hub_alias"`) — matches content against a hub's title/aliases
  (strong) or `related_terms` (weak, ≥2 hits). Any content topically adjacent to a hub gets that
  hub's scope.

Both are working exactly as designed — the bug is that `resolve_current_state_after_ingest`
consumes their (intentionally broad) output as if it were a narrow identity key.

## Confirmed reproduction (3/3 exact triple matches)

| New content | memory_type | scope | Falsely marked as superseding |
|---|---|---|---|
| `914a75c9-...` (RFC v0 finding) | `anchor` | `retrieval-embeddings` | `10825d3a-...` (unrelated Curator/Orchestrator/Reasoner doctrine note) |
| `bd3cd7e4-...` (RFC v0.1 update) | `evidence` | `retrieval-embeddings` | `47f0499b-...` (unrelated MCP schema defect: list_hubs list-vs-dict) |
| `cdb6284a-...` (finding about bugs 1+2) | `anchor` | `opencb-retrieval-vs-memory-architecture` | `4cb27e68-...` (unrelated retrieval/memory-architecture-layers doctrine note) |

Every single false link is an **exact** `(workspace_id, memory_type, scope)` triple match — no
partial matches, no near-misses. This isn't fuzzy misclassification; it's the resolver doing
precisely what it's written to do, on inputs whose broad-topic-bucket scope was itself working as
designed. Both `memory_type` and `scope` are assigned by the same heuristic classifier
(`classify_mode: heuristic_v1`, `classify_confidence` 0.45–0.72 across the three cases) with no
awareness of subject matter — so any two topically-unrelated saves that happen to land in the same
bucket get wired into a false supersession chain, silently marking one as historical.

## Blast radius

Any workspace/`memory_type`/scope combination that legitimately holds multiple, genuinely
coexisting, non-superseding pieces of content — which is most broad topic scopes resolved via the
`lineage` or `hub_alias` tiers — is at risk of this. Each new save into a shared broad scope risks
silently hiding an unrelated prior save from current-state views (`is_current = FALSE`,
`cb_current_state_anchors.state_status = 'superseded'`). This is a real content-visibility risk, not
just a cosmetic metadata glitch — code/tools that filter on `is_current`/anchor status would miss
the wrongly-superseded content entirely.

## Candidate fix directions (not decided, not implemented — for a future scoped decision)

1. **Narrow the auto-supersession trigger to identity-declaring scope sources only.** Only run the
   "mark previous active anchor superseded" behavior when `scope_source` is `scope_hint` or
   `marker` (explicit, caller-declared, narrow) — skip it for `lineage`/`hub_alias`/
   `classify_metadata`/`keyword_heuristic`/`global_fallback` (broad, inferred). Content in those
   broader scopes could still get `current_state_scope` set for grouping/retrieval purposes, just
   without the singleton-supersession side effect.
2. **Add an actual relatedness check before superseding** — e.g. require semantic/text similarity
   above a threshold between the new and candidate-previous content, or require the caller to
   explicitly declare `supersedes_content_id`, rather than inferring it from scope-bucket
   co-membership alone.
3. **Split the concept** — keep `current_state_scope` as the broad grouping/retrieval tag it already
   behaves as in 2 of 3 pipeline tiers, and introduce a separate, narrower key for the singleton-fact
   tracking `cb_current_state_anchors` was actually built for (CF-001/CF-004 history in this repo's
   memory already distinguishes "timeline" vs "current state" semantics — this may be a related
   distinction that needs the same treatment).

Any of these is itself an architecture decision with its own tradeoffs ((1) is the smallest,
most surgical change; (2) adds real cost/complexity; (3) is the most correct but largest). Per the
`5b019127` precedent from the search-matching investigation, this deserves its own scoped decision
before implementation, not a quick patch bundled into this investigation.

## Note: independent duplicate write-up found in the workspace

Logging this investigation (`content_id=a6bf094e-4e6f-43ca-8d56-a2c032cb0afc`) triggered a
conflict escalation (`conflict_escalation_id=7d52baea-...`, `conflict_content_id=7640cc15-...`,
status `pending`) — legitimately, this time. `7640cc15-...` is an independent prior write-up
of essentially the same finding (same false-positive incident, same remediation direction:
*"automatic current-state supersession must require stronger evidence than coarse scope equality
alone... or must fail to a non-destructive ambiguity state when confidence is insufficient"*).
Left in the conflict queue for proper governance review rather than auto-resolved — unlike the
`cs_supersedes_content_id` false positives elsewhere in this investigation, this one is a real,
plausible content relationship, not a resolver defect instance.

## What was and wasn't done

- **Done**: root cause identified and confirmed via 3 independent reproductions, all fixed at the
  data level (targeted `cs_supersedes_content_id = NULL` corrections, not resolver code changes).
- **Not done**: no change to `memory_lab/current_state/resolver.py` or `scope_pipeline.py`. No
  decision made on which candidate fix direction to pursue. That's the next step, pending review.
