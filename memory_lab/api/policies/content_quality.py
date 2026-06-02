from __future__ import annotations

from typing import Any, Dict, List, Tuple

from memory_lab.api.utils.content_signatures import looks_like_github_ui_chrome, is_placeholder_preview


def is_junk(content: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Deterministic junk detector with explainability.

    Returns:
        (is_junk, reasons)
    """
    reasons: List[str] = []

    full_text = (content.get("full_text") or "")
    strategy = content.get("extraction_strategy")

    # 1) Strong signature helpers (existing behavior)
    if looks_like_github_ui_chrome(full_text):
        reasons.append("github_ui_chrome")

    if is_placeholder_preview(full_text):
        reasons.append("placeholder_preview")

    # 2) Strategy-based junk (hard signal)
    if strategy in ("blocked", "preview", "quarantine"):
        reasons.append(f"strategy:{strategy}")

    return (len(reasons) > 0), reasons


def is_trusted_for_embedding(content: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Stricter filter for embedding backfill.
    Reuses is_junk() and adds quality gates aligned with admin/embed-one guard rails.
    """
    junk, junk_reasons = is_junk(content)
    if junk:
        return False, junk_reasons

    quality_score = content.get("quality_score") or 0
    needs_reextract = bool(content.get("needs_reextract", True))
    word_count = content.get("word_count") or 0

    if quality_score < 6:
        return False, [f"low_quality_score:{quality_score}"]

    if needs_reextract:
        return False, ["needs_reextract_true"]

    if word_count < 200:
        return False, [f"low_word_count:{word_count}"]

    return True, []
