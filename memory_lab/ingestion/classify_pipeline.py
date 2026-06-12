"""
Classify Pipeline — heuristic_v1

Clean-room pure-heuristic implementation.  No LLM calls.  No embeddings.  No provider dependency.
Classifies content into the 7-type memory taxonomy using keyword/structural signals.

Memory taxonomy (from migrations 027-030):
  milestone    — gate completions, released versions, shipped milestones
  decision     — architectural choices, superseded decisions, rationale records
  principle    — doctrine, policy, invariant rules that persist until superseded
  anchor       — current-state, canonical, checkpoint records
  evidence     — validation results, smoke tests, scorecard readings
  plan_roadmap — next gates, proposed work, implementation roadmaps
  raw_memory   — fallback for unclassified or ambiguous content

Ownership (from schema reconciliation):
  This module writes: memory_type, memory_sub_type, classify_confidence, classified_at, domain_id
  This module NEVER writes: is_current, current_state_scope, cs_supersedes_content_id

Design constraints:
  - Never raises — returns raw_memory fallback on any error
  - Deterministic — same input always produces same output
  - Provider-free — no API key, no network, no LLM calls
  - Sync — callers use run_in_threadpool if needed in async context
"""

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

MEMORY_TYPE_VALUES = frozenset({
    "milestone", "decision", "principle", "anchor",
    "evidence", "plan_roadmap", "raw_memory",
})


class MemoryType:
    MILESTONE = "milestone"
    DECISION = "decision"
    PRINCIPLE = "principle"
    ANCHOR = "anchor"
    EVIDENCE = "evidence"
    PLAN_ROADMAP = "plan_roadmap"
    RAW_MEMORY = "raw_memory"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    memory_type: str
    memory_sub_type: Optional[str] = None
    confidence: float = 0.0
    signals: List[str] = field(default_factory=list)
    project_topic: Optional[str] = None
    domain_hint: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "memory_type": self.memory_type,
            "memory_sub_type": self.memory_sub_type,
            "confidence": round(self.confidence, 4),
            "signals": self.signals,
            "project_topic": self.project_topic,
            "domain_hint": self.domain_hint,
        }


# ---------------------------------------------------------------------------
# Heuristic signal tables
# ---------------------------------------------------------------------------
#
# Format: dict[memory_type] -> list of (patterns, weight)
#   patterns: list of lowercase substrings; first match fires the group
#   weight:   contribution to raw score; a group fires AT MOST ONCE per classify call
#
# Confidence bands (from _raw_score_to_confidence):
#   raw >= 7  → 0.93  (multiple strong signals)
#   raw >= 5  → 0.85  (strong signal set)
#   raw >= 3  → 0.72  (moderate match)
#   raw >= 2  → 0.62  (weak match, above threshold)
#   raw <  2  → raw_memory fallback (0.45)

