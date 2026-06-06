"""健康检查接口。"""

from fastapi import APIRouter

from pdd_agent import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "pdd-agent-platform", "version": __version__}
