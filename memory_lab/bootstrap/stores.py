from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from memory_lab.graph.store import GraphStore
from memory_lab.graph.hub_store import HubStore
from memory_lab.graph.hub_edge_store import HubEdgeStore
from memory_lab.graph.alias_store import AliasStore


@dataclass
class StoreBundle:
    graph_store: GraphStore
    hub_store: HubStore
    hub_edge_store: HubEdgeStore
    alias_store: AliasStore


def build_store_bundle(database_url: str) -> StoreBundle:
    # All stores are DSN-backed in PR1a staging scope.
    graph_store = GraphStore(dsn=database_url)
    hub_store = HubStore(dsn=database_url)
    hub_edge_store = HubEdgeStore(dsn=database_url)
    alias_store = AliasStore(dsn=database_url)
    return StoreBundle(
        graph_store=graph_store,
        hub_store=hub_store,
        hub_edge_store=hub_edge_store,
        alias_store=alias_store,
    )
