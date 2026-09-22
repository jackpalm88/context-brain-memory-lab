"""Canonical-body verified-reconstruction fixture matrix (Patch 1, Phase B).

Provider-free, DB-free. Exercises memory_lab.content.canonical_body against
the fixture matrix from the OpenCB-approved canonical-body plan, amended per
decision 5533831e-c751-434a-8ae7-f8f40cdaf0f8 (verified reconstruction from
content_chunks, not direct storage read).

Every fixture either proves an exact hash-verified reconstruction, or proves
the helper fails closed (unverifiable/unavailable) rather than silently
returning a wrong body.
"""
from __future__ import annotations

import hashlib

import pytest

from memory_lab.content.canonical_body import (
    FIDELITY_HASH_VERIFIED,
    FIDELITY_UNAVAILABLE,
    FIDELITY_UNVERIFIABLE,
    VERSION_MATCH,
    VERSION_MISMATCH,
    VERSION_NOT_CHECKED,
    VERSION_UNKNOWN,
    PersistedChunk,
    check_expected_version,
    diagnose_reconstruction,
    reconstruct_canonical_body,
)
from memory_lab.ingestion.chunking import (
    DEFAULT_OVERLAP_CHARS,
    ChunkerConfig,
    DeterministicContentChunker,
)

pytestmark = [pytest.mark.unit, pytest.mark.public_safe]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. single LF chunk + matching raw hash -> hash-verified
# ---------------------------------------------------------------------------
def test_single_chunk_matching_hash_is_verified():
    text = "a short single-chunk body with no line-ending surprises\nsecond line"
    result = reconstruct_canonical_body(
        [PersistedChunk(0, text)], stored_content_hash=_sha256(text)
    )
    assert result.fidelity == FIDELITY_HASH_VERIFIED
    assert result.candidate == text
    assert result.computed_hash == _sha256(text)


# ---------------------------------------------------------------------------
# 2. single CRLF raw input represented by a normalized chunk -> unverifiable
# ---------------------------------------------------------------------------
def test_crlf_raw_body_with_normalized_chunk_is_unverifiable():
    raw = "line1\r\nline2\r\nline3"
    stored_hash = _sha256(raw)  # production hashes the RAW body, pre-normalization
    normalized_chunk_text = raw.replace("\r\n", "\n").replace("\r", "\n")
    result = reconstruct_canonical_body(
        [PersistedChunk(0, normalized_chunk_text)], stored_content_hash=stored_hash
    )
    assert result.fidelity == FIDELITY_UNVERIFIABLE
    assert result.candidate is None


# ---------------------------------------------------------------------------
# 3. multi-chunk clean reconstruction, round-tripped through the real
#    production chunker (no CR/CRLF, so normalization is a no-op and the
#    stored hash should be recoverable exactly).
# ---------------------------------------------------------------------------
def test_multi_chunk_roundtrip_through_real_chunker_is_verified():
    paragraph = (
        "Deterministic chunking must remain stable across releases so that "
        "verified reconstruction keeps working for historical rows. "
    )
    text = "\n\n".join(f"Paragraph {i}. {paragraph * 3}" for i in range(12))
    chunker = DeterministicContentChunker()
    chunk_result = chunker.chunk_text(text)
    assert len(chunk_result.chunks) > 1, "fixture must actually produce multiple chunks"

    chunks = [PersistedChunk(c.index, c.text) for c in chunk_result.chunks]
    stored_hash = _sha256(text)
    result = reconstruct_canonical_body(chunks, stored_content_hash=stored_hash)

    assert result.fidelity == FIDELITY_HASH_VERIFIED
    assert result.candidate == text
    assert result.computed_hash == stored_hash


