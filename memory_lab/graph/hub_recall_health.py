"""B15 deterministic hub recall health service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .health_models import (
    DEFAULT_NON_CLAIMS,
    GraphHealthWarning,
    HubRecallFinding,
    HubRecallHealthReport,
    HubRecallMetrics,
    IndexingStatus,
)

WARNING_HUB_LINKED_NOT_SEARCHABLE = "HUB_LINKED_NOT_SEARCHABLE"
WARNING_HUB_LINKED_NOT_RETRIEVED = "HUB_LINKED_NOT_RETRIEVED"


class HubRecallHealthService:
    """Evaluate saved/searchable/hub-linked/retrieval-observed gaps.

    Input data is provided by callers. This class does not query or mutate any
    database and does not perform retrieval/provider calls.
    """

    def evaluate(
        self,
        *,
        content_items: Iterable[Dict[str, Any]],
        hub_links: Dict[str, Iterable[str]],
        retrieval_observations: Optional[Dict[Tuple[str, str], bool]] = None,
        hub_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> HubRecallHealthReport:
        del now  # reserved for future explicit searchable_after semantics
        retrieval_observations = retrieval_observations or {}
        content_by_id = {str(item.get("content_id")): dict(item) for item in content_items}
        scoped_links = {
            str(h): [str(cid) for cid in ids]
            for h, ids in hub_links.items()
            if hub_id is None or str(h) == str(hub_id)
        }

        linked_count = 0
        searchable_linked_count = 0
        retrieval_observed_count = 0
        not_searchable: List[HubRecallFinding] = []
        not_retrieved: List[HubRecallFinding] = []
        retrieval_available = bool(retrieval_observations)

        for hid in sorted(scoped_links):
            for cid in sorted(scoped_links[hid]):
                linked_count += 1
                item = content_by_id.get(cid, {"content_id": cid, "saved": False})
                searchable = bool(item.get("searchable"))
                graph_reachable = bool(item.get("graph_reachable"))
                status = _status(item)
                observed = retrieval_observations.get((hid, cid))
                if observed is True:
                    retrieval_observed_count += 1
                if searchable:
                    searchable_linked_count += 1

                codes: List[str] = []
                if not searchable:
                    codes.append(WARNING_HUB_LINKED_NOT_SEARCHABLE)
                if observed is False:
                    codes.append(WARNING_HUB_LINKED_NOT_RETRIEVED)

                if codes:
                    finding = HubRecallFinding(
                        hub_id=hid,
                        content_id=cid,
                        saved=bool(item.get("saved", cid in content_by_id)),
                        searchable=searchable,
                        hub_linked=True,
                        graph_reachable=graph_reachable,
                        retrieval_observed=observed,
                        indexing_status=status,
                        warning_codes=codes,
                    )
                    if WARNING_HUB_LINKED_NOT_SEARCHABLE in codes:
                        not_searchable.append(finding)
                    if WARNING_HUB_LINKED_NOT_RETRIEVED in codes:
                        not_retrieved.append(finding)

        score = self.score(
            linked_count=linked_count,
            searchable_linked_count=searchable_linked_count,
            retrieval_observed_count=retrieval_observed_count,
            retrieval_available=retrieval_available,
            hub_linked_not_searchable_count=len(not_searchable),
        )
        warnings: List[GraphHealthWarning] = []
        if not_searchable:
            warnings.append(
                GraphHealthWarning(
                    code=WARNING_HUB_LINKED_NOT_SEARCHABLE,
                    message="Hub-linked content is saved/linked but not searchable.",
                    affected_content_ids=sorted({f.content_id for f in not_searchable}),
                    hub_id=str(hub_id) if hub_id else None,
                )
            )
        if not_retrieved:
            warnings.append(
                GraphHealthWarning(
                    code=WARNING_HUB_LINKED_NOT_RETRIEVED,
                    message="Hub-linked content was not observed in provided retrieval evidence.",
                    affected_content_ids=sorted({f.content_id for f in not_retrieved}),
                    hub_id=str(hub_id) if hub_id else None,
                )
            )

        limitations: List[str] = []
        if linked_count and not retrieval_available:
            limitations.append("retrieval_observed_not_available")

        metrics = HubRecallMetrics(
            hub_id=str(hub_id) if hub_id else None,
            linked_count=linked_count,
            searchable_linked_count=searchable_linked_count,
            retrieval_observed_count=retrieval_observed_count,
            retrieval_observed_available=retrieval_available,
            hub_linked_not_searchable_count=len(not_searchable),
            hub_linked_not_retrieved_count=len(not_retrieved),
        )
        return HubRecallHealthReport(
            hub_id=str(hub_id) if hub_id else None,
            generated_at=datetime.now(timezone.utc),
            score=score,
            metrics=metrics,
            findings=not_searchable + not_retrieved,
            warnings=warnings,
            limitations=limitations,
            non_claims=DEFAULT_NON_CLAIMS,
        )

    def score(
        self,
        *,
        linked_count: int,
        searchable_linked_count: int,
        retrieval_observed_count: int,
        retrieval_available: bool,
        hub_linked_not_searchable_count: int,
    ) -> int:
        if linked_count == 0:
            return 0
        searchable_score = round(10 * (searchable_linked_count / linked_count))
        if retrieval_available:
            retrieval_score = round(10 * (retrieval_observed_count / linked_count))
        else:
            retrieval_score = 5  # conservative partial credit, with limitation
        invisible_penalty_free = 5 if hub_linked_not_searchable_count == 0 else 0
        return max(0, min(25, searchable_score + retrieval_score + invisible_penalty_free))


def _status(item: Dict[str, Any]) -> IndexingStatus:
    raw = item.get("indexing_status")
    if raw:
        try:
            return IndexingStatus(str(raw))
        except ValueError:
            return IndexingStatus.UNKNOWN
    if item.get("searchable"):
        return IndexingStatus.SEARCHABLE
    return IndexingStatus.UNKNOWN
