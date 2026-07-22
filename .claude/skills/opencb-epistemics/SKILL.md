---
name: opencb-epistemics
description: >
  Epistemic discipline for ANY agent consuming OpenCB (Claude sessions, custom
  GPTs, SDK consumers): when a claim may be called "known" vs "suggested by
  evidence" vs "insufficient evidence", how currency and lineage are checked
  before presenting anything as current or final, how tool output is kept
  visibly separate from inference, and how honest empties are reported. Load
  this skill whenever an agent answers questions FROM OpenCB memory — it is the
  discipline layer shared by opencb-memory (save/query mechanics) and any other
  consumer surface. Stage 1 of the skill ratified via OpenCB decision
  9e7cf8dd-e61f-4ef7-aff9-c07a86939d79 (hash-bound GO).
---

# OpenCB Epistemics — the consumer discipline layer

This is a **consumer-habit skill over existing kernel capabilities — not a
kernel feature**. Nothing here requires a new tool or schema; every rule below
is mined from recorded practice (see the GO'd Skill Mining Proposal v0.1 for
the full trace). It teaches how to *read honestly*, in the same way the kernel
is built to *answer honestly*.

**Truth-sync rule (this skill's own maintenance contract):** this skill cites
capabilities by reference to the capability manifest
(`memory_lab/mcp/capability_manifest.yaml` — per-tool `response_shape`,
`avoid_when`, `key_signals`), never by literal tool counts or exhaustive tool
lists. Tool names appear only as examples resolved against the manifest. **If
this skill and the manifest disagree, the manifest is right and this skill has
a defect** — fix forward and log the correction inline.

## The three epistemic states

Every claim an agent makes about workspace memory is in exactly one of these
states, and the state must be visible to the reader:

1. **Known (recorded).** The claim was read from an OpenCB tool result in the
   current session, the source id (content_id / decision_id) is attached, and —
   for anything currency-sensitive — currency was actually read from a record
   (see below). A claim reconstructed from an earlier session, from memory of
   the workspace, or from general world knowledge is never "known"; at best it
   is labeled "outside the memory".
2. **Suggested by evidence.** Supported only by low/medium-trust retrieval
   results, hub or graph adjacency, title matching, or a single uncorroborated
   fragment. Hub/graph signals are corroboration and provenance, never proof —
   that is kernel doctrine, and the consumer habit mirrors it. Present these
   with the mechanism named ("low-trust retrieval hit", "found via title
   match", "hub-adjacent"); they may motivate a further check, they may not
   ground an assertion.
3. **Insufficient evidence.** Declared only after the two-check honest-empty
   protocol: (1) the semantic answer surface returned its honest-empty
   envelope, AND (2) one reworded evidence retrieval returned nothing
   relevant. Until both checks ran, report *what was checked and what was
   found* — never a flat "nothing". Never conclude "not found" from a single
   semantic lookup.

## Currency and lineage discipline

- **Superseded is never current.** `is_current: false` means SUPERSEDED, full
  stop. Currency is read from a record (`is_current`, current-state anchors),
  never inferred from wording, recency, or plausibility.
- A currency answer is COMPLETE only when currency was actually read. When
  showing a superseded item, name the successor (via the anchor chain for
  content, lineage descendants for decisions) or say explicitly that the
  successor is unknown.
- **Lineage before finality.** A decision is not presented as "the final word"
  until its lineage was checked for descendants — if descendants exist, it was
  replaced; say so.

## Tool-output vs inference separation

Every response visibly distinguishes (a) what tool results said, with ids
attached, from (b) what the agent concluded from them. Sources attach to
facts, never to conclusions the tools did not return. Secondhand or relayed
claims are labeled as such, not silently re-asserted as verified. Name the
mechanism honestly: "linked decision" and "found via title match" are
different answers, and the reader must be able to tell which one happened.

## Honest empties and ambiguity

- `count: 0` and honest-empty envelopes are **facts to report, never errors**
  to retry around and never gaps to fill with plausible text.
- Consult the manifest's `response_shape` for what a surface's honest empty
  looks like before interpreting one — read the shape before asserting the
  semantics.
- **Ambiguity is reported, not silently resolved.** If several items or
  decisions plausibly match, list the candidates and ask, or state which was
  chosen and why. Silent selection is a violation.

## Non-goals (Stage 1)

- Not a kernel change of any kind; any kernel need discovered while applying
  this skill is a Consumer Finding (CF), minted separately.
- Not a replacement for `opencb-memory` (save/query mechanics) or `opencb-ops`
  (admin loops) — this is the discipline layer they share.
- Not machine enforcement: this skill teaches; it does not gate.
- `GPT_SYSTEM_PROMPT.md` remains the deployed consumer-specific rendering of
  the same discipline for the minimal-schema GPT; this skill is the portable
  source.

## Validation

The skill's discipline is validated by the three-fragment scenario harness —
see `docs/EPISTEMICS_VALIDATION.md` (scenarios E1–E4 with explicit PASS/FAIL,
seeded by `scripts/epistemics_validation_seed.sh`). Stage 2 extensions are
gated on real usage evidence of Stage 1, never on anticipation.
