import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    deterministic_retrieval_only: bool = True
    provider_embeddings_enabled: bool = False
    vector_embeddings_enabled: bool = False
    pgvector_retrieval_enabled: bool = False
    reasoning_provider_synthesis_enabled: bool = False
    ask_provider_synthesis_enabled: bool = False


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    provider_embeddings_enabled = _env_bool("MEMORY_LAB_PROVIDER_EMBEDDINGS_ENABLED", False)
    vector_embeddings_enabled = _env_bool("MEMORY_LAB_VECTOR_EMBEDDINGS_ENABLED", False) or provider_embeddings_enabled
    pgvector_retrieval_enabled = _env_bool("MEMORY_LAB_PGVECTOR_RETRIEVAL_ENABLED", False)
    reasoning_provider_synthesis_enabled = _env_bool("MEMORY_LAB_REASONING_PROVIDER_SYNTHESIS_ENABLED", False)
    ask_provider_synthesis_enabled = _env_bool("MEMORY_LAB_ASK_PROVIDER_SYNTHESIS_ENABLED", False)
    deterministic_retrieval_only = not pgvector_retrieval_enabled
    return Settings(
        database_url=os.environ.get("DATABASE_URL", ""),
        deterministic_retrieval_only=deterministic_retrieval_only,
        provider_embeddings_enabled=provider_embeddings_enabled,
        vector_embeddings_enabled=vector_embeddings_enabled,
        pgvector_retrieval_enabled=pgvector_retrieval_enabled,
        reasoning_provider_synthesis_enabled=reasoning_provider_synthesis_enabled,
        ask_provider_synthesis_enabled=ask_provider_synthesis_enabled,
    )


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
    from fastapi.routing import APIRouter, request_response

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
                flattened_routes = list(getattr(router, "routes", ()))
                for route in flattened_routes:
                    if hasattr(route, "dependency_overrides_provider"):
                        route.dependency_overrides_provider = getattr(self, "dependency_overrides_provider", self)
                        if hasattr(route, "get_route_handler"):
                            route.app = request_response(route.get_route_handler())
                self.routes[before:] = flattened_routes
        return None

    include_router_flat._memory_lab_flat_routes = True
    APIRouter.include_router = include_router_flat


ensure_legacy_flat_app_routes()
