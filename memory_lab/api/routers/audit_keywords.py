"""memory_lab/api/routers/audit_keywords.py

DX-3 Part B — Keyword Audit Endpoint.

GET /v1/audit/keywords?limit=N

Returns the top N keywords derived from persisted chunk_text within the
caller's workspace.  Output is deterministic: same DB state → same order.

Algorithm (simple, no ML dependency):
    1. Pull chunk_text for the workspace (via content_items.workspace_id JOIN).
    2. Tokenise: lower-case, alpha-only, split on non-alpha.
    3. Drop English stop-words (built-in list, no NLTK dependency).
    4. Count token frequencies.
    5. Return top-N by (count DESC, token ASC) — ASC tiebreak = deterministic.

Constraints:
    - Read-only; no mutations.
    - Workspace-isolated: only chunks linked to caller's workspace_id.
    - Configurable limit (default 20, max 100).
    - Structured 422 / 503 errors; no raw tracebacks.
    - No new DB tables.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

import psycopg2
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from memory_lab.api.auth_context import AuthContext
from memory_lab.api.config import get_settings
from memory_lab.api.dependencies.auth import require_permission

router = APIRouter(prefix="/v1/audit", tags=["audit"])

# ---------------------------------------------------------------------------
# Stop-words (compact; no external dependency)
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset = frozenset(
    """
    a about above after again against all am an and any are aren't as at be because
    been before being below between both but by can't cannot could couldn't did didn't
    do does doesn't doing don't down during each few for from further get got had hadn't
    has hasn't have haven't having he he'd he'll he's her here here's hers herself him
    himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself
    let's me more most mustn't my myself no nor not of off on once only or other ought
    our ours ourselves out over own same shan't she she'd she'll she's should shouldn't
    so some such than that that's the their theirs them themselves then there there's
    these they they'd they'll they're they've this those through to too under until up
    very was wasn't we we'd we'll we're we've were weren't what what's when when's where
    where's which while who who's whom why why's will with won't would wouldn't you you'd
    you'll you're you've your yours yourself yourselves
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z]+")

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_CHUNK_FETCH_LIMIT = 5_000  # safety cap on rows pulled per request


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class KeywordEntry(BaseModel):
    keyword: str
    count: int


class KeywordAuditResponse(BaseModel):
    workspace_id: str
    limit: int
    total_chunks_scanned: int
    keywords: List[KeywordEntry]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/keywords", response_model=KeywordAuditResponse)
def get_keywords(
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description="Max keywords to return"),
    auth: AuthContext = Depends(require_permission("retrieval.search")),
) -> KeywordAuditResponse:
    settings = get_settings()
    database_url = settings.database_url

    chunks = _fetch_chunks(database_url, auth.workspace_id)
    counter = _count_keywords(chunks)
    top = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]

    return KeywordAuditResponse(
        workspace_id=auth.workspace_id,
        limit=limit,
        total_chunks_scanned=len(chunks),
        keywords=[KeywordEntry(keyword=kw, count=cnt) for kw, cnt in top],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_chunks(database_url: str, workspace_id: str) -> List[str]:
    """Return chunk_text list for workspace, capped at _CHUNK_FETCH_LIMIT rows."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cc.chunk_text
                  FROM content_chunks cc
                  JOIN content_items ci ON ci.content_id = cc.content_id
                 WHERE ci.workspace_id = %s::uuid
                   AND cc.chunk_text IS NOT NULL
                 ORDER BY cc.chunk_id
                 LIMIT %s
                """,
                (workspace_id, _CHUNK_FETCH_LIMIT),
            )
            return [row[0] for row in cur.fetchall()]


def _count_keywords(chunks: List[str]) -> Counter:
    """Tokenise chunks and count non-stop-word tokens of length >= 3."""
    counter: Counter = Counter()
    for text in chunks:
        for token in _TOKEN_RE.findall(text.lower()):
            if len(token) >= 3 and token not in _STOP_WORDS:
                counter[token] += 1
    return counter
