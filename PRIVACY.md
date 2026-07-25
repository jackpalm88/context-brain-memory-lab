# Privacy Policy

## Self-Hosted Only

context-brain-memory-lab is a self-hosted Python package.
There is no hosted service. Your data stays in your own PostgreSQL instance.
This document describes how the package handles data when you run it yourself.

---

## No Telemetry

By default, this package collects **no telemetry**:

- No analytics or usage tracking
- No error reporting to any external server
- No version ping or build-time callback
- No network activity outside your own DATABASE_URL

---

## Data Flow (Default)

```
Your request --> API/MCP --> memory_lab (local process) --> PostgreSQL (your instance)
                                     |
                     No external network calls in this path
```

All data stays within your local process and your PostgreSQL instance.

---

## Optional Provider Path

If you configure provider keys, the matching opt-in provider path may send request text to that provider:

- : save-time scoring / provider-backed wording can send content text to Anthropic.
- : opt-in embedding paths can send text to OpenAI for embedding generation.
- Provider responses are used by this package; content text is NOT stored externally by this package.
- You are responsible for reviewing each provider's data retention and privacy policy.
- Disable at any time by unsetting the provider key and provider flag -- fallback paths activate automatically.

---

## What Data Is Stored Locally

PostgreSQL tables store:

- Content text (chunk_text)
- Governance scores (quality, relevance, novelty, composite)
- Tier metadata (tier, tier_reason, tier_assigned_at)
- Hub links, decision records, graph edges
- Retrieval metadata (retrieval_count, last_retrieved_at)

By design, this package does **not** store:
- Biometric data
- Authentication tokens
- PII -- unless you explicitly save PII as content

---

## User Responsibility

- You control and operate your own PostgreSQL instance
- You are responsible for database backup, retention, and access control
- This package does not provide GDPR-compliant deletion SLA -- implement
  data lifecycle policies at the infrastructure level for regulated workloads

---

## Private Modules Boundary

The modules audit.py, conflict_detector.py, and ask_v2.py are not included
in this public package. Any data these modules handle in a private deployment is
not accessible through this package.

---

## Contact

For privacy-related questions, open a GitHub Issue or use the GitHub profile contact.
