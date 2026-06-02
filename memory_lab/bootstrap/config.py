from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class BootstrapConfig:
    database_url: Optional[str]


def load_config() -> BootstrapConfig:
    db = os.environ.get("DATABASE_URL")
    db = db.strip() if db else None
    return BootstrapConfig(database_url=db)
