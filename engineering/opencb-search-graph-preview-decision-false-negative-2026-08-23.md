# search_graph_preview(node_type=decision) false negative — root cause atskaite

**Datums:** 2026-08-23
**Repo:** /opt/cbml (CBML / memory_lab)
**Statuss:** diagnoze pabeigta, saglabāta OpenCB; bounded fix IMPLEMENTĒTS un pārbaudīts (sk. "Implementācija" sadaļu apakšā). Vēl NAV commitots.

## Izcelsme

Aizsākts no ārējas (citas sesijas) atskaites par OpenCB hub `a7fb3e05-6c70-4340-a527-cbd188c67bca`
("OpenCB Bugs & Reliability"), finding `8fd5f91e-9df2-404d-9167-ad56b9e26069` un aktīvo lēmumu
`99a841ec-104f-4e4c-adf4-2c2ed05be2e9". Bounded izmeklēšana veikta tieši pret CBML kodabāzi.

## ⚠️ Workspace identitātes brīdinājums

Šī sesija saglabāja atskaiti caur `claude.ai OpenCB` MCP konektoru. Pārbaudot to pašu workspace:

- `list_hubs` atgrieza 48 hubus — starp tiem **nav** neviena ar nosaukumu "OpenCB Bugs & Reliability".
- `get_content_by_id(8fd5f91e-9df2-404d-9167-ad56b9e26069)` → `not found`.
- `explain_decision(99a841ec-104f-4e4c-adf4-2c2ed05be2e9)` → `not_found`.

T.i. **neviens** no trim ID, kas minēti sākotnējā (ārējā) atskaitē, šajā workspace neeksistē.

Iespējamais cēlonis: šī Claude konta MCP savienojumu vēsturē (`claudeAiMcpEverConnected` iekš
`/root/.claude.json`) figurē **divi atšķirīgi** Context Brain konektori:

- `claude.ai OpenCB` — konektors, ko lieto šī sesija (un caur ko saglabāta šī atskaite).
- `claude.ai context-brain-v2` — cits, iepriekš pieslēgts konektors.

Tas ir ticamākais skaidrojums: sākotnējā atskaite, iespējams, nāca no sesijas, kas bija pieslēgta
`context-brain-v2` (citam backend/workspace), nevis `OpenCB` konektoram, ko izmanto šī sesija.
Nav bijis iespējams programmatiski noteikt precīzu workspace_id UUID, uz kuru `claude.ai OpenCB`
konektors ir sasaistīts (nav workspace_id lauka pieejamo tool atbildēs; tas ir cloud-hostēts
konektors, nevis lokāla `MEMORY_LAB_MCP_DEFAULT_WORKSPACE_ID` konfigurācija — kāda gan tiek lietota
lokālajos dev/test skriptos `.claude/settings.local.json`, kur redzami VAIRĀKI dažādi workspace_id
dažādiem test-run kontekstiem, piem. `ac462647-...`, `afb0fc8f-...`, `f0a40f59-...`, `7d9edf14-...`).

**Lietotāja prasība (2026-08-23): "Visiem Aģentiem jālieto vienu!"** — šis ir atklāts jautājums, kas
jārisina ārpus šī konkrētā bug fix: nepieciešams pārbaudīt/nofiksēt, kurš workspace_id ir kanoniskais,
un pārliecināties, ka visi aģenti/konektori (Claude sesijas, MCP serveri, lokālie dev skripti) uz to
norāda konsekventi. Jaunizveidotais hub `2ada1498-a9eb-4f8a-aecb-c95dc6e0cc63` un saglabātā atskaite
`1535d862-e552-4a96-9fec-1056fbc0a216` dzīvo TIKAI `claude.ai OpenCB` workspace — tos vajadzēs
pārvietot/dublēt, ja izrādīsies, ka kanoniskais workspace ir cits.

## Root cause: divi nesaistīti "decision" jēdzieni ar vienu nosaukumu

Sistēmā ir **divas pilnīgi atsevišķas, nesinhronizētas** decision reprezentācijas:

1. **`content_items.node_type = 'decision'`** — vispārīgs klasifikācijas karogs uz parastiem content
   nodes, ieviests migrācijā `008_add_node_type.sql` ("Phase 4 — Node Type Layer"):
   ```sql
   ALTER TABLE content_items
     ADD COLUMN IF NOT EXISTS node_type VARCHAR(32) NOT NULL DEFAULT 'raw_note'
       CHECK (node_type IN (
         'decision', 'fact', 'hypothesis', 'question', 'playbook',
         'concept', 'source', 'task', 'event', 'raw_note'
       ));
   ```
   Uzstādāms TIKAI manuāli caur `classify_content_node` → `ApiAdapter.set_node_type()`
   (`memory_lab/api/services/api_adapter.py:797`).

2. **`cb_decision_nodes`** — pilnvērtīga, atsevišķa tabula (migrācija `010_add_decision_memory.sql`)
   ar `title`, `decision_reason`, `decision_context`, `why_this_matters`, `decision_tags`,
   `alternatives_considered`, `confidence_level`, lineage (`supersedes_decision_id` /
   `superseded_by_decision_id`). Aizpildīta caur `create_decision_memory` / `POST /decisions/`
   (`memory_lab/api/routers/decisions.py`, `memory_lab/decisions/store.py`). Šī ir dokumentāli
   ieteiktā izveides plūsma lēmumiem:
   > "Prefer this over a plain content save for decisions the workspace must track"
   > (`memory_lab/mcp/tools.py:510`)

`search_graph_preview` (`memory_lab/api/services/api_adapter.py:896`, izsaukts caur
`memory_lab/api/routers/graph.py:37` un MCP tool `memory_lab/mcp/tools.py:474`) izpilda SQL **tikai**
pret `content_items LEFT JOIN content_chunks`, filtrējot `ci.node_type = %s`:

```sql
WHERE (LOWER(quick_summary) LIKE %q% OR LOWER(chunk_text) LIKE %q%)
  AND ci.node_type = 'decision'   -- šis lauks NEKAD nesatur reālos lēmumus
