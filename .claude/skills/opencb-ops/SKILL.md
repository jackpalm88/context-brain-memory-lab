---
name: opencb-ops
description: Operate and govern a Context Brain Memory Lab (OpenCB) instance — review conflict escalations, run edge inference and embedding backfill, TTL cleanup, and tier overrides. Use for admin/maintenance requests on the memory store, not for daily save/query (use opencb-memory for that).
---

# OpenCB Ops — governance and maintenance loops

All write-side governance keeps one invariant: machines compute proposals,
humans decide. Approvals/rejections are audited (`cb_audit_events`) and tier
changes emit governance events (`cb_governance_events`).

## Escalation queue (conflict human gate)

Saves that contradict existing memory create `cb_escalations` rows; severity
`requires_review` quarantines the new content at `tier: conflicted`.

- `GET /v1/escalations?status=pending` — review queue (workspace-scoped).
- `POST /v1/escalations/{id}/approve` — promote the escalated content to
  `persistent` (human approval is the only path there).
- `POST /v1/escalations/{id}/reject` — archive it (soft-delete, never hard).
- Pending escalations expire per severity TTL (warning 7d, requires_review 30d;
  env: `CB_ESCALATION_TTL_*_DAYS`). Expired-pending refuses resolution and is
  flipped by the cleanup job.
- Requires `escalations.resolve` (owner/admin); reads need `escalations.read`.

Workflow: list pending → read `conflict_summary` (candidate id, detection rule,
counterpart content) → fetch both contents → present the contradiction to the
user → apply their decision.

## Inferred-edge producer (EDGE-INF-1)

Deterministic, provider-free hub-edge proposals (co-membership + tag alignment):

```bash
python scripts/edge_inference.py --dsn "$DSN" --workspace-id <UUID> --dry-run
python scripts/edge_inference.py --dsn "$DSN" --workspace-id <UUID>   # live
```

Writes `status=inferred, origin=ai_suggested` rows only; never overwrites
manual/approved/rejected edges and never resurrects rejected pairs. Consume via
`POST /v1/edges/inferred/approve|reject`. Re-runs are idempotent.

## Embedding backfill (EMB-1C)

```bash
python scripts/embedding_backfill.py --dsn "$DSN" --dry-run              # plan
python scripts/embedding_backfill.py --dsn "$DSN" --workspace-id <UUID>  # live
```

Requires a configured embedding provider for live mode; dry-run never does.
Embeddings are best-effort everywhere — saves never depend on them.

## TTL cleanup

`POST /admin/cleanup/ttl {"dry_run": true}` (permission `admin.cleanup`) —
expires stale pending escalations and archives old transient content. Always
dry-run first and show the plan; conflicted/hub-linked/decision-sourced content
is protected from archiving.

## Tier override

`POST /v1/tier-override` (permission `admin.tier_override`) — manual tier
change with mandatory reason; emits a governance event. `decision_artifact`
tier is only ever set through the decision router, never by scoring.

## Demo / local stack

- `docker compose up --build` — Postgres(pgvector) + migrations + API on :8088.
- `docker compose --profile demo up seed` — DEMO-1 synthetic corpus.
- Compose auth is local_dev_bypass with a fixed dev subject — local only;
  switch to `MEMORY_LAB_AUTH_MODE=api_key` for anything network-exposed.

## Diagnostics

- `GET /health` — truthful health (checks DB when configured).
- `POST /v1/retrieval/search` with `"debug": true` — stage_metrics envelope.
- `GET /v1/graph/health` — graph coverage/orphan report (also
  `scripts/b15_graph_health_report.py`).
