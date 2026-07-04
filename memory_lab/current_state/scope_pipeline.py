"""Deterministic scope resolver pipeline (FV-FIX-2B).

Replaces the single keyword-heuristic fallback with a tiered resolution.
Priority order — the first tier that yields a scope wins:

1. explicit ``scope_hint`` (API/MCP caller) — authoritative
2. in-text marker (``current_state_scope:`` / ``scope:`` / ``anchor:`` lines)
3. existing anchor lineage — active ``cb_current_state_anchors`` scopes in the
   workspace whose slug tokens all appear in the content
4. hub alias match — active ``cb_hubs`` matched via title/aliases (strong) and
   related_terms (weak, needs >= 2 hits); deterministic alias resolution,
   not graph traversal
5. classification metadata (``project_topic``)
6. keyword heuristic (``domain_hint``)
7. ``global`` last-resort fallback

Invariants:
- provider-free and deterministic: DB tiers are read-only with ordered,
  bounded queries; an ambiguous tie skips the tier instead of guessing
- best-effort: a DB error skips that tier; the pipeline never raises
- workspace-isolated: lineage and hub tiers only see the caller's workspace
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

_MAX_SCOPE_LEN = 120
_MAX_CANDIDATE_ROWS = 200
_MIN_TERM_LEN = 3
_MIN_WEAK_HITS = 2

_MARKER_PATTERNS = (
    r"(?im)^\s*current_state_scope\s*[:=]\s*([^\n#;]+)",
    r"(?im)^\s*current-state-scope\s*[:=]\s*([^\n#;]+)",
    r"(?im)^\s*scope\s*[:=]\s*([^\n#;]+)",
    r"(?im)^\s*anchor\s*[:=]\s*([^\n#;]+)",
)

SOURCE_SCOPE_HINT = "scope_hint"
SOURCE_MARKER = "marker"
SOURCE_LINEAGE = "lineage"
SOURCE_HUB_ALIAS = "hub_alias"
SOURCE_CLASSIFY_METADATA = "classify_metadata"
SOURCE_KEYWORD_HEURISTIC = "keyword_heuristic"
SOURCE_GLOBAL_FALLBACK = "global_fallback"


@dataclass(frozen=True)
class ScopeResolution:
    """Scope plus the pipeline tier that produced it (explainability)."""

    scope: str
    source: str


def _slugify_scope(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return "global"
    raw = re.sub(r"[`'\"<>]", "", raw)
    raw = re.sub(r"[^a-z0-9._:/-]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-._:/")
    return (raw[:_MAX_SCOPE_LEN].strip("-._:/") or "global")


def _extract_marker(content_text: Optional[str]) -> Optional[str]:
    text = content_text or ""
    for pattern in _MARKER_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _content_tokens(content_text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", content_text.lower()) if len(t) >= 2}


def _term_in_text(term: str, text_lower: str) -> bool:
    term = term.strip().lower()
    if len(term) < _MIN_TERM_LEN:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text_lower) is not None


def _unique_best(scored: Iterable[tuple[str, int]]) -> Optional[str]:
    """Highest-scoring candidate, or None when nothing matched or the top is tied."""
    best: Optional[str] = None
    best_score = 0
    tied = False
    for candidate, score in scored:
        if score <= 0:
            continue
        if score > best_score:
            best, best_score, tied = candidate, score, False
        elif score == best_score and candidate != best:
            tied = True
    return None if tied else best


def _match_lineage_scope(conn: Any, workspace_id: str, content_text: str) -> Optional[str]:
    """Reuse an existing active anchor scope whose slug tokens all appear in the content."""
    tokens = _content_tokens(content_text)
    if not tokens:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT scope
              FROM cb_current_state_anchors
             WHERE workspace_id = %s::uuid
               AND state_status = 'active'
               AND scope <> 'global'
             ORDER BY scope
             LIMIT %s
            """,
            (workspace_id, _MAX_CANDIDATE_ROWS),
        )
        rows = cur.fetchall()

    def score(scope: str) -> int:
        scope_tokens = [t for t in re.split(r"[-._:/]+", scope) if len(t) >= 2]
        if not scope_tokens:
            return 0
        return len(scope_tokens) if all(t in tokens for t in scope_tokens) else 0

    candidates = [str(row[0]) for row in rows if row and row[0]]
    return _unique_best((scope, score(scope)) for scope in candidates)


def _match_hub_scope(conn: Any, workspace_id: str, content_text: str) -> Optional[str]:
    """Match active workspace hubs by title/aliases (strong) and related_terms (weak)."""
    text_lower = content_text.lower()
    if not text_lower.strip():
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT title, aliases, related_terms
              FROM cb_hubs
             WHERE status = 'active'
               AND workspace_uuid = %s::uuid
             ORDER BY title
             LIMIT %s
            """,
            (workspace_id, _MAX_CANDIDATE_ROWS),
        )
        rows = cur.fetchall()

    scored: list[tuple[str, int]] = []
    for row in rows:
        title = str(row[0] or "")
        aliases = [str(a) for a in (row[1] or [])]
        related = [str(r) for r in (row[2] or [])]
        strong = sum(1 for term in [title, *aliases] if _term_in_text(term, text_lower))
        weak = sum(1 for term in related if _term_in_text(term, text_lower))
        if strong >= 1 or weak >= _MIN_WEAK_HITS:
            scored.append((title, strong * 2 + weak))
    matched_title = _unique_best(scored)
    return _slugify_scope(matched_title) if matched_title else None


def resolve_scope(
    conn: Any = None,
    *,
    workspace_id: Optional[str] = None,
    content_text: Optional[str] = None,
    scope_hint: Optional[str] = None,
    project_topic: Optional[str] = None,
    domain_hint: Optional[str] = None,
) -> ScopeResolution:
    """Run the scope resolver pipeline; never raises."""

    if scope_hint and scope_hint.strip():
        return ScopeResolution(scope=_slugify_scope(scope_hint), source=SOURCE_SCOPE_HINT)

    marker = _extract_marker(content_text)
    if marker and marker.strip():
        return ScopeResolution(scope=_slugify_scope(marker), source=SOURCE_MARKER)

    text = (content_text or "").strip()
    if conn is not None and workspace_id and text:
        for tier_fn, source in (
            (_match_lineage_scope, SOURCE_LINEAGE),
            (_match_hub_scope, SOURCE_HUB_ALIAS),
        ):
            try:
                scope = tier_fn(conn, workspace_id, text)
            except Exception as exc:
                logger.warning("[scope_pipeline] %s tier skipped: %s", source, exc)
                scope = None
            if scope and scope != "global":
                return ScopeResolution(scope=scope, source=source)

    if project_topic and project_topic.strip():
        return ScopeResolution(scope=_slugify_scope(project_topic), source=SOURCE_CLASSIFY_METADATA)

    if domain_hint and domain_hint.strip():
        return ScopeResolution(scope=_slugify_scope(domain_hint), source=SOURCE_KEYWORD_HEURISTIC)

    return ScopeResolution(scope="global", source=SOURCE_GLOBAL_FALLBACK)
