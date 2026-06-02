from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from memory_lab.api.policies.content_quality import is_junk

# ---------------------------------------------------------------------------
# Node-type-aware embedding eligibility thresholds (Fix 6 - Phase 7c hardening)
# ---------------------------------------------------------------------------
_EMBEDDING_MIN_WORDS_DEFAULT = 200
_EMBEDDING_MIN_WORDS_BY_NODE_TYPE = {
    "decision": 80,
    "architecture": 80,
    "concept": 80,
    "playbook": 80,
    "fact": 120,
    "hypothesis": 120,
    "question": 80,
}


def embedding_min_words(node_type=None):
    if node_type:
        return _EMBEDDING_MIN_WORDS_BY_NODE_TYPE.get(node_type.lower(), _EMBEDDING_MIN_WORDS_DEFAULT)
    return _EMBEDDING_MIN_WORDS_DEFAULT


@dataclass
class QualityResult:
    score: float
    flags: List[str]
    is_acceptable: bool
    word_count: int
    embedding_eligible: bool = True
    embedding_skip_reason: Optional[str] = None


class ContentQualityAnalyzer:

    def analyze(self, text: str, node_type=None) -> QualityResult:
        text = text or ""
        word_count = len(text.split())

        content = {
            "full_text": text,
            "extraction_strategy": None,
            "quality_score": None,
            "needs_reextract": None,
            "word_count": word_count,
        }

        junk, reasons = is_junk(content)
        flags = list(reasons)

        score = 10.0
        if word_count < 50:
            flags.append("too_short")
            score = min(score, 2.0)
        elif word_count < 200:
            flags.append("short")
            score = min(score, 5.0)

        if junk:
            flags.append("junk")
            score = min(score, 1.0)

        min_words = embedding_min_words(node_type)
        embedding_eligible = (not junk) and (word_count >= min_words)
        embedding_skip_reason = None
        if not embedding_eligible:
            if junk:
                embedding_skip_reason = "junk_content"
            else:
                nt_suffix = f" (node_type={node_type})" if node_type else ""
                embedding_skip_reason = f"embedding_not_eligible: word_count={word_count}, min={min_words}{nt_suffix}"

        return QualityResult(
            score=float(score),
            flags=flags,
            is_acceptable=bool(embedding_eligible),
            word_count=int(word_count),
            embedding_eligible=bool(embedding_eligible),
            embedding_skip_reason=embedding_skip_reason,
        )
