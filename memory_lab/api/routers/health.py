import os
from fastapi import APIRouter

router = APIRouter(tags=["health"])

_SERVICE = "memory-lab-api"
_VERSION = "pr1b-minimal"


@router.get("/health")
def get_health() -> dict:
    """Return service health. Reports 'unavailable' when DATABASE_URL is not configured."""
    db_configured = bool(os.environ.get("DATABASE_URL", "").strip())
    if db_configured:
        return {"status": "ok", "service": _SERVICE, "version": _VERSION}
    return {
        "status": "unavailable",
        "reason": "database_url_not_configured",
        "service": _SERVICE,
        "version": _VERSION,
    }
