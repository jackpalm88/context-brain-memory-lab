"""Manifest Loader — capability_manifest.yaml into a runtime model.

No heuristics: the loader validates shape and vocabularies and indexes the
entries. Anything semantically clever belongs to the router, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROLES = {"liveness", "write", "read", "search", "answer", "curate", "govern", "lineage", "diagnose"}
DETERMINISM = {"deterministic", "deterministic_core", "provider_opt_in"}
ROUTING = {"normal", "discouraged", "alias"}
# CF-001/004 v0.2: the mechanical layer — where rows live in a response.
SHAPE_KINDS = {"keyed_list", "status_buckets", "record", "answer_envelope",
               "graph_snapshot", "id_envelope", "status", "ack", "lineage_tree"}
_ROWLESS_KINDS = {"record", "id_envelope", "status", "ack"}

_DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "memory_lab" / "mcp" / "capability_manifest.yaml"
)


@dataclass(frozen=True)
class ResponseShape:
    """v0.2 mechanical contract: where rows live in a successful response."""

    kind: str
    rows_keys: tuple = ()
    count_key: Optional[str] = None
    bucket_keys: tuple = ()
    context_keys: tuple = ()


@dataclass(frozen=True)
class ToolSpec:
    name: str
    role: str
    answers: List[str]
    use_when: str
    determinism: str
    required_inputs: List[str]
    output_kind: str
    suggested_followups: List[Dict[str, str]]
    failure: str
    response_shape: ResponseShape = ResponseShape(kind="record")
    avoid_when: Optional[str] = None
    optional_inputs: List[str] = field(default_factory=list)
    key_signals: List[str] = field(default_factory=list)
    honest_contract: Optional[str] = None
    routing: str = "normal"


@dataclass(frozen=True)
class Manifest:
    manifest_version: str
    opencb_version: str
    tools: Dict[str, ToolSpec]

    def routable(self) -> Dict[str, ToolSpec]:
        """Tools the router may select (routing=normal only)."""
        return {n: t for n, t in self.tools.items() if t.routing == "normal"}


class ManifestError(ValueError):
    pass


def _parse_response_shape(tool_name: str, raw: Any) -> ResponseShape:
    if not isinstance(raw, dict):
        raise ManifestError(f"{tool_name}: response_shape is required in manifest v0.2")
    kind = raw.get("kind")
    if kind not in SHAPE_KINDS:
        raise ManifestError(f"{tool_name}: unknown response_shape.kind {kind!r}")
    shape = ResponseShape(
        kind=kind,
        rows_keys=tuple(raw.get("rows_keys") or ()),
        count_key=raw.get("count_key"),
        bucket_keys=tuple(raw.get("bucket_keys") or ()),
        context_keys=tuple(raw.get("context_keys") or ()),
    )
    if kind == "keyed_list" and (len(shape.rows_keys) != 1 or not shape.count_key):
        raise ManifestError(f"{tool_name}: keyed_list requires exactly one rows_key and a count_key")
    if kind == "status_buckets" and (not shape.bucket_keys or not shape.rows_keys or not shape.count_key):
        raise ManifestError(f"{tool_name}: status_buckets requires bucket_keys, flat rows_keys and count_key")
    if kind in _ROWLESS_KINDS and (shape.rows_keys or shape.count_key or shape.bucket_keys):
        raise ManifestError(f"{tool_name}: {kind} must not declare rows/count/buckets")
    return shape


def load_manifest(path: Optional[Path] = None) -> Manifest:
    raw = yaml.safe_load(Path(path or _DEFAULT_MANIFEST_PATH).read_text())
    if not isinstance(raw, dict) or "tools" not in raw:
        raise ManifestError("manifest must be a mapping with a 'tools' list")

    tools: Dict[str, ToolSpec] = {}
    for entry in raw["tools"]:
        shape = _parse_response_shape(entry["name"], entry.get("response_shape"))
        spec = ToolSpec(
            name=entry["name"],
            response_shape=shape,
            role=entry["role"],
            answers=list(entry["answers"]),
            use_when=entry["use_when"],
            determinism=entry["determinism"],
            required_inputs=list(entry["required_inputs"]),
            output_kind=entry["output_kind"],
            suggested_followups=list(entry["suggested_followups"]),
            failure=entry["failure"],
            avoid_when=entry.get("avoid_when"),
            optional_inputs=list(entry.get("optional_inputs", [])),
            key_signals=list(entry.get("key_signals", [])),
            honest_contract=entry.get("honest_contract"),
            routing=entry.get("routing", "normal"),
        )
        if spec.role not in ROLES:
            raise ManifestError(f"{spec.name}: unknown role {spec.role!r}")
        if spec.determinism not in DETERMINISM:
            raise ManifestError(f"{spec.name}: unknown determinism {spec.determinism!r}")
        if spec.routing not in ROUTING:
            raise ManifestError(f"{spec.name}: unknown routing {spec.routing!r}")
        if spec.name in tools:
            raise ManifestError(f"duplicate tool entry {spec.name!r}")
        tools[spec.name] = spec

    return Manifest(
        manifest_version=str(raw["manifest_version"]),
        opencb_version=str(raw["opencb_version"]),
        tools=tools,
    )
