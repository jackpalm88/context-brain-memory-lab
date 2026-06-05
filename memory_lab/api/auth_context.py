from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from memory_lab.api.workspace_context import WorkspaceContext


@dataclass(frozen=True)
class AuthContext:
    auth_subject_id: str
    subject_type: str
    workspace_id: str
    role: str
    auth_method: str
    is_local_dev_bypass: bool = False
    key_prefix: Optional[str] = None
    workspace: Optional[WorkspaceContext] = None

    @property
    def workspace_source(self) -> Optional[str]:
        return self.workspace.source if self.workspace else None
