"""FastAPI 应用工厂 — 预留 Vue3 前端对接。"""

from fastapi import FastAPI

from pdd_agent.api.routes.health import router as health_router
from pdd_agent.api.routes.tasks import router as tasks_router


def create_app() -> FastAPI:
    app = FastAPI(title="PDD Agent Platform", version="0.1.0")
    app.include_router(health_router, prefix="/api")
    app.include_router(tasks_router, prefix="/api")
    return app
