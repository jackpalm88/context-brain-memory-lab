"""Report-only B15 alias hygiene candidate generation."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Sequence

from .health_models import AliasCandidate, AliasCandidateReport, DEFAULT_NON_CLAIMS, GraphHealthWarning

WARNING_ALIAS_CANDIDATE_REVIEW_REQUIRED = "ALIAS_CANDIDATE_REVIEW_REQUIRED"


class AliasHygieneService:
    """Generate deterministic HITL alias candidates without mutation."""

    def generate_candidates(self, labels: Iterable[str]) -> AliasCandidateReport:
        groups: Dict[str, List[str]] = defaultdict(list)
        for label in labels:
            text = str(label).strip()
            if not text:
                continue
            groups[normalize_entity_name(text)].append(text)

        candidates: List[AliasCandidate] = []
        for norm in sorted(groups):
            unique_terms = sorted(set(groups[norm]), key=lambda s: (s.casefold(), s))
            if len(unique_terms) < 2:
                continue
            candidates.append(
                AliasCandidate(
                    candidate_id=f"alias_candidate:{norm}",
                    terms=unique_terms,
                    candidate_type=_candidate_type(unique_terms),
                    confidence=0.8,
                    evidence=["same_normalized_label"],
                    requires_human_review=True,
                    mutation_allowed=False,
                )
            )

        warnings: List[GraphHealthWarning] = []
        if candidates:
            warnings.append(
                GraphHealthWarning(
                    code=WARNING_ALIAS_CANDIDATE_REVIEW_REQUIRED,
                    message="Alias/canonical candidates are report-only and require HITL review.",
                    affected_node_ids=sorted({term for c in candidates for term in c.terms}),
                )
            )

        return AliasCandidateReport(
            generated_at=datetime.now(timezone.utc),
            candidate_count=len(candidates),
            candidates=candidates,
            warnings=warnings,
            limitations=[] if candidates else ["no_alias_candidates_detected_from_provided_labels"],
            non_claims=DEFAULT_NON_CLAIMS,
        )


def normalize_entity_name(value: str) -> str:
    """Normalize labels deterministically for candidate grouping.

    This is intentionally conservative: it folds case/diacritics, trims common
    punctuation, and collapses whitespace. It does not decide canonical truth.
    """

    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    folded = folded.casefold().strip()
    folded = re.sub(r"[\W_]+", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip()
    return folded


def _candidate_type(terms: Sequence[str]) -> str:
    lowered = {t.casefold() for t in terms}
    normalized = {normalize_entity_name(t) for t in terms}
    if len(lowered) == 1 and len(terms) > 1:
        return "duplicate"
    if len(normalized) == 1:
        return "alias_or_multilingual_variant"
    return "ambiguous"
