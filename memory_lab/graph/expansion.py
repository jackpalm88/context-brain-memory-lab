from typing import List, Optional, Set

from .store import GraphStore


def expand_query(
    query_terms: List[str],
    graph: GraphStore,
    max_hops: int = 1,
    min_confidence: float = 0.7,
    alias_store=None,  # AliasStore | None — optional to avoid circular import
) -> List[str]:
    expanded: Set[str] = {t.lower().strip() for t in query_terms}

    # Alias resolution: map variant terms to canonical graph nodes before BFS
    if alias_store is not None:
        expanded = {s.lower().strip() for s in alias_store.resolve_terms(expanded)}

    current_layer: Set[str] = set(expanded)

    for _ in range(max_hops):
        next_layer: Set[str] = set()
        for term in current_layer:
            for neighbor in graph.get_neighbors(term, min_confidence):
                n = neighbor.lower().strip()
                if n not in expanded:
                    expanded.add(n)
                    next_layer.add(n)
        current_layer = next_layer
        if not current_layer:
            break

    return list(expanded)
