"""B15 Graph Health Report Generator.

Produces deterministic JSON-compatible reports from the B15 graph health
service layer without API wiring, database dependencies, provider calls,
or graph mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from memory_lab.graph.health_models import GraphHealthReport
from memory_lab.graph.health_service import GraphHealthService


class GraphHealthReportGenerator:
    """Generate deterministic graph health reports from fixture data."""

    def generate(
        self,
        *,
        scenario_name: str,
        nodes: Optional[Iterable[str]] = None,
        edges: Optional[Iterable[Any]] = None,
        content_items: Optional[Iterable[Dict[str, Any]]] = None,
        hub_links: Optional[Dict[str, Iterable[str]]] = None,
        retrieval_observations: Optional[Dict[Any, bool]] = None,
        alias_labels: Optional[Iterable[str]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        report = GraphHealthService().evaluate(
            nodes=nodes,
            edges=edges,
            content_items=content_items,
            hub_links=hub_links,
            retrieval_observations=retrieval_observations,
            alias_labels=alias_labels,
            now=now,
        )
        return self._to_jsonable(report, scenario_name=scenario_name)

    def _to_jsonable(self, report: GraphHealthReport, scenario_name: str) -> Dict[str, Any]:
        return {
            "scenario": scenario_name,
            "generated_at": report.generated_at.isoformat() if report.generated_at else None,
            "status": report.status,
            "health_score": report.health_score,
            "component_scores": report.component_scores.model_dump(),
            "topology_metrics": report.topology_metrics.model_dump(),
            "index_searchability_metrics": report.index_searchability_metrics.model_dump(),
            "hub_recall_metrics": report.hub_recall_metrics.model_dump(),
            "warnings": [w.model_dump() for w in report.warnings],
            "hub_recall_findings": [f.model_dump() for f in report.hub_recall_findings],
            "alias_candidates": [c.model_dump() for c in report.alias_candidates],
            "affected_content_ids": report.affected_content_ids,
            "affected_node_ids": report.affected_node_ids,
            "limitations": report.limitations,
            "non_claims": report.non_claims,
        }

    @classmethod
    def generate_all_scenarios(cls, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        generator = cls()
        now = now or datetime(2026, 1, 1, tzinfo=timezone.utc)
        scenarios: List[Dict[str, Any]] = []

        # 1. Healthy connected graph
        scenarios.append(
            generator.generate(
                scenario_name="healthy_connected_graph",
                nodes=["a", "b", "c"],
                edges=[("a", "b"), ("b", "c"), ("a", "c")],
                content_items=[
                    {
                        "content_id": "a",
                        "searchable": True,
                        "embedding_present": True,
                        "graph_reachable": True,
                    },
                    {
                        "content_id": "b",
                        "searchable": True,
                        "embedding_present": True,
                        "graph_reachable": True,
                    },
                    {
                        "content_id": "c",
                        "searchable": True,
                        "embedding_present": True,
                        "graph_reachable": True,
                    },
                ],
                hub_links={"hub1": ["a", "b", "c"]},
                retrieval_observations={
                    ("hub1", "a"): True,
                    ("hub1", "b"): True,
                    ("hub1", "c"): True,
                },
                alias_labels=["Context Brain", "D.O.M.A", "Riga"],
                now=now,
            )
        )

        # 2. Missing embedding / null searchable
        scenarios.append(
            generator.generate(
                scenario_name="missing_embedding_null_searchable",
                nodes=["missing"],
                content_items=[
                    {
                        "content_id": "missing",
                        "searchable": False,
                        "embedding_present": False,
                    }
                ],
                now=now,
            )
        )

        # 3. Hub-linked not searchable / not retrieved
        scenarios.append(
            generator.generate(
                scenario_name="hub_linked_not_searchable_or_retrieved",
                content_items=[
                    {
                        "content_id": "c1",
                        "searchable": False,
                        "indexing_status": "pending",
                    }
                ],
                hub_links={"hub1": ["c1"]},
                retrieval_observations={("hub1", "c1"): False},
                now=now,
            )
        )

        # 4. Alias candidate case
        scenarios.append(
            generator.generate(
                scenario_name="alias_candidate_case",
                nodes=["x"],
                alias_labels=["D.O.M.A", "DOMA", "doma", "Context Brain", "Context_Brain"],
                content_items=[
                    {
                        "content_id": "x",
                        "searchable": True,
                        "embedding_present": True,
                        "graph_reachable": True,
                    }
                ],
                now=now,
            )
        )

        # 5. Empty graph
        scenarios.append(
            generator.generate(
                scenario_name="empty_graph",
                now=now,
            )
        )

        return scenarios
