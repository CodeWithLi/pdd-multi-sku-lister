"""FastAPI 应用工厂。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dy_agent.api.routes.health import router as health_router
from dy_agent.api.routes.runs import router as runs_router
from dy_agent.api.routes.tasks import router as tasks_router
from dy_agent.core.config import load_yaml_settings
from dy_agent.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_yaml_settings()
    setup_logging(settings.app.get("log_level", "INFO"))
    logger.info("dy-agent API started")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="抖音运营智能体平台",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(tasks_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    return app
