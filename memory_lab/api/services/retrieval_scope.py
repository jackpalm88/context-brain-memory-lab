"""memory_lab/api/services/retrieval_scope.py

First-class scoped retrieval primitive (docs/DESIGN_SCOPED_RETRIEVAL.md, Option B).

RetrievalScope is the caller-supplied, pre-scoring candidate-set restriction shared
by the REST retrieval request (RetrievalRequest.retrieval_scope) and the ask request
(AskRequest.retrieval_scope). It wraps two axes, both backed by schema that already
exists and is already indexed:

    allowed_hubs   — restrict candidates to content linked (via cb_hub_content) to
                      one of these hub ids.
    content_types  — restrict candidates by memory_type; semantically identical to
                      the pre-existing memory_type/memory_types filter, expressed
                      inside the scope envelope so a caller can combine "these hubs"
                      and "these memory types" as one contract.

subject_scope and policy_scope are reserved names for future axes with no backing
persistence; they are intentionally NOT implemented here (design doc §8).

Absent (None) retrieval_scope must not change behavior for any existing caller —
this model is purely additive.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from memory_lab.ingestion.classify_pipeline import MEMORY_TYPE_VALUES


class RetrievalScope(BaseModel):
    """Optional, additive pre-scoring candidate-set restriction. See module docstring."""

    allowed_hubs: Optional[List[str]] = Field(
        default=None,
        description="Restrict candidates to content linked (via cb_hub_content) to one of these hub ids.",
    )
    content_types: Optional[List[str]] = Field(
        default=None,
        description="Restrict candidates by memory_type. Same semantics as the legacy memory_type/memory_types filter.",
    )

    @model_validator(mode="after")
    def _validate(self):
        if self.allowed_hubs is not None and len(self.allowed_hubs) == 0:
            raise ValueError("retrieval_scope.allowed_hubs must not be empty when provided.")
        if self.content_types is not None:
            if len(self.content_types) == 0:
                raise ValueError("retrieval_scope.content_types must not be empty when provided.")
            invalid = [v for v in self.content_types if v not in MEMORY_TYPE_VALUES]
            if invalid:
                raise ValueError(
                    f"Unknown retrieval_scope.content_types value(s): {sorted(invalid)!r}. "
                    f"Allowed: {sorted(MEMORY_TYPE_VALUES)!r}"
                )
        return self


def validate_scope_vs_legacy_content_types(
    legacy: Optional[List[str]], scoped: Optional[List[str]]
) -> None:
    """Raise ValueError if legacy memory_type(s) and retrieval_scope.content_types name
    different sets. Equivalent constraints (same set, any order/duplication) may coexist."""
    if legacy is not None and scoped is not None and set(legacy) != set(scoped):
        raise ValueError(
            "retrieval_scope.content_types conflicts with memory_type/memory_types. "
            "Provide equivalent values or supply only one."
        )


def resolve_content_types(
    legacy: Optional[List[str]], scoped: Optional[List[str]]
) -> Optional[List[str]]:
    """Merge legacy memory_type(s) and retrieval_scope.content_types into one effective
    filter. Caller must have already validated the two do not conflict."""
    return scoped if scoped is not None else legacy
