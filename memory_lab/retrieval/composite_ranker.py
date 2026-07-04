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

M12-4 (ranking parity closure) adds the private ranking surface on top of the formula:
- post-formula curation boosts with production constants — curated graph neighbor +0.04
  (graph-rescued rows without hub corroboration), manual hub link +0.15 (rows reached only
  via hub recall);
- per-result ``confidence``, ``score_components``, ``result_trust``, ``ranking_reason``,
  ``source_path`` (semantic / hub_linked / mixed / graph_neighbor);
- ``build_ranking_signals`` — the RankingSignals envelope computed from the ranked rows.
"""

from __future__ import annotations

from typing import Any, Dict, List

from memory_lab.ingestion.chunk_scorer_v2 import (
    _tokens,
    build_ranking_reason,
    compute_chunk_score,
    score_to_trust_level,
)

_LEXICAL_PATHS = {"content_chunk_workspace_scoped", "deterministic_fallback"}
_HUB_ONLY_DISTANCE = 2.0  # no semantic distance -> vector_score 0

# M12-4: post-formula curation boosts. Production constants (search_by_text_v2):
# fixed, not caller-configurable — Doctrine #4.
CURATED_GRAPH_BOOST = 0.04   # graph-rescued neighbor without hub corroboration
MANUAL_LINK_BOOST = 0.15     # reached only via hub recall (manual curation signal)

_HUB_PATHS = {"hub_link_workspace_scoped"}
_GRAPH_RESCUE_PATHS = {
    "graph_rescue_zero_result_workspace_scoped",
    "graph_rescue_nonzero_workspace_scoped",
}
SCORING_MODEL = "v2_weighted_components"


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


def _graph_signal(row: Dict[str, Any]) -> List[str]:
    """Resolve graph provenance fed to Scoring Model v2.

    M12-2B is metadata feed only: consume existing ``graph_match`` first, then
    fall back to already-attached ``knowledge_path`` graph entries when present.
    No candidate expansion, rescue, boost, or formula changes happen here.
    """
    signal = _as_list(row.get("graph_match"))
    if signal:
        return signal

    path = row.get("knowledge_path") or []
    graph_terms: List[str] = []
    for item in path if isinstance(path, list) else []:
        if isinstance(item, dict):
            value = item.get("value") or item.get("node") or item.get("term")
            if value:
                graph_terms.append(str(value))
        elif isinstance(item, str) and item.startswith("graph:"):
            graph_terms.append(item.split(":", 1)[1])
    return graph_terms


def source_path_for_row(row: Dict[str, Any]) -> str:
    """Classify how a candidate reached the result set (production source_path parity).

    hub_linked     — reached only via hub recall (hub retrieval path);
    mixed          — hub corroboration on a row that arrived via another path;
    graph_neighbor — admitted by a graph rescue stage;
    semantic       — plain vector/lexical retrieval.
    """
    retrieval_path = str(row.get("retrieval_path") or "")
    has_hub = bool(_as_list(row.get("hub_match")))
    if retrieval_path in _HUB_PATHS:
        return "hub_linked"
    if has_hub:
        return "mixed"
    if row.get("graph_rescue") or retrieval_path in _GRAPH_RESCUE_PATHS:
        return "graph_neighbor"
    return "semantic"


def _score_row(row: Dict[str, Any], query_tokens) -> tuple[Any, float]:
    distance = _rank_distance(row)
    sc = compute_chunk_score(
        distance=distance,
        graph_match=_graph_signal(row),
        hub_match=_as_list(row.get("hub_match")),
        hub_aliases=_as_list(row.get("hub_aliases")),          # DP2: empty -> hub_score base 0.30
        hub_related_terms=_as_list(row.get("hub_related_terms")),
        query_tokens=query_tokens,
        chunk_text=str(row.get("text") or row.get("snippet") or ""),
        source_query_count=len(row.get("source_queries") or []) or 1,
    )
    return sc, distance


def rank_by_composite(rows: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Rank retrieval candidates by the composite ``final_score``.

    Returns new row dicts (originals are not mutated) with ``final_score`` set and ``score``
    overwritten by the composite. Order: ``(-final_score, distance)``.

    M12-4: applies the fixed curation boosts and attaches the per-result ranking
    surface (confidence, score_components, result_trust, ranking_reason, source_path).
    """
    query_tokens = _tokens(query or "")
    scored: List[tuple[float, float, Dict[str, Any]]] = []
    for row in rows:
        sc, distance = _score_row(row, query_tokens)
        graph_match = _graph_signal(row)
        hub_match = _as_list(row.get("hub_match"))
        source_queries = row.get("source_queries") or []
        source_path = source_path_for_row(row)

        boost_prefix = ""
        if source_path == "graph_neighbor" and not hub_match:
            sc.final_score = min(1.0, sc.final_score + CURATED_GRAPH_BOOST)
            boost_prefix = f"curated graph neighbor (+{CURATED_GRAPH_BOOST:.2f}); "
        elif source_path == "hub_linked":
            sc.final_score = min(1.0, sc.final_score + MANUAL_LINK_BOOST)

        reason = build_ranking_reason(sc, graph_match, hub_match, len(source_queries) or 1)
        if source_path == "hub_linked" and hub_match:
            hub_label = str(row.get("hub_title") or hub_match[0])
            reason = (
                f"manually linked to hub '{hub_label}'; retrieved via hub recall"
                f" (vector_score={sc.vector_score:.2f}, boost=+{MANUAL_LINK_BOOST})"
            )
        elif boost_prefix:
            reason = boost_prefix + reason

        enriched = dict(row)
        enriched["final_score"] = round(sc.final_score, 4)
        enriched["score"] = round(sc.final_score, 4)
        enriched["confidence"] = round(sc.final_score, 3)
        enriched["score_components"] = {
            "vector_score": round(sc.vector_score, 4),
            "graph_score": round(sc.graph_score, 4),
            "hub_score": round(sc.hub_score, 4),
            "keyword_score": round(sc.keyword_score, 4),
            "trust_score": round(sc.trust_score, 4),
            "penalty": round(sc.penalty, 4),
            "final_score": round(sc.final_score, 4),
        }
        enriched["result_trust"] = score_to_trust_level(sc)
        enriched["ranking_reason"] = reason
        enriched["source_path"] = source_path
        scored.append((sc.final_score, distance, enriched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored]


def build_ranking_signals(ranked_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """RankingSignals envelope (production parity), computed from ranked rows only."""
    hub_linked_in_results = sum(1 for r in ranked_rows if _as_list(r.get("hub_match")))
    hub_recall_results = sum(1 for r in ranked_rows if r.get("source_path") in ("hub_linked", "mixed"))
    curated_neighbors = sum(1 for r in ranked_rows if r.get("source_path") == "graph_neighbor")
    used_graph = any(_as_list(r.get("graph_match")) for r in ranked_rows)
    return {
        "used_scoring_v2": True,
        "scoring_model": SCORING_MODEL,
        "used_hub_boost": hub_linked_in_results > 0,
        "hub_linked_in_results": hub_linked_in_results,
        "used_hub_recall": hub_recall_results > 0,
        "hub_recall_results_returned": hub_recall_results,
        "manual_link_boost": MANUAL_LINK_BOOST if hub_recall_results else 0.0,
        "used_graph_boost": used_graph,
        "used_curated_graph": curated_neighbors > 0,
        "curated_graph_boost": CURATED_GRAPH_BOOST if curated_neighbors else 0.0,
        "curated_neighbors_count": curated_neighbors,
    }