# ---------------------------------------------------------------------------
# 4. multi-chunk unambiguous overlap, hand-crafted at the exact configured
#    overlap width -> hash-verified.
# ---------------------------------------------------------------------------
def test_multi_chunk_exact_configured_overlap_is_verified():
    overlap = DEFAULT_OVERLAP_CHARS
    part_a = "X" * 200
    part_b = "Y" * 200
    full = part_a + part_b
    chunk0 = full[: 200 + overlap // 2]  # ends partway into part_b
    chunk1 = full[len(chunk0) - overlap :]  # starts `overlap` chars before chunk0 ends
    assert chunk0[-overlap:] == chunk1[:overlap]

    chunks = [PersistedChunk(0, chunk0), PersistedChunk(1, chunk1)]
    result = reconstruct_canonical_body(chunks, stored_content_hash=_sha256(full))
    assert result.fidelity == FIDELITY_HASH_VERIFIED
    assert result.candidate == full


# ---------------------------------------------------------------------------
# 5. no-overlap / overlap-guard case: a chunk shorter than the configured
#    overlap window, mirroring the chunker's own zero-overlap fallback.
# ---------------------------------------------------------------------------
def test_short_final_chunk_zero_overlap_is_verified():
    chunk0 = "A" * 100
    chunk1 = "B" * 30  # shorter than DEFAULT_OVERLAP_CHARS -> no overlap possible
    full = chunk0 + chunk1
    chunks = [PersistedChunk(0, chunk0), PersistedChunk(1, chunk1)]
    result = reconstruct_canonical_body(chunks, stored_content_hash=_sha256(full))
    assert result.fidelity == FIDELITY_HASH_VERIFIED
    assert result.candidate == full


# ---------------------------------------------------------------------------
# 6. ambiguous / coincidental overlap match -> the naive stitch is wrong,
#    but the final hash gate still fails closed to unverifiable rather than
#    returning the wrong body.
# ---------------------------------------------------------------------------
def test_coincidental_overlap_match_fails_closed_not_silently_wrong():
    overlap = DEFAULT_OVERLAP_CHARS
    # chunk0's tail coincidentally equals chunk1's head (repetitive content),
    # but chunk1 is NOT actually the true continuation of chunk0.
    repeated = "Z" * overlap
    chunk0 = "prefix-" + repeated
    chunk1 = repeated + "-unrelated-suffix-that-was-never-part-of-the-original-body"
    true_original = "prefix-" + repeated + "-this-is-the-real-continuation-nobody-guessed"

    chunks = [PersistedChunk(0, chunk0), PersistedChunk(1, chunk1)]
    result = reconstruct_canonical_body(
        chunks, stored_content_hash=_sha256(true_original)
    )
    assert result.fidelity == FIDELITY_UNVERIFIABLE
    assert result.candidate is None


# ---------------------------------------------------------------------------
# 7 & 9. chunk-index gap / missing chunk -> fail closed
# ---------------------------------------------------------------------------
def test_chunk_index_gap_fails_closed():
    chunks = [PersistedChunk(0, "aaaa"), PersistedChunk(2, "bbbb")]
    result = reconstruct_canonical_body(chunks, stored_content_hash=_sha256("aaaabbbb"))
    assert result.fidelity == FIDELITY_UNVERIFIABLE
    assert result.reason == "chunk_index_gap"
    assert result.candidate is None


# ---------------------------------------------------------------------------
# 8. duplicate chunk index -> fail closed
# ---------------------------------------------------------------------------
def test_duplicate_chunk_index_fails_closed():
    chunks = [PersistedChunk(0, "aaaa"), PersistedChunk(0, "bbbb")]
    result = reconstruct_canonical_body(chunks, stored_content_hash=_sha256("aaaabbbb"))
    assert result.fidelity == FIDELITY_UNVERIFIABLE
    assert result.reason == "duplicate_chunk_index"
    assert result.candidate is None


# ---------------------------------------------------------------------------
# 10. plain hash mismatch, no structural issue -> unverifiable
# ---------------------------------------------------------------------------
def test_plain_hash_mismatch_is_unverifiable():
    chunks = [PersistedChunk(0, "the actual persisted text")]
    result = reconstruct_canonical_body(
        chunks, stored_content_hash=_sha256("a completely different original body")
    )
    assert result.fidelity == FIDELITY_UNVERIFIABLE
    assert result.reason == "hash_mismatch"
    assert result.candidate is None


# ---------------------------------------------------------------------------
# 11. chunk count at/near the max-chunk guard + mismatch -> unverifiable,
#     with a diagnostic (never asserted as fact) reason.
# ---------------------------------------------------------------------------
def test_max_chunk_guard_mismatch_flags_possible_truncation_diagnostic_only():
    guard = 5
    chunks = [PersistedChunk(i, f"chunk-{i}-") for i in range(guard)]
    result = reconstruct_canonical_body(
        chunks,
        stored_content_hash=_sha256("this will not match the stitched candidate"),
        max_chunks_guard=guard,
    )
    assert result.fidelity == FIDELITY_UNVERIFIABLE
    assert result.reason == "hash_mismatch_possible_max_chunk_truncation"
    assert result.candidate is None


# ---------------------------------------------------------------------------
# 12. "raw fallback chunk-0" case: a single persisted chunk at index 0 whose
#     exact raw hash matches -> hash-verified (same code path as case 1,
#     named explicitly because the create-path's empty-chunker fallback
#     writes a single chunk-0 row too).
# ---------------------------------------------------------------------------
def test_single_fallback_chunk_zero_with_matching_hash_is_verified():
    text = "fallback raw chunk-0 tuple text"
    chunks = [PersistedChunk(0, text)]
    result = reconstruct_canonical_body(chunks, stored_content_hash=_sha256(text))
    assert result.fidelity == FIDELITY_HASH_VERIFIED
    assert result.candidate == text


# ---------------------------------------------------------------------------
# 13. empty-body behavior, explicitly decided and tested.
# ---------------------------------------------------------------------------
def test_empty_body_with_matching_empty_hash_is_verified():
    result = reconstruct_canonical_body([], stored_content_hash=_sha256(""))
    assert result.fidelity == FIDELITY_HASH_VERIFIED
    assert result.candidate == ""


def test_no_chunks_with_non_empty_hash_is_unavailable():
    result = reconstruct_canonical_body([], stored_content_hash=_sha256("something"))
    assert result.fidelity == FIDELITY_UNAVAILABLE
    assert result.candidate is None


def test_no_chunks_and_no_stored_hash_is_unavailable():
    result = reconstruct_canonical_body([], stored_content_hash=None)
    assert result.fidelity == FIDELITY_UNAVAILABLE
    assert result.candidate is None


def test_missing_stored_hash_with_chunks_present_is_unavailable():
    result = reconstruct_canonical_body(
        [PersistedChunk(0, "some text")], stored_content_hash=None
    )
    assert result.fidelity == FIDELITY_UNAVAILABLE
    assert result.reason == "missing_stored_content_hash"
    assert result.candidate is None


# ---------------------------------------------------------------------------
# 14. the normal result never exposes a non-verified candidate as body.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "chunks,stored_hash",
    [
        ([PersistedChunk(0, "aaaa"), PersistedChunk(2, "bbbb")], _sha256("aaaabbbb")),
        ([PersistedChunk(0, "aaaa"), PersistedChunk(0, "bbbb")], _sha256("aaaabbbb")),
        ([PersistedChunk(0, "text")], _sha256("different")),
        ([], _sha256("nonempty")),
        ([], None),
    ],
)
def test_candidate_is_never_populated_unless_hash_verified(chunks, stored_hash):
    result = reconstruct_canonical_body(chunks, stored_content_hash=stored_hash)
    assert result.fidelity != FIDELITY_HASH_VERIFIED
    assert result.candidate is None


