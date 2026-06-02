from typing import Any, Dict, List, Callable

from memory_lab.graph.adapter import CBGraphAdapter
from memory_lab.graph.store import GraphStore


class RetrievalAdapter:
    """Provider-neutral retrieval adapter with deterministic defaults."""

    def __init__(self, database_url: str):
        self.graph_store = GraphStore(database_url)
        self.vector_search_fn: Callable[[str], List[Dict[str, Any]]] = self._deterministic_vector_search
        self.rerank_fn: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]] = self._deterministic_rerank
        self.adapter = CBGraphAdapter(
            graph_store=self.graph_store,
            vector_search_fn=self.vector_search_fn,
            rerank_fn=self.rerank_fn,
        )

    def _deterministic_vector_search(self, query: str) -> List[Dict[str, Any]]:
        # Deterministic fixture-only baseline; provider-backed embeddings disabled by default.
        return [
            {"id": "r1", "score": 0.91, "text": f"synthetic hit for: {query}"},
            {"id": "r2", "score": 0.85, "text": f"synthetic hit for: {query}"},
        ]

    def _deterministic_rerank(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(results, key=lambda x: x.get("score", 0), reverse=True)

    def search(self, query: str, max_hops: int = 1, min_confidence: float = 0.7, graph_boost: float = 0.1) -> List[Dict[str, Any]]:
        return self.adapter.search(
            query=query,
            max_hops=max_hops,
            min_confidence=min_confidence,
            graph_boost=graph_boost,
        )
