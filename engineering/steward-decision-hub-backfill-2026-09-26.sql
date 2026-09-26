-- Steward decision↔hub backfill (Tier A only). Idempotent; pinned ID list; no updated_at bump.
-- Rule: title matches \mSteward\M (word boundary) OR names steward_portfolio_scan. 80 decisions.
\set ON_ERROR_STOP on
\set ws '69984891-9fd4-4a39-b3e8-c1f0459c9087'
\set hub '8404d619-b079-4311-aea8-2a46559f9aaa'
BEGIN;
CREATE TEMP TABLE bf_ids ON COMMIT DROP AS SELECT unnest(ARRAY['4b1c3c3c-1ec7-4561-bedf-46df0b5fc29f','31544c35-8ca7-45b0-b94e-697d17d074b3','13fc8c9a-7cb6-40c1-9cb1-523610a0e1de','d0a14d58-fb41-4e69-ad6d-1e436f33d6e8','a8041ef8-88e4-4375-af07-cdcd32104859','c5e5c4ed-bdab-4770-bac8-8376573f66dc','957efa8c-ef0a-4410-9d9e-ec23fa645ced','6f6c753c-4e4f-4a7f-b40d-bea048ee0c24','0741296d-1463-410f-851d-44ab590d7e69','8d0a88f6-1eb6-473f-8afa-b78809450dd6','d6f732e6-57f7-4bd8-8af7-f5830e50571e','37da86ad-852b-43e8-a388-25bfbcabcf8c','7be7e6d4-f1ec-4fff-9251-51c62ea7a3c1','addf3f01-7e87-4674-a5a5-8179f03afeea','befaa5ac-53c9-49da-b14e-5c43e3064f22','64b67f87-6b94-4cac-aac2-7fa9cbc1453a','450f944d-170d-4ba9-b07a-08aeca049443','5848cc69-f503-4491-a8ec-d78470cd7280','005cf2ab-0296-4682-b47c-0fd8813cc23d','1d1d8375-967f-4a4b-81e3-85a358d8d84c','50e96e1f-29c3-49b4-abfb-47f5923e6943','59a482f5-02fe-4369-8d5f-5d94369a504a','7c348153-2619-49a4-8229-614ccdef8eca','48b13a4e-04c9-4ae5-a1c4-7cab72e1127a','8440be53-4415-4c1f-9345-34d41aebac70','3f3e1bf0-c620-471b-bc5f-3e284e6d3bbb','02a21e60-0353-433b-b32c-d316dd5598bc','d8f388df-f0a1-484e-9483-e574e81a5bda','a8e6f72b-bb6e-4a3a-8e63-554557aaec5f','c8957d81-f68a-4aed-bf0b-81d23a22bfd4','9319e793-3445-47c9-88da-fd7fa7ea26d7','95763656-a02b-4bce-b97a-0973787ffa39','9a07173f-9a6e-4cae-971b-45379eeac93c','d2588510-576f-4317-a6f4-530d786b0361','f64c4efa-b105-41fa-b88e-241e68f71a09','23e102c9-b27c-40ef-add5-95efcb9a9083','5e520c66-b1d2-42b9-97b9-fbe12ef2c393','2bcfdce2-ac3a-4f21-aa32-80b380a2e0e8','0d988359-7b2c-40b8-84b6-3785b3d0700a','dd4228cd-68c8-4404-b0d6-84e04d4d5570','fab26762-cb65-4dfe-a1af-b402b884532f','be802fc3-03da-4bc4-a5d3-2c2d7d024e3d','1c36ff60-ed4b-4562-8867-ce6d3015778a','9863c963-db75-466e-af4c-7f3dcf27d07f','24d9c3de-101d-4e2e-8fa1-904075b8a9c8','3f6d5ea0-8b92-451d-824c-116c49b12945','e5fb5b4c-826b-4dc6-965b-b3f1518c3b2d','df530753-7adb-4d6f-b009-c3df44bb8f13','07dceab2-70d6-464e-a204-a4bc50b2f656','affdf752-d471-458b-b290-4cd00d887f98','8a7eab45-db29-4bff-8ac6-69a138202a78','0fe5e517-9f83-45bb-bf49-980c9e1155ea','2437ad59-bc02-4563-a650-57f73f6f7d5b','f16a90e0-bb92-473e-98bb-27df04cfce0c','d55d22ba-4339-486a-8405-193ab1313a21','f02a55cf-cb48-4d2d-a7d6-86fd7cec66e9','49ec6a54-1d2a-440d-b3ae-6323334ef0aa','67af5faa-b17a-4e6f-a3aa-607a6151cada','ac586138-4751-44ee-9e8a-8d0d0423262e','c4711322-6f36-4a8e-8b13-fb663fac0314','fc943a3d-2d56-42cd-bf36-bac43ed9b205','adcdba2d-c337-4769-ad54-816634595150','dba72934-9391-418b-a8da-c89a6c9fd99d','0337ecb3-f6e3-46fe-9d37-e564596ae4cd','e12049d2-0068-45a0-abbe-b7e661ea0094','d79cbd6b-6de4-4c07-a9fb-a3857f11205a','4188fd4d-58d5-4834-81a3-60c3d35a000c','bfd414af-6217-4f95-be3e-51010c910b8c','90cc75dc-bd23-4747-8f9e-18e2b441dd89','05a59cfe-749f-4bf7-abec-6cb587f0b281','d982ed99-2a26-4116-9a8d-18068eff3b8c','86093db9-a7c2-416c-9928-77ae056c6fae','e9db3ba9-8923-49ea-af40-d27e411696d0','6302369a-1b41-4453-92ff-89d970801efc','2bc23c88-4827-4d55-a517-f98f2d0e29aa','88711657-9aec-4f9d-b6e0-957dc696fb8e','747bc282-84d2-4cdc-97fa-3c63029b3d32','22b439dc-8109-47e3-aad7-bb58bcb2b618','f9057e21-d2a2-4367-8b75-cf9797af0da6','39f91495-345c-4e49-a010-3c774cd371a6']::uuid[]) AS decision_id;
-- Guards: hub owned by ws; every pinned id exists in ws; nothing outside the list is touched.
DO $$BEGIN
  IF NOT EXISTS (SELECT 1 FROM cb_hubs WHERE hub_id='8404d619-b079-4311-aea8-2a46559f9aaa' AND workspace_uuid='69984891-9fd4-4a39-b3e8-c1f0459c9087') THEN RAISE EXCEPTION 'hub not owned by workspace'; END IF;
  IF (SELECT count(*) FROM bf_ids b JOIN cb_decision_nodes d USING (decision_id) WHERE d.workspace_id='69984891-9fd4-4a39-b3e8-c1f0459c9087') <> 80 THEN RAISE EXCEPTION 'pinned id set mismatch'; END IF;
