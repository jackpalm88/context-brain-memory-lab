from typing import Any, Callable, Dict, List, Optional, Set

from .expansion import expand_query
from .store import GraphStore

VectorSearchFn = Callable[[str], List[Dict[str, Any]]]
RerankFn = Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]


def _matched_graph_terms(result: Dict[str, Any], graph_terms: List[str]) -> List[str]:
    """Return expanded graph terms evidenced by the candidate text/provenance.

    This keeps M12-2B as a provenance feed: an expanded query may retrieve rows
    because of original query terms, but only rows that actually carry the expanded
    graph term should expose graph_match to the scorer.
    """
    text = str(result.get("text") or result.get("snippet") or "").lower()
    return [term for term in graph_terms if term.lower() in text]


def hybrid_search(
    query: str,
    graph: GraphStore,
    vector_search_fn: VectorSearchFn,
    rerank_fn: RerankFn,
    max_expanded_queries: int = 5,
    max_hops: int = 1,
    min_confidence: float = 0.7,
    graph_boost: float = 0.1,
    workspace_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    terms = query.lower().split()
    expanded_terms = expand_query(terms, graph, max_hops, min_confidence, workspace_id=workspace_id)

    new_terms = [t for t in expanded_terms if t not in terms][:max_expanded_queries]
    expanded_queries = [query] + [f"{query} {t}" for t in new_terms]

    all_results: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    for q in expanded_queries:
        for r in vector_search_fn(q):
            if workspace_id and r.get("workspace_id") and str(r.get("workspace_id")) != str(workspace_id):
                continue
            rid = str(r.get("id", r.get("entry_id", r.get("content_id", ""))))
            if rid not in seen_ids:
                seen_ids.add(rid)
                r["source_queries"] = [q]
                r["_graph_boosted"] = False
                r["graph_match"] = _matched_graph_terms(r, new_terms)
                if r["graph_match"]:
                    r["knowledge_path"] = [
                        {"type": "query", "value": query},
                        *[{"type": "graph", "value": t} for t in r["graph_match"]],
                        {"type": "content", "value": rid},
                    ]
                all_results.append(r)
            else:
                for existing in all_results:
                    eid = str(existing.get("id", existing.get("entry_id", existing.get("content_id", ""))))
                    if eid == rid and q not in existing["source_queries"]:
                        existing["source_queries"].append(q)
                        graph_terms = _matched_graph_terms(existing, new_terms)
                        if graph_terms:
                            merged = list(existing.get("graph_match") or [])
                            for term in graph_terms:
                                if term not in merged:
                                    merged.append(term)
                            existing["graph_match"] = merged
                            existing["knowledge_path"] = [
                                {"type": "query", "value": query},
                                *[{"type": "graph", "value": t} for t in merged],
                                {"type": "content", "value": rid},
                            ]
                        break

    for r in all_results:
        query_count = len(r["source_queries"])
        if query_count > 1:
            current_score = r.get("score", r.get("similarity", 0.0))
            r["score"] = current_score * (1.0 + graph_boost * (query_count - 1))
            r["_graph_boosted"] = True

    return rerank_fn(all_results)
