from typing import Any, Callable, Dict, List, Optional, Set

from .expansion import expand_query
from .store import GraphStore

VectorSearchFn = Callable[[str], List[Dict[str, Any]]]
RerankFn = Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]


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
                r["graph_match"] = [t for t in new_terms if t in q]
                all_results.append(r)
            else:
                for existing in all_results:
                    eid = str(existing.get("id", existing.get("entry_id", existing.get("content_id", ""))))
                    if eid == rid and q not in existing["source_queries"]:
                        existing["source_queries"].append(q)
                        break

    for r in all_results:
        query_count = len(r["source_queries"])
        if query_count > 1:
            current_score = r.get("score", r.get("similarity", 0.0))
            r["score"] = current_score * (1.0 + graph_boost * (query_count - 1))
            r["_graph_boosted"] = True

    return rerank_fn(all_results)
