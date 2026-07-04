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
    "hub_match",
    "graph_match",
    "knowledge_path",
    "retrieval_reason",
    "ranking_reason",
    "score_components",
    "result_trust",
    "source_path",
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


def _retrieval_reason(row: dict[str, Any], *, retrieval_path: str) -> str:
    explicit = row.get("retrieval_reason")
    if explicit:
        return str(explicit)
    if retrieval_path == "content_chunk_workspace_scoped":
        return "Matched chunk text in workspace-scoped deterministic retrieval."
    if retrieval_path == "hub_link_workspace_scoped":
        return "Included through workspace-scoped hub-linked content provenance."
    if retrieval_path == "pgvector_knn":
        return "Matched by pgvector nearest-neighbor retrieval."
    if retrieval_path == "deterministic_fallback":
        return "Matched by deterministic fallback retrieval after provider/vector search was unavailable."
    return f"Matched through retrieval path: {retrieval_path}."


def _ranking_reason(row: dict[str, Any]) -> str:
    explicit = row.get("ranking_reason")
    if explicit:
        return str(explicit)
    return "Rank preserves the existing retrieval adapter order; diagnostics did not rerank."


def _knowledge_path(row: dict[str, Any], *, content_id: str, chunk_id: str | None, retrieval_path: str) -> list[Any]:
    explicit = row.get("knowledge_path")
    if isinstance(explicit, list):
        return explicit
    path: list[Any] = [{"type": "retrieval_path", "value": retrieval_path}]
    hub_match = row.get("hub_match")
    if hub_match is not None:
        path.append({"type": "hub", "value": hub_match})
    graph_match = row.get("graph_match")
    if graph_match is not None:
        path.append({"type": "graph", "value": graph_match})
    path.append({"type": "content", "value": content_id})
    if chunk_id:
        path.append({"type": "chunk", "value": chunk_id})
    return path


def _score_components(row: dict[str, Any], *, score: Any, score_kind: str, retrieval_path: str) -> dict[str, Any]:
    explicit = row.get("score_components")
    if isinstance(explicit, dict):
        return {k: v for k, v in explicit.items() if v is not None}
    components: dict[str, Any] = {
        "score_kind": score_kind,
        "retrieval_path": retrieval_path,
        "diagnostic_only": True,
    }
    if score is not None:
        components["score"] = float(score)
    if row.get("distance") is not None:
        components["distance"] = float(row["distance"])
    return components


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
                retrieval_reason=_retrieval_reason(row, retrieval_path=retrieval_path),
                ranking_reason=_ranking_reason(row),
                hub_match=row.get("hub_match"),
                graph_match=row.get("graph_match"),
                knowledge_path=_knowledge_path(
                    row,
                    content_id=content_id,
                    chunk_id=chunk_id_str,
                    retrieval_path=retrieval_path,
                ),
                score_components=_score_components(
                    row,
                    score=score,
                    score_kind=score_kind,
                    retrieval_path=retrieval_path,
                ),
                distance=float(row["distance"]) if row.get("distance") is not None else None,
                confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
                result_trust=row.get("result_trust"),
                source_path=row.get("source_path"),
            )
        )
    return evidence
