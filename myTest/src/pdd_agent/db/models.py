"""数据库 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.mysql import JSON as MySQLJSON
from sqlalchemy.orm import Mapped, mapped_column

from pdd_agent.db.base import Base


class AccountORM(Base):
    """店铺账号。"""

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    username: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    shop_display_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
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
    shop_display_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
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
    __table_args__ = (
        Index("ix_task_queue_claim", "status", "scheduled_at", "account_id"),
    )

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


class ListedAssetFolderORM(Base):
    """已上架素材文件夹（普通上架与整合链路共用）。"""

    __tablename__ = "listed_asset_folders"
    __table_args__ = (
        Index("ix_listed_asset_folders_account_selector", "account_id", "folder_selector"),
    )

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    folder_selector: Mapped[str] = mapped_column(String(512), index=True, nullable=False)
    family_code: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    image_set: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    listing_label: Mapped[str] = mapped_column(String(255), index=True, default="", nullable=False)
    asset_path: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), index=True, default="listing", nullable=False)
    pipeline_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    pdd_product_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    listed_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IntegratedPipelineORM(Base):
    """上架 → 活动 → 推广 整合链路。"""

    __tablename__ = "integrated_pipelines"

    pipeline_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    current_step: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    product_codes: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    activity_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    auto_promotion: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    activity_delay_hours: Mapped[float] = mapped_column(Float, default=24.0, nullable=False)
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    listing_run_id: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    campaign_run_id: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    traffic_run_id: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    pdd_product_ids: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    mapping_ids: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    scheduled_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta: Mapped[dict] = mapped_column(MySQLJSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IntegratedPipelineIssueReportORM(Base):
    """整合链路专用报错记录（独立于 listing_failure_details / run_records 日志）。"""

    __tablename__ = "integrated_pipeline_issue_reports"

    issue_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    batch_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    stage: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    chain_step: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), index=True, default="error", nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    context: Mapped[dict | None] = mapped_column(MySQLJSON, nullable=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    activity_id: Mapped[str] = mapped_column(String(32), default="", index=True, nullable=False)
    product_selector: Mapped[str] = mapped_column(String(512), default="", index=True, nullable=False)
    source_location: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True, nullable=False
    )


class IntegratedPipelineListingSkipORM(Base):
    """整合链路上架前跳过明细：平台跳过去重 / 笔袋视图无编码。"""

    __tablename__ = "integrated_pipeline_listing_skips"
    __table_args__ = (
        Index("ix_pipeline_listing_skips_pipeline_kind", "pipeline_id", "skip_kind"),
    )

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    listing_run_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    skip_kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    product_selector: Mapped[str] = mapped_column(String(512), default="", index=True, nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(128), default="", index=True, nullable=False)
    listing_label: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True, nullable=False
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


class DailyListingRecordORM(Base):
    """每日上架成功记录（追加日志，用于统计当天上架商品数）。"""

    __tablename__ = "daily_listing_records"
    __table_args__ = (
        Index("ix_daily_listing_records_listed_at_account", "listed_at", "account_id"),
        Index("ix_daily_listing_records_run_product", "source_run_id", "pdd_product_id"),
        Index("ix_daily_listing_records_status", "status"),
    )

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    shop_display_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    pdd_product_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    product_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    family_code: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    image_set: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    listing_label: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    source_run_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), index=True, default="listing", nullable=False)
    pipeline_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    listed_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class DailyCycleRelistRecordORM(Base):
    """失败日志循环上架：每日触发整合链路记录。"""

    __tablename__ = "daily_cycle_relist_records"
    __table_args__ = (
        Index("ix_daily_cycle_relist_triggered_at_account", "triggered_at", "account_id"),
    )

    record_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    feishu_record_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    shop_display_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(255), index=True, default="", nullable=False)
    pipeline_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    product_codes: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    report_platform: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(32), index=True, default="auto_watch", nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class FailureCycleRelistPollLogORM(Base):
    """失败日志循环上架：每次轮询拉取的候选快照。"""

    __tablename__ = "failure_cycle_relist_poll_logs"
    __table_args__ = (
        Index("ix_failure_cycle_relist_poll_polled_at", "polled_at"),
    )

    poll_log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    polled_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    candidate_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fetch_mode: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    fetch_page_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    table_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    table_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    candidates: Mapped[list[dict]] = mapped_column(MySQLJSON, default=list, nullable=False)
    new_candidates: Mapped[list[dict]] = mapped_column(MySQLJSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class FailureCycleRelistActionLogORM(Base):
    """失败日志循环上架：单条候选的处理结果。"""

    __tablename__ = "failure_cycle_relist_action_logs"
    __table_args__ = (
        Index("ix_failure_cycle_relist_action_at", "action_at"),
        Index("ix_failure_cycle_relist_action_feishu_record", "feishu_record_id"),
    )

    action_log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    poll_log_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    feishu_record_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    account_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    report_platform: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    pipeline_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(32), default="auto_watch", nullable=False)
    action_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )


class FailureSequentialJobORM(Base):
    """失败日志分阶段流水线：上架 → 限时限量购 → 活动 → 推广（独立于整合链路）。"""

    __tablename__ = "failure_sequential_jobs"
    __table_args__ = (
        Index("ix_failure_seq_jobs_batch_phase", "batch_id", "current_phase"),
        Index("ix_failure_seq_jobs_feishu", "feishu_record_id"),
        Index("ix_failure_seq_jobs_overall", "overall_status"),
    )

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    feishu_record_id: Mapped[str] = mapped_column(String(64), nullable=False)
    merchant_code: Mapped[str] = mapped_column(String(255), index=True, default="", nullable=False)
    account_id: Mapped[str] = mapped_column(String(64), index=True, default="", nullable=False)
    account_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    failure_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    report_platform: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    product_codes: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    current_phase: Mapped[str] = mapped_column(String(32), index=True, default="listing", nullable=False)
    overall_status: Mapped[str] = mapped_column(String(32), index=True, default="active", nullable=False)
    pdd_product_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    mapping_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    listing_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    listing_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    listing_run_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    limited_time_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    limited_time_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    limited_time_run_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    limited_time_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activity_618_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    activity_618_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    activity_618_run_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    activity_discount_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    activity_discount_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    activity_discount_run_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    promotion_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    promotion_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    promotion_run_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    meta: Mapped[dict] = mapped_column(MySQLJSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FailureSequentialBatchORM(Base):
    """失败日志分阶段流水线批次状态。"""

    __tablename__ = "failure_sequential_batches"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="listing", nullable=False)
    job_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    listing_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    limited_time_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activity_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    promotion_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activity_unlocked: Mapped[bool] = mapped_column(default=False, nullable=False)
    activity_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activity_unlocked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AccountLifecycleORM(Base):
    """店铺当前运营周期（一店一行；周期结束后删除）。"""

    __tablename__ = "account_lifecycles"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lifecycle_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    owner_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    phase: Mapped[str] = mapped_column(String(32), index=True, default="listing", nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(16), index=True, default="active", nullable=False)
    wake_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    product_selectors: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CommerceIntentORM(Base):
    """待执行的整合链路上架意图（四入口统一排队）。"""

    __tablename__ = "commerce_intents"
    __table_args__ = (
        Index("ix_commerce_intents_account_status", "account_id", "status", "priority"),
        Index("ix_commerce_intents_dedupe", "dedupe_key", "status"),
    )

    intent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    product_selectors: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    payload: Mapped[dict] = mapped_column(MySQLJSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), index=True, default="pending", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), index=True, default="", nullable=False)
    block_reason: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    block_detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result_pipeline_id: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    result_owner_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True, nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ProductClaimORM(Base):
    """商品占用（防止同套图被多入口重复启动）。"""

    __tablename__ = "product_claims"

    claim_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    lifecycle_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    intent_id: Mapped[str] = mapped_column(String(64), default="", index=True, nullable=False)
    listing_selector: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ListingProductAttributeORM(Base):
    """上架商品属性：拼多多发布页「商品属性」下拉选项与当前选中值。"""

    __tablename__ = "listing_product_attributes"

    field_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_value: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    options: Mapped[list[str]] = mapped_column(MySQLJSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
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
