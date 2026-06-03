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
  (LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY)

**Fallback behavior (no key configured):**
Scoring defaults to composite=0.30, tier=transient, fallback_reason exposed in
response. The system does not fail silently -- it always returns a governed score.

---

## Admin Endpoints

The following endpoints are **unauthenticated** in this release.
They are intended for **localhost and trusted internal network use only.**

```
POST /admin/cleanup/ttl
POST /admin/content/{id}/tier/override
POST /admin/content/{id}/tier/rollback
```

**Do not expose port 8000 to a public network without an auth layer.**

Recommended mitigations:
- Bind to 127.0.0.1 only in production
- Place behind a reverse proxy with auth (nginx auth_basic, OAuth2 proxy)
- Restrict access via network firewall

There is no built-in credential or token -- auth must be added externally.

---

## Secrets Guidance

- Never commit .env files to version control
- DATABASE_URL contains credentials -- use environment variables or a secrets manager
- ANTHROPIC_API_KEY is optional; fallback scoring operates without it
- No hardcoded secrets or default credentials exist in this package

---

## Excluded Private Modules

The following modules are intentionally **not included** in this public package:

- audit.py -- internal write audit log
- conflict_detector.py -- internal semantic conflict detection
- ask_v2.py -- internal LLM query interface

Their absence is intentional and is not a security gap.

---

## What This Package Does NOT Provide

- No multi-user access control or role-based permissions
- No row-level security
- No built-in audit trail (audit.py excluded)
- No TLS termination -- handle at the reverse proxy / infrastructure layer
- No production-grade auth -- single-tenant local/dev baseline only

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
