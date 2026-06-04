-- 021_add_workspace_fk_constraints_not_valid.sql
-- Prestage 3 P3A2: add workspace FK constraints in a compatibility-safe staged form.
-- Scope: additive constraints only. Existing data validation is deferred.
-- Idempotent: safe to run multiple times.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'content_items_workspace_fk') THEN
        ALTER TABLE content_items
            ADD CONSTRAINT content_items_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'content_chunks_workspace_fk') THEN
        ALTER TABLE content_chunks
            ADD CONSTRAINT content_chunks_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_hubs_workspace_uuid_fk') THEN
        ALTER TABLE cb_hubs
            ADD CONSTRAINT cb_hubs_workspace_uuid_fk
            FOREIGN KEY (workspace_uuid) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_hub_content_workspace_fk') THEN
        ALTER TABLE cb_hub_content
            ADD CONSTRAINT cb_hub_content_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_hub_edges_workspace_fk') THEN
        ALTER TABLE cb_hub_edges
            ADD CONSTRAINT cb_hub_edges_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_edges_workspace_fk') THEN
        ALTER TABLE cb_edges
            ADD CONSTRAINT cb_edges_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_aliases_workspace_fk') THEN
        ALTER TABLE cb_aliases
            ADD CONSTRAINT cb_aliases_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_alias_candidates_workspace_fk') THEN
        ALTER TABLE cb_alias_candidates
            ADD CONSTRAINT cb_alias_candidates_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_decision_nodes_workspace_fk') THEN
        ALTER TABLE cb_decision_nodes
            ADD CONSTRAINT cb_decision_nodes_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_ingestion_log_workspace_fk') THEN
        ALTER TABLE cb_ingestion_log
            ADD CONSTRAINT cb_ingestion_log_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_escalations_workspace_fk') THEN
        ALTER TABLE cb_escalations
            ADD CONSTRAINT cb_escalations_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'cb_governance_events_workspace_fk') THEN
        ALTER TABLE cb_governance_events
            ADD CONSTRAINT cb_governance_events_workspace_fk
            FOREIGN KEY (workspace_id) REFERENCES cb_workspaces(workspace_id)
            NOT VALID;
    END IF;
END $$;