_KEYWORD_SIGNALS = {
    MemoryType.MILESTONE: [
        # Strong: specific gate pass/fail patterns (governance events)
        (["_schema_apply_pass", "_design_pass", "_review_pass",
          "_implementation_pass", "_apply_pass", "schema_apply_pass",
          "gate_pass", "gate: pass", "_implementation_pass"], 3),
        # Moderate: gate name prefixes
        (["go_classify", "go_current_state", "go_context_brain",
          "go_retrieval", "go_auth", "go_conflict", "go_ingestion",
          "go_tier", "go_graph"], 2),
        # Moderate: version/release markers
        (["v0.1.0", "0.1.0b", "released:", "public release",
          "publicly released", "shipped:", "package published"], 2),
        # Weak: schema/migration application event
        (["migration boundary", "migrations applied", "schema apply complete"], 1),
        # Moderate: explicit milestone vocabulary
        (["milestone:", "gate complete", "gate closed",
          "phase complete", "stage complete"], 2),
    ],

    MemoryType.DECISION: [
        # Strong: explicit decision declarations
        (["we decided", "decision:", "architectural decision",
          "decided to use", "decided to go with", "we chose", "chosen:"], 3),
        # Moderate: supersession vocabulary
        (["supersedes", "superseded by", "reversed decision",
          "option a —", "option b —", "option c —",
          "option a:", "option b:", "option c:"], 2),
        # Moderate: rejection/acceptance framing
        (["rejected:", "accepted over", "trade-off", "tradeoff",
          "alternative considered", "instead of using"], 2),
        # Weak: decision vocabulary
        (["rationale:", "decision made", "we will use", "chosen approach"], 1),
    ],

    MemoryType.PRINCIPLE: [
        # Strong: explicit principle/invariant declarations
        (["principle:", "invariant:", "doctrine:", "policy:"], 3),
        # Moderate: strong rule language (never/must not as standalone phrases)
        (["must not", "must never", "forbidden:", "never:", "prohibited:",
          "ownership invariant", "critical invariant"], 2),
        # Moderate: principle vocabulary
        (["principle", "invariant", "governance rule",
          "design principle", "architectural principle"], 2),
        # Weak: rule-like directive forms
        (["always:", "never write", "do not write", "do not call",
          "do not modify", "do not expose"], 1),
    ],

    MemoryType.ANCHOR: [
        # Strong: current-state / canonical terminology
        (["current state", "current-state", "is_current",
          "canonical state", "active anchor", "state anchor"], 3),
        # Moderate: authoritative/checkpoint markers
        (["canonical:", "authoritative:", "source of truth",
          "checkpoint:", "current scope", "current canonical"], 2),
        # Weak: anchor vocabulary
        (["anchor:", "current_state_scope",
          "is current for", "scope anchor"], 1),
    ],

    MemoryType.EVIDENCE: [
        # Strong: smoke/test result markers
        (["smoke_001", "smoke_002", "smoke_003", "30/30",
          "smoke checks", "smoke test", "checks passed",
          "all checks pass"], 3),
        # Strong: scorecard/metrics output
        (["scorecard", "layer scores", "layer score",
          "% headline", "full cb score", "score:"], 3),
        # Moderate: explicit validation evidence
        (["evidence:", "validated:", "verified:", "test result",
          "test passed", "tests pass", "confirmed:"], 2),
        # Moderate: pass/fail record markers
        (["pass:", "fail:", "check_id", "n/n pass",
          "checks", "test run"], 2),
        # Weak: general test vocabulary
        (["unit test", "integration test", "pytest result",
          "assertion", "assert fails"], 1),
    ],

    MemoryType.PLAN_ROADMAP: [
        # Strong: explicit next-gate / gate-sequence markers
        (["next gate:", "next gates:", "recommended next gate",
          "open gates:", "gate sequence:", "pending gates"], 3),
        # Strong: roadmap/plan declarations
        (["roadmap:", "implementation plan:", "migration plan:",
          "proposed:", "planned work:", "plan:"], 3),
        # Moderate: future work markers
        (["upcoming:", "future work", "to-do:", "todo:",
          "planned:", "in progress"], 2),
        # Weak: planning vocabulary
        (["next step", "stage plan", "phase plan", "work ahead"], 1),
    ],
}

# node_type → memory_type boost (from migration 008 node_type values)
_NODE_TYPE_BOOST = {
    "milestone": MemoryType.MILESTONE,
    "event":     MemoryType.MILESTONE,
    "decision":  MemoryType.DECISION,
    "fact":      MemoryType.EVIDENCE,
    "hypothesis":MemoryType.EVIDENCE,
    "source":    MemoryType.EVIDENCE,
    "concept":   MemoryType.PRINCIPLE,
    "playbook":  MemoryType.PLAN_ROADMAP,
    "task":      MemoryType.PLAN_ROADMAP,
    "raw_note":  MemoryType.RAW_MEMORY,
}

# Domain inference keywords — minimum 2 distinct keywords needed for a match
_DOMAIN_KEYWORDS: dict = {
    "schema":     ["schema", "migration", "alter table", "create table", "index"],
    "api":        ["endpoint", "router", "fastapi", "http", "post /", "get /"],
    "retrieval":  ["retrieval", "vector search", "embedding", "similarity", "semantic"],
    "ingestion":  ["ingestion", "ingest", "scorer", "classify", "pipeline", "chunk"],
    "auth":       ["auth", "authentication", "api_key", "workspace_member", "subject"],
    "governance": ["governance", "gate", "constitutional", "policy", "rule_id"],
}

# Project topic extraction patterns
_PROJECT_PATTERNS = [
    (r"context[_\-]brain", "context_brain_memory_lab"),
    (r"memory[_\-]lab",    "context_brain_memory_lab"),
    (r"context brain",     "context_brain_memory_lab"),
    (r"cb[_\-]memory",     "context_brain_memory_lab"),
]

# Minimum raw score to classify as anything other than raw_memory
_MIN_SCORE_THRESHOLD = 2.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(
    content: str,
    title: str = "",
    node_type: Optional[str] = None,
    tier: Optional[str] = None,
    composite_score: Optional[float] = None,
    topic_tags: Optional[List[str]] = None,
) -> ClassificationResult:
    """
    Classify content into the 7-type memory taxonomy.

    Heuristic v1: keyword/structural signals only.  No LLM calls.  Never raises.

    Args:
        content:         Main content text to classify.
        title:           Optional title (also searched for signals).
        node_type:       Optional existing node_type hint (from schema migration 008).
        tier:            Optional memory_tier ('transient', 'working', 'long_term', etc.).
        composite_score: Optional ingestion quality score (0–1); not used in v1 logic.
        topic_tags:      Optional list of existing tags (used for domain_hint).

    Returns:
        ClassificationResult.  Falls back to raw_memory on any error.
    """
    try:
        return _classify_impl(content, title, node_type, tier, composite_score, topic_tags)
    except Exception as exc:
        logger.error("[classify_pipeline] classification error: %s", exc)
        return ClassificationResult(
            memory_type=MemoryType.RAW_MEMORY,
            confidence=0.0,
            signals=["fallback:error"],
        )


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

