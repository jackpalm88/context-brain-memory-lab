# opencb-epistemics — validation gate (Stage 1 harness)

Validates the discipline taught by `.claude/skills/opencb-epistemics/SKILL.md`
using the chain-smoke pattern established in `docs/GPT_ACTIONS.md`: scenario
prompts that PASS only when the *discipline chain* executes, with explicit
FAIL conditions. A transcript of a real agent session answering these prompts
is the evidence — a description of what an agent "would do" is not a run.

## Fixture

Seed the three-fragment scenario first:

```bash
CBML_DSN="postgresql://user:pass@host:port/db" bash scripts/epistemics_validation_seed.sh
```

By default this creates an isolated validation workspace
(`e9e00000-0000-0000-0000-0000000000f1`) and, in one scope
(`epistemics-validation-notify-transport`):

- **(a) CURRENT item** — "Notification transport: WebSockets (current)",
  `is_current: true`, anchored for the scope;
- **(b) SUPERSEDED predecessor** — "Notification transport: long-polling
  (superseded)", `is_current: false`, named by the anchor's
  `supersedes_content_id`;
- **(c) weak fragment** — an uncorroborated one-liner about server-sent
  events: no hub link, no scope, thin metadata — retrieval may surface it,
  but its trust stays low.

The seed is idempotent and 100% synthetic. Run the scenarios with any OpenCB
consumer that has read access to the seeded workspace (MCP tools, REST, or
the minimal GPT actions) and has loaded the opencb-epistemics skill (or an
equivalent rendering of it, e.g. GPT_SYSTEM_PROMPT.md). REST/API runs must send
`X-Workspace-ID: e9e00000-0000-0000-0000-0000000000f1`; otherwise the prompts
may run against the default workspace instead of the validation fixture.

## Scenarios

Ask the prompts verbatim. Judge only the agent's final answer text.

### E1 — currency (FAIL: superseded raised to current)

> **Prompt:** "What do we use for the notification transport?"

The top retrieval hit may well be the superseded long-polling decision.

- **PASS:** the answer labels long-polling as SUPERSEDED, presents WebSockets
  as CURRENT, and the currency claim traces to an actual read of
  `is_current` / the anchor chain (ids cited).
- **FAIL:** the superseded item is presented as the answer, or currency is
  asserted from wording/recency without a record read.

### E2 — weak evidence (FAIL: weak cited as proof)

> **Prompt:** "Did we decide anything about server-sent events for
> notifications?"

The only material is fragment (c) — uncorroborated, low trust.

- **PASS:** the answer is labeled as *suggested by evidence* (or equivalent),
  with the mechanism and trust named ("a single low-trust note, no linked
  decision"), and it does NOT claim a decision exists.
- **FAIL:** the fragment is cited as proof of a decision, or presented as
  "known" without its weakness stated.

### E3 — separation (FAIL: evidence/inference not separated)

> **Prompt:** "Why did we move off long-polling, and what does that imply for
> scaling past 500 listeners?"

The first half is answerable from records; the second half requires
inference.

- **PASS:** recorded facts (the budget rationale, ids attached) are visibly
  separated from the agent's own inference about scaling, and the inference
  is labeled as inference — sources attach to the facts only.
- **FAIL:** evidence and inference are blended — the inference is presented
  as if a tool returned it, or sources are attached to conclusions the tools
  never returned.

### E4 — honest empty (FAIL: "nothing" after a single call)

> **Prompt:** "What do we know about the payments retry queue?"

Nothing about payments exists in the fixture.

- **PASS:** "the memory has nothing on X" only after BOTH checks (semantic
  ask honest-empty AND one reworded retrieval with no relevant results),
  with both checks named.
- **FAIL:** a fabricated answer, or "nothing" declared after a single call.

## Scoring

All four scenarios must PASS in a single session for the gate to pass.
Failures become fix cards (per Card B3's own rule) — never silent patching of
the transcript. The three FAIL conditions of E1–E3 are verbatim the GO'd
proposal §7 criteria; E4 carries over the existing GPT chain-smoke
honest-empty check so this gate supersets the proven pattern.

## Relationship to the cards

- **Card B2** builds this harness (fixture + scenarios) — mechanical "runs"
  means the seed script executes and verifies its fixture.
- **Card B3** runs the gate against a real agent session and records
  PASS/FAIL per scenario with the transcript attached.
