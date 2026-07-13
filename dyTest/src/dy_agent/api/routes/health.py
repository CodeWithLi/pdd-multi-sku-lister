"""健康检查。"""

from fastapi import APIRouter

from dy_agent import __version__
from dy_agent.core.config import get_database_name, get_runtime_profile, resolve_env_file
from dy_agent.db import database_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    db = database_status()
    return {
        "status": "ok",
        "service": "dy-agent-platform",
        "version": __version__,
        "runtime_profile": get_runtime_profile(),
        "database": get_database_name(),
        "database_configured": bool(db.get("configured")),
        "database_available": bool(db.get("available")),
        "database_error": str(db.get("error") or ""),
        "env_file": resolve_env_file(),
    }
