"""Canonical internal query/evidence layer.

Provider-free, DB-free helpers that normalize public RetrievalAdapter rows into
the stable evidence contract shared by the ask, reasoning, and context-pack read
surfaces. This module is the neutral owner of evidence normalization; callers in
``memory_lab.reasoning`` re-export from here for backwards compatibility.
"""

from .evidence import normalize_evidence

__all__ = [
    "normalize_evidence",
]
