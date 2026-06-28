from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AlternativeConsidered(BaseModel):
    option: str
    reason_rejected: str


class DecisionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    decision_reason: str = Field(..., min_length=1)
    decision_context: Optional[str] = None
    why_this_matters: Optional[str] = None
    decision_status: str = Field("active", pattern="^(active|superseded|reversed|draft)$")
    reversible: bool = True
    source_content_ids: List[UUID] = Field(default_factory=list)
    linked_hub_ids: List[UUID] = Field(default_factory=list)
    supersedes_decision_id: Optional[UUID] = None
    alternatives_considered: List[AlternativeConsidered] = Field(default_factory=list)
    contradicting_evidence: Optional[str] = None
    confidence_level: str = Field("medium", pattern="^(low|medium|high)$")
    decision_tags: List[str] = Field(default_factory=list)


class DecisionStatusUpdate(BaseModel):
    decision_status: str = Field(..., pattern="^(active|superseded|reversed|draft)$")


class DecisionSummary(BaseModel):
    decision_id: str
    title: str
    decision_status: str
    reversible: bool
    confidence_level: Optional[str] = None
    decision_tags: List[str] = Field(default_factory=list)
    created_by_subject: Optional[str] = None
    created_at: datetime


class DecisionFull(BaseModel):
    decision_id: str
    content_id: Optional[str] = None
    title: str
    decision_reason: str
    decision_context: Optional[str] = None
    why_this_matters: Optional[str] = None
    decision_status: str
    reversible: bool
    source_content_ids: List[str] = Field(default_factory=list)
    linked_hub_ids: List[str] = Field(default_factory=list)
    supersedes_decision_id: Optional[str] = None
    superseded_by_decision_id: Optional[str] = None
    alternatives_considered: List[Dict[str, Any]] = Field(default_factory=list)
    contradicting_evidence: Optional[str] = None
    confidence_level: str = "medium"
    decision_tags: List[str] = Field(default_factory=list)
    created_by_subject: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DecisionCreateResponse(BaseModel):
    decision_id: str
    title: str
    decision_status: str
    created_at: datetime


class DecisionListResponse(BaseModel):
    decisions: List[DecisionSummary]
    count: int


class LineageNode(BaseModel):
    decision_id: str
    title: str
    decision_status: str
    created_by_subject: Optional[str] = None
    created_at: datetime


class DecisionLineageResponse(BaseModel):
    decision_id: str
    title: str
    ancestors: List[LineageNode]
    descendants: List[LineageNode]
    depth: int
    depth_limit_reached: bool = False


class ConflictPair(BaseModel):
    decision_a: LineageNode
    decision_b: LineageNode
    conflict_reason: str


class DecisionConflictsResponse(BaseModel):
    conflicts: List[ConflictPair]
    count: int


class DecisionTimelineResponse(BaseModel):
    active: List[DecisionSummary] = Field(default_factory=list)
    superseded: List[DecisionSummary] = Field(default_factory=list)
    reversed: List[DecisionSummary] = Field(default_factory=list)
    draft: List[DecisionSummary] = Field(default_factory=list)
    total: int
