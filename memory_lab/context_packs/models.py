from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from memory_lab.ingestion.classify_pipeline import MEMORY_TYPE_VALUES

PACK_VERSION = "b12_context_pack_v1"

CONTEXT_PACK_WARNINGS: List[str] = [
    "context_pack_is_not_answer",
    "truth_arbitration_disabled",
    "provider_backed_reasoning_disabled",
    "computed_read_only_no_db_mutation",
    "conflict_candidates_are_unresolved_candidates",
    "stale_items_are_not_automatically_false",
]

CONTEXT_PACK_NON_CLAIMS: List[str] = [
    "no_full_context_brain_claim",
    "no_truth_arbitration",
    "no_automatic_conflict_resolution",
    "no_provider_backed_reasoning_by_default",
    "no_wrapper_sdk_yet",
    "no_pypi_publish_claim",
    "no_production_tenancy_or_billing",
    "no_1_0_api_stability",
]


class ContextPackBuildRequest(BaseModel):
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

    @staticmethod
    def _clean(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @model_validator(mode="after")
    def _validate_and_normalize(self):
        self.workspace_id = self._clean(self.workspace_id)
        self.query = self._clean(self.query)
        self.scope = self._clean(self.scope)
        self.memory_type = self._clean(self.memory_type)
        if self.memory_types is not None:
            self.memory_types = [v for v in (self._clean(v) for v in self.memory_types) if v]
        if not self.query and not self.scope:
            raise ValueError("At least one of query or scope is required.")
        effective = self.resolved_memory_types()
        invalid = [v for v in effective or [] if v not in MEMORY_TYPE_VALUES]
        if invalid:
            raise ValueError(
                f"Unknown memory_type value(s): {sorted(invalid)!r}. "
                f"Allowed: {sorted(MEMORY_TYPE_VALUES)!r}"
            )
        return self

    def resolved_memory_types(self) -> Optional[List[str]]:
        values: List[str] = []
        if self.memory_type:
            values.append(self.memory_type)
        if self.memory_types:
            values.extend(self.memory_types)
        deduped = sorted({v for v in values if v})
        return deduped or None

    def effective_query(self) -> str:
        return self.query or self.scope or ""


class ContextPackSummaryMetadata(BaseModel):
    mode: str = "computed_read_only_context_pack"
    pack_version: str = PACK_VERSION
    limits: Dict[str, int]
    include_flags: Dict[str, bool]
    memory_types: List[str] = Field(default_factory=list)
    source_services: List[str] = Field(default_factory=list)
    truth_arbitration: bool = False
    provider_backed_reasoning: bool = False
    db_mutation: bool = False


class ContextPackEvidenceRef(BaseModel):
    evidence_id: str
    content_id: str
    chunk_id: Optional[str] = None
    rank: Optional[int] = None
    snippet: str = ""
    score: Optional[float] = None
    score_kind: Optional[str] = None
    memory_type: Optional[str] = None
    memory_sub_type: Optional[str] = None
    classify_confidence: Optional[float] = None
    is_current: Optional[bool] = None
    current_state_scope: Optional[str] = None
    cs_supersedes_content_id: Optional[str] = None
    role: Optional[str] = None
    source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ContextPackOmittedItem(BaseModel):
    reason: str
    source: str
    count: int = 0
    metadata: Optional[Dict[str, Any]] = None


class ContextPackBuildResponse(BaseModel):
    context_pack_id: str
    workspace_id: str
    query: Optional[str] = None
    scope: Optional[str] = None
    summary_metadata: ContextPackSummaryMetadata
    supporting_evidence: List[ContextPackEvidenceRef] = Field(default_factory=list)
    current_state_signals: List[ContextPackEvidenceRef] = Field(default_factory=list)
    conflict_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    counterfindings: List[ContextPackEvidenceRef] = Field(default_factory=list)
    stale_or_superseded_items: List[ContextPackEvidenceRef] = Field(default_factory=list)
    omitted_items: List[ContextPackOmittedItem] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=lambda: list(CONTEXT_PACK_WARNINGS))
    non_claims: List[str] = Field(default_factory=lambda: list(CONTEXT_PACK_NON_CLAIMS))
