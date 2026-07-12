"""健康检查。"""

from fastapi import APIRouter

from dy_agent import __version__
from dy_agent.core.config import get_runtime_profile, resolve_env_file

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "dy-agent-platform",
        "version": __version__,
        "runtime_profile": get_runtime_profile(),
        "env_file": resolve_env_file(),
    }
