from __future__ import annotations

import time
from dataclasses import dataclass
import re
from typing import Optional

from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.providers.llm_backend import LLMBackend
from memory_lab.query.ask_audit import derive_retrieval_path, record_ask_event
from memory_lab.query.context_pack_adapter import (
    build_support_only_context_pack_for_ask,
    evidence_items_from_supporting_context_pack,
)
from memory_lab.query.current_state_enrichment import enrich_evidence_with_current_state
from memory_lab.query.evidence import normalize_evidence
from memory_lab.query.provider_answer import apply_provider_answer
from memory_lab.reasoning.answer_synthesizer import synthesize_answer
from memory_lab.reasoning.intent_detector import detect_intent
from memory_lab.reasoning.models import AskRequest, AskResponse


_ASK_RELEVANCE_STOPWORDS = {
    "about",
    "anything",
    "from",
    "have",
    "know",
    "known",
    "memory",
    "tell",
    "that",
    "the",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
}


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", (text or "").lower())
        if token not in _ASK_RELEVANCE_STOPWORDS
    }


def _has_meaningful_overlap(query: str, evidence) -> bool:
    query_tokens = _meaningful_tokens(query)
    if not query_tokens:
        return True
    for item in evidence:
        haystack = " ".join(
            part
            for part in (
                getattr(item, "snippet", "") or "",
                getattr(item, "title", "") or "",
            )
            if part
        )
        if query_tokens & _meaningful_tokens(haystack):
            return True
    return False
from memory_lab.reasoning.policy_generator import policy_for_intent


@dataclass
class QueryService:
    """Canonical internal orchestration owner for public query execution."""

    retrieval_adapter: RetrievalAdapter
    provider_synthesis_enabled: bool = False
    backend: Optional[LLMBackend] = None

    @classmethod
    def from_database_url(
        cls,
        database_url: str,
        provider_synthesis_enabled: bool = False,
        backend: Optional[LLMBackend] = None,
    ) -> "QueryService":
        return cls(
            retrieval_adapter=RetrievalAdapter(database_url),
            provider_synthesis_enabled=provider_synthesis_enabled,
            backend=backend,
        )

    def execute(self, request: AskRequest, workspace_id: str) -> AskResponse:
        t0 = time.monotonic()

        query = request.normalized_query()
        detection = detect_intent(query)
        policy = policy_for_intent(detection.intent, request.top_k)
        results = self.retrieval_adapter.search(
            query=query,
            max_hops=1,
            min_confidence=0.0,
            graph_boost=0.1,
            workspace_id=workspace_id,
            memory_types=request.resolved_content_types(),
            allowed_hubs=request.resolved_allowed_hubs(),
        )
        evidence = normalize_evidence(results[: policy.top_k], limit=policy.snippet_char_limit)
        # FV-FIX-3: surface resolver-owned current-state signals to the answer path.
        # Post-retrieval, best-effort, and never reorders across scopes.
        evidence = enrich_evidence_with_current_state(
            evidence,
            database_url=getattr(self.retrieval_adapter, "database_url", None),
            query=query,
        )
        if not _has_meaningful_overlap(query, evidence):
            evidence = []
        context_pack = build_support_only_context_pack_for_ask(
            request=request,
            workspace_id=workspace_id,
            query=query,
            evidence=evidence,
            limit=policy.top_k,
        )
        ask_evidence = evidence_items_from_supporting_context_pack(context_pack)
        response = synthesize_answer(
            request=request,
            detection=detection,
            policy=policy,
            evidence=ask_evidence,
            workspace_id=workspace_id,
        )
        # Provider synthesis only applies to a successful deterministic answer; unsupported and
        # insufficient-evidence outcomes stay deterministic and never trigger a provider call.
        if response.status == "ok":
            response = apply_provider_answer(
                response=response,
                request=request,
                query=query,
                evidence=ask_evidence,
                provider_synthesis_enabled=self.provider_synthesis_enabled,
                backend=self.backend,
            )

        # ---- DX-3: emit ask audit event (fire-and-forget, never raises) ----
        latency_ms = int((time.monotonic() - t0) * 1000)
        db_url = getattr(self.retrieval_adapter, "database_url", None)
        stage_metrics = getattr(self.retrieval_adapter, "last_debug_metadata", {}).get(
            "stage_metrics"
        )
        retrieval_path = derive_retrieval_path(stage_metrics, len(ask_evidence))
        degraded_reason = getattr(response, "degraded_reason", None)
        if db_url:
            record_ask_event(
                database_url=db_url,
                workspace_id=workspace_id,
                latency_ms=latency_ms,
                retrieval_path=retrieval_path,
                result_status=response.status,
                result_mode=getattr(response, "mode", "deterministic"),
                evidence_count=len(ask_evidence),
                degraded=getattr(response, "degraded", False),
                degraded_reason=degraded_reason,
                provider_used=getattr(response, "mode", "") == "provider_backed",
                requested_scope=request.retrieval_scope.model_dump() if request.retrieval_scope else None,
            )

        return response