def _classify_impl(
    content: str,
    title: str,
    node_type: Optional[str],
    tier: Optional[str],
    composite_score: Optional[float],
    topic_tags: Optional[List[str]],
) -> ClassificationResult:
    if not content and not title:
        return ClassificationResult(
            memory_type=MemoryType.RAW_MEMORY,
            confidence=0.45,
            signals=["fallback:empty_content"],
        )

    full_text = f"{title}\n{content}".lower()

    # Score each type
    raw_scores: dict = {t: 0.0 for t in MEMORY_TYPE_VALUES - {MemoryType.RAW_MEMORY}}
    fired_signals: dict = {t: [] for t in raw_scores}

    for mtype, groups in _KEYWORD_SIGNALS.items():
        for patterns, weight in groups:
            for pattern in patterns:
                if pattern in full_text:
                    raw_scores[mtype] += weight
                    fired_signals[mtype].append(pattern)
                    break  # each group fires at most once

    # node_type structural hint
    if node_type and node_type in _NODE_TYPE_BOOST:
        boosted = _NODE_TYPE_BOOST[node_type]
        if boosted in raw_scores:
            raw_scores[boosted] += 1.5
            fired_signals[boosted].append(f"node_type:{node_type}")

    # Transient-tier penalty: milestone/principle rarely survive ephemeral content
    if tier in ("transient", "ephemeral"):
        raw_scores[MemoryType.MILESTONE] *= 0.5
        raw_scores[MemoryType.PRINCIPLE] *= 0.5

    best_type = max(raw_scores, key=lambda t: raw_scores[t])
    best_score = raw_scores[best_type]

    if best_score < _MIN_SCORE_THRESHOLD:
        return ClassificationResult(
            memory_type=MemoryType.RAW_MEMORY,
            memory_sub_type=None,
            confidence=0.45,
            signals=fired_signals.get(best_type, []) or ["fallback:below_threshold"],
            project_topic=_extract_project_topic(full_text),
            domain_hint=_extract_domain_hint(full_text, topic_tags),
        )

    return ClassificationResult(
        memory_type=best_type,
        memory_sub_type=_classify_subtype(best_type, full_text),
        confidence=_raw_score_to_confidence(best_score),
        signals=fired_signals[best_type],
        project_topic=_extract_project_topic(full_text),
        domain_hint=_extract_domain_hint(full_text, topic_tags),
    )


def _raw_score_to_confidence(raw_score: float) -> float:
    """Map raw keyword score to a deterministic confidence band."""
    if raw_score >= 7:
        return 0.93
    if raw_score >= 5:
        return 0.85
    if raw_score >= 3:
        return 0.72
    return 0.62  # score == 2


def _classify_subtype(memory_type: str, text: str) -> Optional[str]:
    """Assign a memory_sub_type based on memory_type and content signals."""
    if memory_type == MemoryType.MILESTONE:
        if any(s in text for s in ["schema apply", "_schema_apply_pass", "schema_apply"]):
            return "schema_apply"
        if any(s in text for s in ["v0.1.0", "0.1.0b", "released:", "shipped:"]):
            return "release_milestone"
        if any(s in text for s in ["scorecard", "layer score", "score updated"]):
            return "scorecard_update"
        return "governance_milestone"

    if memory_type == MemoryType.DECISION:
        if any(s in text for s in ["schema", "migration", "architecture"]):
            return "schema_design"
        return None

    if memory_type == MemoryType.PRINCIPLE:
        return "architecture_principle"

    if memory_type == MemoryType.ANCHOR:
        return "current_state_anchor"

    if memory_type == MemoryType.EVIDENCE:
        if any(s in text for s in ["scorecard", "layer score", "% headline", "layer scores"]):
            return "scorecard_update"
        return "implementation_evidence"

    if memory_type == MemoryType.PLAN_ROADMAP:
        return "roadmap_plan"

    return None


def _extract_project_topic(text: str) -> Optional[str]:
    """Extract a project_topic hint from text using public-safe patterns."""
    for pattern, topic in _PROJECT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return topic
    return None


def _extract_domain_hint(text: str, topic_tags: Optional[List[str]]) -> Optional[str]:
    """Suggest a domain name based on keyword density. Requires >= 2 keyword hits."""
    if topic_tags:
        tag_blob = " ".join(topic_tags).lower()
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            if sum(1 for kw in keywords if kw in tag_blob) >= 1:
                return domain

    best_domain: Optional[str] = None
    best_count = 0
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_domain = domain

    return best_domain if best_count >= 2 else None
