"""Optional semantic enrichment — provider-neutral.

Produces topic and metadata annotations (today: topic_tags / meta_tags) for a
piece of content. The provider is an implementation detail behind LLMBackend;
with no configured provider — or on any provider degradation / failure — it
falls back to a deterministic keyword extractor so the content-save path stays
deterministic and ALWAYS succeeds. Never raises.

This is "optional semantic enrichment", not "tag generation by vendor X": the
contract is the concept (semantic annotations), the model/provider is internal,
and the annotation shape may later carry more than tags without a contract break.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

from memory_lab.providers.llm_backend import LLMBackend, LLMRequest

logger = logging.getLogger(__name__)

MAX_TOPIC_TAGS = 7
MAX_META_TAGS = 3
_MIN_TAG_LEN = 4

# Conceptual metadata markers (vs. free topic annotations). Internal — not a
# public enum; the public contract is simply "topic" vs "metadata" annotations.
META_TAG_PATTERNS = frozenset({
    "milestone", "decision", "principle", "anchor", "evidence", "plan",
    "roadmap", "governance", "audit", "release", "reference", "policy", "note",
})

_JUNK = frozenset({
    "http", "https", "www", "com", "io", "your", "tools", "tool", "mode",
    "linkedin", "subscribe", "cookie", "privacy", "terms", "sign", "signin",
    "login", "log", "click", "share",
})
_URL_CHARS = frozenset("/?#=.")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "was", "are", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "this", "that", "these", "those", "it", "we", "they",
    "you", "ko", "kas", "ir", "un", "vai", "bet", "ari", "tikai", "sis", "tas",
})


@dataclass
class AnnotationResult:
    topic_tags: List[str] = field(default_factory=list)
    meta_tags: List[str] = field(default_factory=list)
    mode: str = "empty"            # "enriched" | "fallback" | "empty"
    warnings: tuple = ()


def sanitize_tags(tags: Optional[List[Any]]) -> List[str]:
    """Lowercase, underscore spaces, drop URL-like/junk/short, dedupe (order kept)."""
    out: List[str] = []
    seen = set()
    for tag in tags or []:
        if not tag:
            continue
        clean = str(tag).lower().strip().replace(" ", "_")
        if len(clean) < _MIN_TAG_LEN:
            continue
        if clean in _JUNK:
            continue
        if any(ch in clean for ch in _URL_CHARS):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _split_topic_meta(tags: List[str]) -> "tuple[List[str], List[str]]":
    topic = [t for t in tags if t not in META_TAG_PATTERNS][:MAX_TOPIC_TAGS]
    meta = [t for t in tags if t in META_TAG_PATTERNS][:MAX_META_TAGS]
    return topic, meta


def _extract_keywords(text: str, top_n: int = 12) -> List[str]:
    """Deterministic keyword fallback: frequency-ranked, stopword/junk filtered."""
    counts: "dict[str, int]" = {}
    for w in re.findall(r"\b\w+\b", (text or "").lower()):
        if len(w) < _MIN_TAG_LEN or w in _STOPWORDS or w in _JUNK or "http" in w:
            continue
        counts[w] = counts.get(w, 0) + 1
    return sorted(counts, key=lambda w: (-counts[w], w))[:top_n]


def annotate(content: Optional[str], *, llm_backend: Optional[LLMBackend] = None,
             domain_hint: Optional[str] = None) -> AnnotationResult:
    """Produce semantic annotations for ``content``. Never raises."""
    text = content or ""
    if not text.strip():
        return AnnotationResult(mode="empty")

    backend = llm_backend if llm_backend is not None else _resolve_backend()
    raw = _enrich_via_provider(text, backend, domain_hint)
    mode = "enriched"
    if raw is None:
        raw = _extract_keywords(text)
        mode = "fallback"

    clean = sanitize_tags(raw)
    if not clean:
        return AnnotationResult(mode="empty")
    topic, meta = _split_topic_meta(clean)
    return AnnotationResult(topic_tags=topic, meta_tags=meta, mode=mode)


def _resolve_backend() -> LLMBackend:
    """Anthropic if a key is present, else a Noop (degraded) backend. Never raises."""
    try:
        from memory_lab.providers.anthropic import AnthropicLLMBackend
        backend = AnthropicLLMBackend()
        if backend.is_configured:
            return backend
    except Exception:
        pass
    from memory_lab.providers.noop import NoopLLMBackend
    return NoopLLMBackend()


def _enrich_via_provider(text: str, backend: Optional[LLMBackend],
                         domain_hint: Optional[str]) -> Optional[List[str]]:
    """Return raw annotation strings from the provider, or None to signal fallback."""
    if backend is None or not getattr(backend, "is_configured", False):
        return None
    try:
        from memory_lab.ingestion.scorer import _is_circuit_open
        if _is_circuit_open():
            return None
    except Exception:
        pass

    # Prompt-injection sanitization consistent with the scorer pattern.
    safe = text[:2000].replace("{", "{{").replace("}", "}}")
    safe_domain = (domain_hint or "")[:100].replace("{", "{{").replace("}", "}}")
    system = (
        "Produce 3-7 concise semantic annotations (topic and metadata) for the content "
        "as a JSON object {\"tags\": [\"...\"]}. Lowercase, underscores for spaces, 4+ chars, "
        "no URLs, no UI/navigation terms."
    )
    prompt = f"Content:\n{safe}\nDomain hint: {safe_domain or '(none)'}\nReturn JSON only."
    try:
        response = backend.complete_json(LLMRequest(prompt=prompt, system=system, max_tokens=150))
    except Exception:
        return None
    if response is None or response.degraded or response.json_data is None:
        return None
    data = response.json_data
    tags = data.get("tags") if isinstance(data, dict) else None
    if not isinstance(tags, list):
        return None
    return [str(t) for t in tags]
