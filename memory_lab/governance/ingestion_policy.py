"""
Constitution loader for Memory Lab governance.

Loads constitutionrules.yaml from the installed memory_lab.governance package.
This is intentionally package-local: no private cwd lookup, no hardcoded
staging path, and no /opt/contentingestor dependency.
"""
from __future__ import annotations

import logging
import os
import re
from importlib import resources
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_RULES: Dict[str, Any] = {}
_LOADED = False


def _find_rules_file() -> Path:
    package_files = resources.files("memory_lab.governance")
    candidate = package_files / "constitutionrules.yaml"
    with resources.as_file(candidate) as resolved:
        path = Path(resolved)
        if path.exists():
            return path
    raise FileNotFoundError(
        "constitutionrules.yaml not found in memory_lab.governance package assets"
    )


def _extract_with_regex(text: str, pattern: str, cast=str, default=None):
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not match:
        return default
    value = match.group(1)
    return cast(value) if cast is not str else value


def _fallback_parse_rules_text(raw_text: str) -> Dict[str, Any]:
    def block(name: str) -> str:
        pattern = rf"^  {name}:\n(.*?)(?=^  [A-Za-z_]+:|\Z)"
        m = re.search(pattern, raw_text, re.MULTILINE | re.DOTALL)
        return m.group(1) if m else ""

    def nested_default(section_text: str, key: str, field: str, fallback: float) -> float:
        pattern = rf"^    {key}:\n(?:.*\n)*?^        {field}:\n(?:.*\n)*?^          default: ([0-9.]+)"
        return _extract_with_regex(section_text, pattern, float, fallback)

    def nested_env(section_text: str, key: str, field: str, fallback: str) -> str:
        pattern = rf"^    {key}:\n(?:.*\n)*?^        {field}:\n(?:.*\n)*?^          env_var: ([A-Z0-9_]+)"
        return _extract_with_regex(section_text, pattern, str, fallback)

    tiers_text = block('tiers')
    scoring_text = block('scoring')
    circuit_text = block('circuit_breaker')

    return {
        'metadata': {
            'version': _extract_with_regex(raw_text, r'^  version: "([^"]+)"', str, 'fallback'),
        },
        'scoring': {
            'axes': {
                'quality': {
                    'min_score': {
                        'default': nested_default(scoring_text, 'quality', 'min_score', 0.4),
                        'env_var': nested_env(scoring_text, 'quality', 'min_score', 'CB_SCORE_MIN_QUALITY'),
                    }
                }
            },
            'composite': {
                'min_score': {
                    'default': _extract_with_regex(scoring_text, r'^    min_score:\n(?:.*\n)*?^      default: ([0-9.]+)', float, 0.5),
                    'env_var': _extract_with_regex(scoring_text, r'^    min_score:\n(?:.*\n)*?^      env_var: ([A-Z0-9_]+)', str, 'CB_SCORE_MIN_COMPOSITE'),
                },
                'persistent_threshold': {
                    'default': _extract_with_regex(scoring_text, r'^    persistent_threshold:\n(?:.*\n)*?^      default: ([0-9.]+)', float, 0.7),
                    'env_var': _extract_with_regex(scoring_text, r'^    persistent_threshold:\n(?:.*\n)*?^      env_var: ([A-Z0-9_]+)', str, 'CB_SCORE_PERSISTENT_THRESHOLD'),
                },
            },
        },
        'tiers': {
            'discard': {
                'composite_max': {
                    'default': _extract_with_regex(tiers_text, r'^    discard:\n(?:.*\n)*?^      composite_max:\n(?:.*\n)*?^        default: ([0-9.]+)', float, 0.3),
                    'env_var': _extract_with_regex(tiers_text, r'^    discard:\n(?:.*\n)*?^      composite_max:\n(?:.*\n)*?^        env_var: ([A-Z0-9_]+)', str, 'CB_TIER_DISCARD_MAX'),
                }
            },
            'transient': {
                'composite_max': {
                    'default': _extract_with_regex(tiers_text, r'^    transient:\n(?:.*\n)*?^      composite_max:\n(?:.*\n)*?^        default: ([0-9.]+)', float, 0.5),
                    'env_var': _extract_with_regex(tiers_text, r'^    transient:\n(?:.*\n)*?^      composite_max:\n(?:.*\n)*?^        env_var: ([A-Z0-9_]+)', str, 'CB_TIER_TRANSIENT_MAX'),
                }
            },
            'probationary': {
                'composite_max': {
                    'default': _extract_with_regex(tiers_text, r'^    probationary:\n(?:.*\n)*?^      composite_max:\n(?:.*\n)*?^        default: ([0-9.]+)', float, 0.7),
                    'env_var': _extract_with_regex(tiers_text, r'^    probationary:\n(?:.*\n)*?^      composite_max:\n(?:.*\n)*?^        env_var: ([A-Z0-9_]+)', str, 'CB_TIER_PROBATIONARY_MAX'),
                }
            },
        },
        'circuit_breaker': {
            'failure_threshold': _extract_with_regex(circuit_text, r'^  failure_threshold: ([0-9]+)', int, 3),
            'window_seconds': _extract_with_regex(circuit_text, r'^  window_seconds: ([0-9]+)', int, 60),
            'open_duration_seconds': _extract_with_regex(circuit_text, r'^  open_duration_seconds: ([0-9]+)', int, 300),
            'fallback_composite_score': _extract_with_regex(circuit_text, r'^  fallback_composite_score: ([0-9.]+)', float, 0.3),
            'fallback_tier': {
                'default': _extract_with_regex(circuit_text, r'^    default: "([^"]+)"', str, 'transient'),
                'env_var': _extract_with_regex(circuit_text, r'^    env_var: ([A-Z0-9_]+)', str, 'CB_SCORE_FALLBACK_TIER'),
            },
        },
        'scoring_prompt': {},
    }


