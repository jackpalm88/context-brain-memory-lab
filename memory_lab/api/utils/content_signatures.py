from __future__ import annotations

import hashlib

def looks_like_github_ui_chrome(text: str) -> bool:
    """
    Check if text looks like GitHub UI chrome rather than actual content.
    (Moved from main.py to avoid circular imports and allow reuse in policy layer.)
    """
    if not text:
        return True

    t = text.lower()

    # HTML content detection (strong signal) - check at start to avoid false positives
    t_stripped = t.lstrip()
    if t_stripped.startswith("<!doctype") or t_stripped.startswith("<html"):
        return True

    # very strong signals (keep specific — "sign in" alone is too broad,
    # e.g. README docs say "sign in to <service>")
    strong = [
        "you must be signed in",
        "notification settings",
    ]
    if any(s in t for s in strong):
        return True

    # weaker UI terms; only check in first 1000 chars where UI chrome lives,
    # not in full content (README docs often mention these terms legitimately)
    t_head = t[:1000]
    weak = [
        "notifications",
        "pull requests",
        "branches",
        "tags",
        "activity",
    ]
    hits = sum(1 for w in weak if w in t_head)
    return hits >= 3


def is_placeholder_preview(text: str) -> bool:
    """
    Check if content preview is a placeholder that shouldn't be used for deduplication.
    (Moved from main.py to avoid circular imports and allow reuse in policy layer.)
    """
    if not text:
        return True

    text_stripped = text.strip()
    if not text_stripped:
        return True

    # Check for very short previews
    if len(text_stripped) < 30:
        return True

    # Check for common placeholder values (case-insensitive)
    placeholder_values = {
        "no-preview", "no preview", "preview not available",
        "loading...", "loading", "...", "n/a", "na", "none",
        "placeholder", "coming soon", "tbd", "to be determined",
    }

    return text_stripped.lower() in placeholder_values


def compute_content_hash(text: str | None) -> str:
    """SHA-256 hex of the raw content body, for content-level deduplication.

    Matches production compute_content_hash exactly (no normalization).
    None is treated as empty so the hash is always well-defined.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
