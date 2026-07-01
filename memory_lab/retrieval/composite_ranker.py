"""Composite retrieval ranking authority (OPENCB-M12-1, Strategy A).

Makes the shared Scoring Model v2 (`memory_lab.ingestion.chunk_scorer_v2`) the ranking
authority for public retrieval, replacing the flat per-path score sort. Deterministic and
provider-free.

Rank key: ``(-final_score, distance)`` — matching the private ranking authority
(`app/services/chunk_scorer.py` + `search_by_text_v2`). The composite `final_score` is also
surfaced as the row ``score``.

Signal feed (per approved M12-0 decision points):
- distance:
  - pgvector rows use their real vector ``distance``;
  - deterministic lexical rows use a pseudo-distance ``2*(1 - score)`` so ``vector_score`` stays
    vector-like even without embeddings (DP1a);
  - hub-only / distance-less rows use ``distance = 2.0`` → ``vector_score = 0`` (no semantic signal).
- hub scoring uses the formula; with no alias/related terms available the corroboration bonus is
  absent, so hub rows fall back to the base ``hub_score = 0.30`` rather than a flat 0.95 (DP2).

Out of scope for M12-1 (Strategy A): rescue stages, graph/hub orchestration rewrite, and any
recency/current-state/tier signal in the rank.
"""

from __future__ import annotations

from typing import Any, Dict, List

from memory_lab.ingestion.chunk_scorer_v2 import _tokens, compute_chunk_score

_LEXICAL_PATHS = {"content_chunk_workspace_scoped", "deterministic_fallback"}
_HUB_ONLY_DISTANCE = 2.0  # no semantic distance -> vector_score 0


def _as_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _rank_distance(row: Dict[str, Any]) -> float:
    """Resolve the distance fed to the scorer per the approved distance mapping."""
    distance = row.get("distance")
    if distance is not None:
        return float(distance)
    if row.get("retrieval_path") in _LEXICAL_PATHS:
        # DP1a: deterministic lexical score -> pseudo-distance so vector_score stays vector-like.
        score = float(row.get("score") or 0.0)
        return max(0.0, min(2.0, 2.0 * (1.0 - score)))
    return _HUB_ONLY_DISTANCE


def _score_row(row: Dict[str, Any], query_tokens) -> tuple[float, float]:
    distance = _rank_distance(row)
    sc = compute_chunk_score(
        distance=distance,
        graph_match=_as_list(row.get("graph_match")),
        hub_match=_as_list(row.get("hub_match")),
        hub_aliases=_as_list(row.get("hub_aliases")),          # DP2: empty -> hub_score base 0.30
        hub_related_terms=_as_list(row.get("hub_related_terms")),
        query_tokens=query_tokens,
        chunk_text=str(row.get("text") or row.get("snippet") or ""),
        source_query_count=len(row.get("source_queries") or []) or 1,
    )
    return sc.final_score, distance


def rank_by_composite(rows: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Rank retrieval candidates by the composite ``final_score``.

    Returns new row dicts (originals are not mutated) with ``final_score`` set and ``score``
    overwritten by the composite. Order: ``(-final_score, distance)``.
    """
    query_tokens = _tokens(query or "")
    scored: List[tuple[float, float, Dict[str, Any]]] = []
    for row in rows:
        final_score, distance = _score_row(row, query_tokens)
        enriched = dict(row)
        enriched["final_score"] = round(final_score, 4)
        enriched["score"] = round(final_score, 4)
        scored.append((final_score, distance, enriched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]
