# Steward decision↔hub linkage — classification (2026-09-26)

Workspace `69984891-9fd4-4a39-b3e8-c1f0459c9087`, hub `8404d619-b079-4311-aea8-2a46559f9aaa` (Steward Agent).
Context: `hub_scope=strict` (a93edb8) returns 0 Steward decisions because 0 decisions carry this hub in `linked_hub_ids`.
Checkpoints: ca15b460 (task), 961516f2 (GPT-B deploy decision).

## Signals evaluated (973 workspace decisions)
| Signal | Count | Verdict |
|---|---|---|
| title contains `steward` (substring) | 81 | strong, but 1 false positive via "stewardship" |
| title `\mSteward\M` or `steward_portfolio_scan` | **80** | **Tier A: deterministic** |
| body-only mention (reason/context/why) | 49 | ambiguous: mostly Research/Coding/Planner/portfolio-test decisions mentioning Steward in passing |
| source_content in Steward hub | 54 (41 without any Steward text) | **not usable as proof**: hub content is contaminated (see below) |
| decision_tags containing steward | 0 | none |
| existing linked_hub_ids (any hub) on Tier A | 0 | additive link cannot overwrite anything |

## Finding: the Steward hub itself is mixed
Of its 40 content items, most are Planner, canonical-body, MCP workspace-scoping and the search-preview incident (4fcfa5bf), not Steward.
Inheriting a hub link through `source_content_ids` would carry that curation error over into the decisions. That is a separate hub-curation task.

## Tier A rule and backfill
`title ~* '\mSteward\M' OR title ILIKE '%steward_portfolio_scan%'`, giving 80 decisions (70 active, 10 superseded/other).
Script: `steward-decision-hub-backfill-2026-09-26.sql`. It has a pinned ID list and guards (hub owner = ws, 80/80 ids in ws), uses `array_append` only when the hub is absent (idempotent), and does not bump `updated_at` (to protect Steward freshness ranking). It reads back before/after, checks collateral, and simulates strict scope.
Dry run (ROLLBACK): after=80/80, updated_at_changed=0, prior_links_lost=0, collateral=0, strict_preview=80, second run no-op.

Multi-subject in Tier A (additive link, low risk, flagged for review): a8041ef8 (roadmap sequencing "…then Steward"), 6302369a, d0a14d58, 2bc23c88.

## Applied 2026-09-26 (GO bf144278, content 0e93b74a)
- Committed run: before 0/80, after 80/80, updated_at_changed=0, prior_links_lost=0, collateral=0.
- The 894 decisions outside the list have an identical fingerprint before and after (md5 over id, linked_hub_ids, updated_at).
- Second committed run: `UPDATE 0`, Tier A fingerprint unchanged (idempotent).
- Live API: `node_type=decision&hub_id=<Steward>&hub_scope=strict&limit=50` returned 50/50 decision_node rows, all in Tier A, all hub_match=true, with scope_applied present.
  Annotate mode on the same query still includes non-Tier-A 3dd35661 (hub_match=false).
- Not done here (by decision): Steward hub content cleanup, the 49 body-only decisions, the 41 source-inherited decisions.
- Backlog: there is no governed API write path for decision↔hub links after creation, so direct SQL was required.

## Left AMBIGUOUS (no backfill)
- 3dd35661: "stewardship" (Crystallization topic)
- 49 body-only decisions (list below)
- 41 source-only decisions (hub contamination)

