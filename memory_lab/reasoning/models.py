from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
            # Deterministic, conservative choice: prefer canonical query.
            return query
        return query or question


class EvidenceItem(BaseModel):
    evidence_id: str
    content_id: str
    chunk_id: Optional[str] = None
    snippet: str
    score: Optional[float] = None
    source: Optional[str] = None


class Citation(BaseModel):
    evidence_id: str
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
