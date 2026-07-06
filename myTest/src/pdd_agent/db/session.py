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
        if not statements:
            return
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))
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


def _ensure_listed_folders_backfill(engine: Engine) -> None:
    try:
        inspector = inspect(engine)
        if "listed_asset_folders" not in inspector.get_table_names():
            return
        from pdd_agent.api.services.listed_folder_service import ensure_listed_folder_backfill
        from pdd_agent.core.config import load_yaml_settings
        from pdd_agent.db.repositories import build_catalog_set_index, prune_listed_folders_against_catalog
        from pdd_agent.db.repositories import prune_stale_listed_asset_folders

        created = ensure_listed_folder_backfill()
        pruned_published = prune_stale_listed_asset_folders()
        catalog_index = build_catalog_set_index(load_yaml_settings())
        pruned_catalog = prune_listed_folders_against_catalog(catalog_index=catalog_index)
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
    global _engine, _sessionmaker, _available, _last_error

    if _available is not None:
        return _available

    env = get_env_settings()
    database_url = (env.database_url or "").strip()
    if not database_url:
        _available = False
        _last_error = "DATABASE_URL 未配置"
        return False

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
        _ensure_daily_listing_records_columns(engine)
        _ensure_integrated_pipelines_created_at_index(engine)
        _ensure_listing_product_attributes_seed(engine)
        _engine = engine
        _sessionmaker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        _available = True
        _last_error = ""
        # backfill 会调用 is_database_available()，须在 _available=True 之后执行，避免 init 重入
        _ensure_listed_folders_backfill(engine)
        return True
    except Exception as exc:
        _engine = None
        _sessionmaker = None
        _available = False
        _last_error = str(exc)
        return False


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
