"""FV-FIX-5: read-only term adjacency over the curated hub graph.

The M12 BFS query expansion (memory_lab/graph/expansion.py) walks a term
graph via ``get_neighbors(term)``. Its original source, ``cb_edges``, has no
public writer in cbml, so the expansion had nothing to walk and the curated
hub graph (``cb_hubs`` + ``cb_hub_edges``) was never consulted — the FV-6
finding.

HubTermGraph exposes that curated hub graph as term adjacency for the
EXISTING hop-bounded BFS. It is deliberately not a traversal engine:

- one bounded read per instance (workspace's active hubs + non-archived
  human-curated edges), adjacency answered from memory afterwards
- a term matches a hub by exact lowercased title/alias equality, or — for
  single-word terms — by token membership in the title/aliases
- neighbors returned are the connected hubs' lowercase title + aliases
- only curated edges are walked: status='manual' (approved proposals are
  promoted to manual by the approve flow), never 'inferred' proposals
- NULL edge confidence means human-curated and is treated as 1.0
- falls back through to the inner GraphStore (cb_edges) so installations
  that do populate the term graph keep their behavior

Consumers opt in explicitly (RetrievalAdapter.search(consult_hub_graph=True),
used by reasoning traverse/explain only); default retrieval is unchanged.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_MAX_HUBS = 500
_MAX_EDGES = 2000


def _terms_of(title: str, aliases: List[str]) -> Set[str]:
    return {t.strip().lower() for t in [title, *aliases] if t and t.strip()}


def _tokens(term: str) -> Set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", term.lower()) if len(t) >= 3}


class HubTermGraph:
    """GraphStore-compatible neighbor source backed by the curated hub graph."""

    def __init__(self, database_url: str, inner: Any = None):
        self.database_url = database_url
        self.inner = inner
        self._loaded_for: Optional[str] = None
        self._hub_terms: Dict[str, Set[str]] = {}
        self._edges: List[Tuple[str, str, float]] = []

    def _conn(self):
        import psycopg2

        return psycopg2.connect(self.database_url)

    def _load(self, workspace_id: Optional[str]) -> None:
        if self._loaded_for == (workspace_id or ""):
            return
        hub_terms: Dict[str, Set[str]] = {}
        edges: List[Tuple[str, str, float]] = []
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT hub_id::text, title, aliases
                      FROM cb_hubs
                     WHERE status = 'active'
                       AND workspace_uuid = %s::uuid
                     ORDER BY hub_id
                     LIMIT %s
                    """,
                    (workspace_id, _MAX_HUBS),
                )
                for hub_id, title, aliases in cur.fetchall():
                    hub_terms[hub_id] = _terms_of(str(title or ""), [str(a) for a in (aliases or [])])
                cur.execute(
                    """
                    SELECT source_hub_id::text, target_hub_id::text, confidence
                      FROM cb_hub_edges
                     WHERE status = 'manual'
                       AND archived_at IS NULL
                       AND workspace_id = %s::uuid
                     ORDER BY id
                     LIMIT %s
                    """,
                    (workspace_id, _MAX_EDGES),
                )
                for source, target, confidence in cur.fetchall():
                    edges.append((source, target, 1.0 if confidence is None else float(confidence)))
        self._hub_terms = hub_terms
        self._edges = edges
        self._loaded_for = workspace_id or ""

    def _hubs_matching(self, term: str) -> Set[str]:
        needle = term.strip().lower()
        if not needle:
            return set()
        matched: Set[str] = set()
        needle_is_single_word = " " not in needle and len(needle) >= 3
        for hub_id, terms in self._hub_terms.items():
            if needle in terms:
                matched.add(hub_id)
                continue
            if needle_is_single_word and any(needle in _tokens(t) for t in terms):
                matched.add(hub_id)
        return matched

    def get_neighbors(self, node: str, min_confidence: float = 0.7, workspace_id: Optional[str] = None) -> Set[str]:
        neighbors: Set[str] = set()
        if workspace_id:
            try:
                self._load(workspace_id)
                matched_hubs = self._hubs_matching(node)
                if matched_hubs:
                    for source, target, confidence in self._edges:
                        if confidence < min_confidence:
                            continue
                        other = None
                        if source in matched_hubs and target not in matched_hubs:
                            other = target
                        elif target in matched_hubs and source not in matched_hubs:
                            other = source
                        if other is not None:
                            neighbors |= self._hub_terms.get(other, set())
            except Exception as exc:
                logger.warning("[hub_term_graph] adjacency skipped: %s", exc)
        if self.inner is not None:
            try:
                neighbors |= set(self.inner.get_neighbors(node, min_confidence, workspace_id=workspace_id))
            except Exception as exc:
                logger.warning("[hub_term_graph] inner term-graph skipped: %s", exc)
        return neighbors
