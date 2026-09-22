"""Provider-free canonical-body reconstruction (Patch 1, verified-reconstruction MVP).

OpenCB decision 00393c53-1056-4178-9a68-e16d583387ba found that the ratified
canonical-body read contract (get_canonical_body_verified) assumes an
authoritative stored raw body, but the live /opt/cbml write path
(memory_lab/api/services/api_adapter.py::create_content_minimal) never writes
one: content_items carries only content_hash, and the body exists solely as
normalized content_chunks rows. OpenCB decision
5533831e-c751-434a-8ae7-f8f40cdaf0f8 amended the approach for the existing
corpus accordingly: reconstruct the body from persisted chunks and promote it
to canonical only when it hash-matches the stored content_hash exactly.
Otherwise fail closed. This module implements that reconstruction; it has no
DB, FastAPI, or provider dependency, and does not decide authorization,
versioning, or the public response shape (those belong to the read-path
seam this helper is built for, not yet authorized).

Fidelity states:
  hash-verified  -- candidate's sha256 matches the stored content_hash exactly.
                    This is the only state that proves exact raw-body fidelity.
  unverifiable   -- chunk evidence exists but exact raw body cannot be proven
                    (hash mismatch, or chunk structure fails validation).
  unavailable    -- no usable body evidence exists at all (no chunks, no hash).

A candidate body is never exposed as `body` unless fidelity is
hash-verified -- ReconstructionResult.candidate is None in every other case.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional, Sequence

from memory_lab.ingestion.chunking import (
    DEFAULT_MAX_CHUNKS_PER_ITEM,
    DEFAULT_OVERLAP_CHARS,
)

FIDELITY_HASH_VERIFIED = "hash-verified"
FIDELITY_UNVERIFIABLE = "unverifiable"
FIDELITY_UNAVAILABLE = "unavailable"

# What content_hash actually covers on this repository's write path (M10.2):
# sha256 of the raw UTF-8 submitted body, computed before deterministic
# chunking. Chunking normalizes CRLF/CR to LF, so a body that originally
# contained CR/CRLF cannot hash-verify from chunk text alone -- it will
# correctly resolve to `unverifiable`, not a false match.
HASH_SEMANTICS = "sha256(raw_submitted_body.encode('utf-8')); no normalization at hash time"


@dataclass(frozen=True)
class PersistedChunk:
    """One content_chunks row's relevant fields, cursor/backend-agnostic."""

    index: int
    text: str


@dataclass(frozen=True)
class ReconstructionResult:
    """Outcome of a reconstruction attempt.

    Internal/diagnostic detail (``reason``) may be richer than whatever a
    public API surface built on top of this later chooses to expose.
    """

    candidate: Optional[str]
    fidelity: str
    reason: str
    computed_hash: Optional[str]


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_index_set(chunks: Sequence[PersistedChunk]) -> Optional[str]:
    """Fail-closed structural check. Returns a reason string, or None if sound."""
    indices = [c.index for c in chunks]
    if len(indices) != len(set(indices)):
        return "duplicate_chunk_index"
    if sorted(indices) != list(range(len(indices))):
        return "chunk_index_gap"
    return None


def _stitch(ordered_texts: Sequence[str], *, overlap_chars: int) -> str:
    """Deterministically stitch ordered chunk texts into one candidate body.

    Mirrors DeterministicContentChunker's write-time behavior: consecutive
    chunks overlap by exactly ``overlap_chars``, except when a chunk is too
    short for that overlap window, in which case the chunker itself falls
    back to zero overlap (next_start == end). This function does not invent
    a separator in either case. It does not need to *prove* the overlap
    choice is correct -- ``reconstruct_canonical_body`` only ever promotes
    the result to hash-verified when the final sha256 matches exactly, so a
    wrong stitch choice fails closed to unverifiable rather than silently
    returning a wrong body.
    """
    if not ordered_texts:
        return ""
    result = ordered_texts[0]
    for text in ordered_texts[1:]:
        if (
            overlap_chars > 0
            and len(result) >= overlap_chars
            and len(text) >= overlap_chars
            and result[-overlap_chars:] == text[:overlap_chars]
        ):
            result = result + text[overlap_chars:]
        else:
            result = result + text
    return result


def reconstruct_canonical_body(
    chunks: Sequence[PersistedChunk],
    stored_content_hash: Optional[str],
    *,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    max_chunks_guard: int = DEFAULT_MAX_CHUNKS_PER_ITEM,
) -> ReconstructionResult:
    """Attempt exact, fail-closed reconstruction of a body from persisted chunks.

    Never returns ``hash-verified`` without an exact SHA-256 match against
    ``stored_content_hash``. Missing/malformed chunk evidence, or a hash that
    fails to verify, always resolves to ``unverifiable`` or ``unavailable``.
    """
    if stored_content_hash is None:
        return ReconstructionResult(None, FIDELITY_UNAVAILABLE, "missing_stored_content_hash", None)

    if not chunks:
        empty_hash = _sha256_hex("")
        if stored_content_hash == empty_hash:
            return ReconstructionResult("", FIDELITY_HASH_VERIFIED, "empty_body_hash_match", empty_hash)
        return ReconstructionResult(None, FIDELITY_UNAVAILABLE, "no_persisted_chunks", None)

    invalid_reason = _validate_index_set(chunks)
    if invalid_reason is not None:
        return ReconstructionResult(None, FIDELITY_UNVERIFIABLE, invalid_reason, None)

    ordered = [c.text for c in sorted(chunks, key=lambda c: c.index)]
    candidate = _stitch(ordered, overlap_chars=overlap_chars)
    computed = _sha256_hex(candidate)

    if computed == stored_content_hash:
        return ReconstructionResult(candidate, FIDELITY_HASH_VERIFIED, "verified_reconstruction", computed)

    # Diagnostic-only signal, never asserted as fact: reaching the configured
    # max-chunk guard is consistent with truncation but is not proof of it,
    # since guard state is not persisted alongside the chunks.
    reason = "hash_mismatch"
    if len(chunks) >= max_chunks_guard:
        reason = "hash_mismatch_possible_max_chunk_truncation"
    return ReconstructionResult(None, FIDELITY_UNVERIFIABLE, reason, computed)


