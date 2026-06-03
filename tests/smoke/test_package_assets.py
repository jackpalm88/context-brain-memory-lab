"""Smoke tests — package assets (constitutionrules.yaml). No DB, no provider."""
import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.public_safe]


def test_constitutionrules_yaml_readable():
    import importlib.resources as pkg_resources
    data = pkg_resources.files("memory_lab").joinpath("governance/constitutionrules.yaml").read_text()
    assert len(data) > 100


def test_constitutionrules_has_scoring_key():
    import importlib.resources as pkg_resources
    import yaml
    data = pkg_resources.files("memory_lab").joinpath("governance/constitutionrules.yaml").read_text()
    rules = yaml.safe_load(data)
    assert "scoring" in rules


def test_constitutionrules_has_circuit_breaker_key():
    import importlib.resources as pkg_resources
    import yaml
    data = pkg_resources.files("memory_lab").joinpath("governance/constitutionrules.yaml").read_text()
    rules = yaml.safe_load(data)
    assert "circuit_breaker" in rules
