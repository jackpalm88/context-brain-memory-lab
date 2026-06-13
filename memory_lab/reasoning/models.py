from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class AskRequest(BaseModel):
    """Public ask request. Workspace/auth come from AuthContext, not body fields."""

    query: Optional[str] = None
    question: Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=10)
    include_evidence: bool = True
    degraded_ok: bool = True

    def normalized_query(self) -> str:
        query = (self.query or "").strip()
        question = (self.question or "").strip()
        if query and question and query != question:
            return query
        return query or question


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
