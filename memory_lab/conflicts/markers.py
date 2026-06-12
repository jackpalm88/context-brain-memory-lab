"""Deterministic marker parsing for B11 conflict candidates.

No provider calls, no semantic expansion, no truth arbitration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

COUNTERFINDING_MARKERS = {"counterfinding", "rejected", "reason_rejected", "reversal", "reversed"}
CONTRADICTION_MARKERS = {"contradicts", "conflicts_with"}
SUPPORT_MARKERS = {"supports", "confirmed", "evidence_for", "implemented"}
SCOPE_MARKERS = {"current_state_scope", "scope"}
ALL_LINE_MARKERS = COUNTERFINDING_MARKERS | CONTRADICTION_MARKERS | SUPPORT_MARKERS | SCOPE_MARKERS | {"must", "must_not", "allowed", "forbidden", "claim", "status", "decision"}
_MARKER_RE = re.compile(r"^\s*([a-zA-Z_]+)\s*:\s*(.+?)\s*$")
_SAFE_PUNCT_RE = re.compile(r"[^a-z0-9\-\s]")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class MarkerValue:
    name: str
    value: str


@dataclass(frozen=True)
class OpposingClaimMarker:
    kind: str
    polarity: str
    obj: str
    raw: str


@dataclass
class ParsedMarkers:
    scope: Optional[str] = None
    counterfinding: List[MarkerValue] = field(default_factory=list)
    contradiction: List[MarkerValue] = field(default_factory=list)
    support: List[MarkerValue] = field(default_factory=list)
    opposing_claims: List[OpposingClaimMarker] = field(default_factory=list)
    matched_markers: List[str] = field(default_factory=list)


def normalize_scope(value: Optional[str]) -> str:
    text = (value or "global").strip().lower().replace("_", "-")
    text = _SAFE_PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub("-", text).strip("-")
    return text or "global"


def normalize_object(value: Optional[str]) -> str:
    text = (value or "").strip().lower().replace("_", " ").replace("-", " ")
    text = _SAFE_PUNCT_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def parse_opposing_claims(text: str) -> List[OpposingClaimMarker]:
    claims: List[OpposingClaimMarker] = []
    for raw_line in (text or "").splitlines():
        m = _MARKER_RE.match(raw_line)
        if not m:
            continue
        name = m.group(1).strip().lower()
        value = m.group(2).strip()
        obj = normalize_object(value)
        if name == "must" and obj:
            claims.append(OpposingClaimMarker("must", "positive", obj, value))
        elif name == "must_not" and obj:
            claims.append(OpposingClaimMarker("must", "negative", obj, value))
        elif name == "allowed" and obj:
            claims.append(OpposingClaimMarker("allowed", "positive", obj, value))
        elif name == "forbidden" and obj:
            claims.append(OpposingClaimMarker("allowed", "negative", obj, value))
        elif name == "claim":
            if obj.endswith(" is enabled"):
                claims.append(OpposingClaimMarker("claim_enabled_disabled", "positive", obj[:-len(" is enabled")], value))
            elif obj.endswith(" is disabled"):
                claims.append(OpposingClaimMarker("claim_enabled_disabled", "negative", obj[:-len(" is disabled")], value))
        elif name == "status":
            if obj == "active":
                claims.append(OpposingClaimMarker("status_active_obsolete", "positive", "status", value))
            elif obj in {"deprecated", "obsolete"}:
                claims.append(OpposingClaimMarker("status_active_obsolete", "negative", "status", value))
        elif name == "decision":
            if obj.startswith("use "):
                claims.append(OpposingClaimMarker("decision_use", "positive", obj[4:], value))
            elif obj.startswith("do not use "):
                claims.append(OpposingClaimMarker("decision_use", "negative", obj[len("do not use "):], value))
    return [c for c in claims if c.obj]


def extract_markers(text: str) -> ParsedMarkers:
    parsed = ParsedMarkers()
    for raw_line in (text or "").splitlines():
        m = _MARKER_RE.match(raw_line)
        if not m:
            continue
        name = m.group(1).strip().lower()
        value = m.group(2).strip()
        if name not in ALL_LINE_MARKERS:
            continue
        parsed.matched_markers.append(name)
        mv = MarkerValue(name, value)
        if name in SCOPE_MARKERS:
            parsed.scope = normalize_scope(value)
        elif name in COUNTERFINDING_MARKERS:
            parsed.counterfinding.append(mv)
        elif name in CONTRADICTION_MARKERS:
            parsed.contradiction.append(mv)
        elif name in SUPPORT_MARKERS:
            parsed.support.append(mv)
    parsed.opposing_claims = parse_opposing_claims(text or "")
    return parsed


def is_support_only(markers: ParsedMarkers) -> bool:
    return bool(markers.support) and not markers.counterfinding and not markers.contradiction and not markers.opposing_claims
