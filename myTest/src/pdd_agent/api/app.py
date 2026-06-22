"""FastAPI 应用工厂。"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pdd_agent.api.routes.agents import router as agents_router
from pdd_agent.api.routes.catalog import router as catalog_router
from pdd_agent.api.routes.config import router as config_router
from pdd_agent.api.routes.failures import router as failures_router
from pdd_agent.api.routes.feishu_bitable import router as feishu_bitable_router
from pdd_agent.api.routes.feishu_oauth import router as feishu_oauth_router
from pdd_agent.api.routes.health import router as health_router
from pdd_agent.api.routes.login import router as login_router
from pdd_agent.api.routes.published_products import router as published_products_router
from pdd_agent.api.routes.style_colors import router as style_colors_router
from pdd_agent.api.routes.listed_folders import router as listed_folders_router
from pdd_agent.api.routes.pipelines import router as pipelines_router
from pdd_agent.api.routes.pipeline_issues import router as pipeline_issues_router
from pdd_agent.api.routes.queue import router as queue_router
from pdd_agent.api.routes.runs import router as runs_router
from pdd_agent.api.routes.tasks import router as tasks_router
from pdd_agent.api.routes.traffic_report_schedule import router as traffic_report_schedule_router
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger, setup_logging
from pdd_agent.db import database_status, init_database
from pdd_agent.api.services.traffic_report_scheduler import get_traffic_report_scheduler
from pdd_agent.api.services.task_queue import TaskQueueWorker

logger = get_logger(__name__)
worker = TaskQueueWorker()
traffic_report_scheduler = get_traffic_report_scheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_yaml_settings()
    setup_logging(settings.app.get("log_level", "INFO"))
    init_database()
    db = database_status()
    if db["configured"] and not db["available"]:
        logger.warning("Database unavailable: %s", db["error"])
    worker.start()
    traffic_report_scheduler.start()
    async def _ensure_feishu_table(label: str, fn):
        try:
            return await asyncio.to_thread(fn)
        except Exception as exc:
            from pdd_agent.integrations.feishu.client import FeishuAPIError

            if isinstance(exc, FeishuAPIError) and (
                "OAuth" in str(exc) or "refresh_token" in str(exc) or "user_access_token" in str(exc)
            ):
                logger.error(
                    "%s 初始化失败：飞书 user_access_token 已失效，请打开主前端「上架/下架」页完成 OAuth 授权",
                    label,
                )
                print(
                    f"[feishu] {label} 跳过：授权已失效，请打开主前端侧边栏「飞书授权」完成 OAuth",
                    flush=True,
                )
            else:
                logger.exception("%s 初始化失败", label)
            return {"failed": True, "error": str(exc)}

    try:
        from pdd_agent.integrations.feishu.traffic_report_sync import ensure_pdd_marketing_log_table_ready
        from pdd_agent.integrations.feishu.pdd_activity_log_sync import ensure_pdd_activity_log_table_ready
        from pdd_agent.integrations.feishu.pdd_upload_sync import ensure_pdd_upload_log_tables_ready
        from pdd_agent.integrations.feishu.pdd_promotion_log_sync import ensure_pdd_promotion_log_tables_ready
        from pdd_agent.integrations.feishu.pdd_price_compare_sync import ensure_pdd_price_compare_table_ready
        from pdd_agent.integrations.feishu.pdd_product_catalog_sync import ensure_pdd_product_catalog_table_ready

        marketing_ready = await _ensure_feishu_table("PDD营销日志表", ensure_pdd_marketing_log_table_ready)
        upload_ready = await _ensure_feishu_table("PDD发布日志表", ensure_pdd_upload_log_tables_ready)
        promotion_log_ready = await _ensure_feishu_table(
            "PDD推广日志表",
            ensure_pdd_promotion_log_tables_ready,
        )
        activity_ready = await _ensure_feishu_table("PDD活动日志表", ensure_pdd_activity_log_table_ready)
        price_compare_ready = await _ensure_feishu_table(
            "拼多多比价定价",
            ensure_pdd_price_compare_table_ready,
        )
        product_catalog_ready = await _ensure_feishu_table(
            "拼多多所有商品",
            ensure_pdd_product_catalog_table_ready,
        )
        if upload_ready.get("ready"):
            logger.info(
                "pdd upload log tables ready success=%s(%s) failure=%s(%s)",
                upload_ready.get("success_table_id"),
                upload_ready.get("success_resolve_method"),
                upload_ready.get("failure_table_id"),
                upload_ready.get("failure_resolve_method"),
            )
            print(
                "[feishu] PDD发布日志表已就绪："
                f"{upload_ready.get('success_table_id')} / "
                f"失败表(淘宝+拼多多)={upload_ready.get('failure_table_id')}",
                flush=True,
            )
        elif not upload_ready.get("skipped"):
            logger.error("pdd upload log tables not ready: %s", upload_ready)
        if promotion_log_ready.get("ready"):
            logger.info(
                "pdd promotion log table ready table=%s(%s)",
                promotion_log_ready.get("table_id"),
                promotion_log_ready.get("resolve_method"),
            )
            print(
                f"[feishu] PDD推广日志表已就绪：{promotion_log_ready.get('table_id')}",
                flush=True,
            )
        elif not promotion_log_ready.get("skipped"):
            logger.error("pdd promotion log tables not ready: %s", promotion_log_ready)
        if activity_ready.get("ready"):
            logger.info(
                "pdd activity log table ready table=%s(%s)",
                activity_ready.get("table_id"),
                activity_ready.get("resolve_method"),
            )
            print(
                f"[feishu] PDD活动日志表已就绪：{activity_ready.get('table_id')}",
                flush=True,
            )
        elif not activity_ready.get("skipped"):
            logger.error("pdd activity log table not ready: %s", activity_ready)
        if price_compare_ready.get("ready"):
            logger.info(
                "pdd price compare table ready table=%s(%s)",
                price_compare_ready.get("table_id"),
                price_compare_ready.get("resolve_method"),
            )
            print(
                f"[feishu] 拼多多比价定价表已就绪：{price_compare_ready.get('table_id')}",
                flush=True,
            )
        elif not price_compare_ready.get("skipped"):
            logger.error("pdd price compare table not ready: %s", price_compare_ready)
        if product_catalog_ready.get("ready"):
            logger.info(
                "pdd product catalog table ready table=%s(%s)",
                product_catalog_ready.get("table_id"),
                product_catalog_ready.get("resolve_method"),
            )
            print(
                f"[feishu] 拼多多所有商品表已就绪：{product_catalog_ready.get('table_id')}",
                flush=True,
            )
        elif not product_catalog_ready.get("skipped"):
            logger.error("pdd product catalog table not ready: %s", product_catalog_ready)
    except Exception:
        logger.exception("ensure pdd feishu tables on startup failed")
    logger.info("PDD Agent API started")
    yield
    await traffic_report_scheduler.stop()
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
    app.include_router(traffic_report_schedule_router, prefix="/api")
    app.include_router(pipelines_router, prefix="/api")
    app.include_router(pipeline_issues_router, prefix="/api")
    app.include_router(listed_folders_router, prefix="/api")
    app.include_router(queue_router, prefix="/api")
    app.include_router(failures_router, prefix="/api")
    app.include_router(feishu_bitable_router, prefix="/api")
    app.include_router(feishu_oauth_router, prefix="/api")
    app.include_router(login_router, prefix="/api")
    app.include_router(published_products_router, prefix="/api")
    app.include_router(style_colors_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(agents_router, prefix="/api")
    return app
