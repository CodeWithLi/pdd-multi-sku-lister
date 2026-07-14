"""数据库 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy.orm import Mapped, mapped_column

from dy_agent.db.base import Base


class AccountORM(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    username: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    password: Mapped[str] = mapped_column(Text, default="", nullable=False)
    login_mode: Mapped[str] = mapped_column(String(32), default="sms", nullable=False)
    shop_display_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    product_codes: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LoginStatusORM(Base):
    __tablename__ = "login_statuses"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    shop_display_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RunRecordORM(Base):
    __tablename__ = "run_records"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    listing_labels: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    artifacts: Mapped[dict[str, str]] = mapped_column(MySQLJSON, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(MySQLJSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PublishedProductORM(Base):
    """抖店上架成功后的商品映射（先落库，飞书同步后续再接）。"""

    __tablename__ = "published_products"
    __table_args__ = (
        Index("ix_published_products_account_dy_id", "account_id", "dy_product_id"),
    )

    mapping_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    family_code: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    image_set: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    listing_label: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(255), index=True, default="", nullable=False)
    dy_product_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    list_status: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    platform_status: Mapped[str] = mapped_column(String(32), default="on_sale", nullable=False)
    product_link: Mapped[str] = mapped_column(Text, default="", nullable=False)
    listed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    capture_meta: Mapped[dict | None] = mapped_column(MySQLJSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
