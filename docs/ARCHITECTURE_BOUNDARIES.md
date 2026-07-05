# Architecture Boundaries — v1.0 Scope-Freeze Contract

Ratified by the CBML v1.0 Architecture Review (2026-07-05). This document is
binding for all contributions until explicitly amended. It exists so that
boundary decisions are mechanical, not re-negotiated per pull request.

## Standing doctrines (constitution)

1. **Deterministic, provider-free core.** The public save/retrieve/reason loop
   must work with no LLM or embedding provider configured. Providers only ever
   *reword or enrich*; they never gate persistence or decide truth.
2. **The hub is not authority.** Graph/hub signals are corroboration and
   provenance, never proof. No component may treat graph adjacency as evidence
   that content is true or current.
3. **Human gate on curation.** Nothing machine-proposed (inferred edges,
   conflict escalations) becomes curated state without an explicit human
   approve/reject step.
4. **Determinism over tunability.** Admission thresholds for graph-derived
   candidates are module constants (see `memory_lab/graph/hybrid_search.py`),
   not runtime parameters.

## The graph authority model

```text
Authoritative graph:      cb_hubs, cb_hub_edges, cb_hub_content
Non-authoritative:        cb_edges (legacy term layer, empty by design)
```

The curated hub graph is the **only edge authority** in v1.0. `cb_edges` has
no writer by design; giving it one is a frozen item (below). If a writer is
ever approved, the `HubTermGraph` union over both layers must be re-reviewed —
one BFS must not walk two authority models indistinguishably.

## Frozen until vNext (Graph Navigation scope freeze)

The following may not be built, extended, or prototyped in-repo without an
explicit unfreeze GO from the project owner **naming the frozen item**:

- new graph traversal engines (anything beyond the existing hop-bounded BFS in
  `memory_lab/graph/expansion.py`)
- authority-model changes (graph/hub signals treated as truth or currency)
- new recall or ranking modes
- LLM- or embedding-driven graph expansion
- path-finding APIs
- any graph write path without a human gate
- a writer for `cb_edges`

## Allowed under freeze (containment checklist)

A change touching graph mechanics is permissible without unfreezing only if
**all five** hold (precedent: FV-FIX-5 boundary amendment, commit `678178e`):

1. read-only with respect to the graph (no writes),
2. operates inside an existing, already-shipped bounded mechanism,
3. candidate admission stays governed by the non-tunable module constants,
4. opt-in per surface (callers not opting in are byte-identical),
5. honestly named for what it is (adjacency/projection, not "traversal" or
   "reasoning" it does not perform).

**Silence-defect fixes that do not change capability semantics are not
considered scope expansion.** (A silence defect: the system already knows a
truth — e.g. that an item is superseded, or that a resolver step was skipped —
but does not show it on an observable surface.)

## v1.0 exception policy

Implementation changes before the v1.0 tag are permitted only when all of the
following hold:

1. They eliminate an epistemic blocker.
2. They do not expand capability.
3. They do not violate scope freeze.
4. They improve truthfulness of observable behavior.

## Boundary amendment procedure

Any request that touches the frozen list must ship a written amendment BEFORE
implementation, containing: root cause (why the boundary blocks the fix), the
containment argument (checklist above, point by point), the opt-in surface,
and the live proof planned. Amendments are accepted or rejected by the project
owner; acceptance is recorded with the commit hash.

## vNext entry criteria

vNext graph-navigation design work opens only on one of:

- (a) a concrete user need that traverse cannot express with existing
  read-only steps,
- (b) accepted demand for a `cb_edges` (term-layer) writer,
- (c) multi-workspace federation requirements.
