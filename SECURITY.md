# Security Policy

## Scope

This document covers **context-brain-memory-lab** -- a self-hosted Python package
providing governed agent memory via API and MCP surfaces.
It does not apply to any upstream hosted Context Brain service.

---

## Provider-Neutral Baseline

By default, this package makes **no external network calls**:

- No API keys are required for the baseline runtime
- The only external connection is to your own DATABASE_URL (local PostgreSQL)
- No class or function initiates outbound requests unless explicitly configured
  (for example, LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY, or EMBEDDING_PROVIDER=openai + OPENAI_API_KEY)

**Fallback behavior (no key configured):**
Scoring defaults to composite=0.30, tier=transient, fallback_reason exposed in
response. The system does not fail silently -- it always returns a governed score.

---

## Authentication and Authorization

The API has two auth modes, selected by `MEMORY_LAB_AUTH_MODE`:

- **`local_dev_bypass`** -- the Docker quickstart default. Requests run as a
  fixed bootstrap subject; requires
  `MEMORY_LAB_AUTH_ALLOW_LOCAL_DEV_BYPASS=true`. Local development only --
  never expose a bypass-mode instance to a network.
- **`api_key`** -- for anything network-exposed. Bearer tokens are validated
  against the `api_keys` table by SHA-256 hash (constant-time compare, plus
  revocation, expiry, and subject-status checks). Only the hash is stored;
  mint keys with `bash scripts/create_api_key.sh`.

Authorization is role-based per workspace: every protected route requires a
permission (e.g. `content.create`, `escalations.resolve`) that is checked
against the caller's `workspace_memberships` role (`owner`, `admin`, `writer`,
`reader`, `service_agent`, `auditor`). All data access is workspace-scoped;
workspace selection via `X-Workspace-ID` is a selector, not authentication --
membership is still enforced. On the MCP HTTP transport in `api_key` mode the
workspace is resolved from the key and any client-supplied workspace header is
stripped.

Auth denials and admin actions are audited to the `cb_audit_events` table
(no token material is ever written; disable with
`MEMORY_LAB_AUTH_AUDIT_ENABLED=false`).

### Admin Endpoints

```
POST /admin/cleanup/ttl
POST /admin/content/{id}/tier/override
POST /admin/content/{id}/tier/rollback
```

These require an `owner` or `admin` workspace role and are audited. They are
destructive; even authenticated, they are intended for operator use, not for
agent-facing schemas.

**Do not expose the API port (8000 for local uvicorn, 8088 for the Docker
quickstart) to a public network while in `local_dev_bypass` mode.** For
network exposure:

- Switch to `MEMORY_LAB_AUTH_MODE=api_key` and provision real subjects/keys
- Terminate TLS at a reverse proxy (nginx, caddy) -- the app itself does not do TLS
- Restrict access via network firewall where possible

---

## Secrets Guidance

- Never commit .env files to version control
- DATABASE_URL contains credentials -- use environment variables or a secrets manager
- API-key tokens are printed once at creation and stored only as hashes;
  treat the printed token like any other secret
- ANTHROPIC_API_KEY and OPENAI_API_KEY are optional; deterministic fallback paths operate without them
- No hardcoded secrets or default API credentials exist in this package
  (the compose stack's Postgres password is a documented local-dev default --
  change it for any network-exposed stack)

---

## Excluded Private Modules

The following upstream-private modules are intentionally **not included** in
this public package:

- audit.py -- the private write-audit module (the public package has its own
  auth/admin audit trail in `cb_audit_events`, described above)
- conflict_detector.py -- internal semantic conflict detection
- ask_v2.py -- internal LLM query interface

Their absence is intentional and is not a security gap.

---

## What This Package Does NOT Provide

- No production multi-tenancy, billing, or quota enforcement -- workspaces
  isolate data and roles, but this is a single-operator deployment model
- No Postgres row-level security -- workspace scoping is enforced in the
  application layer
- No rate limiting or abuse protection -- add at the reverse proxy if exposed
- No TLS termination -- handle at the reverse proxy / infrastructure layer
- No key-management UI -- keys are minted/revoked via script and SQL

---

## Vulnerability Reporting

**How to report:**
Open a GitHub Issue with the label "security", or use the GitHub profile contact.

**Scope:** This package only (context-brain-memory-lab).

**SLA:** None guaranteed -- this is a personal/open-source project.

**Response:** Best-effort, typically reviewed within 7-14 days.

**Disclosure coordination:**
For sensitive issues, please coordinate before opening a fully public issue.
A private initial contact via GitHub profile is preferred.
