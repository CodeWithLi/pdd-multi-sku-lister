"""SQLAlchemy engine/session 管理。"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from pdd_agent.core.config import get_env_settings
from pdd_agent.db.base import Base
import pdd_agent.db.models  # noqa: F401

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None
_available: bool | None = None
_initializing: bool = False
_listed_folders_backfill_done: bool = False
_last_error: str = ""


def _create_mysql_database_if_missing(database_url: str) -> None:
    """连接 MySQL server，自动创建目标 database。"""
    url = make_url(database_url)
    if not url.get_backend_name().startswith("mysql") or not url.database:
        return

    database = url.database
    if not re.match(r"^[A-Za-z0-9_]+$", database):
        raise ValueError("DATABASE_URL 中的数据库名仅支持字母、数字、下划线")

    server_url = url.set(database="")
    server_engine = create_engine(server_url, pool_pre_ping=True, future=True)
    try:
        with server_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        server_engine.dispose()


def _ensure_task_queue_claim_index(engine: Engine) -> None:
    """为已有 task_queue 表补充 claim 复合索引（create_all 不会给旧表加索引）。"""
    try:
        inspector = inspect(engine)
        if "task_queue" not in inspector.get_table_names():
            return
        existing = {idx["name"] for idx in inspector.get_indexes("task_queue")}
        if "ix_task_queue_claim" in existing:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX ix_task_queue_claim "
                    "ON task_queue (status, scheduled_at, account_id)"
                )
            )
    except Exception:
        return


def _ensure_accounts_columns(engine: Engine) -> None:
    """为 accounts 表补充拼多多后台店铺展示名（右上角红框，如「指尖上的美好时光」）。"""
    try:
        inspector = inspect(engine)
        if "accounts" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("accounts")}
        with engine.begin() as conn:
            if "shop_display_name" not in existing:
                conn.execute(
                    text(
                        "ALTER TABLE accounts "
                        "ADD COLUMN shop_display_name VARCHAR(128) NOT NULL DEFAULT ''"
                    )
                )
            if "login_statuses" in inspector.get_table_names():
                conn.execute(
                    text(
                        "UPDATE accounts a "
                        "INNER JOIN login_statuses l ON a.account_id = l.account_id "
                        "SET a.shop_display_name = l.shop_display_name "
                        "WHERE TRIM(l.shop_display_name) <> '' "
                        "AND TRIM(a.shop_display_name) = ''"
                    )
                )
    except Exception:
        return


def _ensure_login_statuses_columns(engine: Engine) -> None:
    try:
        inspector = inspect(engine)
        if "login_statuses" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("login_statuses")}
        if "shop_display_name" in existing:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE login_statuses "
                    "ADD COLUMN shop_display_name VARCHAR(128) NOT NULL DEFAULT ''"
                )
            )
    except Exception:
        return


def _ensure_published_products_columns(engine: Engine) -> None:
    try:
        inspector = inspect(engine)
        if "published_products" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("published_products")}
        dialect = engine.dialect.name
        statements: list[str] = []
        if "family_code" not in existing:
            statements.append("ALTER TABLE published_products ADD COLUMN family_code VARCHAR(64) NOT NULL DEFAULT ''")
        if "spec_metadata" not in existing:
            if dialect.startswith("mysql"):
                statements.append("ALTER TABLE published_products ADD COLUMN spec_metadata JSON NULL")
            else:
                statements.append("ALTER TABLE published_products ADD COLUMN spec_metadata JSON NULL")
        if "limited_time_status" not in existing:
            statements.append(
                "ALTER TABLE published_products ADD COLUMN limited_time_status VARCHAR(16) NOT NULL DEFAULT ''"
            )
        if "limited_time_error" not in existing:
            if dialect.startswith("mysql"):
                # MySQL 不允许 TEXT/BLOB 列带 DEFAULT，用 NULL 列即可（应用层默认 ""）
                statements.append(
                    "ALTER TABLE published_products ADD COLUMN limited_time_error TEXT NULL"
                )
            else:
                statements.append(
                    "ALTER TABLE published_products ADD COLUMN limited_time_error TEXT NOT NULL DEFAULT ''"
                )
        if "limited_time_run_id" not in existing:
            statements.append(
                "ALTER TABLE published_products ADD COLUMN limited_time_run_id VARCHAR(64) NOT NULL DEFAULT ''"
            )
        if "limited_time_completed_at" not in existing:
            statements.append(
                "ALTER TABLE published_products ADD COLUMN limited_time_completed_at DATETIME NULL"
            )
        if not statements:
            return
        from pdd_agent.core.logging import get_logger

        log = get_logger(__name__)
        for stmt in statements:
            try:
                with engine.begin() as conn:
                    conn.execute(text(stmt))
            except Exception:
                log.warning("published_products migration skipped: %s", stmt, exc_info=True)
    except Exception:
        return


def _ensure_failure_sequential_job_columns(engine: Engine) -> None:
    try:
        inspector = inspect(engine)
        if "failure_sequential_jobs" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("failure_sequential_jobs")}
        if "limited_time_completed_at" in existing:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE failure_sequential_jobs "
                    "ADD COLUMN limited_time_completed_at DATETIME NULL"
                )
            )
    except Exception:
        return


def _ensure_failure_sequential_batch_columns(engine: Engine) -> None:
    try:
        inspector = inspect(engine)
        if "failure_sequential_batches" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("failure_sequential_batches")}
        statements: list[str] = []
        if "activity_unlocked" not in existing:
            statements.append(
                "ALTER TABLE failure_sequential_batches "
                "ADD COLUMN activity_unlocked TINYINT(1) NOT NULL DEFAULT 0"
            )
        if "activity_scheduled_at" not in existing:
            statements.append(
                "ALTER TABLE failure_sequential_batches "
                "ADD COLUMN activity_scheduled_at DATETIME NULL"
            )
        if "activity_unlocked_at" not in existing:
            statements.append(
                "ALTER TABLE failure_sequential_batches "
                "ADD COLUMN activity_unlocked_at DATETIME NULL"
            )
        if not statements:
            return
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
    except Exception:
        return


def _ensure_inventory_delist_records_columns(engine: Engine) -> None:
    """为 inventory_delist_records 补充扩展字段。"""
    try:
        inspector = inspect(engine)
        if "inventory_delist_records" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("inventory_delist_records")}
        statements: list[str] = []
        if "is_relisted" not in existing:
            statements.append(
                "ALTER TABLE inventory_delist_records "
                "ADD COLUMN is_relisted TINYINT(1) NOT NULL DEFAULT 0"
            )
        if "relisted_at" not in existing:
            statements.append(
                "ALTER TABLE inventory_delist_records "
                "ADD COLUMN relisted_at DATETIME NULL"
            )
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
            conn.execute(
                text(
                    "UPDATE inventory_delist_records "
                    "SET relisted_at = CURRENT_TIMESTAMP "
                    "WHERE is_relisted = 1 AND relisted_at IS NULL"
                )
            )
    except Exception:
        return


def _ensure_listing_submit_ai_title_config_columns(engine: Engine) -> None:
    """为 listing_submit_ai_title_config 表补充兜底模型字段（老库平滑升级）。"""
    try:
        inspector = inspect(engine)
        if "listing_submit_ai_title_config" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("listing_submit_ai_title_config")}
        dialect = engine.dialect.name
        statements: list[str] = []
        if "fallback_enabled" not in existing:
            statements.append(
                "ALTER TABLE listing_submit_ai_title_config "
                "ADD COLUMN fallback_enabled TINYINT(1) NOT NULL DEFAULT 1"
            )
        if "fallback_provider" not in existing:
            statements.append(
                "ALTER TABLE listing_submit_ai_title_config "
                "ADD COLUMN fallback_provider VARCHAR(32) NOT NULL DEFAULT 'glm'"
            )
        if "fallback_model" not in existing:
            statements.append(
                "ALTER TABLE listing_submit_ai_title_config "
                "ADD COLUMN fallback_model VARCHAR(128) NOT NULL DEFAULT 'glm-4-flash'"
            )
        if "fallback_base_url" not in existing:
            statements.append(
                "ALTER TABLE listing_submit_ai_title_config "
                "ADD COLUMN fallback_base_url VARCHAR(255) NOT NULL DEFAULT 'https://open.bigmodel.cn/api/paas/v4'"
            )
        if "fallback_api_key" not in existing:
            if dialect.startswith("mysql"):
                statements.append(
                    "ALTER TABLE listing_submit_ai_title_config "
                    "ADD COLUMN fallback_api_key TEXT NULL"
                )
                # MySQL TEXT 不允许 DEFAULT，这里后续读时按空串处理
            else:
                statements.append(
                    "ALTER TABLE listing_submit_ai_title_config "
                    "ADD COLUMN fallback_api_key TEXT NOT NULL DEFAULT ''"
                )
        if not statements:
            return
        from pdd_agent.core.logging import get_logger

        log = get_logger(__name__)
        for stmt in statements:
            try:
                with engine.begin() as conn:
                    conn.execute(text(stmt))
            except Exception:
                log.warning("submit_ai_title_config migration skipped: %s", stmt, exc_info=True)
    except Exception:
        return


def _ensure_daily_listing_records_columns(engine: Engine) -> None:
    """为 daily_listing_records 补充逻辑删除字段。"""
    try:
        inspector = inspect(engine)
        if "daily_listing_records" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("daily_listing_records")}
        statements: list[str] = []
        if "status" not in existing:
            statements.append(
                "ALTER TABLE daily_listing_records "
                "ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'active'"
            )
        if "delisted_at" not in existing:
            statements.append(
                "ALTER TABLE daily_listing_records ADD COLUMN delisted_at DATETIME NULL"
            )
        if not statements:
            return
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
    except Exception:
        return


def _ensure_wecom_daily_contents_columns(engine: Engine) -> None:
    """为 wecom_daily_contents 补充日报预览保存字段。"""
    try:
        inspector = inspect(engine)
        if "wecom_daily_contents" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("wecom_daily_contents")}
        statements: list[str] = []
        if "pdd_progress_summary" not in existing:
            statements.append(
                "ALTER TABLE wecom_daily_contents "
                "ADD COLUMN pdd_progress_summary TEXT NOT NULL"
            )
        if "pdd_store_progress" not in existing:
            statements.append(
                "ALTER TABLE wecom_daily_contents "
                "ADD COLUMN pdd_store_progress TEXT NOT NULL"
            )
        if "pdd_listing_window_start" not in existing:
            statements.append(
                "ALTER TABLE wecom_daily_contents "
                "ADD COLUMN pdd_listing_window_start VARCHAR(32) NOT NULL DEFAULT ''"
            )
        if "pdd_listing_window_end" not in existing:
            statements.append(
                "ALTER TABLE wecom_daily_contents "
                "ADD COLUMN pdd_listing_window_end VARCHAR(32) NOT NULL DEFAULT ''"
            )
        if "pdd_git_window_start" not in existing:
            statements.append(
                "ALTER TABLE wecom_daily_contents "
                "ADD COLUMN pdd_git_window_start VARCHAR(32) NOT NULL DEFAULT ''"
            )
        if "pdd_git_window_end" not in existing:
            statements.append(
                "ALTER TABLE wecom_daily_contents "
                "ADD COLUMN pdd_git_window_end VARCHAR(32) NOT NULL DEFAULT ''"
            )
        if "pdd_preview_saved" not in existing:
            statements.append(
                "ALTER TABLE wecom_daily_contents "
                "ADD COLUMN pdd_preview_saved TINYINT(1) NOT NULL DEFAULT 0"
            )
        if not statements:
            return
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
    except Exception:
        return


def _ensure_integrated_pipelines_created_at_index(engine: Engine) -> None:
    """为 integrated_pipelines.created_at 补充索引（list 按时间倒序）。"""
    try:
        inspector = inspect(engine)
        if "integrated_pipelines" not in inspector.get_table_names():
            return
        existing = {idx["name"] for idx in inspector.get_indexes("integrated_pipelines")}
        if "ix_integrated_pipelines_created_at" in existing:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE INDEX ix_integrated_pipelines_created_at "
                    "ON integrated_pipelines (created_at)"
                )
            )
    except Exception:
        return


def _ensure_listing_product_attributes_seed(engine: Engine) -> None:
    try:
        inspector = inspect(engine)
        if "listing_product_attributes" not in inspector.get_table_names():
            return
        from pdd_agent.db.repositories import seed_listing_product_attributes

        created = seed_listing_product_attributes()
        if created:
            from pdd_agent.core.logging import get_logger

            logger = get_logger(__name__)
            logger.info("seeded %s listing product attribute fields", created)
    except Exception:
        return


def _startup_catalog_set_index() -> tuple[dict[str, frozenset[str]], bool]:
    """启动时对齐素材目录：MinIO 已配置时用 MinIO 索引并按商品编码匹配。"""
    from pdd_agent.core.config import load_yaml_settings
    from pdd_agent.integrations.minio.config import load_minio_config, minio_configured

    cfg = load_minio_config()
    if not cfg.enabled or minio_configured(cfg):
        from pdd_agent.integrations.minio.catalog import build_minio_catalog_set_index

        return build_minio_catalog_set_index(cfg), True

    from pdd_agent.db.repositories import build_catalog_set_index

    return build_catalog_set_index(load_yaml_settings()), False


def _ensure_listed_folders_backfill(engine: Engine) -> None:
    global _listed_folders_backfill_done

    if _listed_folders_backfill_done:
        return
    try:
        inspector = inspect(engine)
        if "listed_asset_folders" not in inspector.get_table_names():
            _listed_folders_backfill_done = True
            return
        from pdd_agent.api.services.listed_folder_service import ensure_listed_folder_backfill
        from pdd_agent.db.repositories import prune_listed_folders_against_catalog
        from pdd_agent.db.repositories import prune_stale_listed_asset_folders

        created = ensure_listed_folder_backfill()
        pruned_published = prune_stale_listed_asset_folders()
        catalog_index, match_by_product_code = _startup_catalog_set_index()
        pruned_catalog = prune_listed_folders_against_catalog(
            catalog_index=catalog_index,
            match_by_product_code=match_by_product_code,
        )
        _listed_folders_backfill_done = True
        if created or pruned_published or pruned_catalog:
            from pdd_agent.core.logging import get_logger

            logger = get_logger(__name__)
            if created:
                logger.info("backfilled %s listed asset folders from published_products", created)
            if pruned_published:
                logger.info("pruned %s stale listed asset folders (published products)", pruned_published)
            if pruned_catalog:
                logger.info("pruned %s stale listed asset folders (catalog drift)", pruned_catalog)
    except Exception:
        return


def init_database() -> bool:
    """初始化数据库连接与表结构；未配置 DATABASE_URL 时返回 False。"""
    global _engine, _sessionmaker, _available, _initializing, _last_error

    if _available is not None:
        return _available
    if _initializing:
        return _sessionmaker is not None

    env = get_env_settings()
    database_url = (env.database_url or "").strip()
    if not database_url:
        _available = False
        _last_error = "DATABASE_URL 未配置"
        return False

    _initializing = True
    try:
        _create_mysql_database_if_missing(database_url)
        engine = create_engine(
            database_url,
            echo=env.database_echo,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=max(1, int(env.database_pool_size or 5)),
            max_overflow=max(0, int(env.database_max_overflow or 5)),
            pool_timeout=max(5, int(env.database_pool_timeout or 30)),
            future=True,
        )
        Base.metadata.create_all(engine)
        _ensure_task_queue_claim_index(engine)
        _ensure_accounts_columns(engine)
        _ensure_login_statuses_columns(engine)
        _ensure_published_products_columns(engine)
        _ensure_failure_sequential_job_columns(engine)
        _ensure_failure_sequential_batch_columns(engine)
        _ensure_inventory_delist_records_columns(engine)
        _ensure_listing_submit_ai_title_config_columns(engine)
        _ensure_daily_listing_records_columns(engine)
        _ensure_wecom_daily_contents_columns(engine)
        _ensure_integrated_pipelines_created_at_index(engine)
        # seed / backfill 会调用 is_database_available()，须先发布 session，避免 init 递归
        _engine = engine
        _sessionmaker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        _available = True
        _last_error = ""
        _ensure_listing_product_attributes_seed(engine)
        _ensure_listed_folders_backfill(engine)
        return True
    except Exception as exc:
        _engine = None
        _sessionmaker = None
        _available = False
        _last_error = str(exc)
        return False
    finally:
        _initializing = False


def is_database_available() -> bool:
    return init_database()


def database_status() -> dict[str, str | bool]:
    env = get_env_settings()
    available = init_database()
    return {
        "configured": bool((env.database_url or "").strip()),
        "available": available,
        "error": "" if available else _last_error,
    }


@contextmanager
def session_scope() -> Iterator[Session]:
    if not init_database() or _sessionmaker is None:
        raise RuntimeError(_last_error or "数据库不可用")

    session = _sessionmaker()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
