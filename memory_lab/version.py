"""Single source of truth for the runtime-reported package version.

pyproject.toml must be kept in sync at release time; runtime surfaces
(/health, FastAPI metadata) read from here so the API never reports a
stale or codename version.
"""

__version__ = "1.0.0"