def load() -> Dict[str, Any]:
    global _RULES, _LOADED
    if _LOADED:
        return _RULES
    try:
        import yaml
        path = _find_rules_file()
        with path.open("r", encoding="utf-8") as fh:
            _RULES = yaml.safe_load(fh) or {}
        _LOADED = True
        logger.info(
            "[ingestion_policy] Constitution loaded from %s (package-local asset)",
            path,
        )
    except ImportError:
        path = _find_rules_file()
        raw_text = path.read_text(encoding="utf-8")
        _RULES = _fallback_parse_rules_text(raw_text)
        _LOADED = True
        logger.warning("[ingestion_policy] PyYAML not installed — using fallback parser for package-local constitutionrules.yaml from %s", path)
    except Exception as exc:
        logger.error("[ingestion_policy] Failed to load package-local constitutionrules.yaml: %s", exc)
        _RULES = {}
        _LOADED = True
    return _RULES


def get_threshold(rule_path: str, default: float) -> float:
    rules = load()
    node: Any = rules
    for part in rule_path.split("."):
        if not isinstance(node, dict):
            return _apply_env_override(None, default)
        node = node.get(part)

    if not isinstance(node, dict):
        return _apply_env_override(None, default)

    env_var = node.get("env_var")
    yaml_default = node.get("default", default)
    return _apply_env_override(env_var, yaml_default)


def _apply_env_override(env_var: Any, default: float) -> float:
    if env_var:
        raw = os.environ.get(str(env_var), "").strip()
        if raw:
            try:
                return float(raw)
            except ValueError:
                logger.warning("[ingestion_policy] Invalid float for %s=%r", env_var, raw)
    return float(default)


def get_scoring_prompt() -> Dict[str, Any]:
    rules = load()
    return rules.get("scoring_prompt", {})


def get_circuit_config() -> Dict[str, Any]:
    rules = load()
    cb = rules.get("circuit_breaker", {})
    fallback_node = cb.get("fallback_tier", {})
    env_var = fallback_node.get("env_var", "CB_SCORE_FALLBACK_TIER") if isinstance(fallback_node, dict) else None
    fallback_default = fallback_node.get("default", "transient") if isinstance(fallback_node, dict) else "transient"
    fallback_tier = os.environ.get(env_var or "", fallback_default) if env_var else fallback_default
    return {
        "failure_threshold": cb.get("failure_threshold", 3),
        "window_seconds": cb.get("window_seconds", 60),
        "open_duration_seconds": cb.get("open_duration_seconds", 300),
        "fallback_composite_score": cb.get("fallback_composite_score", 0.3),
        "fallback_tier": fallback_tier,
    }


_EPISTEMIC_ARTIFACT_TYPES = frozenset({
    "decision_artifact", "decision", "fact", "playbook"
})
_EPISTEMIC_ARTIFACT_MIN_QUALITY = 0.25


def min_quality(node_type: str = "") -> float:
    if node_type and node_type.lower() in _EPISTEMIC_ARTIFACT_TYPES:
        return _EPISTEMIC_ARTIFACT_MIN_QUALITY
    return get_threshold("scoring.axes.quality.min_score", 0.4)


def min_composite() -> float:
    return get_threshold("scoring.composite.min_score", 0.5)


def persistent_threshold() -> float:
    return get_threshold("scoring.composite.persistent_threshold", 0.7)
