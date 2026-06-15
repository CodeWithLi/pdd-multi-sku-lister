"""数据库 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy.orm import Mapped, mapped_column

from pdd_agent.db.base import Base


class AccountORM(Base):
    """店铺账号。"""

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    password: Mapped[str] = mapped_column(Text, default="", nullable=False)
    product_codes: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class RunRecordORM(Base):
    """任务运行记录。"""

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LoginStatusORM(Base):
    """店铺登录状态。"""

    __tablename__ = "login_statuses"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    current_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TaskQueueORM(Base):
    """持久任务队列。"""

    __tablename__ = "task_queue"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    agent: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    payload: Mapped[dict] = mapped_column(MySQLJSON, default=dict, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QueueControlORM(Base):
    """Task queue global/account pause controls."""

    __tablename__ = "queue_controls"

    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="")
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ListingFailureDetailORM(Base):
    """上架失败明细：阶段、原因码与上下文，供人工排查。"""

    __tablename__ = "listing_failure_details"

    detail_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    failure_item_id: Mapped[str] = mapped_column(String(128), default="", index=True, nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    listing_label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    image_set: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    family_code: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    phase: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    step: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="error", nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    detail: Mapped[dict | None] = mapped_column(MySQLJSON, nullable=True)
    screenshot_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    page_url: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True, nullable=False
    )


class FailureItemORM(Base):
    """Manual workflow state for failed listing items."""

    __tablename__ = "failure_items"

    item_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    listing_label: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    image_set: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    item_status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    decision_status: Mapped[str] = mapped_column(String(32), index=True, default="open", nullable=False)
    decision_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    retry_run_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PublishedProductORM(Base):
    """店铺上架成功后的拼多多商品映射。"""

    __tablename__ = "published_products"

    mapping_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    family_code: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    image_set: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    listing_label: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(255), index=True, default="", nullable=False)
    pdd_product_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    spec_metadata: Mapped[dict | None] = mapped_column(MySQLJSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="on_sale", nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AccountLockORM(Base):
    """店铺 Profile 运行锁。"""

    __tablename__ = "account_locks"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductStyleColorORM(Base):
    """商品编码 → AI/人工识别的款式颜色（缓存，省 token）。"""

    __tablename__ = "product_style_colors"

    product_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    color_label: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="ai", nullable=False)
    image_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    image_mtime: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
