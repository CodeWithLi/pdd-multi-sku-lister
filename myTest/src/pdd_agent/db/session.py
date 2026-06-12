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
            future=True,
        )
        Base.metadata.create_all(engine)
        _ensure_published_products_columns(engine)
        _engine = engine
        _sessionmaker = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        _available = True
        _last_error = ""
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