```

`cb_decision_nodes` šajā vaicājumā **nekad netiek pieskarts**. `create_decision_memory` nekad neraksta
atpakaļ uz `content_items.node_type` (pat ja tiek padots izvēles `content_id`/`source_content_ids`).

**Rezultāts:** `search_graph_preview(node_type="decision", query=<jebkas>)` ir strukturāli spiests
atgriezt `count=0` gandrīz vienmēr, neatkarīgi no tā, cik lēmumu patiesībā eksistē
`cb_decision_nodes` — tas nav retrieval kvalitātes jautājums, bet arhitektūras split-brain.

## Pārbaudītie 5 hipotēžu punkti

| Jautājums | Secinājums |
|---|---|
| Vai tagi nav populēti? | **Nav vainīgais.** `decision_tags` uz `cb_decision_nodes` strādā korekti (izmantoti timeline/conflicts), bet `search_graph_preview` tos vispār nelasa. |
| Vai title/context/reason nav graph indeksā? | **Jā — tieši šeit.** Šie lauki fiziski eksistē tikai `cb_decision_nodes`, ko `search_graph_preview` neindeksē. |
| Vai hub membership netiek izmantota? | Tiek izmantota (`hub_id` → `cb_hub_content` join content_items pusē), bet tas ir papildu filtrs, ne cēlonis. |
| Vai ir MCP/API wrapper atšķirība? | **Nē.** Pārbaudīta pilna ķēde: MCP tool → `_client().graph_search_preview` → `graph.py` router → tas pats `ApiAdapter.search_graph_preview`. Nav divergences starp virsmām. |
| Vai UI/tool semantika sajauc "0 tagged matches" ar "0 actual decisions"? | **Jā, sekundārs/pastiprinošs efekts.** Atbildes forma `{results, count}` neko nepasaka par to, ka `node_type='decision'` meklē citā, atsevišķā korpusā nekā `cb_decision_nodes`; aģentam nav veida atšķirt godīgu tukšumu no nepareiza indeksa. |

## Implementācija (2026-08-23, veikta šajā sesijā)

Paplašināts `ApiAdapter.search_graph_preview`, lai `node_type == "decision"` gadījumā UNION-o
rezultātus arī no `cb_decision_nodes`, izmantojot esošo `DecisionStore` — bez jaunas tiešas SQL
`api_adapter.py` iekšā:

- `memory_lab/decisions/store.py`: jauna metode `DecisionStore.search_preview(query, limit, hub_id,
  workspace_id)` — ILIKE pret `title`/`decision_reason`/`decision_context`/`why_this_matters`,
  workspace-scoped, hub_match caur `linked_hub_ids`.
- `memory_lab/api/services/api_adapter.py:897` (`search_graph_preview`): content_items rezultāti
  tagad marķēti `source: "content_item"`; kad `node_type == "decision"`, papildus izsauc
  `DecisionStore.search_preview` un merge-o rezultātus ar `source: "decision_node"`, kārto pēc
  `score` un apgriež uz `limit`.
- `memory_lab/mcp/tools.py` (`search_graph_preview` docstring): dokumentēts `source` lauks un
  follow-up ceļš (`load_graph_node_full` priekš `content_item`, `explain_decision` priekš
  `decision_node`).

**Regresijas testi:** `tests/integration/test_search_graph_preview_decision_union.py` (jauns fails,
2 testi):
1. `test_real_decision_found_via_search_graph_preview` — formāls lēmums, kas eksistē TIKAI
   `cb_decision_nodes`, tiek atrasts.
2. `test_zero_query_match_vs_zero_workspace_mismatch_are_distinguishable` — vienā workspace pozitīvs
   trāpījums pierāda korpusu + fix strādā; tajā pašā workspace nesaistīts query dod godīgu 0; citā
   workspace tas pats query dod 0 workspace izolācijas dēļ — trīs dažādi cēloņi, neviens nesajaucams
   ar "lēmumu nav".

**Pierādīts, ka testi tveram bug:** `git stash` (atgriežot pirms-fix stāvokli) → abi jaunie testi FAIL
ar `count: 0` tieši tur, kur pēc fix tie PASS. `git stash pop` atjaunoja fix.

**Regresijas pārbaude:** pilna esošā decision/graph/MCP virsmas testu kopa (69 testi) + classify/ingest
wiring integration (28, 1 pre-eksistējošs skip) + pilns unit gate (1627 passed, 9 skipped) — viss
zaļš pēc izmaiņām, nekas nesalūza.

**Vēl NAV izdarīts:** commit. Gaida lietotāja apstiprinājumu.

## OpenCB saglabāšanas pēdas (šajā, `claude.ai OpenCB` workspace)

- Hub (jaunizveidots, jo oriģinālais `a7fb3e05-...` šeit neeksistē): `2ada1498-a9eb-4f8a-aecb-c95dc6e0cc63`
  — "OpenCB Bugs & Reliability"
- Saglabātā atskaite (content): `1535d862-e552-4a96-9fec-1056fbc0a216` (tier=probationary)

## Papildu workspace verifikācijas mēģinājums (trešā reize)

Pēc šī faila sākotnējās saglabāšanas ienāca vēl viena ārējas sesijas atskaite ar trešo, atšķirīgu ID
kopu: apgalvotais "kanoniskais workspace_id" `69984891-9fd4-4a39-b3e8-c1f0459c9087`, lēmums
`3efededb-c0e9-4eff-b4aa-f7e16d3906e0`, finding `b804653c-29d1-4d9e-a456-b5a582c90515`. Pārbaude:

- `list_hubs` (49 hubi, ieskaitot iepriekš izveidoto `2ada1498-...`) — `a7fb3e05-...` joprojām NAV.
- `explain_decision(3efededb-...)` → `not_found`.
- `load_graph_node_full(b804653c-...)` → `not found`.

T.i. trīs secīgas ārējās atskaites, trīs dažādas ID kopas, NEVIENA neresolvējas šajā `claude.ai
OpenCB` konektorā. Nav pieejama neviena MCP tool parametra, kas ļautu šo savienojumu pārvirzīt uz
apgalvoto workspace_id — tas ir cloud-hostēts konektors bez `workspace_id` argumenta jebkurā no 34
pieejamajiem rīkiem. Kanoniskā workspace apgalvojuma nevar apstiprināt no šīs puses; tas paliek
lietotāja/konta administrēšanas jautājums.

## Status

Diagnoze pabeigta. Bounded fix IMPLEMENTĒTS un pārbaudīts (sk. "Implementācija" sadaļu) — kods,
regresijas testi, pierādījums caur git stash, un pilns zaļš gate. Commit VĒL NAV veikts, gaida
lietotāja GO. Workspace identitātes jautājums ("Visiem Aģentiem jālieto vienu!") paliek atklāts un
nebloķē šo fix — tas jārisina atsevišķi, konta/konektoru līmenī.