### Tier A IDs
- 4b1c3c3c-1ec7-4561-bedf-46df0b5fc29f,active,OpenCB Steward gets broad reorganization capability but proposal-first governed authority
- 31544c35-8ca7-45b0-b94e-697d17d074b3,active,OpenCB Steward/Crystallization actions must produce an auditable action log
- 13fc8c9a-7cb6-40c1-9cb1-523610a0e1de,active,Adopt a minimal Steward Audit & Evidence Contract before generalizing an ExecutionReceipt platform
- d0a14d58-fb41-4e69-ad6d-1e436f33d6e8,active,"Research Agent may persist append-only research evidence, while Steward owns semantic organization and canonical promotion"
- a8041ef8-88e4-4375-af07-cdcd32104859,active,"Next work sequence after Agent-Builder hardening: finish Research context/persistence, then build bounded Coding Worker, then Steward"
- c5e5c4ed-bdab-4770-bac8-8376573f66dc,superseded,Repo/context intelligence v0 DONE; GO — Steward MVP
- 957efa8c-ef0a-4410-9d9e-ec23fa645ced,active,"Correction — build Steward MVP through Hermes + Agent-Builder, not as a direct Claude implementation"
- 6f6c753c-4e4f-4a7f-b40d-bea048ee0c24,active,GO — Steward v0.1 runtime acceptance verification
- 0741296d-1463-410f-851d-44ab590d7e69,superseded,"Steward runtime failure is a Builder/conformance defect, not a Hermes-wide outage"
- 8d0a88f6-1eb6-473f-8afa-b78809450dd6,active,Steward live manifest hotfix accepted for recovery; permanent fix must be Builder-regenerated and conformance-enforced
- d6f732e6-57f7-4bd8-8af7-f5830e50571e,active,Continue Steward v0.1 verification with one real provider-served activation; do not promote candidate status before serving receipts exist
- 37da86ad-852b-43e8-a388-25bfbcabcf8c,superseded,Steward scan behavior PASS; runtime acceptance still OPEN because provider dispatch/serving identity remains unproven
- 7be7e6d4-f1ec-4fff-9251-51c62ea7a3c1,active,Steward v0.1 live read/propose-only agent — runtime acceptance PASS
- addf3f01-7e87-4674-a5a5-8179f03afeea,active,GO — Steward proposal→crystallization acceptance v0
- befaa5ac-53c9-49da-b14e-5c43e3064f22,active,Steward v0.2 evidence annotations must be receipt-backed; decision readiness is derived
- 64b67f87-6b94-4cac-aac2-7fa9cbc1453a,active,GO — Steward v0.2 epistemic evidence core implementation
- 450f944d-170d-4ba9-b07a-08aeca049443,superseded,Steward v0.2 implementation PASS; live behavioral acceptance still required
- 5848cc69-f503-4491-a8ec-d78470cd7280,active,Steward v0.2 behavioral discipline PASS; final acceptance requires runtime validation/derivation wiring
- 005cf2ab-0296-4682-b47c-0fd8813cc23d,active,"Steward v0.2 live acceptance remains OPEN; fix evidence capture, not validator semantics"
- 1d1d8375-967f-4a4b-81e3-85a358d8d84c,active,Authorize controlled Hermes gateway restart for Steward v0.2 receipt-seam live acceptance
- 50e96e1f-29c3-49b4-abfb-47f5923e6943,active,Grant Steward a narrow brokered OpenCB read surface for canonical evidence; do not lower v0.2 acceptance bar
- 59a482f5-02fe-4369-8d5f-5d94369a504a,active,Split host-side scoped OpenCB MCP call path into its own engineering GO before resuming Steward v0.2 acceptance
- 7c348153-2619-49a4-8229-614ccdef8eca,active,Authorize live sync/reload for scoped OpenCB read bridge and resume Steward v0.2 acceptance
- 48b13a4e-04c9-4ae5-a1c4-7cab72e1127a,active,Steward v0.2 bridge deployment is not yet live-accepted; trace provider-visible tool exposure end to end
- 8440be53-4415-4c1f-9345-34d41aebac70,active,Scoped OpenCB bridge live exposure PASS; run final Steward v0.2 live epistemic acceptance
- 3f3e1bf0-c620-471b-bc5f-3e284e6d3bbb,superseded,"Treat latest Steward v0.2 failure as specialist lifecycle/session-reset defect, not bridge failure"
- 02a21e60-0353-433b-b32c-d316dd5598bc,active,Telegram specialist-private candidate expansion accepted; resume final Steward v0.2 live acceptance
- d8f388df-f0a1-484e-9483-e574e81a5bda,active,Trace exact live provider request payload before any further Steward bridge changes
- a8e6f72b-bb6e-4a3a-8e63-554557aaec5f,active,Accept MCP-refresh reinjection fix; rerun unchanged Steward v0.2 live acceptance
- c8957d81-f68a-4aed-bf0b-81d23a22bfd4,superseded,Live scoped OpenCB wrapper path is proven; final Steward v0.2 acceptance awaits deterministic derivation
- 9319e793-3445-47c9-88da-fd7fa7ea26d7,active,Steward v0.2 epistemically-aware reporting — PROVEN LIVE
- 95763656-a02b-4bce-b97a-0973787ffa39,active,Do not cron Steward yet; first prove the complete portfolio cycle manually
- 9a07173f-9a6e-4cae-971b-45379eeac93c,active,"Hermes should invoke Steward through a bounded service contract, not by exposing Steward-private tools"
- d2588510-576f-4317-a6f4-530d786b0361,superseded,Steward integration first slice is the typed `steward_portfolio_scan` service contract
- f64c4efa-b105-41fa-b88e-241e68f71a09,active,`steward_portfolio_scan` runs a real Steward agent turn inside a deterministic service envelope
- 23e102c9-b27c-40ef-add5-95efcb9a9083,superseded,GO — Build `steward_portfolio_scan` first-slice callable service now
- 5e520c66-b1d2-42b9-97b9-fbe12ef2c393,active,Fix canonical specialist provider resolution in `steward_portfolio_scan`; do not hardcode provider/model
- 2bcfdce2-ac3a-4f21-aa32-80b380a2e0e8,active,`steward_portfolio_scan` first slice — PROVEN LIVE
- 0d988359-7b2c-40b8-84b6-3785b3d0700a,active,Next milestone: prove one complete manual Steward portfolio cycle on a real thread
- dd4228cd-68c8-4404-b0d6-84e04d4d5570,active,Use Coding Agent multi-backend provider policy as the first full Steward portfolio-cycle thread
- fab26762-cb65-4dfe-a1af-b402b884532f,active,GO — Run the first complete manual Steward portfolio cycle on Coding Agent multi-backend policy
- be802fc3-03da-4bc4-a5d3-2c2d7d024e3d,active,First manual Steward portfolio-cycle output verified; full Research handoff still open
- 1c36ff60-ed4b-4562-8867-ce6d3015778a,superseded,First complete manual Steward→Research→Crystallization portfolio cycle — PROVEN LIVE
- 9863c963-db75-466e-af4c-7f3dcf27d07f,active,Hermes-autonomous Steward→Research→Crystallization portfolio orchestration — PROVEN LIVE
- 24d9c3de-101d-4e2e-8fa1-904075b8a9c8,active,First real Steward→Research→Crystallization→canonical OpenCB loop — PROVEN LIVE
- 3f6d5ea0-8b92-451d-824c-116c49b12945,superseded,GO: expose bounded Research/Steward service wrappers to base Hermes control plane
- e5fb5b4c-826b-4dc6-965b-b3f1518c3b2d,active,Base-Hermes Research/Steward orchestration wrappers — PROVEN LIVE; resume fourth portfolio completion
- df530753-7adb-4d6f-b009-c3df44bb8f13,active,Steward owns continuous idea-portfolio review and resurfacing
- 07dceab2-70d6-464e-a204-a4bc50b2f656,active,"Before full Steward→Research→Crystallization→Planner E2E, run a Hermes/Agent-Builder integrity and discovery audit"
- affdf752-d471-458b-b290-4cd00d887f98,active,Do not bypass Steward in cognition E2E; treat GPT-5.5 429 as provider-availability blocker and preserve model-policy authority
- 8a7eab45-db29-4bff-8ac6-69a138202a78,active,Trace specialist routing-boundary reset before further Steward behavioral testing
- 0fe5e517-9f83-45bb-bf49-980c9e1155ea,active,Do not delete Steward adapter copies until loader discovery is proven; source-vs-live mirror may be intentional
- 2437ad59-bc02-4563-a650-57f73f6f7d5b,active,Canonical Steward should add MiniMax-M3 as approved fallback rather than create a separate test profile
- f16a90e0-bb92-473e-98bb-27df04cfce0c,active,"Before adding MiniMax fallback to Steward, prove the actual runtime consumption path with a read-only probe"
- d55d22ba-4339-486a-8405-193ab1313a21,active,Steward MiniMax fallback remains pending one real loader run and a dedicated approval decision
- f02a55cf-cb48-4d2d-a7d6-86fd7cec66e9,active,GO read-only Steward configuration audit A/B/C before any fallback patch
- 49ec6a54-1d2a-440d-b3ae-6323334ef0aa,active,Approve MiniMax-M3/minimax-oauth as canonical Steward fallback runtime pair
- 67af5faa-b17a-4e6f-a3aa-607a6151cada,active,"Before Steward fallback mutation, verify Builder manifest and real emit/hash path"
- ac586138-4751-44ee-9e8a-8d0d0423262e,active,Proceed with Steward MiniMax fallback patch; do not touch unrelated canonical-source hashes
- c4711322-6f36-4a8e-8b13-fb663fac0314,active,Do not treat FinanceAgent as Steward; resume patch only from verified Hermes Steward source tree
- fc943a3d-2d56-42cd-bf36-bac43ed9b205,active,Steward MiniMax fallback configuration is ready for live E2E
- adcdba2d-c337-4769-ad54-816634595150,active,Treat OpenCB canonical-state degradation as primary cause of the weak Steward incident; keep MiniMax suitability as open hypothesis
- dba72934-9391-418b-a8da-c89a6c9fd99d,active,Replay the exact Steward preview_search payload before any baseline retrieval test
- 0337ecb3-f6e3-46fe-9d37-e564596ae4cd,active,Split Steward incident remediation into two independent fixes
- e12049d2-0068-45a0-abbe-b7e661ea0094,active,Continue Steward testing; defer non-blocking OpenCB retrieval-quality gaps
- d79cbd6b-6de4-4c07-a9fb-a3857f11205a,active,Do not mark the latest Steward real-prompt run fully verified until the P2 PRE-scope evidence mismatch is reconciled
- 4188fd4d-58d5-4834-81a3-60c3d35a000c,active,Treat latest Steward P2 scope error as adjacent-source attribution bug; require exact content-id keyed citation checks
- bfd414af-6217-4f95-be3e-51010c910b8c,active,Steward prioritization should be gated by freshness/authority before choosing the next work item
- 90cc75dc-bd23-4747-8f9e-18e2b441dd89,active,"For Steward model selection, use a matched real-task Codex vs MiniMax A/B, not Coding-Agent canary machinery"
- 05a59cfe-749f-4bf7-abec-6cb587f0b281,active,Run immediate matched Codex Steward retest using identical natural prompts and verify actual serving identity
- d982ed99-2a26-4116-9a8d-18068eff3b8c,active,"Treat Codex as provisional leader on the first matched Steward A/B prompt, but do not finalize long-term preference yet"
- 86093db9-a7c2-416c-9928-77ae056c6fae,active,Use Codex/GPT-5.5 as Steward primary; keep MiniMax-M3 as fallback while refining current-state precision
- e9db3ba9-8923-49ea-af40-d27e411696d0,active,Patch Steward freshness/authority retrieval first; instrument #54878 before attempting a routing fix
- 6302369a-1b41-4453-92ff-89d970801efc,active,"Prioritize production-grade Steward, then verify Research as a genuinely independent specialist; defer Crystallization/Planner"
- 2bc23c88-4827-4d55-a517-f98f2d0e29aa,active,Keep Steward local/OpenCB-focused; use Research as the independent local+web investigation layer
- 88711657-9aec-4f9d-b6e0-957dc696fb8e,active,Implement Steward freshness fix as strict scoped dual-channel retrieval; do not guess current_state_scope
- 747bc282-84d2-4cdc-97fa-3c63029b3d32,active,GO: keep the local dual-channel Steward retrieval patch; next finish server-side hub scoping before behavioral acceptance
- 22b439dc-8109-47e3-aad7-bb58bcb2b618,active,Do not finalize Steward decision precedence until lifecycle/currency semantics are enforced
- f9057e21-d2a2-4367-8b75-cf9797af0da6,active,GO commit local Steward decision-visibility/currency patch; production acceptance remains blocked on hub scoping and live gateway replay
- 39f91495-345c-4e49-a010-3c774cd371a6,active,GO push strict hub-scope backend patch; do not enable strict decision retrieval in Steward until decision↔hub linkage gap is addressed

