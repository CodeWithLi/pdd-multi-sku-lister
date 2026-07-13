"""FastAPI 应用工厂。"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dy_agent.api.routes.catalog import router as catalog_router
from dy_agent.api.routes.config import router as config_router
from dy_agent.api.routes.feishu_cache import router as feishu_cache_router
from dy_agent.api.routes.feishu_oauth import router as feishu_oauth_router
from dy_agent.api.routes.health import router as health_router
from dy_agent.api.routes.login import router as login_router
from dy_agent.api.routes.runs import router as runs_router
from dy_agent.api.routes.tasks import router as tasks_router
from dy_agent.core.config import get_database_name, load_yaml_settings
from dy_agent.core.logging import get_logger, setup_logging
from dy_agent.db import database_status, init_database

logger = get_logger(__name__)


async def _ensure_feishu_table(label: str, fn):
    try:
        return await asyncio.to_thread(fn)
    except Exception as exc:
        from dy_agent.integrations.feishu.client import FeishuAPIError

        if isinstance(exc, FeishuAPIError) and (
            "OAuth" in str(exc) or "refresh_token" in str(exc) or "user_access_token" in str(exc)
        ):
            logger.error("%s 初始化失败：飞书 user_access_token 已失效，请完成 OAuth 授权", label)
            print(
                f"[feishu] {label} 跳过：授权已失效，请打开侧边栏「飞书授权」完成 OAuth",
                flush=True,
            )
        else:
            logger.exception("%s 初始化失败", label)
        return {"failed": True, "error": str(exc)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_yaml_settings()
    setup_logging(settings.app.get("log_level", "INFO"))
    init_database()
    db = database_status()
    if db["configured"] and not db["available"]:
        logger.warning("Database unavailable: %s", db["error"])
    else:
        logger.info("dy-agent API started db=%s", get_database_name() or "json-fallback")

    try:
        from dy_agent.integrations.feishu.config import load_feishu_config, resolve_feishu_config_path
        from dy_agent.integrations.feishu.client import FeishuAPIError, FeishuClient

        cfg_path = resolve_feishu_config_path()
        logger.info("feishu config path=%s exists=%s", cfg_path, cfg_path.is_file())
        print(f"[feishu] 配置文件: {cfg_path}", flush=True)

        cfg = load_feishu_config()
        if cfg.use_user_access_token and cfg.app_id and cfg.app_secret:
            try:
                client = FeishuClient(cfg)
                await asyncio.to_thread(client.get_user_access_token)
                logger.info("feishu user_access_token ready (auto-refresh enabled)")
                print("[feishu] user_access_token 已就绪（过期时自动刷新）", flush=True)
            except FeishuAPIError as exc:
                logger.warning("feishu token probe failed: %s", exc)
                print(
                    f"[feishu] 授权未就绪：{exc}；请打开侧边栏「飞书授权」完成 OAuth",
                    flush=True,
                )
    except Exception:
        logger.exception("feishu auth probe on startup failed")

    try:
        from dy_agent.integrations.feishu.pdd_price_compare_sync import ensure_pdd_price_compare_table_ready
        from dy_agent.integrations.feishu.pdd_product_catalog_sync import ensure_pdd_product_catalog_table_ready

        price_compare_ready = await _ensure_feishu_table(
            "拼多多比价定价",
            ensure_pdd_price_compare_table_ready,
        )
        product_catalog_ready = await _ensure_feishu_table(
            "拼多多所有商品",
            ensure_pdd_product_catalog_table_ready,
        )
        if price_compare_ready.get("ready"):
            logger.info(
                "feishu price compare table ready table=%s(%s)",
                price_compare_ready.get("table_id"),
                price_compare_ready.get("resolve_method"),
            )
            print(
                f"[feishu] 拼多多比价定价表已就绪：{price_compare_ready.get('table_id')}",
                flush=True,
            )
        if product_catalog_ready.get("ready"):
            logger.info(
                "feishu product catalog table ready table=%s(%s)",
                product_catalog_ready.get("table_id"),
                product_catalog_ready.get("resolve_method"),
            )
            print(
                f"[feishu] 拼多多所有商品表已就绪：{product_catalog_ready.get('table_id')}",
                flush=True,
            )
    except Exception:
        logger.exception("ensure feishu tables on startup failed")

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
    app.include_router(config_router, prefix="/api")
    app.include_router(login_router, prefix="/api")
    app.include_router(catalog_router, prefix="/api")
    app.include_router(tasks_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(feishu_oauth_router, prefix="/api")
    app.include_router(feishu_cache_router, prefix="/api")
    return app
