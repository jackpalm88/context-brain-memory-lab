"""Neutral provider-answer gate shared by the reasoning answer path and the ask/query path.

This module owns the public-safe discipline for turning a deterministic answer into an
optionally provider-backed one WITHOUT ever deciding truth, resolving conflicts, or citing
evidence that was not supplied:

- dual gate: a per-request opt-in (`enable_provider_synthesis`) AND a deployment config gate
  (`provider_synthesis_enabled`) must both be true before any backend is called;
- forbidden-term rejection (`provider_text_allowed`);
- citation allow-list (`provider_citations_allowed`): the provider may only cite evidence_id
  values that were supplied;
- typed degraded fallback: on any non-happy path the deterministic text is returned unchanged
  and a typed `failure_reason` is set.

The gate is intentionally free of reasoning/query model imports so both callers can adapt the
neutral `ProviderGateResult` into their own response/metadata shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Set

from memory_lab.providers.llm_backend import LLMBackend, LLMRequest
from memory_lab.providers.noop import NoopLLMBackend

FORBIDDEN_PROVIDER_TERMS = {"verdict", "truth decision", "resolution", "winner", "canonical truth"}
EVIDENCE_ID_PATTERN = re.compile(r"\bev_[A-Za-z0-9_-]+\b")


@dataclass
class ProviderGateResult:
    """Neutral outcome of the provider-answer gate.

    `mode` is one of: "deterministic" | "provider_backed" | "degraded".
    On every non-`provider_backed` outcome, `text` is the supplied deterministic text.
    """

    text: str
    mode: str
    provider_name: str
    attempted: bool
    configured: bool
    degraded: bool
    failure_reason: Optional[str] = None
    model: Optional[str] = None


def provider_text_allowed(text: str) -> bool:
    """Reject empty output or output containing truth-deciding / conflict-resolving terms."""
    lowered = text.lower()
    return bool(text.strip()) and not any(term in lowered for term in FORBIDDEN_PROVIDER_TERMS)


def provider_citations_allowed(text: str, allowed_evidence_ids: Set[str]) -> bool:
    """Allow only when every cited evidence_id was supplied (cited ⊆ allowed)."""
    cited = set(EVIDENCE_ID_PATTERN.findall(text))
    return cited <= set(allowed_evidence_ids)


def _failure_reason(response) -> str:
    failure = getattr(response, "failure_reason", None)
    if failure is not None:
        return str(failure.value)
    return "provider_degraded"


def gate_provider_answer(
    *,
    enable_provider_synthesis: bool,
    provider_synthesis_enabled: bool,
    deterministic_text: str,
    allowed_evidence_ids: Set[str],
    prompt: str,
    system: str,
    backend: Optional[LLMBackend] = None,
    max_tokens: int = 400,
) -> ProviderGateResult:
    """Run the shared provider-answer gate and return a neutral result.

    Never raises; always returns the deterministic text unless a provider produced
    allow-listed, non-forbidden wording.
    """
    # Gate 1 — per-request opt-in. Default behavior is deterministic, no provider object touched.
    if not enable_provider_synthesis:
        return ProviderGateResult(
            text=deterministic_text,
            mode="deterministic",
            provider_name="none",
            attempted=False,
            configured=False,
            degraded=False,
        )

    # Gate 2 — deployment config. Opted in but disabled by config: degrade without calling.
    if not provider_synthesis_enabled:
        return ProviderGateResult(
            text=deterministic_text,
            mode="degraded",
            provider_name="none",
            attempted=False,
            configured=False,
            degraded=True,
            failure_reason="provider_disabled",
        )

    llm = backend or NoopLLMBackend()
    response = llm.summarize(
        LLMRequest(prompt=prompt, system=system, max_tokens=max_tokens, temperature=0.0)
    )
    model = response.model or None

    if response.degraded:
        return ProviderGateResult(
            text=deterministic_text,
            mode="degraded",
            provider_name=llm.provider_name,
            attempted=True,
            configured=llm.is_configured,
            degraded=True,
            failure_reason=_failure_reason(response),
            model=model,
        )

    text = str(response.text or "").strip()
    if not provider_text_allowed(text) or not provider_citations_allowed(text, allowed_evidence_ids):
        return ProviderGateResult(
            text=deterministic_text,
            mode="degraded",
            provider_name=llm.provider_name,
            attempted=True,
            configured=llm.is_configured,
            degraded=True,
            failure_reason="provider_output_rejected",
            model=model,
        )

    return ProviderGateResult(
        text=text,
        mode="provider_backed",
        provider_name=llm.provider_name,
        attempted=True,
        configured=llm.is_configured,
        degraded=False,
        failure_reason=None,
        model=model,
    )
