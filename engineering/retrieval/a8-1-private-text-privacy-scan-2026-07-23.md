# A8.1 Private Text Privacy Scan

Date: 2026-07-23
Executor: Codex/server lane
Repo HEAD before scan: 9c5e4d5

## Scope

A8.1 asks for an inventory of cited-but-private texts and a privacy scan per text.
The scan used public-repo citation search plus local private artifact lookup. The
artifact text was scanned in place; this report intentionally does not reproduce
private source text beyond filenames and risk categories.

Public citation evidence found in this repo:

- `scripts/safe_push.sh` and `tests/smoke/test_safe_push_guard.py` cite
  `AGENT_CONTRACT §10`.
- `CHANGELOG.md` cites `engineering CF-001-004_DESIGN_PROPOSAL` and
  `engineering CF-002_DESIGN_PROPOSAL`.
- `memory_lab/governance/constitutionrules.yaml` and
  `memory_lab/governance/tier_router.py` cite `PHASE7_BRIEFING.md`.

The local engineering reconstruction also names `REFERENCE_FRAMEWORK_V0_FINDINGS`
as a private canonical source behind the CF design-proposal citations.

## Scan Commands

Commands were run from `/opt/cbml`.

```bash
rg -n "AGENT_CONTRACT|MAS_Agent|MAS contract|MAS_Agent_CB_Write_Contract|CLAUDE\.md|CLAUDE|approved hash|approved_hash|§10|Section 10" -S /opt/cbml /opt/cbml.local /opt/cbml-plan
rg -n "CF-002_DESIGN_PROPOSAL|CF-001-004_DESIGN_PROPOSAL|REFERENCE_FRAMEWORK_V0_FINDINGS|PHASE7_BRIEFING|CF design proposals|REFERENCE_FRAMEWORK" -S /opt/cbml /opt/cbml.local /opt/cbml-plan
find /opt -maxdepth 6 -iname '*PHASE7*' -o -iname '*BRIEFING*'
rg -n "(sk-[A-Za-z0-9]|api[_-]?key|token|secret|password|passwd|Bearer|DATABASE_URL|postgres(ql)?://|mysql://|redis://|OPENAI_API_KEY|ANTHROPIC_API_KEY|AWS_ACCESS_KEY|PRIVATE KEY|BEGIN [A-Z ]*PRIVATE KEY|ssh-rsa|ghp_[A-Za-z0-9]|github_pat_|xox[baprs]-)" <private-files>
rg -n "(https?://|/opt/|/home/|/root/|/srv/|/var/|[0-9]{1,3}(\.[0-9]{1,3}){3}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}|@[A-Za-z0-9_.-]+)" <private-files>
rg -n "(Ricardo|Ritvars|Hermes|Fable|Claude|OpenAI|Anthropic|Contabo|contentingestor|superagents|cbml|OpenCB|private|public|publish|push|GO|gate)" <private-files>
```

## Inventory And Privacy Results

| Private text | Local artifact scanned | Public citation path | Secret scan | Privacy risk | Publishability verdict |
| --- | --- | --- | --- | --- | --- |
| `AGENT_CONTRACT.md` | `/opt/cbml-plan/AGENT_CONTRACT.md` | `scripts/safe_push.sh`, `tests/smoke/test_safe_push_guard.py` cite `AGENT_CONTRACT §10` | No credential/token/private-key values found. Mentions env/key concepts only as absence requirements. | Contains private local path `/opt/cbml`, human name/alias, agent-role process, GO/push doctrine, and historical process incident hashes. | Not safe for raw publication without redaction or public-contract rewrite. Safe extract candidate: §10 hash-bound push invariant, with personal names and private paths generalized. |
| `MAS_Agent_CB_Write_Contract_v2.yaml` | `/opt/cbml-plan/MAS_Agent_CB_Write_Contract_v2.yaml` | Not directly cited by current public repo search, but private companion contract cited by local governance reconstruction. | No credential/token/private-key values found. | Contains private local path `/opt/cbml-plan/ROADMAP.md`, decision id, human name, internal memory-write policy, and query-memory operational status. | Not safe for raw publication. Could be rewritten as a public memory-write contract after removing private paths, human identifiers, and live-system status details. |
| `CF-001-004_DESIGN_PROPOSAL.md` | `/opt/cbml.local/engineering/CF-001-004_DESIGN_PROPOSAL.md` | `CHANGELOG.md` cites `engineering CF-001-004_DESIGN_PROPOSAL` | No credential/token/private-key values found. | Contains private workflow/status notes, commit hashes, agent names, and public-surface design rationale. No IPs or URLs found by scan. | Mostly publishable after light redaction and status normalization. Should remove private lane references and clarify whether it is historical proposal or ratified design. |
| `CF-002_DESIGN_PROPOSAL.md` | `/opt/cbml.local/engineering/CF-002_DESIGN_PROPOSAL.md` | `CHANGELOG.md` cites `engineering CF-002_DESIGN_PROPOSAL` | No credential/token/private-key values found. Regex hit on ordinary word "token" only; not a secret. | Contains private production source path `/opt/contentingestor/...`, commit hashes, agent/process notes, and detailed kernel relationship design. | Not safe for raw publication because of private production path. Public version is feasible after replacing private path with a neutral source reference and normalizing status/process notes. |
| `REFERENCE_FRAMEWORK_V0_FINDINGS.md` | `/opt/cbml.local/engineering/REFERENCE_FRAMEWORK_V0_FINDINGS.md` | Named as private canonical source in local reconstruction behind CF citations; not directly cited by current public repo search. | No credential/token/private-key values found. | Contains decision id, commit hashes, GO/methodology notes, and CF register details. No private paths, IPs, URLs, or credentials found by scan. | Publishable with moderate cleanup if decision ids and private-process notes are acceptable; otherwise publish a summarized CF register instead. |
| `PHASE7_BRIEFING.md` | `/opt/contentingestor/.planning/PHASE7_BRIEFING.md` | `memory_lab/governance/constitutionrules.yaml`, `memory_lab/governance/tier_router.py` cite it | No credential/token/private-key values found. No path/IP/URL hits found. | Contains author names/aliases, contributor instructions, and product governance doctrine. | Strong public-doc candidate after author/person-name redaction and a short note that it is historical doctrine. |

Adjacent artifact found but not counted as directly cited by current public repo:

- `/opt/contentingestor/.planning/PHASE7_PLAN.md`: no credentials, private paths,
  IPs, or URLs found by scan. Contains Anthropic dependency/latency discussion,
  SQL/schema snippets, implementation sequence, and contributor/process notes.
  Treat as not in A8.1 core inventory unless a later card expands the scope from
  cited texts to planning bundle publication.

## Result

Inventory exists and every inventoried text has a scan result.

No live credential, API token, private key, URL, or IP address was found in the
scanned cited-private texts. The blocking risks for raw publication are instead:

- private local/server paths;
- human names and agent/persona aliases;
- internal GO/push/process doctrine;
- commit hashes and decision ids that may be acceptable as public provenance but
  should be reviewed deliberately;
- private production source references in CF-002.

Recommendation: do not publish any private source text raw. Prepare public-safe
extracts in this order: `AGENT_CONTRACT §10`, `PHASE7_BRIEFING`, CF proposals,
then MAS v2 only if the project wants public memory-write governance.