END$$;
-- Audit: before-state
SELECT 'before' phase, count(*) FILTER (WHERE :'hub'::uuid = ANY(coalesce(linked_hub_ids,'{}'))) linked, count(*) total FROM cb_decision_nodes WHERE decision_id IN (SELECT decision_id FROM bf_ids);
CREATE TEMP TABLE bf_before ON COMMIT DROP AS SELECT decision_id, updated_at, linked_hub_ids FROM cb_decision_nodes WHERE decision_id IN (SELECT decision_id FROM bf_ids);
UPDATE cb_decision_nodes d
   SET linked_hub_ids = array_append(coalesce(d.linked_hub_ids,'{}'), :'hub'::uuid)
 WHERE d.decision_id IN (SELECT decision_id FROM bf_ids)
   AND d.workspace_id = :'ws'::uuid
   AND NOT (:'hub'::uuid = ANY(coalesce(d.linked_hub_ids,'{}')));
-- Readback
SELECT 'after' phase, count(*) FILTER (WHERE :'hub'::uuid = ANY(d.linked_hub_ids)) linked, count(*) total,
       count(*) FILTER (WHERE d.updated_at <> b.updated_at) updated_at_changed,
       count(*) FILTER (WHERE NOT (b.linked_hub_ids IS NULL OR b.linked_hub_ids <@ d.linked_hub_ids)) prior_links_lost
  FROM cb_decision_nodes d JOIN bf_before b USING (decision_id);
SELECT 'collateral' phase, count(*) FROM cb_decision_nodes WHERE :'hub'::uuid = ANY(coalesce(linked_hub_ids,'{}')) AND decision_id NOT IN (SELECT decision_id FROM bf_ids);
-- Strict decision-scope simulation (same predicate as DecisionStore.search_preview strict)
SELECT 'strict_preview_steward' phase, count(*) FROM cb_decision_nodes
 WHERE workspace_id=:'ws'::uuid AND :'hub'::uuid = ANY(linked_hub_ids)
   AND (LOWER(title) LIKE '%steward%' OR LOWER(decision_reason) LIKE '%steward%' OR LOWER(COALESCE(decision_context,'')) LIKE '%steward%' OR LOWER(COALESCE(why_this_matters,'')) LIKE '%steward%');
