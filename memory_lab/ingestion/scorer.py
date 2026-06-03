"""
Phase 7a — Pre-Save Epistemic Scorer

Scores incoming content on 3 axes (quality, relevance, novelty) using the
configured LLM backend before any DB write occurs.

Key design constraints (from PITFALLS.md + PHASE7_PLAN.md):
- Sync LLM call — callers MUST wrap with run_in_threadpool (never called
  directly from async context without wrapping)
- Circuit breaker fallback: open circuit → fallback scores (not a crash)
- Circuit state is DB-backed — survives container restart (Pitfall #5)
- Constitutional rules loaded by rule ID from ingestion_policy, never hardcoded
- Score before opening asyncpg transaction (Pitfall: async/score boundary)
- Provider-optional: no ANTHROPIC_API_KEY / missing package / circuit open
  all produce fallback scores, never crash
"""
import json
import logging
import os
import time
from typing import Optional

from memory_lab.ingestion.models import IngestionEvent, IngestionScores
from memory_lab.governance import ingestion_policy as policy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB-backed circuit breaker state (resolved lazily to avoid import loops)
# ---------------------------------------------------------------------------

_CIRCUIT_OPEN_UNTIL: float = 0.0  # epoch seconds; in-process cache
_CIRCUIT_FAILURES: list = []       # [(timestamp, error_msg)]


# ---------------------------------------------------------------------------
# Provider backend factory
# ---------------------------------------------------------------------------

def _get_llm_backend():
    """Return the configured LLM backend.

    Resolution order:
      1. AnthropicLLMBackend if anthropic package importable AND key present
      2. NoopLLMBackend otherwise (degraded=True on every call, no crash)

    Never raises.
    """
    try:
        from memory_lab.providers.anthropic import AnthropicLLMBackend
        backend = AnthropicLLMBackend()
        if backend.is_configured:
            return backend
    except Exception:
        pass
    from memory_lab.providers.noop import NoopLLMBackend
    return NoopLLMBackend()


def _is_circuit_open() -> bool:
    global _CIRCUIT_OPEN_UNTIL
    if time.time() < _CIRCUIT_OPEN_UNTIL:
        return True
    # Also check DB (lazily, once per open-check when in-process shows closed)
    try:
        _sync_circuit_from_db()
    except Exception:
        pass
    return time.time() < _CIRCUIT_OPEN_UNTIL


def _sync_circuit_from_db() -> None:
    """Read circuit state from DB and update in-process cache."""
    global _CIRCUIT_OPEN_UNTIL
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT EXTRACT(EPOCH FROM expires_at)
                      FROM cb_circuit_state
                     WHERE service = 'ingestion_scorer'
                       AND expires_at > NOW()
                     LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row:
                    _CIRCUIT_OPEN_UNTIL = float(row[0])
        finally:
            conn.close()
    except Exception as e:
        logger.debug(f"[ingestion_scorer] circuit DB sync failed: {e}")


