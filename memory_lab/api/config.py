import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    deterministic_retrieval_only: bool = True
    provider_embeddings_enabled: bool = False


def get_settings() -> Settings:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    return Settings(database_url=database_url)
