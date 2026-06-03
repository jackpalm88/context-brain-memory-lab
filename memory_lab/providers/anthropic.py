"""
Anthropic LLM adapter — implements LLMBackend.

Design constraints:
- Top-level module does NOT import `anthropic` — safe to import when package absent.
- All `import anthropic` calls are deferred to method bodies / _get_client().
- is_configured = True only if: ANTHROPIC_API_KEY non-empty AND anthropic importable.
- Never raises outside the adapter boundary.
- No embedding support.
- No DB dependency.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from .failure import FailureCode
from .llm_backend import LLMBackend, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class AnthropicLLMBackend(LLMBackend):
    """LLMBackend adapter for the Anthropic messages API.

    Usage::

        backend = AnthropicLLMBackend()
        resp = backend.complete_json(LLMRequest(prompt="..."))
        if resp.degraded:
            # use fallback — failure_reason indicates why
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def is_configured(self) -> bool:
        """True iff anthropic package importable AND API key present."""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        return bool(key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self):
        """Return an Anthropic client, or None if not configured.

        Returns (client, failure_code):
          - (client, None) on success
          - (None, FailureCode) on any setup failure
        """
        try:
            import anthropic
        except ImportError:
            return None, FailureCode.PROVIDER_IMPORT_MISSING
        key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not key:
            return None, FailureCode.MISSING_API_KEY
        try:
            return anthropic.Anthropic(api_key=key), None
        except Exception as exc:
            logger.debug("[anthropic_adapter] client init error: %s", exc)
            return None, FailureCode.UNKNOWN_ERROR

    def _degraded(self, code: FailureCode, model: str = "") -> LLMResponse:
        return LLMResponse(
            provider=self.provider_name,
            model=model,
            degraded=True,
            failure_reason=code,
        )

    def _call_messages(
        self,
        request: LLMRequest,
        system: str | None,
        user_msg: str,
    ) -> LLMResponse:
        """Core Anthropic messages.create() call with full failure mapping."""
        client, init_fail = self._get_client()
        if client is None:
            return self._degraded(init_fail)

        model = (os.environ.get("ANTHROPIC_DEFAULT_MODEL") or _DEFAULT_MODEL).strip()

        try:
            import anthropic as _anthropic

            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": request.max_tokens,
                "messages": [{"role": "user", "content": user_msg}],
            }
            if system:
                kwargs["system"] = system

            response = client.messages.create(**kwargs)
            text = response.content[0].text.strip()
            return LLMResponse(
                text=text,
                provider=self.provider_name,
                model=model,
                degraded=False,
            )

        except Exception as exc:
            code = self._map_exception(exc)
            logger.debug("[anthropic_adapter] call failed (%s): %s", code, exc)
            return self._degraded(code, model=model)

    @staticmethod
    def _map_exception(exc: Exception) -> FailureCode:
        """Map an anthropic (or other) exception to a FailureCode."""
        # Attempt class-name based matching to avoid hard import at module level
        cls_name = type(exc).__name__
        module = getattr(type(exc), "__module__", "") or ""

        if "anthropic" in module or cls_name.startswith("Anthropic"):
            if "RateLimitError" in cls_name:
                return FailureCode.RATE_LIMITED
            if "APITimeoutError" in cls_name or "Timeout" in cls_name:
                return FailureCode.TIMEOUT
            if "APIStatusError" in cls_name or "APIError" in cls_name:
                return FailureCode.PROVIDER_HTTP_ERROR
            if "AuthenticationError" in cls_name:
                return FailureCode.MISSING_API_KEY
        return FailureCode.UNKNOWN_ERROR

    # ------------------------------------------------------------------
    # LLMBackend interface
    # ------------------------------------------------------------------

    def complete_text(self, request: LLMRequest) -> LLMResponse:
        """Return raw text completion."""
        return self._call_messages(request, system=request.system, user_msg=request.prompt)

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        """Return JSON completion. Parses and optionally validates schema.

        On success: degraded=False, text=raw, json_data=parsed dict.
        On parse failure: degraded=True, failure_reason=invalid_json.
        On schema mismatch: degraded=True, failure_reason=schema_validation_failed.
        """
        resp = self._call_messages(request, system=request.system, user_msg=request.prompt)
        if resp.degraded:
            return resp

        # Parse JSON
        raw = resp.text
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            data = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("[anthropic_adapter] JSON parse failed: %s | raw=%r", exc, raw[:200])
            return LLMResponse(
                text=raw,
                provider=self.provider_name,
                model=resp.model,
                degraded=True,
                failure_reason=FailureCode.INVALID_JSON,
            )

        # Optional schema validation (shallow key presence check)
        if request.expected_schema:
            missing = [k for k in request.expected_schema if k not in data]
            if missing:
                logger.debug("[anthropic_adapter] schema mismatch, missing keys: %s", missing)
                return LLMResponse(
                    text=raw,
                    provider=self.provider_name,
                    model=resp.model,
                    degraded=True,
                    failure_reason=FailureCode.SCHEMA_VALIDATION_FAILED,
                )

        return LLMResponse(
            text=raw,
            json_data=data,
            provider=self.provider_name,
            model=resp.model,
            degraded=False,
        )

    def classify(self, request: LLMRequest, labels: list[str]) -> LLMResponse:
        """Return one of the given labels as text."""
        return self._call_messages(request, system=request.system, user_msg=request.prompt)

    def summarize(self, request: LLMRequest) -> LLMResponse:
        """Return a text summary."""
        return self._call_messages(request, system=request.system, user_msg=request.prompt)