### Ambiguous body-only IDs (human review)
- 08b4d1b2-33e7-404f-952a-b54aabdf6d78,active,Begin Agent-Builder next; using Psychology as the first proven specialist reference rather than expanding OpenCB further first
- b578f208-579c-473b-8e2c-4896c1ea1209,active,Mature OpenCB changes require a crystallized change dossier before planning or implementation
- 0180b005-2228-4015-9719-5cd2127f6833,active,Research Agent should launch as a narrow provenance-first MVP; then expand source adapters modularly
- 8dd5b485-a81e-40d3-96b1-aab9fd8e12e5,active,First Research Agent GO is a bounded v0.1 Foundation build; ending before live promotion
- afa98f51-d8c2-4c2f-a27c-16cc4e7e0c2b,active,Research Agent should use scoped task/project continuity; not Psychology-style broad personal continuity by default
- eafa324f-f44e-4456-98f4-beb48ff43be0,active,First user-driven Research Agent task should assess the external landscape and differentiation for Context Brain + specialist-agent orchestration
- bea84ab0-7ba6-4291-8771-718c601a735b,active,Research Agent should combine scoped internal Context Brain research with external source research when the question concerns Context Brain itself
- c1c5f1ea-4ee8-4ee1-91d0-add94927ae6d,active,Frame future self-improvement as human-directed governed capability evolution; not autonomous agent self-design
- f940019d-03ce-43b4-bcd9-065eb4e984ce,superseded,Formalize existing autonomy rules as a cross-cutting Authority/Risk Policy during Coding Worker design; not as a separate precondition project
- 691e6960-45b8-4a20-a5cc-9d654f4dea6d,active,Next Coding Worker priority: Hermes→worker production dispatch first; then provider-egress hardening; then task-quality evals and repo intelligence
- e49f2092-a515-47b0-8e56-234e66cce2d9,active,Hermes→Coding Worker production-dispatch GO PASS
- 3b2a3f80-4744-43dc-92cb-c433a2534078,active,Keep current Agent Construction roadmap; Coding Agent remains MVP
- 406d2cd2-d906-40af-a550-9a9828911151,active,Pause provider-egress activation on root-access blocker; continue roadmap with Coding Agent evals
- c822b090-4dd5-452c-870b-42830c50712d,active,GO — Implement host-side scoped OpenCB read bridge v0 now
- 5a696279-d797-47eb-9fa0-18cae234e170,superseded,Fix Telegram pre-narrowing toolset candidate list; with non-specialist visibility guard
- 2850c01e-b91e-45e3-985b-d19639d4e036,superseded,Implement specialist-private candidate expansion after contract attachment; do not bypass platform safety generically
- 088a2fbf-e178-403a-8585-08ecb9171837,active,First full portfolio cycle exposes missing Hermes→Research callable service seam
- fbde17f0-22dc-48e0-a20d-199c45baf54c,superseded,Verify the independent portfolio-cycle artifacts before starting Provider Parity Canary Matrix v0
- 979cf367-e418-44a1-83d3-2e3ea9662065,active,GO — Run the Coding Agent multi-backend evidence gap through the live Research callable service
- 7b780b6f-29b4-4686-af2f-d6e6d2d1c77c,superseded,Corrected status: portfolio cycle manually orchestrated end-to-end; Hermes-autonomous orchestration not yet proven
- 279a7033-c33d-45bd-8dbf-78861ab5d62a,superseded,Hermes-autonomous portfolio cycle is a verification candidate; independently verify before final promotion
- f64e1895-3fae-4edc-8b06-2611594e06c3,active,Preserve the governed service/OpenCB architecture pattern for future Planner integration
- 8c898b3a-dd6a-4a9e-9e7b-877a23096cfe,active,Next milestone: close Crystallization → canonical OpenCB promotion before Planner or cron
- 7fd11821-258d-433c-b95c-ea7c7b650de5,reversed,Coding Agent multi-backend provider policy v0 (Claude/Codex/MiniMax under one CodingRun contract)
- 4621e81c-258f-4150-8cb6-589ad1a75895,superseded,Build a trusted OpenCB current-state promotion seam next
- 7208eb9a-5490-4ee7-9e7f-2183ba4db714,superseded,GO: re-run real Coding Agent provider-policy Crystallization Promotion through trusted OpenCB seam
- e3f21f6e-0346-4640-9d13-92ee5c7b96a9,active,Second heterogeneous portfolio test: Hermes direct-terminal vs Coding Agent authority boundary
- 8fd5c805-d0bc-4311-9099-2890d4f28b62,active,Third heterogeneous portfolio test: skill-evolution governance from live execution evidence
- d876536c-1aaf-41a8-83e0-4af21c44153c,active,Third heterogeneous portfolio cycle PASS; but correct authority precedence in promoted skill-governance principle
- 0080daef-798c-4095-a5db-8d4306e0dce9,active,GO: fourth heterogeneous portfolio test — evaluate distributed skills over MCP against current architecture
- 65fd19e6-0262-44a2-b175-1e039537af97,superseded,Fourth heterogeneous test remains incomplete until Research service + trusted promotion legs are replayed
- e7abf25a-c5c0-4525-8def-e00a19c6a169,active,Keep specialist containment; expose portfolio service invocation at base-Hermes control plane
- a1b30ea0-9365-4a4e-923d-aa4190e8c1bf,superseded,Reopen Hermes runtime diagnosis: `/new` base session still receives narrow specialist-like tool surface
- 375da048-e036-4947-bff8-34e4c92c1d7b,active,Stale Hermes gateway root cause fixed; rerun fourth portfolio completion on fresh live base session
- 9c897c1b-8f04-426a-b0a3-e032f64d7b1a,active,Fifth heterogeneous portfolio test: validate context-preserving Crystallization before refining the base
- 4395e4de-e789-4af2-8996-8830fdc62e51,active,Fifth heterogeneous portfolio meta-test — PASS; context-preservation risk confirmed narrowly
- 9ce96925-9fe5-4fa7-87b9-4911d0b0dea7,active,Move Coding Agent to maintenance/secondary mode and return mainline effort to OpenCB product work via Hermes/Minimax
- b5dcc736-c5c3-4003-b814-5ff3529c7217,active,Semi-automatic plan governance loop with explicit approval for canonical changes
- c76d607e-38f0-4301-ae39-23ececf24b07,active,MCP workspace-scoping gap is closed; resume downstream canonical-body consumers with a fresh Planner context probe
- 0581fc19-3b08-46a7-abbe-f3b79199d2bd,active,Resume Hermes-first environment building now that OpenCB canonical-body and MCP auth blockers are closed
- 75f3e01c-3fd0-4dae-b23e-7141e6b3a1ea,active,Planner Tier 3 is not closed until live smoke traverses run_planner_bounded_turn and external OpenCB trust anchor exists
- c1f933b7-979a-4a0c-a3df-6eedaa6267fe,active,Close Planner seam for this iteration and move to full cognition-pipeline E2E
- 2c54e061-0a7c-4fbb-9e65-a843c09db6b7,active,Full cognition E2E recon must separate Crystallization proposal from governed promotion execution
- 6972f16d-8e6d-49b7-9cb3-39de04fe4c8a,active,Reclassify current cognition recon as harness proof; require reassembled provider-visible after-state and live specialist phases before claiming E2E value
- 97dab6f9-98f8-4ca3-ab88-8e77351e2037,active,Create a durable Hermes session-bootstrap manifest for the cognition pipeline
- 61224f86-ec65-4119-aaa9-50964289d2ae,active,Keep agent-identity isolation canonical in OpenCB; local Hermes memory may hold only a compact bootstrap pointer
- e1797d36-492c-4aa6-af41-ad0b21146f8b,active,GO: apply narrow OpenCB search-preview hub_id join fix with real-DB regression coverage
- 55ba999d-aa1f-400a-977e-843477722b3e,active,GO commit/push OpenCB search-preview hub_id fix after live validation
- 35972540-08f7-4d64-b19b-41644cc44db3,active,Treat Procedural Graph as a deferred read-first Procedural Governance Index; not a new workflow engine
