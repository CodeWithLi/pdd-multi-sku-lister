"""飞书测试专用 FastAPI 应用（与主 API 完全隔离）。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pdd_agent.core.logging import setup_logging
from pdd_agent.db import init_database
from pdd_agent.integrations.feishu.routes import router as feishu_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging("INFO")
    init_database()
    yield


def create_feishu_test_app() -> FastAPI:
    app = FastAPI(
        title="PDD Feishu Test API",
        version="0.1.0",
        description="飞书多维表格联调专用 API（端口 8001，不接入主系统）",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def root():
        return {
            "service": "feishu-test-api",
            "docs": "/docs",
            "api_prefix": "/api/feishu",
        }

    app.include_router(feishu_router, prefix="/api")
    return app
