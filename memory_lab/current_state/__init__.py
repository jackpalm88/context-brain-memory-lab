"""Current-state resolver package.

Owns current-state anchor/supersession writes. Classify does not write these fields.
"""

from .resolver import CurrentStateResolution, derive_current_state_scope, resolve_current_state_after_ingest

__all__ = [
    "CurrentStateResolution",
    "derive_current_state_scope",
    "resolve_current_state_after_ingest",
]
