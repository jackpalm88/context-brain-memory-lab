"""B23 public-safe context candidate packaging.

Builds evidence references from ranked caller-supplied records. The builder is
local, deterministic, and does not fetch stored content or wire any API.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import hashlib

from memory_lab.retrieval.search_by_purpose import RankedContextCandidate, B23_SEARCH_NON_CLAIMS

B23_CONTEXT_SCOPE = "public_safe_stable_evidence_packaging_supplied_records_only"

@dataclass(frozen=True)
class ContextCandidateBuildRequest:
    query: str
    ranked_candidates: tuple[RankedContextCandidate, ...]
    max_candidates: int = 8
    max_context_chars: int = 4000
    snippet_chars: int = 600

@dataclass(frozen=True)
class ContextEvidenceRef:
    evidence_id: int
    evidence_key: str
    item_id: str
    rank: int
    score: float
    snippet: str
    source_metadata: Mapping[str, Any]
    reason: str
    limitations: tuple[str, ...]

@dataclass(frozen=True)
class ContextCandidatePackage:
    query: str
    evidence: tuple[ContextEvidenceRef, ...]
    context_text: str
    total_context_chars: int
    truncated: bool
    limitations: tuple[str, ...]
    non_claims: tuple[str, ...] = B23_SEARCH_NON_CLAIMS
    scope: str = B23_CONTEXT_SCOPE

def build_context_candidates(request: ContextCandidateBuildRequest) -> ContextCandidatePackage:
    selected = _dedupe_ranked(request.ranked_candidates)[: max(0, request.max_candidates)]
    refs: list[ContextEvidenceRef] = []
    parts: list[str] = []
    truncated = False
    package_limitations: list[str] = []
    for index, ranked in enumerate(selected, start=1):
        source_text = ranked.candidate.snippet or ranked.candidate.text or ""
        snippet = source_text.strip()[: max(0, request.snippet_chars)]
        if len(source_text.strip()) > len(snippet):
            package_limitations.append(f"snippet_truncated:{ranked.item_id}")
        evidence_key = _evidence_key(request.query, ranked.item_id, ranked.rank)
        block = _format_block(index, evidence_key, ranked, snippet)
        next_text = "\n\n".join(parts + [block])
        if len(next_text) > request.max_context_chars and parts:
            package_limitations.append("context_budget_exhausted")
            truncated = True
            break
        if len(next_text) > request.max_context_chars:
            block = block[: max(0, request.max_context_chars)]
            snippet = snippet[: max(0, request.max_context_chars)]
            package_limitations.append("context_budget_truncated_first_item")
            truncated = True
        refs.append(ContextEvidenceRef(index, evidence_key, ranked.item_id, ranked.rank, ranked.score, snippet, dict(ranked.candidate.source_metadata), ranked.reason, ranked.limitations))
        parts.append(block)
        if truncated:
            break
    limitations = tuple(_dedupe(package_limitations + [lim for ref in refs for lim in ref.limitations]))
    context_text = "\n\n".join(parts)
    return ContextCandidatePackage(request.query, tuple(refs), context_text, len(context_text), truncated, limitations)

def _dedupe_ranked(candidates: Sequence[RankedContextCandidate]) -> list[RankedContextCandidate]:
    best: dict[str, RankedContextCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.item_id)):
        if candidate.item_id not in best:
            best[candidate.item_id] = candidate
    return sorted(best.values(), key=lambda item: (-item.score, item.item_id))

def _evidence_key(query: str, item_id: str, rank: int) -> str:
    digest = hashlib.sha256(f"b23|{query}|{item_id}|{rank}".encode("utf-8")).hexdigest()[:12]
    return f"B23-EVID-{digest}"

def _format_block(index: int, evidence_key: str, ranked: RankedContextCandidate, snippet: str) -> str:
    lines = [
        f"[{index}] evidence_key={evidence_key} item_id={ranked.item_id} rank={ranked.rank} score={ranked.score:.4f}",
        f"reason={ranked.reason}",
    ]
    if ranked.limitations:
        lines.append("limitations=" + ",".join(ranked.limitations))
    lines.append(snippet)
    return "\n".join(lines).strip()

def _dedupe(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out
