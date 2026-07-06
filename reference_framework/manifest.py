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

_DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "memory_lab" / "mcp" / "capability_manifest.yaml"
)


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


def load_manifest(path: Optional[Path] = None) -> Manifest:
    raw = yaml.safe_load(Path(path or _DEFAULT_MANIFEST_PATH).read_text())
    if not isinstance(raw, dict) or "tools" not in raw:
        raise ManifestError("manifest must be a mapping with a 'tools' list")

    tools: Dict[str, ToolSpec] = {}
    for entry in raw["tools"]:
        spec = ToolSpec(
            name=entry["name"],
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
