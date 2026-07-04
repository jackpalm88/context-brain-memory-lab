"""Current-state resolver package.

Owns current-state anchor/supersession writes. Classify does not write these fields.
"""

from .resolver import CurrentStateResolution, derive_current_state_scope, resolve_current_state_after_ingest
from .scope_pipeline import ScopeResolution, resolve_scope

__all__ = [
    "CurrentStateResolution",
    "ScopeResolution",
    "derive_current_state_scope",
    "resolve_current_state_after_ingest",
    "resolve_scope",
]
