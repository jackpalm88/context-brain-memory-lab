from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from memory_lab.api.services.retrieval_scope import (
    RetrievalScope,
    resolve_content_types,
    validate_scope_vs_legacy_content_types,
)


class AskRequest(BaseModel):
    """Public ask request. Workspace/auth come from AuthContext, not body fields."""

    query: Optional[str] = None
    question: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=10)
    include_evidence: bool = True
    degraded_ok: bool = True
    memory_type: Optional[str] = None
    memory_types: Optional[List[str]] = None
    retrieval_scope: Optional[RetrievalScope] = Field(
        default=None,
        description=(
            "Optional first-class scoped-retrieval envelope (docs/DESIGN_SCOPED_RETRIEVAL.md). "
            "allowed_hubs restricts candidates to content linked to those hubs; content_types is "
            "an alias for memory_type/memory_types expressed inside the scope. Absent by default; "
            "omitting it is byte-identical to pre-scoped-retrieval behavior."
        ),
    )
    enable_provider_synthesis: bool = False

    @model_validator(mode="after")
    def _validate_scope_vs_legacy_content_types(self):
        scoped = self.retrieval_scope.content_types if self.retrieval_scope else None
        validate_scope_vs_legacy_content_types(self.resolved_memory_types(), scoped)
        return self

    def resolved_content_types(self) -> Optional[List[str]]:
        """Effective content-type filter merging legacy memory_type(s) and
        retrieval_scope.content_types (validated equivalent-or-conflicting above).
        None means no filter."""
        scoped = self.retrieval_scope.content_types if self.retrieval_scope else None
        return resolve_content_types(self.resolved_memory_types(), scoped)

    def resolved_allowed_hubs(self) -> Optional[List[str]]:
        return self.retrieval_scope.allowed_hubs if self.retrieval_scope else None

    def normalized_query(self) -> str:
        query = (self.query or "").strip()
        question = (self.question or "").strip()
        if query and question and query != question:
            return query
        return query or question

    def resolved_memory_types(self) -> Optional[List[str]]:
        """Merge the optional single memory_type and memory_types into a deduped filter list.

        Returns None when no usable filter is supplied (memory-type-agnostic ask), so the
        retrieval adapter applies no memory_type restriction.
        """
        values: List[str] = []
        if self.memory_type and self.memory_type.strip():
            values.append(self.memory_type.strip())
        for value in self.memory_types or []:
            if value and value.strip():
                values.append(value.strip())
        deduped = list(dict.fromkeys(values))
        return deduped or None


class EvidenceItem(BaseModel):
    evidence_id: str
    rank: int
    content_id: str
    chunk_id: Optional[str] = None
    snippet: str
    score: Optional[float] = None
    score_kind: str
    retrieval_path: str
    source: Optional[str] = None
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    retrieval_reason: Optional[str] = None
    ranking_reason: Optional[str] = None
    hub_match: Optional[Any] = None
    graph_match: Optional[Any] = None
    knowledge_path: Optional[List[Any]] = None
    score_components: Optional[Dict[str, Any]] = None
    distance: Optional[float] = None
    # M12-4 ranking surface parity
    confidence: Optional[float] = None
    result_trust: Optional[str] = None
    source_path: Optional[str] = None
    # FV-FIX-3 ask current-state awareness (resolver-owned fields, read-only here)
    is_current: Optional[bool] = None
    current_state_scope: Optional[str] = None
    cs_supersedes_content_id: Optional[str] = None


class Citation(BaseModel):
    evidence_id: str
    rank: int
    content_id: str
    chunk_id: Optional[str] = None
    score: Optional[float] = None


class Claim(BaseModel):
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)


class AskResponse(BaseModel):
    answer: str
    intent: str
    confidence: float
    confidence_explanation: str
    citations: list[Citation] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    degraded: bool = False
    insufficient_evidence: bool = False
    workspace_id: str
    status: str
    failure_reason: Optional[str] = None
    mode: str = "deterministic"


class ReasoningRequest(BaseModel):
    """Public B13 reasoning request. Auth workspace remains authoritative."""

    workspace_id: Optional[str] = None
    query: Optional[str] = None
    scope: Optional[str] = None
    memory_type: Optional[str] = None
    memory_types: Optional[List[str]] = None
    include_supporting_evidence: bool = True
    include_current_state: bool = True
    include_conflicts: bool = True
    include_counterfindings: bool = True
    limit: int = Field(default=10, ge=1, le=50)
    max_hops: int = Field(default=2, ge=1, le=3)
    enable_provider_synthesis: bool = False

    @model_validator(mode="after")
    def _require_query_or_scope(self):
        self.workspace_id = (self.workspace_id or "").strip() or None
        self.query = (self.query or "").strip() or None
        self.scope = (self.scope or "").strip() or None
        self.memory_type = (self.memory_type or "").strip() or None
        if self.memory_types is not None:
            self.memory_types = [str(v).strip() for v in self.memory_types if str(v).strip()]
        if not self.query and not self.scope:
            raise ValueError("At least one of query or scope is required.")
        return self


class ReasoningTraversalStep(BaseModel):
    step_id: str
    hop: int
    source: str
    relation: str
    target: str
    evidence_ids: List[str] = Field(default_factory=list)
    rationale: str
    degraded: bool = False


class ReasoningProviderMetadata(BaseModel):
    provider: str = "none"
    model: Optional[str] = None
    attempted: bool = False
    configured: bool = False
    degraded: bool = False
    failure_reason: Optional[str] = None


class ReasoningResponse(BaseModel):
    reasoning_id: str
    mode: str
    context_pack_ref: Dict[str, Any]
    traversal_steps: List[ReasoningTraversalStep] = Field(default_factory=list)
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    explanation: Dict[str, Any] = Field(default_factory=dict)
    conflict_warnings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    provider_metadata: ReasoningProviderMetadata = Field(default_factory=ReasoningProviderMetadata)
    degraded_reason: Optional[str] = None
    non_claims: List[str] = Field(default_factory=list)


class ReasoningAnswerResponse(BaseModel):
    reasoning_id: str
    mode: Literal["deterministic", "provider_backed", "degraded"]
    answer_candidate: str
    evidence_refs: List[Dict[str, Any]] = Field(default_factory=list)
    context_pack_ref: Dict[str, Any]
    traversal_steps: List[ReasoningTraversalStep] = Field(default_factory=list)
    conflict_warnings: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    provider_metadata: ReasoningProviderMetadata = Field(default_factory=ReasoningProviderMetadata)
    degraded_reason: Optional[str] = None
    non_claims: List[str] = Field(default_factory=list)
