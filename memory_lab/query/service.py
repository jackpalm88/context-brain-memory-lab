from __future__ import annotations

from dataclasses import dataclass

from memory_lab.api.services.retrieval_adapter import RetrievalAdapter
from memory_lab.query.context_pack_adapter import (
    build_support_only_context_pack_for_ask,
    evidence_items_from_supporting_context_pack,
)
from memory_lab.query.evidence import normalize_evidence
from memory_lab.reasoning.answer_synthesizer import synthesize_answer
from memory_lab.reasoning.intent_detector import detect_intent
from memory_lab.reasoning.models import AskRequest, AskResponse
from memory_lab.reasoning.policy_generator import policy_for_intent


@dataclass
class QueryService:
    """Canonical internal orchestration owner for public query execution."""

    retrieval_adapter: RetrievalAdapter

    @classmethod
    def from_database_url(cls, database_url: str) -> "QueryService":
        return cls(retrieval_adapter=RetrievalAdapter(database_url))

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
        return synthesize_answer(
            request=request,
            detection=detection,
            policy=policy,
            evidence=ask_evidence,
            workspace_id=workspace_id,
        )
