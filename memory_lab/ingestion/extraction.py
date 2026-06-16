"""Deterministic public-safe content extraction for local ingestion inputs.

B17 intentionally introduced a noop extractor. B18 adds a real but bounded
extractor that operates only on caller-supplied text. It performs no URL
fetching, HTTP access, provider use, DB/private Context Brain access, embedding
work, vector search, or mutation. The implementation is deliberately mechanical:
line-ending normalization, basic HTML-ish cleanup, markdown-ish structure
preservation, and deterministic field extraction from visible local text.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import re
from typing import Mapping, Sequence

from memory_lab.ingestion.interfaces import (
    DEFAULT_LIMITATIONS,
    SYNTHETIC_DATA_SOURCE,
    ContentExtractionResult,
    IngestionTextInput,
)

NOOP_EXTRACTOR_MODE = "noop_extractor_v1"
DETERMINISTIC_EXTRACTOR_MODE = "deterministic_extractor_v1"

NOOP_EXTRACTOR_LIMITATIONS: Sequence[str] = DEFAULT_LIMITATIONS + (
    "noop content extractor only",
    "no real content extraction",
    "no semantic extraction",
    "no entity extraction",
    "no fact extraction",
    "no summarization",
    "no document parsing beyond supplied text",
    "no provider calls",
    "no DB/private Context Brain access",
    "no embeddings or vector operations",
)

DETERMINISTIC_EXTRACTOR_LIMITATIONS: Sequence[str] = DEFAULT_LIMITATIONS + (
    "deterministic local-text extraction only",
    "caller-supplied text only",
    "basic HTML and markdown structure cleanup only",
    "no URL fetching",
    "no HTTP access",
    "no DB/private Context Brain access",
    "no embeddings or vector operations",
    "no semantic understanding claim",
    "no entity/fact/summarization claim",
)

_BLOCK_TAG_RE = re.compile(r"</?(?:article|aside|blockquote|br|div|h[1-6]|header|footer|li|main|p|section|table|tr|ul|ol)[^>]*>", re.I)
_STRIP_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<\s*(script|style|noscript|svg)\b[^>]*>.*?<\s*/\s*\1\s*>", re.I | re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_LINK_RE = re.compile(r"\bhttps?://[^\s<>)\]]+", re.I)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
_KEY_VALUE_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _/-]{1,48})\s*:\s*(.+?)\s*$")
_INLINE_KEY_VALUE_RE = re.compile(r"\b([A-Z][A-Za-z0-9 _/-]{1,48})\s*:\s*([^:\n.]+(?:\.[^A-Z:\n][^:\n.]*)?)")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _normalize_line_endings(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _htmlish_to_text(text: str) -> str:
    cleaned = _COMMENT_RE.sub("\n", text)
    cleaned = _SCRIPT_STYLE_RE.sub("\n", cleaned)
    cleaned = re.sub(r"<\s*li\b[^>]*>", "\n- ", cleaned, flags=re.I)
    cleaned = _BLOCK_TAG_RE.sub("\n", cleaned)
    cleaned = _STRIP_TAG_RE.sub("", cleaned)
    return unescape(cleaned)


def _clean_visible_text(text: str) -> str:
    text = _normalize_line_endings(text)
    if "<" in text and ">" in text:
        text = _htmlish_to_text(text)
    else:
        text = unescape(text)
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def _collect_headings(text: str) -> tuple[str, ...]:
    headings: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            headings.append(match.group(1).strip())
        elif line.endswith(":") and 2 <= len(line.split()) <= 8:
            headings.append(line[:-1].strip())
    return tuple(dict.fromkeys(item for item in headings if item))


def _collect_bullets(text: str) -> tuple[str, ...]:
    bullets: list[str] = []
    for line in text.splitlines():
        match = _BULLET_RE.match(line)
        if match:
            bullets.append(match.group(1).strip())
    return tuple(bullets)


def _collect_key_values(text: str) -> Mapping[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _KEY_VALUE_LINE_RE.match(line)
        if match and line.count(":") == 1:
            values[match.group(1).strip().lower().replace(" ", "_")] = match.group(2).strip()
    for segment in re.split(r"\.\s+", text):
        match = _KEY_VALUE_LINE_RE.match(segment.strip().rstrip("."))
        if match:
            key = match.group(1).strip().lower().replace(" ", "_")
            values.setdefault(key, match.group(2).strip().rstrip("."))
    return values


def _length_class(text: str) -> str:
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    if not words:
        return "empty"
    if len(words) < 40:
        return "short"
    if len(words) < 160:
        return "medium"
    return "long"


def _content_kind(text: str, headings: Sequence[str], bullets: Sequence[str], key_values: Mapping[str, str]) -> str:
    if not text.strip():
        return "empty"
    if key_values:
        return "key_value_note"
    if headings and bullets:
        return "structured_markdown_note"
    if headings:
        return "sectioned_note"
    if bullets:
        return "list_note"
    if "\n\n" in text or _length_class(text) in {"medium", "long"}:
        return "memo"
    return "short_note"


def _title_candidate(item: IngestionTextInput, text: str, headings: Sequence[str]) -> str:
    if item.title.strip():
        return item.title.strip()
    if headings:
        return headings[0]
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def _confidence(text: str, fields: Mapping[str, object]) -> float:
    if not text.strip():
        return 0.0
    score = 0.58
    if fields.get("headings"):
        score += 0.08
    if fields.get("bullets"):
        score += 0.08
    if fields.get("key_values"):
        score += 0.12
    if fields.get("links"):
        score += 0.04
    return min(round(score, 2), 0.86)


@dataclass(frozen=True)
class NoopContentExtractor:
    """Deterministic noop/identity content extractor retained for B17 regressions."""

    mode: str = NOOP_EXTRACTOR_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = NOOP_EXTRACTOR_LIMITATIONS

    def extract_content(self, item: IngestionTextInput) -> ContentExtractionResult:
        """Return a degraded noop extraction result for supplied in-memory text."""

        extracted_text = "" if item.text.strip() == "" else item.text
        return ContentExtractionResult(
            extracted_text=extracted_text,
            fields={},
            confidence=0.0,
            rationale="noop extractor preserves caller-supplied text only",
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            degraded=True,
            limitations=self.limitations,
        )


@dataclass(frozen=True)
class DeterministicContentExtractor:
    """Public-safe deterministic extractor for caller-supplied local text."""

    mode: str = DETERMINISTIC_EXTRACTOR_MODE
    data_source: str = SYNTHETIC_DATA_SOURCE
    limitations: Sequence[str] = DETERMINISTIC_EXTRACTOR_LIMITATIONS

    def extract_content(self, item: IngestionTextInput) -> ContentExtractionResult:
        extracted_text = _clean_visible_text(item.text)
        if not extracted_text:
            return ContentExtractionResult(
                extracted_text="",
                fields={
                    "title_candidate": item.title.strip(),
                    "headings": (),
                    "bullets": (),
                    "key_values": {},
                    "links": (),
                    "length_class": "empty",
                    "content_kind_hint": "empty",
                },
                confidence=0.0,
                rationale="deterministic extractor found no meaningful caller-supplied text",
                mode=self.mode,
                data_source=item.data_source or self.data_source,
                degraded=True,
                limitations=self.limitations,
            )

        headings = _collect_headings(extracted_text)
        bullets = _collect_bullets(extracted_text)
        key_values = _collect_key_values(extracted_text)
        links = tuple(dict.fromkeys(_LINK_RE.findall(extracted_text)))
        fields: Mapping[str, object] = {
            "title_candidate": _title_candidate(item, extracted_text, headings),
            "headings": headings,
            "bullets": bullets,
            "key_values": key_values,
            "links": links,
            "length_class": _length_class(extracted_text),
            "content_kind_hint": _content_kind(extracted_text, headings, bullets, key_values),
        }
        return ContentExtractionResult(
            extracted_text=extracted_text,
            fields=fields,
            confidence=_confidence(extracted_text, fields),
            rationale="deterministic local-text extraction from caller-supplied content",
            mode=self.mode,
            data_source=item.data_source or self.data_source,
            degraded=False,
            limitations=self.limitations,
        )


def make_noop_content_extractor(
    *,
    mode: str = NOOP_EXTRACTOR_MODE,
    data_source: str = SYNTHETIC_DATA_SOURCE,
    limitations: Sequence[str] = NOOP_EXTRACTOR_LIMITATIONS,
) -> NoopContentExtractor:
    """Create a deterministic noop content extractor with boundary defaults."""

    return NoopContentExtractor(mode=mode, data_source=data_source, limitations=limitations)


def make_deterministic_content_extractor(
    *,
    mode: str = DETERMINISTIC_EXTRACTOR_MODE,
    data_source: str = SYNTHETIC_DATA_SOURCE,
    limitations: Sequence[str] = DETERMINISTIC_EXTRACTOR_LIMITATIONS,
) -> DeterministicContentExtractor:
    """Create a deterministic public-safe content extractor."""

    return DeterministicContentExtractor(mode=mode, data_source=data_source, limitations=limitations)