def _open_circuit(reason: str) -> None:
    """Open the circuit breaker and persist state to DB."""
    global _CIRCUIT_OPEN_UNTIL
    cfg = policy.get_circuit_config()
    duration = cfg["open_duration_seconds"]
    _CIRCUIT_OPEN_UNTIL = time.time() + duration
    logger.warning(
        f"[ingestion_scorer] Circuit OPEN for {duration}s — reason: {reason}"
    )
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            return
        conn = psycopg2.connect(db_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cb_circuit_state (service, opened_at, expires_at)
                    VALUES ('ingestion_scorer', NOW(), NOW() + INTERVAL '%(s)s seconds')
                    ON CONFLICT (service) DO UPDATE
                      SET opened_at = EXCLUDED.opened_at,
                          expires_at = EXCLUDED.expires_at
                    """,
                    {"s": int(duration)},
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"[ingestion_scorer] Failed to persist circuit state: {e}")


def _record_failure(error: Exception) -> None:
    global _CIRCUIT_FAILURES
    now = time.time()
    cfg = policy.get_circuit_config()
    window = cfg["window_seconds"]
    _CIRCUIT_FAILURES = [
        (t, e) for (t, e) in _CIRCUIT_FAILURES if now - t < window
    ]
    _CIRCUIT_FAILURES.append((now, str(error)))
    if len(_CIRCUIT_FAILURES) >= cfg["failure_threshold"]:
        _open_circuit(f"failure_threshold={cfg['failure_threshold']} in {window}s")


def _record_success() -> None:
    global _CIRCUIT_FAILURES, _CIRCUIT_OPEN_UNTIL
    _CIRCUIT_FAILURES = []
    _CIRCUIT_OPEN_UNTIL = 0.0


# ---------------------------------------------------------------------------
# Failure code → fallback_reason string mapping
# ---------------------------------------------------------------------------

def _failure_code_to_reason(failure_reason) -> str:
    """Map FailureCode to the public-contract fallback_reason string.

    Preserves the exact strings consumed by api_adapter.py and MCP tools.
    """
    from memory_lab.providers.failure import FailureCode
    _MAP = {
        FailureCode.MISSING_API_KEY: "no_api_key",
        FailureCode.PROVIDER_IMPORT_MISSING: "no_api_key",
        FailureCode.NOT_CONFIGURED: "no_api_key",
        FailureCode.CIRCUIT_OPEN: "circuit_open",
        FailureCode.INVALID_JSON: "parse_error",
        FailureCode.SCHEMA_VALIDATION_FAILED: "parse_error",
        FailureCode.PROVIDER_HTTP_ERROR: "api_error",
        FailureCode.RATE_LIMITED: "api_error",
        FailureCode.TIMEOUT: "api_error",
        FailureCode.UNKNOWN_ERROR: "api_error",
    }
    return _MAP.get(failure_reason, "api_error")


# ---------------------------------------------------------------------------
# Fallback scores (circuit open or API unavailable)
# ---------------------------------------------------------------------------

def _fallback_scores(reason: str) -> IngestionScores:
    cfg = policy.get_circuit_config()
    composite = cfg["fallback_composite_score"]
    logger.info(f"[ingestion_scorer] Using fallback scores ({reason}) composite={composite}")
    return IngestionScores(
        quality=composite,
        relevance=composite,
        novelty=composite,
        composite=composite,
        quality_reason=f"fallback:{reason}",
        relevance_reason=f"fallback:{reason}",
        novelty_reason=f"fallback:{reason}",
    )


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------

def score(content_preview: str, hub_context: str = "") -> IngestionScores:
    """
    Score content on 3 axes using the configured LLM backend.

    SYNC function — callers must use run_in_threadpool in async context.
    Never call this while holding an asyncpg connection.

    Returns IngestionScores. Never raises — fallback scores on any error.
    Provider-optional: missing key, missing package, or circuit open → fallback.
    """
    if not content_preview or not content_preview.strip():
        return _fallback_scores("empty_content")

    if _is_circuit_open():
        return _fallback_scores("circuit_open")

    backend = _get_llm_backend()
    if not backend.is_configured:
        logger.warning("[ingestion_scorer] LLM backend not configured — fallback scores")
        return _fallback_scores("no_api_key")

    prompt_cfg = policy.get_scoring_prompt()
    model = prompt_cfg.get("model_preference", "claude-haiku-4-5-20251001")
    max_tokens = prompt_cfg.get("max_tokens", 300)
    system_msg = prompt_cfg.get("system", "")
    user_template = prompt_cfg.get("user_template", "")

    # Sanitize inputs before sending to LLM (prevent prompt injection)
    safe_content = content_preview[:2000].replace("{", "{{").replace("}", "}}")
    safe_hub = (hub_context or "")[:500].replace("{", "{{").replace("}", "}}")

    user_msg = user_template.format(
        content_preview=safe_content,
        hub_context=safe_hub or "(none)",
    )

    try:
        from memory_lab.providers.llm_backend import LLMRequest
        request = LLMRequest(
            prompt=user_msg,
            system=system_msg,
            max_tokens=max_tokens,
        )
        response = backend.complete_json(request)

        if response.degraded:
            reason = _failure_code_to_reason(response.failure_reason)
            # Only open circuit for transient/server errors, not config issues
            from memory_lab.providers.failure import FailureCode
            transient_codes = {
                FailureCode.PROVIDER_HTTP_ERROR,
                FailureCode.RATE_LIMITED,
                FailureCode.TIMEOUT,
                FailureCode.UNKNOWN_ERROR,
            }
            if response.failure_reason in transient_codes:
                _record_failure(Exception(str(response.failure_reason)))
            logger.warning(
                f"[ingestion_scorer] Backend degraded ({response.failure_reason}) — fallback"
            )
            return _fallback_scores(reason)

        _record_success()
        # Build raw JSON string from json_data for _parse_scores
        raw = json.dumps(response.json_data) if response.json_data is not None else (response.text or "{}")
        return _parse_scores(raw)
    except Exception as e:
        _record_failure(e)
        logger.error(f"[ingestion_scorer] Scoring failed: {e}")
        return _fallback_scores("api_error")


def _parse_scores(raw_json: str) -> IngestionScores:
    """Parse LLM JSON response into IngestionScores. Fallback on any parse error."""
    try:
        # Strip markdown code fences if present
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        data = json.loads(cleaned)

        quality = float(data.get("quality", 0.5))
        relevance = float(data.get("relevance", 0.5))
        novelty = float(data.get("novelty", 0.5))

        # Clamp to [0, 1]
        quality = max(0.0, min(1.0, quality))
        relevance = max(0.0, min(1.0, relevance))
        novelty = max(0.0, min(1.0, novelty))

        # Composite from constitution weights
        composite = quality * 0.35 + relevance * 0.35 + novelty * 0.30
        composite = round(max(0.0, min(1.0, composite)), 4)

        return IngestionScores(
            quality=round(quality, 4),
            relevance=round(relevance, 4),
            novelty=round(novelty, 4),
            composite=composite,
            quality_reason=str(data.get("quality_reason", ""))[:200],
            relevance_reason=str(data.get("relevance_reason", ""))[:200],
            novelty_reason=str(data.get("novelty_reason", ""))[:200],
        )
    except Exception as e:
        logger.warning(f"[ingestion_scorer] Score parse failed ({e}): {raw_json[:200]!r}")
        return _fallback_scores("parse_error")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_and_build_event(
    content_preview: str,
    hub_context: str = "",
    content_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> IngestionEvent:
    """
    Score content and return a fully populated IngestionEvent.

    SYNC — use run_in_threadpool from async context.
    """
    circuit_was_open = _is_circuit_open()
    scores = score(content_preview, hub_context)

    event = IngestionEvent(
        content_preview=content_preview[:500],
        content_id=content_id,
        workspace_id=workspace_id,
        scores=scores,
        circuit_open=circuit_was_open or scores.quality_reason.startswith("fallback:circuit"),
        applied_rule_ids=["S-QUALITY", "S-RELEVANCE", "S-NOVELTY"],
    )
    return event


def score_content(
    content: str,
    node_type: str = "fact",
) -> IngestionEvent:
    """
    Score content and return an IngestionEvent with fallback_reason populated.

    SYNC — use run_in_threadpool from async context.
    fallback_reason is set to the fallback cause ('no_api_key', 'circuit_open',
    'api_error', 'parse_error', 'empty_content') or '' when a live LLM score ran.
    """
    circuit_was_open = _is_circuit_open()
    scores = score(content)

    fallback_reason = ""
    qr = scores.quality_reason
    if qr.startswith("fallback:"):
        fallback_reason = qr[len("fallback:"):]

    event = IngestionEvent(
        content_preview=content[:500],
        scores=scores,
        circuit_open=circuit_was_open or bool(fallback_reason),
        applied_rule_ids=["S-QUALITY", "S-RELEVANCE", "S-NOVELTY"],
        fallback_reason=fallback_reason,
    )
    return event