# ---------------------------------------------------------------------------
# diagnose_reconstruction: probe-only view, proves normalization loss only
# from a bounded, explicit alternate-representation hash match.
# ---------------------------------------------------------------------------
def test_diagnostics_proves_bounded_line_ending_normalization_loss():
    raw = "line1\r\nline2\r\nline3"
    stored_hash = _sha256(raw)
    normalized_chunk_text = raw.replace("\r\n", "\n").replace("\r", "\n")
    diag = diagnose_reconstruction(
        [PersistedChunk(0, normalized_chunk_text)], stored_content_hash=stored_hash
    )
    assert diag.fidelity == FIDELITY_UNVERIFIABLE
    assert diag.possible_line_ending_normalization is True


def test_diagnostics_does_not_claim_normalization_when_unproven():
    diag = diagnose_reconstruction(
        [PersistedChunk(0, "persisted text")],
        stored_content_hash=_sha256("a genuinely different original body"),
    )
    assert diag.fidelity == FIDELITY_UNVERIFIABLE
    assert diag.possible_line_ending_normalization is False


# ---------------------------------------------------------------------------
# check_expected_version (Patch 1.1) fixture matrix.
# ---------------------------------------------------------------------------
def test_version_not_checked_when_expected_version_absent():
    result = check_expected_version(_sha256("body"), None)
    assert result.status == VERSION_NOT_CHECKED
    assert result.blocks is False
    assert result.current_version == _sha256("body")


def test_version_match_when_equal_to_stored_hash():
    h = _sha256("body")
    result = check_expected_version(h, h)
    assert result.status == VERSION_MATCH
    assert result.blocks is False


def test_version_mismatch_when_different_from_stored_hash():
    result = check_expected_version(_sha256("body"), _sha256("a different body"))
    assert result.status == VERSION_MISMATCH
    assert result.blocks is True
    assert result.expected_version == _sha256("a different body")
    assert result.current_version == _sha256("body")


def test_version_unknown_when_no_stored_hash_but_expected_version_given():
    result = check_expected_version(None, _sha256("something"))
    assert result.status == VERSION_UNKNOWN
    assert result.blocks is True
    assert result.current_version is None
