"""Hub term matching — HubTermGraph semantics, verbatim (router v0 ratified #2).

There must never be two local definitions of what a hub/title/alias match
means. This module restates the kernel rule for in-memory hub lists (the
kernel's HubTermGraph applies the same rule inside retrieval); a hermetic
parity test pins the two implementations together.

Rule: a term matches a hub when the lowercased term equals the hub title or
an alias exactly, OR — for single-word terms of length >= 3 — when the term
is a token of the title/alias token sets.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set


def _tokens(term: str) -> Set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", term.lower()) if len(t) >= 3}


def _hub_terms(hub: Dict[str, Any]) -> Set[str]:
    values = [str(hub.get("title") or "")] + [str(a) for a in (hub.get("aliases") or [])]
    return {v.strip().lower() for v in values if v and v.strip()}


def term_matches_hub(term: str, hub: Dict[str, Any]) -> bool:
    needle = term.strip().lower()
    if not needle:
        return False
    terms = _hub_terms(hub)
    if needle in terms:
        return True
    if " " not in needle and len(needle) >= 3:
        return any(needle in _tokens(t) for t in terms)
    return False


def match_hubs(text: str, hubs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Hubs matched by any word of `text` (word-boundary, deterministic order)."""
    words = [w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) >= 3]
    matched = []
    for hub in hubs:
        if any(term_matches_hub(w, hub) for w in words) or term_matches_hub(text, hub):
            matched.append(hub)
    return matched
