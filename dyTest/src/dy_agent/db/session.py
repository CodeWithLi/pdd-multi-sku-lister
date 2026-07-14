"""SQLAlchemy engine/session 管理。"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from dy_agent.core.config import get_env_settings
from dy_agent.db.base import Base
import dy_agent.db.models  # noqa: F401

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None
_available: bool | None = None
_initializing: bool = False
_last_error: str = ""


def _create_mysql_database_if_missing(database_url: str) -> None:
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


def _ensure_accounts_columns(engine: Engine) -> None:
    try:
        inspector = inspect(engine)
        if "accounts" not in inspector.get_table_names():
            return
        existing = {col["name"] for col in inspector.get_columns("accounts")}
        with engine.begin() as conn:
            if "phone" not in existing:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN phone VARCHAR(32) NOT NULL DEFAULT ''"))
            if "login_mode" not in existing:
                conn.execute(
                    text("ALTER TABLE accounts ADD COLUMN login_mode VARCHAR(32) NOT NULL DEFAULT 'sms'")
                )
            if "shop_display_name" not in existing:
                conn.execute(
                    text("ALTER TABLE accounts ADD COLUMN shop_display_name VARCHAR(128) NOT NULL DEFAULT ''")
                )
    except Exception:
        return


def init_database() -> bool:
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
        _ensure_accounts_columns(engine)
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
