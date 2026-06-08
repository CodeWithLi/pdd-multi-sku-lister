"""FastAPI 应用工厂。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pdd_agent.api.routes.agents import router as agents_router
from pdd_agent.api.routes.catalog import router as catalog_router
from pdd_agent.api.routes.config import router as config_router
from pdd_agent.api.routes.health import router as health_router
from pdd_agent.api.routes.login import router as login_router
from pdd_agent.api.routes.runs import router as runs_router
from pdd_agent.api.routes.tasks import router as tasks_router
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger, setup_logging
from pdd_agent.db import database_status, init_database
from pdd_agent.api.services.task_queue import TaskQueueWorker

logger = get_logger(__name__)
worker = TaskQueueWorker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_yaml_settings()
    setup_logging(settings.app.get("log_level", "INFO"))
    init_database()
    db = database_status()
    if db["configured"] and not db["available"]:
        logger.warning("Database unavailable: %s", db["error"])
    worker.start()
    logger.info("PDD Agent API started")
    yield
    await worker.stop()
    logger.info("PDD Agent API stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PDD Agent Platform",
        version="0.1.0",
        description="拼多多运营智能体 API（LangGraph + Playwright）",
        lifespan=lifespan,
    )

    # 本地 Vue3 开发用；个人项目允许全部来源
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["root"])
    def root():
        return {
            "service": "pdd-agent-platform",
            "docs": "/docs",
            "redoc": "/redoc",
            "api_prefix": "/api",
        }

    app.include_router(health_router, prefix="/api")
    app.include_router(config_router, prefix="/api")
    app.include_router(catalog_router, prefix="/api")
    app.include_router(tasks_router, prefix="/api")
    app.include_router(login_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(agents_router, prefix="/api")
    return app
