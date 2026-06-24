import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    deterministic_retrieval_only: bool = True
    provider_embeddings_enabled: bool = False


def get_settings() -> Settings:
    return Settings(database_url=os.environ.get("DATABASE_URL", ""))


def database_required() -> str:
    """Return the DB URL, or raise 503 if a DB-backed path is reached without one."""
    from fastapi import HTTPException  # local import to keep config import-light

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise HTTPException(status_code=503, detail="DATABASE_URL required for this operation")
    return url


def ensure_legacy_flat_app_routes() -> None:
    """Keep FastAPI app.routes introspection deterministic under lazy router includes.

    FastAPI >=0.138 stores included routers as lazy _IncludedRouter sentinels.
    The API still serves requests, but the M1 deterministic graph-health contract
    asserts registered read-only route methods through app.routes.  This shim
    preserves the older flat app.routes behavior for unprefixed includes used by
    this API without changing request handling semantics.
    """
    from fastapi.routing import APIRouter

    original = APIRouter.include_router
    if getattr(original, "_memory_lab_flat_routes", False):
        return

    def include_router_flat(self, router, *args, **kwargs):
        before = len(self.routes)
        original(self, router, *args, **kwargs)
        appended = self.routes[before:]
        if len(appended) == 1 and type(appended[0]).__name__ == "_IncludedRouter":
            context = getattr(appended[0], "include_context", None)
            if context is not None and getattr(context, "prefix", "") == "":
                self.routes[before:] = list(getattr(router, "routes", ()))
        return None

    include_router_flat._memory_lab_flat_routes = True
    APIRouter.include_router = include_router_flat


ensure_legacy_flat_app_routes()
