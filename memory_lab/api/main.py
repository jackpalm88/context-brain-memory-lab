from fastapi import FastAPI

from memory_lab.api.routers.health import router as health_router
from memory_lab.api.routers.content import router as content_router
from memory_lab.api.routers.hubs import router as hubs_router
from memory_lab.api.routers.edges import router as edges_router
from memory_lab.api.routers.retrieval import router as retrieval_router


def create_app() -> FastAPI:
    app = FastAPI(title="Context Brain Memory Lab API", version="pr1b-minimal")
    app.include_router(health_router)
    app.include_router(content_router)
    app.include_router(hubs_router)
    app.include_router(edges_router)
    app.include_router(retrieval_router)
    return app


app = create_app()
