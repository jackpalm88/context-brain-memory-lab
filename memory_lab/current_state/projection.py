"""EB-1: the one canonical projection of resolver-owned current-state fields.

Every read surface that exposes current-state must consume this helper so the
field set cannot drift per surface (before this, the save response, ask
evidence and context-pack refs each hand-picked the columns).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

CURRENT_STATE_FIELDS = ("is_current", "current_state_scope", "cs_supersedes_content_id")


def current_state_select_sql(alias: str = "ci") -> str:
    """SQL fragment selecting the canonical current-state columns."""
    return (
        f"{alias}.is_current, {alias}.current_state_scope, "
        f"{alias}.cs_supersedes_content_id::text AS cs_supersedes_content_id"
    )


def current_state_group_by_sql(alias: str = "ci") -> str:
    """GROUP BY companion for aggregating queries that use current_state_select_sql."""
    return f"{alias}.is_current, {alias}.current_state_scope, {alias}.cs_supersedes_content_id"


def project_current_state(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Copy the canonical current-state fields out of a DB row (missing → None)."""
    return {field: row.get(field) for field in CURRENT_STATE_FIELDS}
