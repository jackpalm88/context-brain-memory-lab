from typing import Any, Callable, Dict, List, Optional, Set

from .expansion import expand_query
from .store import GraphStore

# M12-3B: non-zero graph rescue admission constants.
# Module-level constants (not runtime parameters) ensure the rescue gate is
# deterministic and not caller-configurable, preserving Doctrine #4.
_MIN_PRIMARY_FLOOR: int = 3   # rescue activates only when primary count < this
_MAX_RESCUE_ADD: int = 2      # max graph-rescue candidates admitted per call

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


def _candidate_key(result: Dict[str, Any]) -> str:
    """Stable dedup key used before rerank.

    Prefer chunk identity when present; fall back to content identity. Workspace is
    included so candidates are never merged across workspace boundaries.
    """
    workspace = str(result.get("workspace_id") or "")
    content_id = str(result.get("content_id") or result.get("id") or result.get("entry_id") or "")
    chunk_id = result.get("chunk_id")
    if chunk_id:
        return f"{workspace}:chunk:{content_id}:{chunk_id}"
    return f"{workspace}:content:{content_id}"


def _content_value(result: Dict[str, Any]) -> str:
    return str(result.get("id", result.get("entry_id", result.get("content_id", ""))))


def _merge_graph_terms(existing: Dict[str, Any], graph_terms: List[str], query: str, content_value: str) -> None:
    if not graph_terms:
        return
    merged = list(existing.get("graph_match") or [])
    for term in graph_terms:
        if term not in merged:
            merged.append(term)
    existing["graph_match"] = merged
    existing["knowledge_path"] = [
        {"type": "query", "value": query},
        *[{"type": "graph", "value": t} for t in merged],
        {"type": "content", "value": content_value},
    ]


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

    all_results: List[Dict[str, Any]] = []
    seen_keys: Set[str] = set()

    def add_results(rows: List[Dict[str, Any]], source_query: str, rescued: bool = False) -> None:
        for original in rows:
            r = dict(original)
            if workspace_id and r.get("workspace_id") and str(r.get("workspace_id")) != str(workspace_id):
                continue
            key = _candidate_key(r)
            rid = _content_value(r)
            graph_terms = _matched_graph_terms(r, new_terms)
            if key not in seen_keys:
                seen_keys.add(key)
                r["source_queries"] = [source_query]
                r["_graph_boosted"] = False
                if rescued:
                    r["retrieval_path"] = "graph_rescue_zero_result_workspace_scoped"
                    r["graph_rescue"] = True
                r["graph_match"] = graph_terms
                _merge_graph_terms(r, graph_terms, query, rid)
                all_results.append(r)
            else:
                for existing in all_results:
                    if _candidate_key(existing) == key:
                        if source_query not in existing["source_queries"]:
                            existing["source_queries"].append(source_query)
                        if rescued:
                            existing["graph_rescue"] = True
                        _merge_graph_terms(existing, graph_terms, query, rid)
                        break

    # Primary retrieval always runs first. It may receive graph provenance metadata
    # when its own text evidences expanded graph terms, but it does not broaden the
    # candidate set.
    primary_results = vector_search_fn(query)
    add_results(primary_results, query, rescued=False)

    # M12-3A: graph rescue is deliberately narrow. Expanded graph queries may
    # introduce candidates only when primary retrieval produced zero usable rows.
    if not all_results:
        for term in new_terms:
            rescue_query = f"{query} {term}"
            add_results(vector_search_fn(rescue_query), rescue_query, rescued=True)

    # M12-3B: non-zero graph rescue — controlled shortage-fill only.
    # Activates when primary retrieval returned candidates but fewer than
    # _MIN_PRIMARY_FLOOR, indicating a thin result set that may benefit from
    # adjacent graph-linked evidence.
    #
    # Admission rules (all must hold):
    #   1. primary count > 0 and < _MIN_PRIMARY_FLOOR
    #   2. rescue candidate passes workspace-scope check (enforced by add_results)
    #   3. candidate has >= 1 matched graph term in its text (text-corroboration)
    #   4. at most _MAX_RESCUE_ADD candidates admitted
    #   5. content-level dedup: if candidate already in seen_keys, only graph
    #      provenance is merged onto the existing row (no duplicate row added)
    elif 0 < len(all_results) < _MIN_PRIMARY_FLOOR:
        rescue_added = 0
        for term in new_terms:
            if rescue_added >= _MAX_RESCUE_ADD:
                break
            rescue_candidates = vector_search_fn(f"{query} {term}")
            for original in rescue_candidates:
                if rescue_added >= _MAX_RESCUE_ADD:
                    break
                r = dict(original)
                if workspace_id and r.get("workspace_id") and str(r.get("workspace_id")) != str(workspace_id):
                    continue
                matched = _matched_graph_terms(r, new_terms)
                if not matched:
                    # No text corroboration — reject. Hub-link-only candidates
                    # must not be admitted (Doctrine #1: hub is not authority).
                    continue
                key = _candidate_key(r)
                rid = _content_value(r)
                if key in seen_keys:
                    # Content-level dedup: enrich existing row with graph provenance
                    # only; do NOT add a duplicate row. The existing row retains its
                    # original retrieval_path and does NOT gain graph_rescue=True.
                    for existing in all_results:
                        if _candidate_key(existing) == key:
                            _merge_graph_terms(existing, matched, query, rid)
                            break
                else:
                    # New candidate — admit with non-zero rescue provenance.
                    seen_keys.add(key)
                    r["retrieval_path"] = "graph_rescue_nonzero_workspace_scoped"
                    r["graph_rescue"] = True
                    r["source_queries"] = [f"{query} {term}"]
                    r["graph_match"] = matched
                    _merge_graph_terms(r, matched, query, rid)
                    all_results.append(r)
                    rescue_added += 1

    for r in all_results:
        query_count = len(r["source_queries"])
        if query_count > 1:
            current_score = r.get("score", r.get("similarity", 0.0))
            r["score"] = current_score * (1.0 + graph_boost * (query_count - 1))
            r["_graph_boosted"] = True

    return rerank_fn(all_results)
