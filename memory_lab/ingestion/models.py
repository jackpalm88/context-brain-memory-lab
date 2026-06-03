"""Typed models for Phase 7 ingestion events."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IngestionScores:
    quality: float = 0.0
    relevance: float = 0.0
    novelty: float = 0.0
    composite: float = 0.0
    # Reasons from LLM, for observability
    quality_reason: str = ""
    relevance_reason: str = ""
    novelty_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "quality": round(self.quality, 4),
            "relevance": round(self.relevance, 4),
            "novelty": round(self.novelty, 4),
            "composite": round(self.composite, 4),
        }


@dataclass
class IngestionEvent:
    content_preview: str
    content_id: Optional[str] = None
    workspace_id: Optional[str] = None
    scores: IngestionScores = field(default_factory=IngestionScores)
    circuit_open: bool = False
    tier_decision: Optional[str] = None
    conflict_detected: bool = False
    human_gate_triggered: bool = False
    final_state: Optional[str] = None
    score_reason: str = ""
    # Rule IDs applied during scoring
    applied_rule_ids: list = field(default_factory=list)
    # Populated when scorer used a fallback path instead of live LLM call
    fallback_reason: str = ""
