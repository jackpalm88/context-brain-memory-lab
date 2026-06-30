from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.providers.llm_backend import LLMBackend
from memory_lab.query.context_pack_adapter import (
    build_support_only_context_pack_for_ask,
    evidence_items_from_supporting_context_pack,
)
from memory_lab.query.evidence import normalize_evidence
from memory_lab.query.provider_answer import apply_provider_answer
from memory_lab.reasoning.answer_synthesizer import synthesize_answer
from memory_lab.reasoning.intent_detector import detect_intent
from memory_lab.reasoning.models import AskRequest, AskResponse
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
        query = request.normalized_query()
        detection = detect_intent(query)
        policy = policy_for_intent(detection.intent, request.top_k)
        results = self.retrieval_adapter.search(
            query=query,
            max_hops=1,
            min_confidence=0.0,
            graph_boost=0.1,
            workspace_id=workspace_id,
            memory_types=request.resolved_memory_types(),
        )
        evidence = normalize_evidence(results[: policy.top_k], limit=policy.snippet_char_limit)
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
        if response.status != "ok":
            return response
        return apply_provider_answer(
            response=response,
            request=request,
            query=query,
            evidence=ask_evidence,
            provider_synthesis_enabled=self.provider_synthesis_enabled,
            backend=self.backend,
        )