# ---------------------------------------------------------------------------
# expected_version (Patch 1.1, decision b97a9f74-2d8c-4427-af46-4780aa9ce986).
#
# There is no dedicated version column on content_items. content_hash IS the
# body's version identity in this system: it is set once at write time
# (M10.2) and the primary write path never updates it. A caller-supplied
# expected_version is therefore checked directly against the stored
# content_hash -- a body-level optimistic-concurrency check, deliberately
# separate from fidelity (fidelity answers "can this body be proven exact";
# this answers "is it still the version you last saw"). Checked BEFORE any
# reconstruction is attempted, so a mismatch never pays for chunk work.
# ---------------------------------------------------------------------------

VERSION_NOT_CHECKED = "not_checked"
VERSION_MATCH = "match"
VERSION_MISMATCH = "mismatch"
VERSION_UNKNOWN = "version_unknown"


@dataclass(frozen=True)
class VersionCheckResult:
    status: str  # not_checked | match | mismatch | version_unknown
    expected_version: Optional[str]
    current_version: Optional[str]

    @property
    def blocks(self) -> bool:
        """True when this result must short-circuit reconstruction (fail closed)."""
        return self.status in (VERSION_MISMATCH, VERSION_UNKNOWN)


def check_expected_version(
    stored_content_hash: Optional[str], expected_version: Optional[str]
) -> VersionCheckResult:
    """expected_version absent -> not_checked (today's behavior, unchanged).

    Present but stored_content_hash is None -> version_unknown (fail closed;
    there is nothing to compare against). Present and equal -> match. Present
    and different -> mismatch. Callers must not attempt reconstruction when
    `.blocks` is True.
    """
    if expected_version is None:
        return VersionCheckResult(VERSION_NOT_CHECKED, None, stored_content_hash)
    if stored_content_hash is None:
        return VersionCheckResult(VERSION_UNKNOWN, expected_version, None)
    if expected_version == stored_content_hash:
        return VersionCheckResult(VERSION_MATCH, expected_version, stored_content_hash)
    return VersionCheckResult(VERSION_MISMATCH, expected_version, stored_content_hash)


# ---------------------------------------------------------------------------
# Probe-only diagnostics.
#
# The public ReconstructionResult intentionally hides the candidate body
# whenever fidelity is not hash-verified (see module docstring / Phase B
# fixture 14). The read-only live coverage probe still needs the stitched
# candidate internally to classify *why* verification failed (e.g. bounded,
# proven line-ending normalization loss) -- but it must never print body
# text, only aggregate counts. ReconstructionDiagnostics is that separate,
# richer, probe-only view; it must never be wired into a public API response.
# ---------------------------------------------------------------------------

_LINE_ENDING_VARIANTS = (
    lambda s: s.replace("\n", "\r\n"),
    lambda s: s.replace("\n", "\r"),
)


@dataclass(frozen=True)
class ReconstructionDiagnostics:
    fidelity: str
    reason: str
    candidate: Optional[str]  # populated even when not hash-verified -- probe-only
    computed_hash: Optional[str]
    possible_line_ending_normalization: bool


def diagnose_reconstruction(
    chunks: Sequence[PersistedChunk],
    stored_content_hash: Optional[str],
    *,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    max_chunks_guard: int = DEFAULT_MAX_CHUNKS_PER_ITEM,
) -> ReconstructionDiagnostics:
    result = reconstruct_canonical_body(
        chunks,
        stored_content_hash,
        overlap_chars=overlap_chars,
        max_chunks_guard=max_chunks_guard,
    )
    if result.fidelity == FIDELITY_HASH_VERIFIED:
        return ReconstructionDiagnostics(
            result.fidelity, result.reason, result.candidate, result.computed_hash, False
        )
    if not chunks or stored_content_hash is None or _validate_index_set(chunks) is not None:
        return ReconstructionDiagnostics(result.fidelity, result.reason, None, None, False)

    ordered = [c.text for c in sorted(chunks, key=lambda c: c.index)]
    candidate = _stitch(ordered, overlap_chars=overlap_chars)
    possible_normalization = any(
        _sha256_hex(variant(candidate)) == stored_content_hash for variant in _LINE_ENDING_VARIANTS
    )
    return ReconstructionDiagnostics(
        result.fidelity, result.reason, candidate, _sha256_hex(candidate), possible_normalization
    )
