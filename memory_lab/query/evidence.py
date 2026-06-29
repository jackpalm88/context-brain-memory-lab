from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from memory_lab.reasoning.models import EvidenceItem


def _clean_snippet(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _score_kind(retrieval_path: str) -> str:
    if "hub" in retrieval_path:
        return "hub_link"
    return "chunk_text_match"


PROVENANCE_METADATA_KEYS = (
    "retrieval_mode",
    "retrieval_path",
    "embedding_status",
    "distance",
    "score_kind",
)


def _provenance_metadata(row: dict[str, Any], *, retrieval_path: str, score_kind: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    existing = row.get("metadata")
    if isinstance(existing, dict):
        metadata.update({k: v for k, v in existing.items() if v is not None})
    enriched = dict(row)
    enriched.setdefault("retrieval_path", retrieval_path)
    enriched.setdefault("score_kind", score_kind)
    for key in PROVENANCE_METADATA_KEYS:
        value = enriched.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def normalize_evidence(results: list[dict[str, Any]], limit: int = 320) -> list["EvidenceItem"]:
    """Map public RetrievalAdapter rows into stable, deduplicated evidence items."""
    # Imported lazily to keep this canonical module free of an import-time cycle
    # with the reasoning package (which re-exports normalize_evidence).
    from memory_lab.reasoning.models import EvidenceItem

    evidence: list[EvidenceItem] = []
    seen_content_ids: set[str] = set()
    rank = 0
    for row in results:
        content_id = str(row.get("content_id") or row.get("id") or "").strip()
        text = str(row.get("text") or row.get("snippet") or "").strip()
        if not content_id or not text:
            continue
        if content_id in seen_content_ids:
            continue
        seen_content_ids.add(content_id)
        rank += 1
        chunk_id = row.get("chunk_id")
        chunk_id_str = str(chunk_id).strip() if chunk_id else None
        retrieval_path = str(row.get("retrieval_path") or "deterministic_db").strip()
        score_kind = str(row.get("score_kind") or _score_kind(retrieval_path)).strip()
        score = row.get("score")
        metadata = _provenance_metadata(row, retrieval_path=retrieval_path, score_kind=score_kind)
        if chunk_id_str:
            evidence_id = f"ev_{content_id}_{chunk_id_str}"
        else:
            evidence_id = f"ev_{content_id}_{retrieval_path}_{rank}"
        evidence.append(
            EvidenceItem(
                evidence_id=evidence_id,
                rank=rank,
                content_id=content_id,
                chunk_id=chunk_id_str,
                snippet=_clean_snippet(text, limit),
                score=float(score) if score is not None else None,
                score_kind=score_kind,
                retrieval_path=retrieval_path,
                source=row.get("source") or row.get("title"),
                title=row.get("title"),
                metadata=metadata or None,
            )
        )
    return evidence
