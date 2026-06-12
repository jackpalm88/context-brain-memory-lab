"""B11 deterministic conflict/counterfinding candidates.

Computed candidates only: no persistence, no provider calls, no truth arbitration.
"""
from memory_lab.conflicts.models import ConflictCandidate, ConflictEvidenceRef, ConflictSearchResponse

__all__ = ["ConflictCandidate", "ConflictEvidenceRef", "ConflictSearchResponse"]
