"""B15 graph health public-safe models.

These models are intentionally deterministic and read-only. They do not imply
answer correctness, truth arbitration, graph mutation, or Full Context Brain
parity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class IndexingStatus(str, Enum):
    UNKNOWN = "unknown"
    PENDING = "pending"
    INDEXING = "indexing"
    SEARCHABLE = "searchable"
    BLOCKED_EMPTY = "blocked_empty"
    BLOCKED_QUALITY = "blocked_quality"
    BLOCKED_REEXTRACT = "blocked_reextract"
    FAILED = "failed"
    STALE = "stale"


class GraphHealthWarning(BaseModel):
    code: str
    severity: str = "warning"
    message: str
    affected_content_ids: List[str] = Field(default_factory=list)
    affected_node_ids: List[str] = Field(default_factory=list)
    hub_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class GraphHealthComponentScores(BaseModel):
    topology_score: int = Field(ge=0, le=25)
    index_searchability_score: int = Field(ge=0, le=30)
    hub_recall_score: int = Field(ge=0, le=25)
    alias_hygiene_score: int = Field(ge=0, le=10)
    consistency_score: int = Field(ge=0, le=10)

    @property
    def total(self) -> int:
        return max(
            0,
            min(
                100,
                self.topology_score
                + self.index_searchability_score
                + self.hub_recall_score
                + self.alias_hygiene_score
                + self.consistency_score,
            ),
        )


class ContentHealthState(BaseModel):
    content_id: str
    saved: bool = True
    searchable: bool = False
    hub_linked: bool = False
    graph_reachable: bool = False
    retrieval_observed: Optional[bool] = None
    indexing_status: IndexingStatus = IndexingStatus.UNKNOWN
    searchable_after: Optional[datetime] = None
    embedding_present: Optional[bool] = None


class TopologyMetrics(BaseModel):
    node_count: int = 0
    edge_count: int = 0
    isolated_node_count: int = 0
    low_degree_node_count: int = 0
    largest_component_size: int = 0
    largest_component_coverage: float = 0.0


class IndexSearchabilityMetrics(BaseModel):
    total_saved_count: int = 0
    searchable_count: int = 0
    missing_embedding_count: int = 0
    stale_count: int = 0
    null_embedding_backlog_count: int = 0


class HubRecallFinding(BaseModel):
    hub_id: str
    content_id: str
    saved: bool = True
    searchable: bool = False
    hub_linked: bool = True
    graph_reachable: bool = False
    retrieval_observed: Optional[bool] = None
    indexing_status: IndexingStatus = IndexingStatus.UNKNOWN
    warning_codes: List[str] = Field(default_factory=list)


class HubRecallMetrics(BaseModel):
    hub_id: Optional[str] = None
    linked_count: int = 0
    searchable_linked_count: int = 0
    retrieval_observed_count: int = 0
    retrieval_observed_available: bool = False
    hub_linked_not_searchable_count: int = 0
    hub_linked_not_retrieved_count: int = 0


class HubRecallHealthReport(BaseModel):
    hub_id: Optional[str] = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    score: int = Field(ge=0, le=25)
    metrics: HubRecallMetrics
    findings: List[HubRecallFinding] = Field(default_factory=list)
    warnings: List[GraphHealthWarning] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    non_claims: List[str] = Field(default_factory=list)


class AliasCandidate(BaseModel):
    candidate_id: str
    terms: List[str]
    candidate_type: str = "duplicate"
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence: List[str] = Field(default_factory=list)
    requires_human_review: bool = True
    mutation_allowed: bool = False


class AliasCandidateReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    candidate_count: int = 0
    candidates: List[AliasCandidate] = Field(default_factory=list)
    warnings: List[GraphHealthWarning] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    non_claims: List[str] = Field(default_factory=list)


class GraphHealthReport(BaseModel):
    status: str = "ok"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    health_score: int = Field(ge=0, le=100)
    component_scores: GraphHealthComponentScores
    topology_metrics: TopologyMetrics
    index_searchability_metrics: IndexSearchabilityMetrics
    hub_recall_metrics: HubRecallMetrics
    warnings: List[GraphHealthWarning] = Field(default_factory=list)
    affected_content_ids: List[str] = Field(default_factory=list)
    affected_node_ids: List[str] = Field(default_factory=list)
    hub_recall_findings: List[HubRecallFinding] = Field(default_factory=list)
    alias_candidates: List[AliasCandidate] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    non_claims: List[str] = Field(default_factory=list)


DEFAULT_NON_CLAIMS = [
    "graph_health_is_operational_signal_not_answer_correctness",
    "saved_by_id_does_not_guarantee_searchable",
    "hub_link_does_not_guarantee_semantic_recall",
    "alias_candidates_require_human_review",
    "no_graph_mutation_or_automatic_merge",
    "no_truth_arbitration_or_conflict_resolution",
    "no_full_context_brain_claim",
    "no_private_cb_or_ask_v2_port",
]
