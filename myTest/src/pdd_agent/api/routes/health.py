"""健康检查接口。"""

from fastapi import APIRouter

from pdd_agent import __version__
from pdd_agent.core.config import (
    background_jobs_enabled,
    get_database_name,
    get_runtime_profile,
    resolve_env_file,
)
from pdd_agent.db import database_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    db = database_status()
    return {
        "status": "ok",
        "service": "pdd-agent-platform",
        "version": __version__,
        "runtime_profile": get_runtime_profile(),
        "background_jobs": background_jobs_enabled(),
        "database": get_database_name(),
        "database_available": bool(db.get("available")),
        "env_file": resolve_env_file(),
    }
