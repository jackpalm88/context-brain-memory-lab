"""
Scoring Model v2 — explicit weighted scoring for chunk retrieval.

Formula:
  final_score =
    0.45 * vector_score   (semantic similarity, from vector distance)
  + 0.20 * graph_score    (graph path match quality)
  + 0.20 * hub_score      (hub relevance, text-corroborated)
  + 0.10 * keyword_score  (query token overlap, cap 5 hits)
  + 0.05 * trust_score    (evidence quality)
  - penalty               (generic long graph path, weak evidence)

Scores: 0.0–1.0. final_score clamped [0, 1].
Domain terms must NOT appear here — passed via hub/graph data arguments.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Set


@dataclass
class ScoreComponents:
    vector_score: float = 0.0
    graph_score: float = 0.0
    hub_score: float = 0.0
    keyword_score: float = 0.0
    trust_score: float = 0.0
    penalty: float = 0.0
    final_score: float = 0.0


def _tokens(text: str) -> Set[str]:
    return set(re.findall(r"[a-z0-9]{2,}", text.lower()))


def compute_chunk_score(
    *,
    distance: float,
    graph_match: List[str],
    hub_match: List[str],
    hub_aliases: List[str],
    hub_related_terms: List[str],
    query_tokens: Set[str],
    chunk_text: str,
    source_query_count: int,
) -> ScoreComponents:
    sc = ScoreComponents()

    # vector_score: 1 − dist/2, clamped [0, 1]
    sc.vector_score = max(0.0, min(1.0, 1.0 - distance / 2.0))

    # graph_score: shorter direct path → stronger signal
    if graph_match:
        path_len = len(graph_match)
        if path_len == 1:
            sc.graph_score = 0.9
        elif path_len == 2:
            sc.graph_score = 0.7
        elif path_len <= 4:
            sc.graph_score = 0.4
        else:
            sc.graph_score = 0.2

    # hub_score: hub-linked base + text-corroboration bonus
    if hub_match:
        chunk_toks = _tokens(chunk_text)
        hub_term_toks: Set[str] = set()
        for term in (hub_aliases or []) + (hub_related_terms or []):
            hub_term_toks |= _tokens(term)
        overlap = len(hub_term_toks & chunk_toks)
        if overlap >= 2:
            sc.hub_score = min(1.0, 0.70 + 0.20)
        elif overlap == 1:
            sc.hub_score = 0.70
        else:
            sc.hub_score = 0.30  # linked but weak text evidence

    # keyword_score: query token overlap normalised by 5 hits
    chunk_toks = _tokens(chunk_text)
    hits = len(query_tokens & chunk_toks)
    sc.keyword_score = min(1.0, hits / 5.0)

    # trust_score: evidence quality
    has_graph = bool(graph_match)
    has_hub = bool(hub_match)
    has_multi = source_query_count > 1
    if has_graph and has_hub:
        sc.trust_score = 0.8
    elif has_graph or has_hub:
        sc.trust_score = 0.6
    elif has_multi:
        sc.trust_score = 0.45
    else:
        sc.trust_score = 0.3

    # penalty
    if graph_match and len(graph_match) > 3 and not has_hub:
        sc.penalty += 0.10  # generic long graph path, no hub corroboration
    if sc.vector_score < 0.35 and not has_graph and not has_hub:
        sc.penalty += 0.10  # weak evidence all round

    raw = (
        0.45 * sc.vector_score
        + 0.20 * sc.graph_score
        + 0.20 * sc.hub_score
        + 0.10 * sc.keyword_score
        + 0.05 * sc.trust_score
        - sc.penalty
    )
    sc.final_score = max(0.0, min(1.0, raw))
    return sc


def score_to_trust_level(sc: ScoreComponents) -> str:
    if sc.final_score >= 0.70:
        return "high"
    if sc.final_score >= 0.45:
        return "medium"
    return "low"


def build_ranking_reason(
    sc: ScoreComponents,
    graph_match: List[str],
    hub_match: List[str],
    source_query_count: int,
) -> str:
    if graph_match and hub_match:
        return f"hub match: {hub_match[0]} + concept match via graph: {' → '.join(graph_match)}"
    if hub_match:
        return f"hub match: {hub_match[0]}"
    if graph_match:
        return f"concept match via graph: {' → '.join(graph_match)}"
    if source_query_count > 1:
        return f"semantic match reinforced across {source_query_count} query variants"
    return "semantic similarity"
