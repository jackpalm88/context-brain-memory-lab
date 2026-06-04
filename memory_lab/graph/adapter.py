from typing import Any, Callable, Dict, List

from .hybrid_search import hybrid_search
from .store import GraphStore

_ALLOWED_KWARGS = {"max_expanded_queries", "max_hops", "min_confidence", "graph_boost", "workspace_id", "vector_search_fn"}


class CBGraphAdapter:
    """Drop-in wrapper that adds graph expansion to any vector search function."""

    def __init__(
        self,
        graph_store: GraphStore,
        vector_search_fn: Callable,
        rerank_fn: Callable,
    ):
        self.graph = graph_store
        self.vector_search = vector_search_fn
        self.rerank = rerank_fn

    def search(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        vector_search_fn = kwargs.pop("vector_search_fn", self.vector_search)
        return hybrid_search(
            query=query,
            graph=self.graph,
            vector_search_fn=vector_search_fn,
            rerank_fn=self.rerank,
            **{k: v for k, v in kwargs.items() if k in _ALLOWED_KWARGS},
        )
