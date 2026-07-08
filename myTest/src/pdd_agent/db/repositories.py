"""数据库仓储函数。"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError

from pdd_agent.core.config import AccountConfig, YamlSettings
from pdd_agent.db.models import (
    AccountLockORM,
    AccountORM,
    FailureItemORM,
    IntegratedPipelineIssueReportORM,
    IntegratedPipelineORM,
    ListingFailureDetailORM,
    ListingProductAttributeORM,
    LoginStatusORM,
    ProductStyleColorORM,
    PublishedProductORM,
    QueueControlORM,
    DailyCycleRelistRecordORM,
    DailyListingRecordORM,
    FailureCycleRelistActionLogORM,
    FailureCycleRelistPollLogORM,
    InventoryDelistRecordORM,
    ListedAssetFolderORM,
    RunRecordORM,
    TaskQueueORM,
    WecomDailyContentORM,
    WecomGitDigestCacheORM,
    WecomDailyReportLogORM,
)
from pdd_agent.db.session import is_database_available, session_scope


def db_accounts_enabled() -> bool:
    return is_database_available()


def _to_account_config(row: AccountORM) -> AccountConfig:
    return AccountConfig(
        account_id=row.account_id,
        enabled=row.enabled,
        username=row.username or "",
        password=row.password or "",
        product_codes=list(row.product_codes or []),
    )


def seed_accounts_from_yaml(settings: YamlSettings) -> None:
    """数据库 accounts 为空时，用 settings.yaml 里的账号做一次初始导入。"""
    if not is_database_available():
        return
    with session_scope() as session:
        exists = session.scalar(select(AccountORM.account_id).limit(1))
        if exists or not settings.accounts:
            return
        for acc in settings.accounts:
            session.add(
                AccountORM(
                    account_id=acc.account_id,
                    enabled=acc.enabled,
                    username=acc.username,
                    password=acc.password,
                    product_codes=list(acc.product_codes),
                )
            )


def list_account_configs(settings: YamlSettings, *, enabled_only: bool = False) -> list[AccountConfig]:
    if not is_database_available():
        return [a for a in settings.accounts if not enabled_only or a.enabled]

    seed_accounts_from_yaml(settings)
    with session_scope() as session:
        stmt = select(AccountORM).order_by(AccountORM.account_id)
        if enabled_only:
            stmt = stmt.where(AccountORM.enabled.is_(True))
        return [_to_account_config(row) for row in session.scalars(stmt).all()]


def get_account_config(settings: YamlSettings, account_id: str) -> AccountConfig | None:
    if not is_database_available():
        return next((a for a in settings.accounts if a.account_id == account_id), None)

    seed_accounts_from_yaml(settings)
    with session_scope() as session:
        row = session.get(AccountORM, account_id)
        return _to_account_config(row) if row else None


def create_account_config(acc: AccountConfig) -> AccountConfig:
    with session_scope() as session:
        session.add(
            AccountORM(
                account_id=acc.account_id,
                enabled=acc.enabled,
                username=acc.username,
                password=acc.password,
                product_codes=list(acc.product_codes),
            )
        )
    return acc


def update_account_config(account_id: str, data: AccountConfig, *, keep_empty_password: bool) -> AccountConfig | None:
    with session_scope() as session:
        row = session.get(AccountORM, account_id)
        if not row:
            return None
        row.enabled = data.enabled
        row.username = data.username
        if data.password or not keep_empty_password:
            row.password = data.password
        row.product_codes = list(data.product_codes)
        session.flush()
        return _to_account_config(row)


def delete_account_config(account_id: str) -> bool:
    with session_scope() as session:
        row = session.get(AccountORM, account_id)
        if not row:
            return False
        session.delete(row)
        return True


def list_login_status_rows() -> list[LoginStatusORM]:
    if not is_database_available():
        return []
    with session_scope() as session:
        return list(session.scalars(select(LoginStatusORM).order_by(LoginStatusORM.account_id)).all())


def get_login_status_row(account_id: str) -> LoginStatusORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        return session.get(LoginStatusORM, account_id)


def get_cached_shop_display_name(account_id: str) -> str:
    aid = str(account_id or "").strip()
    if not aid or not is_database_available():
        return ""
    with session_scope() as session:
        acc = session.get(AccountORM, aid)
        if acc and str(acc.shop_display_name or "").strip():
            return str(acc.shop_display_name).strip()
        row = session.get(LoginStatusORM, aid)
        if row and str(row.shop_display_name or "").strip():
            return str(row.shop_display_name).strip()
    return ""


def list_enabled_account_ids_by_shop_display_name(display_name: str) -> list[str]:
    """按 accounts 表 shop_display_name 精确匹配已启用账号。"""
    name = str(display_name or "").strip()
    if not name or not is_database_available():
        return []
    with session_scope() as session:
        rows = session.scalars(
            select(AccountORM.account_id)
            .where(AccountORM.enabled.is_(True))
            .where(AccountORM.shop_display_name == name)
            .order_by(AccountORM.account_id)
        ).all()
        return [str(aid) for aid in rows if str(aid or "").strip()]


def update_shop_display_name(account_id: str, shop_display_name: str) -> None:
    name = str(shop_display_name or "").strip()
    aid = str(account_id or "").strip()
    if not aid or not name:
        return
    if not is_database_available():
        print(f"[{aid}] [警告] 数据库未连接，跳过写入 shop_display_name={name}", flush=True)
        return
    with session_scope() as session:
        acc = session.get(AccountORM, aid)
        if acc:
            acc.shop_display_name = name
        row = session.get(LoginStatusORM, aid)
        if row:
            row.shop_display_name = name
        else:
            session.add(
                LoginStatusORM(
                    account_id=aid,
                    status="unknown",
                    shop_display_name=name,
                )
            )


def upsert_login_status(
    *,
    account_id: str,
    status: str,
    reason: str = "",
    current_url: str = "",
    checked_at: datetime | None = None,
) -> None:
    if not is_database_available():
        return
    with session_scope() as session:
        row = session.get(LoginStatusORM, account_id)
        data = {
            "status": status,
            "reason": reason,
            "current_url": current_url,
            "checked_at": checked_at or datetime.now(),
        }
        if row:
            for key, value in data.items():
                setattr(row, key, value)
        else:
            session.add(LoginStatusORM(account_id=account_id, **data))


def enqueue_task(
    *,
    agent: str,
    run_id: str,
    account_id: str,
    payload: dict,
    scheduled_at: datetime,
    max_attempts: int = 1,
) -> TaskQueueORM:
    task = TaskQueueORM(
        task_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8],
        run_id=run_id,
        agent=agent,
        account_id=account_id,
        status="queued",
        payload=dict(payload),
        scheduled_at=scheduled_at,
        max_attempts=max_attempts,
    )
    with session_scope() as session:
        session.add(task)
        session.flush()
        session.expunge(task)
    return task


def requeue_interrupted_tasks() -> int:
    if not is_database_available():
        return 0
    terminal_pipeline_statuses = frozenset({"completed", "failed", "canceled"})
    with session_scope() as session:
        rows = session.scalars(
            select(TaskQueueORM).where(TaskQueueORM.status == "running")
        ).all()
        now = datetime.now()
        account_ids: set[str] = set()
        requeued = 0
        for row in rows:
            payload = dict(row.payload or {})
            pipeline_id = str(payload.get("pipeline_id") or "").strip()
            if pipeline_id:
                pipe = session.get(IntegratedPipelineORM, pipeline_id)
                if pipe and str(pipe.status or "") in terminal_pipeline_statuses:
                    row.status = "canceled"
                    row.finished_at = now
                    row.error = "pipeline terminal; skip requeue after worker restart"
                    continue
            row.status = "queued"
            row.error = "requeued after worker restart"
            row.started_at = None
            row.scheduled_at = now
            if row.account_id:
                account_ids.add(row.account_id)
            requeued += 1
        for account_id in account_ids:
            lock = session.get(AccountLockORM, account_id)
            if lock:
                session.delete(lock)
        return requeued


def count_running_queue_tasks() -> int:
    if not is_database_available():
        return 0
    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count()).select_from(TaskQueueORM).where(TaskQueueORM.status == "running")
            )
            or 0
        )


def list_listing_run_ids_for_pipeline(pipeline_id: str) -> list[str]:
    """按创建顺序返回整合链路上架子任务的 run_id（用于分批状态回填）。"""
    if not is_database_available():
        return []
    pipeline_id = str(pipeline_id or "").strip()
    if not pipeline_id:
        return []
    with session_scope() as session:
        rows = session.scalars(
            select(TaskQueueORM.run_id)
            .where(
                TaskQueueORM.agent == "listing",
                TaskQueueORM.payload["pipeline_id"].as_string() == pipeline_id,
            )
            .order_by(TaskQueueORM.created_at.asc())
        ).all()
    seen: set[str] = set()
    ordered: list[str] = []
    for run_id in rows:
        rid = str(run_id or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        ordered.append(rid)
    return ordered


def queue_status_counts() -> dict[str, int]:
    """队列统计：等待/运行=当前活跃；成功/失败=近 24 小时完成数。"""
    if not is_database_available():
        return {}
    since = datetime.now() - timedelta(hours=24)
    with session_scope() as session:
        counts: dict[str, int] = {}
        for status in ("queued", "running", "canceled"):
            counts[status] = int(
                session.scalar(
                    select(func.count()).select_from(TaskQueueORM).where(TaskQueueORM.status == status)
                )
                or 0
            )
        for status in ("success", "failed"):
            counts[status] = int(
                session.scalar(
                    select(func.count())
                    .select_from(TaskQueueORM)
                    .where(TaskQueueORM.status == status, TaskQueueORM.finished_at >= since)
                )
                or 0
            )
        return counts


def list_queue_rows_for_display(*, limit: int = 50, account_id: str = "") -> list[TaskQueueORM]:
    """优先展示运行中/等待中任务，再补最近完成记录。"""
    if not is_database_available():
        return []
    limit = max(1, min(500, limit))
    with session_scope() as session:
        active_stmt = select(TaskQueueORM).where(TaskQueueORM.status.in_(("running", "queued")))
        if account_id:
            active_stmt = active_stmt.where(TaskQueueORM.account_id == account_id)
        active_stmt = active_stmt.order_by(
            case((TaskQueueORM.status == "running", 0), else_=1),
            TaskQueueORM.scheduled_at.asc(),
            TaskQueueORM.created_at.asc(),
        )
        active_rows = list(session.scalars(active_stmt).all())

        remaining = limit - len(active_rows)
        done_rows: list[TaskQueueORM] = []
        if remaining > 0:
            done_stmt = select(TaskQueueORM).where(
                TaskQueueORM.status.in_(("success", "failed", "canceled"))
            )
            if account_id:
                done_stmt = done_stmt.where(TaskQueueORM.account_id == account_id)
            done_stmt = done_stmt.order_by(
                TaskQueueORM.finished_at.desc(),
                TaskQueueORM.created_at.desc(),
            ).limit(remaining)
            done_rows = list(session.scalars(done_stmt).all())

        rows = active_rows + done_rows
        for row in rows:
            session.expunge(row)
        return rows


def list_queue_rows(*, limit: int = 100, status: str = "", account_id: str = "") -> list[TaskQueueORM]:
    if not is_database_available():
        return []
    limit = max(1, min(500, limit))
    with session_scope() as session:
        stmt = select(TaskQueueORM)
        if status:
            stmt = stmt.where(TaskQueueORM.status == status)
        if account_id:
            stmt = stmt.where(TaskQueueORM.account_id == account_id)
        stmt = stmt.order_by(TaskQueueORM.scheduled_at.asc(), TaskQueueORM.created_at.asc()).limit(limit)
        rows = list(session.scalars(stmt).all())
        for row in rows:
            session.expunge(row)
        return rows


def is_queue_paused(*, account_id: str = "") -> bool:
    if not is_database_available():
        return False
    with session_scope() as session:
        global_row = session.get(QueueControlORM, ("global", ""))
        if global_row and global_row.paused:
            return True
        if account_id:
            account_row = session.get(QueueControlORM, ("account", account_id))
            return bool(account_row and account_row.paused)
        return False


def get_queue_controls() -> list[QueueControlORM]:
    if not is_database_available():
        return []
    with session_scope() as session:
        rows = list(session.scalars(select(QueueControlORM).order_by(QueueControlORM.scope, QueueControlORM.account_id)).all())
        for row in rows:
            session.expunge(row)
        return rows


def set_queue_pause(*, paused: bool, reason: str = "", account_id: str = "") -> None:
    if not is_database_available():
        return
    scope = "account" if account_id else "global"
    key = account_id if account_id else ""
    with session_scope() as session:
        row = session.get(QueueControlORM, (scope, key))
        if row:
            row.paused = paused
            row.reason = reason
        else:
            session.add(
                QueueControlORM(
                    scope=scope,
                    account_id=key,
                    paused=paused,
                    reason=reason,
                )
            )


def _busy_account_ids_for_claim(session) -> set[str]:
    running_accounts = set(
        session.scalars(
            select(TaskQueueORM.account_id).where(TaskQueueORM.status == "running")
        ).all()
    )
    paused_accounts = set(
        session.scalars(
            select(QueueControlORM.account_id).where(
                QueueControlORM.scope == "account",
                QueueControlORM.paused.is_(True),
            )
        ).all()
    )
    return {acc for acc in running_accounts | paused_accounts if acc}


def list_busy_account_ids() -> set[str]:
    """队列运行中、账号暂停或 Profile 锁未过期的 account_id。"""
    if not is_database_available():
        return set()
    now = datetime.now()
    with session_scope() as session:
        busy = _busy_account_ids_for_claim(session)
        locked = set(
            session.scalars(
                select(AccountLockORM.account_id).where(AccountLockORM.expires_at > now)
            ).all()
        )
        busy.update(acc for acc in locked if acc)
        return busy


def count_account_queue_tasks(
    account_id: str,
    *,
    statuses: tuple[str, ...] = ("queued",),
) -> int:
    """统计某店铺在任务队列中指定状态的任务数。"""
    if not is_database_available():
        return 0
    account_id = str(account_id or "").strip()
    if not account_id:
        return 0
    with session_scope() as session:
        stmt = (
            select(func.count())
            .select_from(TaskQueueORM)
            .where(TaskQueueORM.account_id == account_id)
        )
        if statuses:
            stmt = stmt.where(TaskQueueORM.status.in_(statuses))
        return int(session.scalar(stmt) or 0)


def claim_due_task(max_concurrent: int) -> TaskQueueORM | None:
    if not is_database_available():
        return None
    if is_queue_paused():
        return None
    with session_scope() as session:
        running_count = int(
            session.scalar(
                select(func.count()).select_from(TaskQueueORM).where(TaskQueueORM.status == "running")
            )
            or 0
        )
        if running_count >= max_concurrent:
            return None

        exclude_accounts = _busy_account_ids_for_claim(session)

        stmt = (
            select(TaskQueueORM)
            .where(TaskQueueORM.status == "queued")
            .where(TaskQueueORM.scheduled_at <= datetime.now())
            .order_by(TaskQueueORM.scheduled_at.asc(), TaskQueueORM.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if exclude_accounts:
            stmt = stmt.where(TaskQueueORM.account_id.notin_(exclude_accounts))

        row = session.scalar(stmt)
        if not row:
            return None
        row.status = "running"
        row.started_at = datetime.now()
        row.attempts += 1
        row.error = ""
        session.flush()
        session.expunge(row)
        return row


def finish_queue_task(task_id: str, *, success: bool, error: str = "") -> None:
    if not is_database_available():
        return
    with session_scope() as session:
        row = session.get(TaskQueueORM, task_id)
        if not row:
            return
        if row.status == "canceled":
            return
        row.status = "success" if success else "failed"
        row.finished_at = datetime.now()
        row.error = error


def cancel_running_tasks(*, account_id: str = "") -> list[dict[str, str]]:
    """将运行中的队列任务标为 canceled，并释放对应店铺锁。"""
    if not is_database_available():
        return []
    with session_scope() as session:
        stmt = select(TaskQueueORM).where(TaskQueueORM.status == "running")
        if account_id:
            stmt = stmt.where(TaskQueueORM.account_id == account_id)
        rows = list(session.scalars(stmt).all())
        now = datetime.now()
        out: list[dict[str, str]] = []
        account_ids: set[str] = set()
        for row in rows:
            row.status = "canceled"
            row.finished_at = now
            row.error = "canceled by user"
            if row.account_id:
                account_ids.add(row.account_id)
            out.append(
                {
                    "task_id": row.task_id,
                    "run_id": row.run_id,
                    "account_id": row.account_id or "",
                }
            )
        for acc in account_ids:
            lock = session.get(AccountLockORM, acc)
            if lock:
                session.delete(lock)
        return out


def cancel_queued_task_by_run_id(run_id: str) -> bool:
    if not is_database_available():
        return False
    with session_scope() as session:
        row = session.scalar(
            select(TaskQueueORM).where(
                TaskQueueORM.run_id == run_id,
                TaskQueueORM.status == "queued",
            )
        )
        if not row:
            return False
        row.status = "canceled"
        row.finished_at = datetime.now()
        row.error = "canceled by user"
        return True


def cancel_queue_tasks_by_run_ids(run_ids: list[str]) -> list[dict[str, str]]:
    """取消指定 run_id 的排队中或运行中队列任务。"""
    ids = [str(run_id or "").strip() for run_id in run_ids if str(run_id or "").strip()]
    if not ids or not is_database_available():
        return []
    with session_scope() as session:
        stmt = select(TaskQueueORM).where(
            TaskQueueORM.run_id.in_(ids),
            TaskQueueORM.status.in_(("queued", "running")),
        )
        rows = list(session.scalars(stmt).all())
        now = datetime.now()
        out: list[dict[str, str]] = []
        account_ids: set[str] = set()
        for row in rows:
            row.status = "canceled"
            row.finished_at = now
            row.error = "canceled by user"
            if row.account_id:
                account_ids.add(row.account_id)
            out.append(
                {
                    "task_id": row.task_id,
                    "run_id": row.run_id,
                    "account_id": row.account_id or "",
                }
            )
        for acc in account_ids:
            still_running = session.scalar(
                select(func.count())
                .select_from(TaskQueueORM)
                .where(TaskQueueORM.account_id == acc, TaskQueueORM.status == "running")
            )
            if not still_running:
                lock = session.get(AccountLockORM, acc)
                if lock:
                    session.delete(lock)
        return out


def cancel_queued_tasks(*, account_id: str = "") -> list[str]:
    if not is_database_available():
        return []
    with session_scope() as session:
        stmt = select(TaskQueueORM).where(TaskQueueORM.status == "queued")
        if account_id:
            stmt = stmt.where(TaskQueueORM.account_id == account_id)
        rows = list(session.scalars(stmt).all())
        run_ids: list[str] = []
        now = datetime.now()
        for row in rows:
            row.status = "canceled"
            row.finished_at = now
            row.error = "canceled by user"
            run_ids.append(row.run_id)
        return run_ids


def upsert_failure_item(
    *,
    item_id: str,
    source_run_id: str,
    account_id: str,
    listing_label: str,
    product_code: str,
    image_set: str,
    merchant_code: str,
    item_status: str,
    reason: str,
    error: str,
    retryable: bool,
) -> FailureItemORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(FailureItemORM, item_id)
        data = {
            "source_run_id": source_run_id,
            "account_id": account_id,
            "listing_label": listing_label,
            "product_code": product_code,
            "image_set": image_set,
            "merchant_code": merchant_code,
            "item_status": item_status,
            "reason": reason,
            "error": error,
            "retryable": retryable,
        }
        if row:
            for key, value in data.items():
                setattr(row, key, value)
        else:
            row = FailureItemORM(item_id=item_id, **data)
            session.add(row)
        session.flush()
        session.expunge(row)
        return row


def get_failure_item(item_id: str) -> FailureItemORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(FailureItemORM, item_id)
        if row:
            session.expunge(row)
        return row


def search_failure_items(
    *,
    page: int = 1,
    page_size: int = 50,
    account_id: str = "",
    item_status: str = "",
    decision_status: str = "",
    product_code: str = "",
) -> tuple[list[FailureItemORM], int]:
    if not is_database_available():
        return [], 0
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    with session_scope() as session:
        query = session.query(FailureItemORM)
        if account_id:
            query = query.filter(FailureItemORM.account_id == account_id)
        if item_status:
            query = query.filter(FailureItemORM.item_status == item_status)
        if decision_status:
            query = query.filter(FailureItemORM.decision_status == decision_status)
        if product_code:
            pattern = f"%{product_code}%"
            query = query.filter(
                (FailureItemORM.product_code.like(pattern))
                | (FailureItemORM.listing_label.like(pattern))
                | (FailureItemORM.merchant_code.like(pattern))
            )
        total = int(query.order_by(None).count())
        rows = (
            query.order_by(FailureItemORM.updated_at.desc(), FailureItemORM.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows, total


def update_failure_decision(
    *,
    item_id: str,
    decision_status: str,
    decision_note: str = "",
    retry_run_id: str = "",
) -> FailureItemORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(FailureItemORM, item_id)
        if not row:
            return None
        row.decision_status = decision_status
        if decision_note:
            row.decision_note = decision_note
        if retry_run_id:
            row.retry_run_id = retry_run_id
        session.flush()
        session.expunge(row)
        return row


def insert_listing_failure_detail(
    *,
    detail_id: str,
    failure_item_id: str = "",
    source_run_id: str = "",
    account_id: str = "",
    listing_label: str = "",
    product_code: str = "",
    image_set: str = "",
    family_code: str = "",
    merchant_code: str = "",
    phase: str = "",
    step: str = "",
    severity: str = "error",
    reason_code: str = "",
    message: str = "",
    error: str = "",
    detail: dict | None = None,
    screenshot_path: str = "",
    page_url: str = "",
) -> ListingFailureDetailORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = ListingFailureDetailORM(
            detail_id=detail_id,
            failure_item_id=failure_item_id,
            source_run_id=source_run_id,
            account_id=account_id,
            listing_label=listing_label,
            product_code=product_code,
            image_set=image_set,
            family_code=family_code,
            merchant_code=merchant_code,
            phase=phase,
            step=step,
            severity=severity,
            reason_code=reason_code,
            message=message,
            error=error,
            detail=detail or {},
            screenshot_path=screenshot_path,
            page_url=page_url,
        )
        session.add(row)
        session.flush()
        session.expunge(row)
        return row


def list_listing_failure_details(
    *,
    failure_item_id: str = "",
    source_run_id: str = "",
    limit: int = 200,
) -> list[ListingFailureDetailORM]:
    if not is_database_available():
        return []
    limit = max(1, min(limit, 1000))
    with session_scope() as session:
        query = session.query(ListingFailureDetailORM)
        if failure_item_id:
            query = query.filter(ListingFailureDetailORM.failure_item_id == failure_item_id)
        if source_run_id:
            query = query.filter(ListingFailureDetailORM.source_run_id == source_run_id)
        rows = list(
            query.order_by(ListingFailureDetailORM.created_at.asc(), ListingFailureDetailORM.detail_id.asc())
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def _published_mapping_id(account_id: str, product_code: str, image_set: str) -> str:
    raw = "|".join([account_id.strip(), product_code.strip(), image_set.strip()])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def upsert_published_product(
    *,
    account_id: str,
    source_run_id: str,
    product_code: str,
    family_code: str = "",
    image_set: str,
    listing_label: str,
    merchant_code: str,
    pdd_product_id: str,
    spec_metadata: dict | None = None,
    status: str = "on_sale",
    published_at: datetime | None = None,
) -> PublishedProductORM | None:
    if not is_database_available():
        return None
    mapping_id = _published_mapping_id(account_id, product_code, image_set)
    with session_scope() as session:
        row = session.get(PublishedProductORM, mapping_id)
        data = {
            "account_id": account_id,
            "source_run_id": source_run_id,
            "product_code": product_code,
            "family_code": family_code,
            "image_set": image_set,
            "listing_label": listing_label,
            "merchant_code": merchant_code,
            "pdd_product_id": pdd_product_id,
            "spec_metadata": spec_metadata or {},
            "status": status,
            "published_at": published_at or datetime.now(),
        }
        if row:
            for key, value in data.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
        else:
            now = datetime.now()
            row = PublishedProductORM(
                mapping_id=mapping_id,
                created_at=now,
                updated_at=now,
                **data,
            )
            session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def get_published_product(
    *,
    account_id: str,
    product_code: str,
    image_set: str = "",
) -> PublishedProductORM | None:
    if not is_database_available():
        return None
    mapping_id = _published_mapping_id(account_id, product_code, image_set)
    with session_scope() as session:
        row = session.get(PublishedProductORM, mapping_id)
        if row:
            session.expunge(row)
        return row


def get_published_product_by_mapping_id(mapping_id: str) -> PublishedProductORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(PublishedProductORM, mapping_id)
        if row:
            session.expunge(row)
        return row


def get_published_products_by_pdd_product_ids(
    *,
    account_id: str,
    pdd_product_ids: list[str],
) -> list[PublishedProductORM]:
    if not is_database_available():
        return []
    ids = list(dict.fromkeys(str(item).strip() for item in pdd_product_ids if str(item).strip()))
    if not ids:
        return []
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(PublishedProductORM).where(
                    PublishedProductORM.account_id == account_id,
                    PublishedProductORM.pdd_product_id.in_(ids),
                )
            ).all()
        )
        for row in rows:
            session.expunge(row)
        order = {product_id: idx for idx, product_id in enumerate(ids)}
        return sorted(rows, key=lambda row: order.get(row.pdd_product_id, len(order)))


def get_published_products_by_mapping_ids(mapping_ids: list[str]) -> list[PublishedProductORM]:
    if not is_database_available():
        return []
    ids = [str(item).strip() for item in mapping_ids if str(item).strip()]
    if not ids:
        return []
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(PublishedProductORM).where(PublishedProductORM.mapping_id.in_(ids))
            ).all()
        )
        for row in rows:
            session.expunge(row)
        order = {mapping_id: idx for idx, mapping_id in enumerate(ids)}
        return sorted(rows, key=lambda row: order.get(row.mapping_id, len(order)))


def update_published_product_status(mapping_id: str, status: str) -> PublishedProductORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(PublishedProductORM, mapping_id)
        if not row:
            return None
        row.status = status
        if str(status or "").strip() == "delisted":
            mark_daily_listing_records_delisted(
                account_id=row.account_id,
                pdd_product_id=row.pdd_product_id,
                product_code=row.product_code,
                image_set=row.image_set,
            )
            listed_id = _listed_folder_record_id(
                row.account_id,
                build_folder_selector(
                    family_code=row.family_code,
                    image_set=row.image_set,
                    product_code=row.product_code,
                ),
            )
            listed_row = session.get(ListedAssetFolderORM, listed_id)
            if listed_row:
                session.delete(listed_row)
        session.flush()
        session.expunge(row)
        return row


def patch_published_product_spec_metadata(
    mapping_id: str,
    patch: dict,
) -> PublishedProductORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(PublishedProductORM, mapping_id)
        if not row:
            return None
        meta = dict(row.spec_metadata or {})
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(meta.get(key), dict):
                merged = dict(meta[key])
                merged.update(value)
                meta[key] = merged
            else:
                meta[key] = value
        row.spec_metadata = meta
        row.updated_at = datetime.now()
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def update_published_product_limited_time_status(
    mapping_id: str,
    *,
    limited_time_status: str,
    limited_time_error: str = "",
    limited_time_run_id: str = "",
    limited_time_completed_at: datetime | None = None,
) -> PublishedProductORM | None:
    if not is_database_available():
        return None
    mapping_id = str(mapping_id or "").strip()
    if not mapping_id:
        return None
    with session_scope() as session:
        row = session.get(PublishedProductORM, mapping_id)
        if not row:
            return None
        row.limited_time_status = str(limited_time_status or "").strip()
        row.limited_time_error = str(limited_time_error or "").strip()
        row.limited_time_run_id = str(limited_time_run_id or "").strip()
        row.limited_time_completed_at = limited_time_completed_at
        row.updated_at = datetime.now()
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def delete_published_product(mapping_id: str) -> bool:
    if not is_database_available():
        return False
    with session_scope() as session:
        row = session.get(PublishedProductORM, mapping_id)
        if not row:
            return False
        mark_daily_listing_records_delisted(
            account_id=row.account_id,
            pdd_product_id=row.pdd_product_id,
            product_code=row.product_code,
            image_set=row.image_set,
        )
        listed_id = _listed_folder_record_id(
            row.account_id,
            build_folder_selector(
                family_code=row.family_code,
                image_set=row.image_set,
                product_code=row.product_code,
            ),
        )
        listed_row = session.get(ListedAssetFolderORM, listed_id)
        if listed_row:
            session.delete(listed_row)
        session.delete(row)
        return True


def search_published_products(
    *,
    page: int = 1,
    page_size: int = 50,
    account_id: str = "",
    product_code: str = "",
    pdd_product_id: str = "",
) -> tuple[list[PublishedProductORM], int]:
    if not is_database_available():
        return [], 0
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    with session_scope() as session:
        query = session.query(PublishedProductORM)
        if account_id:
            query = query.filter(PublishedProductORM.account_id == account_id)
        if product_code:
            pattern = f"%{product_code}%"
            query = query.filter(
                (PublishedProductORM.product_code.like(pattern))
                | (PublishedProductORM.family_code.like(pattern))
                | (PublishedProductORM.listing_label.like(pattern))
                | (PublishedProductORM.merchant_code.like(pattern))
            )
        if pdd_product_id:
            query = query.filter(PublishedProductORM.pdd_product_id.like(f"%{pdd_product_id}%"))
        total = int(query.order_by(None).count())
        rows = (
            query.order_by(PublishedProductORM.updated_at.desc(), PublishedProductORM.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows, total


def build_folder_selector(*, family_code: str, image_set: str, product_code: str) -> str:
    """标准化素材文件夹 selector，如 BD720/第一套图/BD720A。"""
    family = str(family_code or "").strip()
    image = str(image_set or "").strip()
    product = str(product_code or "").strip()
    if family and image and product:
        return f"{family}/{image}/{product}"
    if family and image:
        return f"{family}/{image}"
    if product and image:
        return f"{product}/{image}"
    return product or family


def _listed_folder_record_id(account_id: str, folder_selector: str) -> str:
    raw = "|".join([account_id.strip(), folder_selector.strip()])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def get_queue_task_by_run_id(run_id: str) -> TaskQueueORM | None:
    if not is_database_available():
        return None
    run_id = str(run_id or "").strip()
    if not run_id:
        return None
    with session_scope() as session:
        row = session.scalar(
            select(TaskQueueORM)
            .where(TaskQueueORM.run_id == run_id)
            .order_by(TaskQueueORM.created_at.desc())
            .limit(1)
        )
        if row:
            session.expunge(row)
        return row


def update_queued_task_schedule(
    task_id: str,
    *,
    scheduled_at: datetime,
    error: str = "",
) -> bool:
    """更新排队中任务的 scheduled_at（供补跑延期策略使用）。"""
    if not is_database_available():
        return False
    task_id = str(task_id or "").strip()
    if not task_id:
        return False
    with session_scope() as session:
        row = session.get(TaskQueueORM, task_id)
        if not row or str(row.status or "") != "queued":
            return False
        row.scheduled_at = scheduled_at
        if error is not None:
            row.error = str(error or "")
        return True


def requeue_running_task(
    task_id: str,
    *,
    scheduled_at: datetime,
    error: str = "",
) -> bool:
    """将 running 任务退回 queued 并改期（活动 defer 时使用）。"""
    if not is_database_available():
        return False
    task_id = str(task_id or "").strip()
    if not task_id:
        return False
    with session_scope() as session:
        row = session.get(TaskQueueORM, task_id)
        if not row or str(row.status or "") != "running":
            return False
        row.status = "queued"
        row.started_at = None
        row.scheduled_at = scheduled_at
        row.error = str(error or "")
        if row.attempts > 0:
            row.attempts -= 1
        return True


def upsert_listed_asset_folder(
    *,
    account_id: str,
    folder_selector: str,
    family_code: str = "",
    image_set: str = "",
    product_code: str = "",
    listing_label: str = "",
    asset_path: str = "",
    source_run_id: str = "",
    source_kind: str = "listing",
    pipeline_id: str = "",
    pdd_product_id: str = "",
    listed_at: datetime | None = None,
) -> ListedAssetFolderORM | None:
    if not is_database_available():
        return None
    account_id = str(account_id or "").strip()
    folder_selector = str(folder_selector or "").strip()
    if not account_id or not folder_selector:
        return None
    record_id = _listed_folder_record_id(account_id, folder_selector)
    now = listed_at or datetime.now()
    with session_scope() as session:
        row = session.get(ListedAssetFolderORM, record_id)
        data = {
            "account_id": account_id,
            "folder_selector": folder_selector,
            "family_code": str(family_code or "").strip(),
            "image_set": str(image_set or "").strip(),
            "product_code": str(product_code or "").strip(),
            "listing_label": str(listing_label or "").strip(),
            "asset_path": str(asset_path or "").strip(),
            "source_run_id": str(source_run_id or "").strip(),
            "source_kind": str(source_kind or "listing").strip() or "listing",
            "pipeline_id": str(pipeline_id or "").strip(),
            "pdd_product_id": str(pdd_product_id or "").strip(),
            "listed_at": now,
        }
        if row:
            for key, value in data.items():
                setattr(row, key, value)
            row.updated_at = datetime.now()
        else:
            row = ListedAssetFolderORM(
                record_id=record_id,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                **data,
            )
            session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def list_listed_asset_folders(
    *,
    account_id: str = "",
    family_code: str = "",
    image_set: str = "",
    product_code: str = "",
    source_kind: str = "",
    limit: int = 200,
) -> list[ListedAssetFolderORM]:
    if not is_database_available():
        return []
    limit = max(1, min(5000, limit))
    with session_scope() as session:
        query = session.query(ListedAssetFolderORM)
        if account_id:
            query = query.filter(ListedAssetFolderORM.account_id == account_id)
        if family_code:
            query = query.filter(ListedAssetFolderORM.family_code == family_code)
        if image_set:
            query = query.filter(ListedAssetFolderORM.image_set == image_set)
        if product_code:
            query = query.filter(ListedAssetFolderORM.product_code == product_code)
        if source_kind:
            query = query.filter(ListedAssetFolderORM.source_kind == source_kind)
        rows = list(
            query.order_by(ListedAssetFolderORM.listed_at.desc(), ListedAssetFolderORM.created_at.desc())
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def delete_listed_asset_folder_for_product(
    *,
    account_id: str,
    product_code: str,
    family_code: str = "",
    image_set: str = "",
    folder_selector: str = "",
) -> bool:
    """移除单个商品文件夹的上架记录。"""
    if not is_database_available():
        return False
    account_id = str(account_id or "").strip()
    if not account_id:
        return False
    selector = str(folder_selector or "").strip() or build_folder_selector(
        family_code=family_code,
        image_set=image_set,
        product_code=product_code,
    )
    if not selector:
        return False
    record_id = _listed_folder_record_id(account_id, selector)
    with session_scope() as session:
        row = session.get(ListedAssetFolderORM, record_id)
        if not row:
            return False
        session.delete(row)
        return True


def build_catalog_set_index(settings) -> dict[str, frozenset[str]]:
    """实时扫描素材目录：套图 selector -> 当前磁盘上的商品编码集合。"""
    from pdd_agent.skills.listing.catalog import list_listing_targets

    return {item.selector: frozenset(item.product_codes) for item in list_listing_targets(settings)}


def build_product_code_selector_index(
    catalog_index: dict[str, frozenset[str]],
) -> dict[str, set[str]]:
    """商品编码 -> 包含该编码的套图 selector 集合。"""
    mapped: dict[str, set[str]] = defaultdict(set)
    for selector, codes in catalog_index.items():
        for code in codes:
            text = str(code or "").strip()
            if text:
                mapped[text].add(selector)
    return mapped


def list_on_sale_published_product_codes(account_id: str) -> frozenset[str]:
    """店铺内在售已发布商品编码（与素材源无关）。"""
    if not is_database_available():
        return frozenset()
    account_id = str(account_id or "").strip()
    if not account_id:
        return frozenset()
    with session_scope() as session:
        rows = session.scalars(
            select(PublishedProductORM.product_code).where(
                PublishedProductORM.account_id == account_id,
                PublishedProductORM.status == "on_sale",
            )
        ).all()
    return frozenset(str(code or "").strip() for code in rows if str(code or "").strip())


def _resolve_listed_set_selector(row) -> str:
    if row.family_code and row.image_set:
        return f"{row.family_code}/{row.image_set}"
    if row.image_set:
        return str(row.image_set)
    folder_selector = str(row.folder_selector or "")
    if "/" in folder_selector:
        return folder_selector.rsplit("/", 1)[0]
    return folder_selector


def _listed_selectors_for_catalog(
    *,
    set_selector: str,
    product_code: str,
    catalog_index: dict[str, frozenset[str]],
    code_to_selectors: dict[str, set[str]],
) -> set[str]:
    """将上架记录映射到当前素材目录套图（允许本地/MinIO 套图名不一致）。"""
    targets: set[str] = set()
    current_codes = catalog_index.get(set_selector)
    if current_codes is not None and product_code in current_codes:
        targets.add(set_selector)
    for selector in code_to_selectors.get(product_code, ()):
        targets.add(selector)
    return targets


def prune_listed_folders_against_catalog(
    *,
    catalog_index: dict[str, frozenset[str]],
    account_id: str = "",
    limit: int = 5000,
    match_by_product_code: bool = False,
) -> int:
    """清理素材目录已不存在或商品已从套图移除的上架记录。"""
    if not is_database_available():
        return 0
    all_catalog_codes: set[str] | None = None
    if match_by_product_code and catalog_index:
        all_catalog_codes = set()
        for codes in catalog_index.values():
            all_catalog_codes.update(str(code).strip() for code in codes if str(code).strip())

    removed = 0
    rows = list_listed_asset_folders(account_id=account_id, limit=limit)
    for row in rows:
        set_selector = _resolve_listed_set_selector(row)
        product_code = str(row.product_code or "").strip()
        if match_by_product_code:
            should_remove = bool(all_catalog_codes) and product_code not in all_catalog_codes
        else:
            current_codes = catalog_index.get(set_selector)
            should_remove = current_codes is None or product_code not in current_codes
        if not should_remove:
            continue
        if delete_listed_asset_folder_for_product(
            account_id=row.account_id,
            product_code=row.product_code,
            family_code=row.family_code,
            image_set=row.image_set,
            folder_selector=row.folder_selector,
        ):
            removed += 1
    return removed


def get_listed_product_codes_for_set(
    account_id: str,
    *,
    catalog_index: dict[str, frozenset[str]] | None = None,
) -> dict[str, list[str]]:
    """按套图 selector 汇总已上架商品编码（仅保留仍存在于当前素材目录的商品）。"""
    rows = list_listed_asset_folders(account_id=account_id, limit=5000)
    grouped: dict[str, set[str]] = {}
    code_to_selectors: dict[str, set[str]] | None = None
    if catalog_index is not None:
        code_to_selectors = build_product_code_selector_index(catalog_index)

    for row in rows:
        product_code = str(row.product_code or "").strip()
        if not product_code:
            continue
        set_selector = _resolve_listed_set_selector(row)

        if catalog_index is not None and code_to_selectors is not None:
            targets = _listed_selectors_for_catalog(
                set_selector=set_selector,
                product_code=product_code,
                catalog_index=catalog_index,
                code_to_selectors=code_to_selectors,
            )
            if not targets:
                continue
            for selector in targets:
                grouped.setdefault(selector, set()).add(product_code)
            continue

        grouped.setdefault(set_selector, set()).add(product_code)
    return {key: sorted(codes) for key, codes in grouped.items()}


def count_listed_asset_folders() -> int:
    if not is_database_available():
        return 0
    with session_scope() as session:
        return int(
            session.scalar(select(func.count()).select_from(ListedAssetFolderORM)) or 0
        )


def prune_stale_listed_asset_folders(*, limit: int = 5000) -> int:
    """清理已无 on_sale 已发布商品对应的上架文件夹记录。"""
    if not is_database_available():
        return 0
    removed = 0
    rows = list_listed_asset_folders(limit=limit)
    for row in rows:
        published = get_published_product(
            account_id=row.account_id,
            product_code=row.product_code,
            image_set=row.image_set,
        )
        if published and (published.status or "") == "on_sale":
            continue
        if delete_listed_asset_folder_for_product(
            account_id=row.account_id,
            product_code=row.product_code,
            family_code=row.family_code,
            image_set=row.image_set,
            folder_selector=row.folder_selector,
        ):
            removed += 1
    return removed


def backfill_listed_folders_from_published_products(*, limit: int = 5000) -> int:
    """从 published_products 补录已上架文件夹（仅当 listed_asset_folders 为空时调用）。"""
    if not is_database_available():
        return 0
    if count_listed_asset_folders() > 0:
        return 0
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(PublishedProductORM)
                .where(PublishedProductORM.status == "on_sale")
                .order_by(PublishedProductORM.updated_at.desc())
                .limit(max(1, min(limit, 5000)))
            ).all()
        )
    created = 0
    for row in rows:
        folder_selector = build_folder_selector(
            family_code=row.family_code,
            image_set=row.image_set,
            product_code=row.product_code,
        )
        if not folder_selector:
            continue
        pipeline_id = ""
        source_kind = "listing"
        task = get_queue_task_by_run_id(row.source_run_id)
        if task:
            pipeline_id = str((task.payload or {}).get("pipeline_id") or "").strip()
            if pipeline_id:
                source_kind = "integrated_pipeline"
        saved = upsert_listed_asset_folder(
            account_id=row.account_id,
            folder_selector=folder_selector,
            family_code=row.family_code,
            image_set=row.image_set,
            product_code=row.product_code,
            listing_label=row.listing_label,
            asset_path="",
            source_run_id=row.source_run_id,
            source_kind=source_kind,
            pipeline_id=pipeline_id,
            pdd_product_id=row.pdd_product_id,
            listed_at=row.published_at or row.updated_at,
        )
        if saved:
            created += 1
    return created


def _lock_owner_alive(owner: str) -> bool:
    """锁 owner 格式为 {pid}_{uuid}；进程不存在则视为 stale。"""
    token = str(owner or "").split("_", 1)[0]
    try:
        pid = int(token)
    except ValueError:
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def release_stale_account_locks(*, max_age_seconds: int = 7200) -> int:
    """清理过期锁或持有进程已退出的锁。"""
    if not is_database_available():
        return 0
    now = datetime.now()
    removed = 0
    with session_scope() as session:
        rows = list(session.scalars(select(AccountLockORM)).all())
        for row in rows:
            expired = row.expires_at <= now
            owner_dead = not _lock_owner_alive(row.owner)
            if expired or owner_dead:
                session.delete(row)
                removed += 1
    return removed


def force_release_account_lock(account_id: str) -> bool:
    if not is_database_available():
        return False
    with session_scope() as session:
        row = session.get(AccountLockORM, account_id)
        if not row:
            return False
        session.delete(row)
        return True


def acquire_account_lock(
    *,
    account_id: str,
    owner: str,
    reason: str,
    ttl_seconds: int = 7200,
) -> bool:
    if not is_database_available():
        return True
    now = datetime.now()
    expires_at = now + timedelta(seconds=ttl_seconds)
    try:
        with session_scope() as session:
            row = session.get(AccountLockORM, account_id)
            if row and row.expires_at > now and row.owner != owner:
                if _lock_owner_alive(row.owner):
                    return False
                session.delete(row)
                row = None
            if row:
                row.owner = owner
                row.reason = reason
                row.locked_at = now
                row.expires_at = expires_at
            else:
                session.add(
                    AccountLockORM(
                        account_id=account_id,
                        owner=owner,
                        reason=reason,
                        locked_at=now,
                        expires_at=expires_at,
                    )
                )
            return True
    except IntegrityError:
        return False


def release_account_lock(*, account_id: str, owner: str) -> None:
    if not is_database_available():
        return
    with session_scope() as session:
        row = session.get(AccountLockORM, account_id)
        if row and row.owner == owner:
            session.delete(row)


def _norm_product_code(code: str) -> str:
    return str(code or "").strip().upper()


def get_cached_style_color(product_code: str, image_path: str | None = None) -> str | None:
    """读取已缓存的款式颜色；规格图变更后自动失效。"""
    if not is_database_available():
        return None
    code = _norm_product_code(product_code)
    if not code:
        return None
    with session_scope() as session:
        row = session.get(ProductStyleColorORM, code)
        if not row or not row.color_label:
            return None
        if row.source == "manual":
            return row.color_label
        check_path = image_path
        if not check_path and row.image_path:
            check_path = row.image_path
        if check_path:
            path = Path(check_path)
            if path.is_file():
                mtime = path.stat().st_mtime
                if row.image_mtime and abs(row.image_mtime - mtime) > 0.5:
                    return None
        return row.color_label


def upsert_cached_style_color(
    product_code: str,
    color_label: str,
    *,
    source: str = "ai",
    image_path: str | None = None,
) -> None:
    if not is_database_available():
        from pdd_agent.core.logging import get_logger

        get_logger(__name__).warning(
            "款式颜色未写入缓存（数据库不可用）code=%s",
            product_code,
        )
        return
    code = _norm_product_code(product_code)
    label = str(color_label or "").strip()
    if not code or not label:
        return
    mtime = 0.0
    if image_path:
        path = Path(image_path)
        if path.is_file():
            mtime = path.stat().st_mtime
    with session_scope() as session:
        row = session.get(ProductStyleColorORM, code)
        if row:
            row.color_label = label
            row.source = source
            row.image_path = str(image_path or "")
            row.image_mtime = mtime
        else:
            session.add(
                ProductStyleColorORM(
                    product_code=code,
                    color_label=label,
                    source=source,
                    image_path=str(image_path or ""),
                    image_mtime=mtime,
                )
            )


def get_style_color_row(product_code: str) -> ProductStyleColorORM | None:
    if not is_database_available():
        return None
    code = _norm_product_code(product_code)
    if not code:
        return None
    with session_scope() as session:
        row = session.get(ProductStyleColorORM, code)
        if row:
            session.expunge(row)
        return row


def search_style_colors(
    *,
    page: int = 1,
    page_size: int = 50,
    product_code: str = "",
    color_label: str = "",
    source: str = "",
) -> tuple[list[ProductStyleColorORM], int]:
    if not is_database_available():
        return [], 0
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    with session_scope() as session:
        query = session.query(ProductStyleColorORM)
        if product_code:
            query = query.filter(ProductStyleColorORM.product_code.like(f"%{product_code.strip().upper()}%"))
        if color_label:
            query = query.filter(ProductStyleColorORM.color_label.like(f"%{color_label.strip()}%"))
        if source:
            query = query.filter(ProductStyleColorORM.source == source.strip().lower())
        total = int(query.order_by(None).count())
        rows = (
            query.order_by(ProductStyleColorORM.updated_at.desc(), ProductStyleColorORM.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows, total


def create_style_color(
    product_code: str,
    color_label: str,
    *,
    source: str = "manual",
    image_path: str | None = None,
) -> ProductStyleColorORM:
    if not is_database_available():
        raise RuntimeError("database unavailable")
    code = _norm_product_code(product_code)
    label = str(color_label or "").strip()
    if not code or not label:
        raise ValueError("product_code and color_label are required")
    with session_scope() as session:
        if session.get(ProductStyleColorORM, code):
            raise ValueError(f"style color already exists: {code}")
        mtime = 0.0
        if image_path:
            path = Path(image_path)
            if path.is_file():
                mtime = path.stat().st_mtime
        row = ProductStyleColorORM(
            product_code=code,
            color_label=label,
            source=source,
            image_path=str(image_path or ""),
            image_mtime=mtime,
        )
        session.add(row)
        session.flush()
        session.expunge(row)
        return row


def update_style_color(
    product_code: str,
    color_label: str,
    *,
    image_path: str | None = None,
) -> ProductStyleColorORM | None:
    if not is_database_available():
        return None
    code = _norm_product_code(product_code)
    label = str(color_label or "").strip()
    if not code or not label:
        return None
    mtime = 0.0
    if image_path:
        path = Path(image_path)
        if path.is_file():
            mtime = path.stat().st_mtime
    with session_scope() as session:
        row = session.get(ProductStyleColorORM, code)
        if not row:
            return None
        row.color_label = label
        row.source = "manual"
        if image_path is not None:
            row.image_path = str(image_path or "")
            row.image_mtime = mtime
        session.flush()
        session.expunge(row)
        return row


def delete_style_color(product_code: str) -> bool:
    if not is_database_available():
        return False
    code = _norm_product_code(product_code)
    if not code:
        return False
    with session_scope() as session:
        row = session.get(ProductStyleColorORM, code)
        if not row:
            return False
        session.delete(row)
        return True


def seed_listing_product_attributes() -> int:
    """初始化上架商品属性表；表为空时写入默认字段。"""
    if not is_database_available():
        return 0
    from pdd_agent.domain.listing_product_attributes import DEFAULT_LISTING_PRODUCT_ATTRIBUTES

    created = 0
    with session_scope() as session:
        existing = session.scalar(select(func.count()).select_from(ListingProductAttributeORM)) or 0
        if existing:
            return 0
        for item in DEFAULT_LISTING_PRODUCT_ATTRIBUTES:
            session.add(
                ListingProductAttributeORM(
                    field_key=item.field_key,
                    label=item.label,
                    selected_value=item.selected_value,
                    options=list(item.options),
                    enabled=item.enabled,
                    sort_order=item.sort_order,
                )
            )
            created += 1
    return created


def list_listing_product_attributes(*, enabled_only: bool = False) -> list[ListingProductAttributeORM]:
    if not is_database_available():
        return []
    with session_scope() as session:
        stmt = select(ListingProductAttributeORM).order_by(
            ListingProductAttributeORM.sort_order.asc(),
            ListingProductAttributeORM.field_key.asc(),
        )
        if enabled_only:
            stmt = stmt.where(ListingProductAttributeORM.enabled.is_(True))
        rows = list(session.scalars(stmt))
        for row in rows:
            session.expunge(row)
        return rows


def get_listing_product_attribute(field_key: str) -> ListingProductAttributeORM | None:
    if not is_database_available():
        return None
    key = str(field_key or "").strip()
    if not key:
        return None
    with session_scope() as session:
        row = session.get(ListingProductAttributeORM, key)
        if row:
            session.expunge(row)
        return row


def update_listing_product_attribute(
    field_key: str,
    *,
    selected_value: str | None = None,
    options: list[str] | None = None,
) -> ListingProductAttributeORM | None:
    if not is_database_available():
        return None
    key = str(field_key or "").strip()
    if not key:
        return None
    with session_scope() as session:
        row = session.get(ListingProductAttributeORM, key)
        if not row:
            return None
        if not row.enabled:
            return None
        if selected_value is not None:
            row.selected_value = str(selected_value).strip()
        if options is not None:
            cleaned = [str(v).strip() for v in options if str(v).strip()]
            if row.selected_value and row.selected_value not in cleaned:
                cleaned.insert(0, row.selected_value)
            row.options = cleaned
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def batch_update_listing_product_attributes(
    updates: dict[str, str],
) -> list[ListingProductAttributeORM]:
    if not is_database_available():
        return []
    if not updates:
        return list_listing_product_attributes(enabled_only=True)
    updated: list[ListingProductAttributeORM] = []
    with session_scope() as session:
        for field_key, value in updates.items():
            key = str(field_key or "").strip()
            if not key:
                continue
            row = session.get(ListingProductAttributeORM, key)
            if not row or not row.enabled:
                continue
            row.selected_value = str(value or "").strip()
            if row.selected_value and row.selected_value not in (row.options or []):
                row.options = [row.selected_value, *(row.options or [])]
            session.flush()
            session.refresh(row)
            session.expunge(row)
            updated.append(row)
    return updated


def create_integrated_pipeline(
    *,
    pipeline_id: str,
    account_id: str,
    product_codes: list[str],
    activity_id: str,
    auto_promotion: bool,
    activity_delay_hours: float,
    demo_mode: bool,
    listing_run_id: str,
    meta: dict | None = None,
) -> IntegratedPipelineORM:
    row = IntegratedPipelineORM(
        pipeline_id=pipeline_id,
        account_id=account_id,
        status="running",
        current_step="listing_queued",
        product_codes=list(product_codes),
        activity_id=activity_id,
        auto_promotion=auto_promotion,
        activity_delay_hours=float(activity_delay_hours),
        demo_mode=bool(demo_mode),
        listing_run_id=listing_run_id,
        meta=dict(meta or {}),
    )
    with session_scope() as session:
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    return row


def get_integrated_pipeline(pipeline_id: str) -> IntegratedPipelineORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(IntegratedPipelineORM, pipeline_id)
        if row:
            session.expunge(row)
        return row


def get_integrated_pipeline_by_listing_run_id(run_id: str) -> IntegratedPipelineORM | None:
    """按当前 listing_run_id 查找整合链路（批内续跑落库用）。"""
    if not is_database_available():
        return None
    run_id = str(run_id or "").strip()
    if not run_id:
        return None
    with session_scope() as session:
        row = session.scalar(
            select(IntegratedPipelineORM)
            .where(IntegratedPipelineORM.listing_run_id == run_id)
            .order_by(IntegratedPipelineORM.updated_at.desc())
            .limit(1)
        )
        if row:
            session.expunge(row)
        return row


def count_integrated_pipelines(*, batch_id: str = "") -> int:
    if not is_database_available():
        return 0
    batch_id = str(batch_id or "").strip()
    with session_scope() as session:
        stmt = select(func.count()).select_from(IntegratedPipelineORM)
        if batch_id:
            stmt = stmt.where(IntegratedPipelineORM.meta["batch_id"].as_string() == batch_id)
        return int(session.scalar(stmt) or 0)


def list_integrated_pipelines(
    *,
    limit: int = 50,
    offset: int = 0,
    batch_id: str = "",
) -> list[IntegratedPipelineORM]:
    if not is_database_available():
        return []
    batch_id = str(batch_id or "").strip()
    with session_scope() as session:
        stmt = select(IntegratedPipelineORM).order_by(IntegratedPipelineORM.created_at.desc())
        if batch_id:
            stmt = stmt.where(IntegratedPipelineORM.meta["batch_id"].as_string() == batch_id)
        stmt = stmt.offset(max(0, int(offset))).limit(max(1, min(limit, 200)))
        rows = session.scalars(stmt).all()
        for row in rows:
            session.expunge(row)
        return list(rows)


def list_mq_auto_phase2_due_pipelines(*, limit: int = 10) -> list[IntegratedPipelineORM]:
    """已到期的 MQ 阶段二候选（waiting_mq_phase2 + scheduled_activity_at <= now）。"""
    if not is_database_available():
        return []
    now = datetime.now()
    with session_scope() as session:
        stmt = (
            select(IntegratedPipelineORM)
            .where(
                IntegratedPipelineORM.current_step == "waiting_mq_phase2",
                IntegratedPipelineORM.scheduled_activity_at.is_not(None),
                IntegratedPipelineORM.scheduled_activity_at <= now,
            )
            .order_by(IntegratedPipelineORM.scheduled_activity_at.asc())
            .limit(max(1, min(limit * 5, 100)))
        )
        rows = session.scalars(stmt).all()
        due: list[IntegratedPipelineORM] = []
        for row in rows:
            meta = row.meta if isinstance(row.meta, dict) else {}
            if not meta.get("mq_auto_deferred_phase2"):
                continue
            if meta.get("mq_phase2_status") != "pending":
                continue
            session.expunge(row)
            due.append(row)
            if len(due) >= max(1, limit):
                break
        return due


def list_mq_auto_phase2_running_pipelines(*, limit: int = 20) -> list[IntegratedPipelineORM]:
    """阶段二进行中的 MQ 链路（用于串行互斥）。"""
    if not is_database_available():
        return []
    with session_scope() as session:
        stmt = (
            select(IntegratedPipelineORM)
            .where(
                IntegratedPipelineORM.meta["mq_phase2_status"].as_string() == "running",
            )
            .order_by(IntegratedPipelineORM.updated_at.asc())
            .limit(max(1, min(limit, 100)))
        )
        rows = session.scalars(stmt).all()
        for row in rows:
            session.expunge(row)
        return list(rows)


def update_integrated_pipeline(
    pipeline_id: str,
    *,
    status: str | None = None,
    current_step: str | None = None,
    listing_run_id: str | None = None,
    campaign_run_id: str | None = None,
    traffic_run_id: str | None = None,
    pdd_product_ids: list[str] | None = None,
    mapping_ids: list[str] | None = None,
    scheduled_activity_at: datetime | None = None,
    error: str | None = None,
    meta_patch: dict | None = None,
) -> IntegratedPipelineORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(IntegratedPipelineORM, pipeline_id)
        if not row:
            return None
        if status is not None:
            row.status = status
        if current_step is not None:
            row.current_step = current_step
        if listing_run_id is not None:
            row.listing_run_id = listing_run_id
        if campaign_run_id is not None:
            row.campaign_run_id = campaign_run_id
        if traffic_run_id is not None:
            row.traffic_run_id = traffic_run_id
        if pdd_product_ids is not None:
            row.pdd_product_ids = list(pdd_product_ids)
        if mapping_ids is not None:
            row.mapping_ids = list(mapping_ids)
        if scheduled_activity_at is not None:
            row.scheduled_activity_at = scheduled_activity_at
        if error is not None:
            row.error = error
        if meta_patch:
            merged = dict(row.meta or {})
            merged.update(meta_patch)
            row.meta = merged
        session.flush()
        session.refresh(row)
        session.expunge(row)
        try:
            from pdd_agent.api.services.commerce_dispatch import sync_lifecycle_from_integrated_pipeline

            sync_lifecycle_from_integrated_pipeline(row)
        except Exception:
            from pdd_agent.core.logging import get_logger

            get_logger(__name__).exception(
                "sync commerce lifecycle failed pipeline_id=%s",
                pipeline_id,
            )
        return row


def insert_pipeline_issue_report(
    *,
    issue_id: str,
    pipeline_id: str,
    batch_id: str = "",
    account_id: str = "",
    stage: str = "",
    chain_step: str = "",
    severity: str = "error",
    reason_code: str = "",
    title: str = "",
    message: str = "",
    error_text: str = "",
    context: dict | None = None,
    run_id: str = "",
    activity_id: str = "",
    product_selector: str = "",
    source_location: str = "",
) -> IntegratedPipelineIssueReportORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = IntegratedPipelineIssueReportORM(
            issue_id=issue_id,
            pipeline_id=pipeline_id,
            batch_id=batch_id or "",
            account_id=account_id or "",
            stage=stage or "orchestration",
            chain_step=chain_step or "",
            severity=severity or "error",
            reason_code=reason_code or "",
            title=title or "",
            message=message or "",
            error_text=error_text or "",
            context=context if isinstance(context, dict) else None,
            run_id=run_id or "",
            activity_id=activity_id or "",
            product_selector=product_selector or "",
            source_location=source_location or "",
        )
        session.add(row)
        session.flush()
        session.expunge(row)
        return row


def get_pipeline_issue_report(issue_id: str) -> IntegratedPipelineIssueReportORM | None:
    if not is_database_available():
        return None
    with session_scope() as session:
        row = session.get(IntegratedPipelineIssueReportORM, issue_id)
        if row:
            session.expunge(row)
        return row


def search_pipeline_issue_reports(
    *,
    page: int = 1,
    page_size: int = 50,
    pipeline_id: str = "",
    batch_id: str = "",
    account_id: str = "",
    stage: str = "",
    severity: str = "",
    keyword: str = "",
) -> tuple[list[IntegratedPipelineIssueReportORM], int]:
    if not is_database_available():
        return [], 0
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    with session_scope() as session:
        query = session.query(IntegratedPipelineIssueReportORM)
        if pipeline_id:
            query = query.filter(IntegratedPipelineIssueReportORM.pipeline_id == pipeline_id)
        if batch_id:
            query = query.filter(IntegratedPipelineIssueReportORM.batch_id == batch_id)
        if account_id:
            query = query.filter(IntegratedPipelineIssueReportORM.account_id == account_id)
        if stage:
            query = query.filter(IntegratedPipelineIssueReportORM.stage == stage)
        if severity:
            query = query.filter(IntegratedPipelineIssueReportORM.severity == severity)
        if keyword:
            pattern = f"%{keyword}%"
            query = query.filter(
                (IntegratedPipelineIssueReportORM.title.like(pattern))
                | (IntegratedPipelineIssueReportORM.message.like(pattern))
                | (IntegratedPipelineIssueReportORM.error_text.like(pattern))
                | (IntegratedPipelineIssueReportORM.product_selector.like(pattern))
                | (IntegratedPipelineIssueReportORM.reason_code.like(pattern))
            )
        total = int(query.order_by(None).count())
        rows = (
            query.order_by(
                IntegratedPipelineIssueReportORM.created_at.desc(),
                IntegratedPipelineIssueReportORM.issue_id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows, total


def list_pipeline_issue_reports_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
    severities: list[str] | None = None,
    limit: int = 20,
) -> list[IntegratedPipelineIssueReportORM]:
    """查询时间段内的整合链路报错（用于日报「正在解决/优化中」草稿）。"""
    if not is_database_available():
        return []
    limit = max(1, min(100, limit))
    with session_scope() as session:
        query = session.query(IntegratedPipelineIssueReportORM).filter(
            IntegratedPipelineIssueReportORM.created_at >= start,
        )
        if inclusive_end:
            query = query.filter(IntegratedPipelineIssueReportORM.created_at <= end)
        else:
            query = query.filter(IntegratedPipelineIssueReportORM.created_at < end)
        if severities:
            query = query.filter(IntegratedPipelineIssueReportORM.severity.in_(severities))
        rows = (
            query.order_by(
                IntegratedPipelineIssueReportORM.created_at.desc(),
                IntegratedPipelineIssueReportORM.issue_id.desc(),
            )
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def count_pipeline_issue_reports(
    *,
    pipeline_id: str = "",
    severity: str = "",
) -> int:
    if not is_database_available():
        return 0
    with session_scope() as session:
        query = session.query(func.count(IntegratedPipelineIssueReportORM.issue_id))
        if pipeline_id:
            query = query.filter(IntegratedPipelineIssueReportORM.pipeline_id == pipeline_id)
        if severity:
            query = query.filter(IntegratedPipelineIssueReportORM.severity == severity)
        return int(query.scalar() or 0)


def _day_bounds(target: date) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, target.day)
    end = start + timedelta(days=1)
    return start, end


def create_daily_listing_record(
    *,
    account_id: str,
    shop_display_name: str = "",
    pdd_product_id: str,
    product_code: str,
    family_code: str = "",
    image_set: str = "",
    listing_label: str = "",
    merchant_code: str = "",
    title: str = "",
    source_run_id: str = "",
    source_kind: str = "listing",
    pipeline_id: str = "",
    listed_at: datetime | None = None,
) -> DailyListingRecordORM | None:
    """上架成功追加一条日志；同一 run + 商品 ID 重复调用时幂等跳过。"""
    if not is_database_available():
        return None
    account_id = str(account_id or "").strip()
    pdd_product_id = str(pdd_product_id or "").strip()
    product_code = str(product_code or "").strip()
    listing_label = str(listing_label or "").strip()
    source_run_id = str(source_run_id or "").strip()
    if not account_id or not pdd_product_id or not product_code:
        return None
    if not listing_label:
        listing_label = f"{product_code}/{image_set}" if image_set else product_code
    now = listed_at or datetime.now()
    with session_scope() as session:
        if source_run_id:
            existing = (
                session.query(DailyListingRecordORM)
                .filter(
                    DailyListingRecordORM.source_run_id == source_run_id,
                    DailyListingRecordORM.pdd_product_id == pdd_product_id,
                )
                .first()
            )
            if existing:
                session.expunge(existing)
                return existing
        row = DailyListingRecordORM(
            record_id=uuid.uuid4().hex,
            account_id=account_id,
            shop_display_name=str(shop_display_name or "").strip(),
            pdd_product_id=pdd_product_id,
            product_code=product_code,
            family_code=str(family_code or "").strip(),
            image_set=str(image_set or "").strip(),
            listing_label=listing_label,
            merchant_code=str(merchant_code or "").strip(),
            title=str(title or "").strip(),
            source_run_id=source_run_id,
            source_kind=str(source_kind or "listing").strip() or "listing",
            pipeline_id=str(pipeline_id or "").strip(),
            status="active",
            listed_at=now,
            delisted_at=None,
            created_at=datetime.now(),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def mark_daily_listing_records_delisted(
    *,
    account_id: str,
    pdd_product_id: str = "",
    product_code: str = "",
    image_set: str = "",
) -> int:
    """逻辑删除每日上架记录（商品下架或重新上架预备时调用）。"""
    if not is_database_available():
        return 0
    account_id = str(account_id or "").strip()
    pdd_product_id = str(pdd_product_id or "").strip()
    product_code = str(product_code or "").strip()
    image_set = str(image_set or "").strip()
    if not account_id or (not pdd_product_id and not product_code):
        return 0
    now = datetime.now()
    with session_scope() as session:
        query = session.query(DailyListingRecordORM).filter(
            DailyListingRecordORM.account_id == account_id,
            DailyListingRecordORM.status == "active",
        )
        if pdd_product_id:
            query = query.filter(DailyListingRecordORM.pdd_product_id == pdd_product_id)
        else:
            query = query.filter(DailyListingRecordORM.product_code == product_code)
            if image_set:
                query = query.filter(DailyListingRecordORM.image_set == image_set)
        rows = query.all()
        for row in rows:
            row.status = "delisted"
            row.delisted_at = now
        return len(rows)


def list_daily_listing_records(
    *,
    account_id: str = "",
    listed_date: date | None = None,
    limit: int = 200,
    active_only: bool = False,
) -> list[DailyListingRecordORM]:
    if not is_database_available():
        return []
    limit = max(1, min(5000, limit))
    target = listed_date or datetime.now().date()
    start, end = _day_bounds(target)
    with session_scope() as session:
        query = session.query(DailyListingRecordORM).filter(
            DailyListingRecordORM.listed_at >= start,
            DailyListingRecordORM.listed_at < end,
        )
        if account_id:
            query = query.filter(DailyListingRecordORM.account_id == account_id.strip())
        if active_only:
            query = query.filter(DailyListingRecordORM.status == "active")
        rows = (
            query.order_by(
                DailyListingRecordORM.listed_at.desc(),
                DailyListingRecordORM.record_id.desc(),
            )
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def list_daily_listing_records_between(
    *,
    account_id: str = "",
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
    limit: int = 200,
    active_only: bool = False,
) -> list[DailyListingRecordORM]:
    if not is_database_available():
        return []
    limit = max(1, min(5000, limit))
    with session_scope() as session:
        query = session.query(DailyListingRecordORM).filter(
            DailyListingRecordORM.listed_at >= start,
        )
        if inclusive_end:
            query = query.filter(DailyListingRecordORM.listed_at <= end)
        else:
            query = query.filter(DailyListingRecordORM.listed_at < end)
        if account_id:
            query = query.filter(DailyListingRecordORM.account_id == account_id.strip())
        if active_only:
            query = query.filter(DailyListingRecordORM.status == "active")
        rows = (
            query.order_by(
                DailyListingRecordORM.listed_at.desc(),
                DailyListingRecordORM.record_id.desc(),
            )
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def count_daily_listing_records_between(
    *,
    account_id: str = "",
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
    active_only: bool = False,
) -> int:
    if not is_database_available():
        return 0
    with session_scope() as session:
        query = session.query(func.count(DailyListingRecordORM.record_id)).filter(
            DailyListingRecordORM.listed_at >= start,
        )
        if inclusive_end:
            query = query.filter(DailyListingRecordORM.listed_at <= end)
        else:
            query = query.filter(DailyListingRecordORM.listed_at < end)
        if account_id:
            query = query.filter(DailyListingRecordORM.account_id == account_id.strip())
        if active_only:
            query = query.filter(DailyListingRecordORM.status == "active")
        return int(query.scalar() or 0)


def count_daily_listing_records(
    *,
    account_id: str = "",
    listed_date: date | None = None,
    active_only: bool = False,
) -> int:
    if not is_database_available():
        return 0
    target = listed_date or datetime.now().date()
    start, end = _day_bounds(target)
    with session_scope() as session:
        query = session.query(func.count(DailyListingRecordORM.record_id)).filter(
            DailyListingRecordORM.listed_at >= start,
            DailyListingRecordORM.listed_at < end,
        )
        if account_id:
            query = query.filter(DailyListingRecordORM.account_id == account_id.strip())
        if active_only:
            query = query.filter(DailyListingRecordORM.status == "active")
        return int(query.scalar() or 0)


def summarize_daily_listing_records(
    *,
    listed_date: date | None = None,
) -> list[dict[str, str | int]]:
    """按店铺汇总指定日期的上架数量（含总计/仍在上架/已下架）。"""
    if not is_database_available():
        return []
    target = listed_date or datetime.now().date()
    start, end = _day_bounds(target)
    with session_scope() as session:
        rows = (
            session.query(
                DailyListingRecordORM.account_id,
                DailyListingRecordORM.shop_display_name,
                func.count(DailyListingRecordORM.record_id),
                func.sum(case((DailyListingRecordORM.status == "active", 1), else_=0)),
            )
            .filter(
                DailyListingRecordORM.listed_at >= start,
                DailyListingRecordORM.listed_at < end,
            )
            .group_by(
                DailyListingRecordORM.account_id,
                DailyListingRecordORM.shop_display_name,
            )
            .order_by(func.count(DailyListingRecordORM.record_id).desc())
            .all()
        )
        return [
            {
                "account_id": str(account_id or ""),
                "shop_display_name": str(shop_name or "").strip(),
                "count": int(count or 0),
                "active_count": int(active_count or 0),
                "delisted_count": int((count or 0) - (active_count or 0)),
            }
            for account_id, shop_name, count, active_count in rows
        ]


def summarize_daily_listing_records_between(
    *,
    start: datetime,
    end: datetime,
) -> list[dict[str, str | int]]:
    """按店铺汇总指定时间段内的上架数量（含边界）。"""
    if not is_database_available():
        return []
    with session_scope() as session:
        rows = (
            session.query(
                DailyListingRecordORM.account_id,
                DailyListingRecordORM.shop_display_name,
                func.count(DailyListingRecordORM.record_id),
                func.sum(case((DailyListingRecordORM.status == "active", 1), else_=0)),
            )
            .filter(
                DailyListingRecordORM.listed_at >= start,
                DailyListingRecordORM.listed_at <= end,
            )
            .group_by(
                DailyListingRecordORM.account_id,
                DailyListingRecordORM.shop_display_name,
            )
            .order_by(func.count(DailyListingRecordORM.record_id).desc())
            .all()
        )
        return [
            {
                "account_id": str(account_id or ""),
                "shop_display_name": str(shop_name or "").strip(),
                "count": int(count or 0),
                "active_count": int(active_count or 0),
                "delisted_count": int((count or 0) - (active_count or 0)),
            }
            for account_id, shop_name, count, active_count in rows
        ]


def summarize_limited_time_success_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    """按店铺汇总时间段内限时限量购成功数（依据 published_products.limited_time_completed_at）。"""
    if not is_database_available():
        return []
    from pdd_agent.api.services.published_limited_time_status_resolver import (
        LIMITED_TIME_STATUS_SUCCESS,
    )

    with session_scope() as session:
        query = session.query(
            PublishedProductORM.account_id,
            func.count(PublishedProductORM.mapping_id),
        ).filter(
            PublishedProductORM.limited_time_status == LIMITED_TIME_STATUS_SUCCESS,
            PublishedProductORM.limited_time_completed_at.isnot(None),
            PublishedProductORM.limited_time_completed_at >= start,
        )
        if inclusive_end:
            query = query.filter(PublishedProductORM.limited_time_completed_at <= end)
        else:
            query = query.filter(PublishedProductORM.limited_time_completed_at < end)
        rows = (
            query.group_by(PublishedProductORM.account_id)
            .order_by(func.count(PublishedProductORM.mapping_id).desc())
            .all()
        )
        return [
            {
                "account_id": str(account_id or ""),
                "count": int(count or 0),
            }
            for account_id, count in rows
        ]


def _count_success_items_from_run_result(
    result: dict | None,
    *,
    payload: dict | None = None,
) -> int:
    data = result if isinstance(result, dict) else {}
    items = [item for item in (data.get("results") or []) if isinstance(item, dict)]
    success = sum(
        1 for item in items if str(item.get("status") or "").strip() == "success"
    )
    if success > 0:
        return success
    if items:
        return 0
    if str(data.get("error") or "").strip():
        return 0
    body = payload if isinstance(payload, dict) else {}
    product_ids = [str(pid).strip() for pid in (body.get("pdd_product_ids") or []) if str(pid).strip()]
    if product_ids:
        return len(product_ids)
    return 1


def summarize_commerce_task_success_between(
    *,
    start: datetime,
    end: datetime,
    agent: str,
    type_key: str,
    type_value: str,
    type_default: str = "",
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    """按店铺汇总时间段内活动报名/推广等任务成功商品数。"""
    if not is_database_available():
        return []
    counts: dict[str, int] = defaultdict(int)
    with session_scope() as session:
        query = (
            session.query(TaskQueueORM, RunRecordORM)
            .join(RunRecordORM, TaskQueueORM.run_id == RunRecordORM.run_id)
            .filter(
                TaskQueueORM.status == "success",
                TaskQueueORM.agent == agent,
                TaskQueueORM.finished_at.isnot(None),
                TaskQueueORM.finished_at >= start,
            )
        )
        if inclusive_end:
            query = query.filter(TaskQueueORM.finished_at <= end)
        else:
            query = query.filter(TaskQueueORM.finished_at < end)
        for task, run in query.all():
            payload = task.payload if isinstance(task.payload, dict) else {}
            actual_type = str(payload.get(type_key) or type_default or "").strip()
            if actual_type != type_value:
                continue
            count = _count_success_items_from_run_result(
                run.result if isinstance(run.result, dict) else {},
                payload=payload,
            )
            if count <= 0:
                continue
            account_id = str(task.account_id or "").strip()
            counts[account_id] += count
    rows = [{"account_id": account_id, "count": count} for account_id, count in counts.items()]
    rows.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
    return rows


def summarize_activity_register_success_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    return summarize_commerce_task_success_between(
        start=start,
        end=end,
        agent="campaign",
        type_key="campaign_type",
        type_value="marketing_activity_register",
        type_default="marketing_activity_register",
        inclusive_end=inclusive_end,
    )


def summarize_promotion_success_between(
    *,
    start: datetime,
    end: datetime,
    inclusive_end: bool = True,
) -> list[dict[str, str | int]]:
    return summarize_commerce_task_success_between(
        start=start,
        end=end,
        agent="traffic",
        type_key="traffic_type",
        type_value="promotion_create",
        type_default="promotion_create",
        inclusive_end=inclusive_end,
    )


def create_daily_cycle_relist_record(
    *,
    feishu_record_id: str,
    account_id: str,
    shop_display_name: str = "",
    merchant_code: str = "",
    pipeline_id: str,
    product_codes: list[str] | None = None,
    report_platform: str = "",
    trigger_source: str = "auto_watch",
    triggered_at: datetime | None = None,
) -> DailyCycleRelistRecordORM | None:
    """失败日志循环上架成功启动整合链路后追加一条记录；同一 pipeline_id 幂等。"""
    if not is_database_available():
        return None
    feishu_record_id = str(feishu_record_id or "").strip()
    account_id = str(account_id or "").strip()
    pipeline_id = str(pipeline_id or "").strip()
    if not account_id or not pipeline_id:
        return None
    now = triggered_at or datetime.now()
    with session_scope() as session:
        existing = (
            session.query(DailyCycleRelistRecordORM)
            .filter(DailyCycleRelistRecordORM.pipeline_id == pipeline_id)
            .first()
        )
        if existing:
            session.expunge(existing)
            return existing
        row = DailyCycleRelistRecordORM(
            record_id=uuid.uuid4().hex,
            feishu_record_id=feishu_record_id,
            account_id=account_id,
            shop_display_name=str(shop_display_name or "").strip(),
            merchant_code=str(merchant_code or "").strip(),
            pipeline_id=pipeline_id,
            product_codes=list(product_codes or []),
            report_platform=str(report_platform or "").strip(),
            trigger_source=str(trigger_source or "auto_watch").strip() or "auto_watch",
            triggered_at=now,
            created_at=datetime.now(),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def list_daily_cycle_relist_records(
    *,
    account_id: str = "",
    triggered_date: date | None = None,
    limit: int = 200,
) -> list[DailyCycleRelistRecordORM]:
    if not is_database_available():
        return []
    limit = max(1, min(5000, limit))
    target = triggered_date or datetime.now().date()
    start, end = _day_bounds(target)
    with session_scope() as session:
        query = session.query(DailyCycleRelistRecordORM).filter(
            DailyCycleRelistRecordORM.triggered_at >= start,
            DailyCycleRelistRecordORM.triggered_at < end,
        )
        if account_id:
            query = query.filter(DailyCycleRelistRecordORM.account_id == account_id.strip())
        rows = (
            query.order_by(
                DailyCycleRelistRecordORM.triggered_at.desc(),
                DailyCycleRelistRecordORM.record_id.desc(),
            )
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def count_daily_cycle_relist_records(
    *,
    account_id: str = "",
    triggered_date: date | None = None,
) -> int:
    if not is_database_available():
        return 0
    target = triggered_date or datetime.now().date()
    start, end = _day_bounds(target)
    with session_scope() as session:
        query = session.query(func.count(DailyCycleRelistRecordORM.record_id)).filter(
            DailyCycleRelistRecordORM.triggered_at >= start,
            DailyCycleRelistRecordORM.triggered_at < end,
        )
        if account_id:
            query = query.filter(DailyCycleRelistRecordORM.account_id == account_id.strip())
        return int(query.scalar() or 0)


def summarize_daily_cycle_relist_records(
    *,
    triggered_date: date | None = None,
) -> list[dict[str, str | int]]:
    if not is_database_available():
        return []
    target = triggered_date or datetime.now().date()
    start, end = _day_bounds(target)
    with session_scope() as session:
        rows = (
            session.query(
                DailyCycleRelistRecordORM.account_id,
                DailyCycleRelistRecordORM.shop_display_name,
                func.count(DailyCycleRelistRecordORM.record_id),
            )
            .filter(
                DailyCycleRelistRecordORM.triggered_at >= start,
                DailyCycleRelistRecordORM.triggered_at < end,
            )
            .group_by(
                DailyCycleRelistRecordORM.account_id,
                DailyCycleRelistRecordORM.shop_display_name,
            )
            .order_by(func.count(DailyCycleRelistRecordORM.record_id).desc())
            .all()
        )
        return [
            {
                "account_id": str(account_id or ""),
                "shop_display_name": str(shop_name or "").strip(),
                "count": int(count or 0),
            }
            for account_id, shop_name, count in rows
        ]


def _compact_cycle_relist_candidate(item: dict) -> dict:
    return {
        "record_id": str(item.get("record_id") or ""),
        "merchant_code": str(item.get("merchant_code") or ""),
        "account_name": str(item.get("account_name") or ""),
        "account_id": str(item.get("account_id") or ""),
        "report_platform": str(item.get("report_platform") or ""),
        "failure_reason": str(item.get("failure_reason") or ""),
        "process_status": str(item.get("process_status") or ""),
        "cycle_relist": str(item.get("cycle_relist") or ""),
        "date": str(item.get("date") or ""),
    }


def create_failure_cycle_relist_poll_log(
    *,
    polled_at: datetime | None = None,
    candidate_total: int = 0,
    new_count: int = 0,
    fetch_mode: str = "",
    fetch_page_size: int = 0,
    table_id: str = "",
    table_name: str = "",
    candidates: list[dict] | None = None,
    new_candidates: list[dict] | None = None,
) -> FailureCycleRelistPollLogORM | None:
    if not is_database_available():
        return None
    now = polled_at or datetime.now()
    compact_all = [_compact_cycle_relist_candidate(item) for item in (candidates or [])]
    compact_new = [_compact_cycle_relist_candidate(item) for item in (new_candidates or [])]
    with session_scope() as session:
        row = FailureCycleRelistPollLogORM(
            poll_log_id=uuid.uuid4().hex,
            polled_at=now,
            candidate_total=int(candidate_total),
            new_count=int(new_count),
            fetch_mode=str(fetch_mode or "").strip(),
            fetch_page_size=int(fetch_page_size or 0),
            table_id=str(table_id or "").strip(),
            table_name=str(table_name or "").strip(),
            candidates=compact_all,
            new_candidates=compact_new,
            created_at=datetime.now(),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def create_failure_cycle_relist_action_log(
    *,
    feishu_record_id: str,
    merchant_code: str = "",
    account_name: str = "",
    account_id: str = "",
    failure_reason: str = "",
    report_platform: str = "",
    status: str,
    message: str = "",
    pipeline_id: str = "",
    trigger_source: str = "auto_watch",
    poll_log_id: str = "",
    action_at: datetime | None = None,
) -> FailureCycleRelistActionLogORM | None:
    if not is_database_available():
        return None
    feishu_record_id = str(feishu_record_id or "").strip()
    if not feishu_record_id:
        return None
    now = action_at or datetime.now()
    with session_scope() as session:
        row = FailureCycleRelistActionLogORM(
            action_log_id=uuid.uuid4().hex,
            poll_log_id=str(poll_log_id or "").strip(),
            feishu_record_id=feishu_record_id,
            merchant_code=str(merchant_code or "").strip(),
            account_name=str(account_name or "").strip(),
            account_id=str(account_id or "").strip(),
            failure_reason=str(failure_reason or "").strip(),
            report_platform=str(report_platform or "").strip(),
            status=str(status or "").strip(),
            message=str(message or "").strip(),
            pipeline_id=str(pipeline_id or "").strip(),
            trigger_source=str(trigger_source or "auto_watch").strip() or "auto_watch",
            action_at=now,
            created_at=datetime.now(),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def list_failure_cycle_relist_action_logs(*, limit: int = 100) -> list[FailureCycleRelistActionLogORM]:
    if not is_database_available():
        return []
    limit = max(1, min(500, limit))
    with session_scope() as session:
        rows = (
            session.query(FailureCycleRelistActionLogORM)
            .order_by(
                FailureCycleRelistActionLogORM.action_at.desc(),
                FailureCycleRelistActionLogORM.action_log_id.desc(),
            )
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def list_failure_cycle_relist_waiting_for_pipeline(
    *,
    pipeline_id: str,
    limit: int = 300,
) -> list[FailureCycleRelistActionLogORM]:
    """查找因指定 pipeline 阻塞而处于 waiting 的最近动作记录（按 record 去重）。"""
    if not is_database_available():
        return []
    pid = str(pipeline_id or "").strip()
    if not pid:
        return []
    limit = max(1, min(500, limit))
    pattern = f"%{pid}%"
    with session_scope() as session:
        rows = (
            session.query(FailureCycleRelistActionLogORM)
            .filter(FailureCycleRelistActionLogORM.status == "waiting")
            .filter(FailureCycleRelistActionLogORM.message.like(pattern))
            .order_by(
                FailureCycleRelistActionLogORM.action_at.desc(),
                FailureCycleRelistActionLogORM.action_log_id.desc(),
            )
            .limit(limit * 3)
            .all()
        )
        latest: dict[str, FailureCycleRelistActionLogORM] = {}
        for row in rows:
            rid = str(row.feishu_record_id or "").strip()
            if rid and rid not in latest:
                latest[rid] = row
        out = list(latest.values())[:limit]
        for row in out:
            session.expunge(row)
        return out


def list_failure_cycle_relist_poll_logs(*, limit: int = 20) -> list[FailureCycleRelistPollLogORM]:
    if not is_database_available():
        return []
    limit = max(1, min(100, limit))
    with session_scope() as session:
        rows = (
            session.query(FailureCycleRelistPollLogORM)
            .order_by(
                FailureCycleRelistPollLogORM.polled_at.desc(),
                FailureCycleRelistPollLogORM.poll_log_id.desc(),
            )
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def latest_failure_cycle_relist_actions_by_record_ids(
    record_ids: list[str],
) -> dict[str, FailureCycleRelistActionLogORM]:
    if not is_database_available():
        return {}
    ids = [str(rid).strip() for rid in record_ids if str(rid).strip()]
    if not ids:
        return {}
    with session_scope() as session:
        rows = (
            session.query(FailureCycleRelistActionLogORM)
            .filter(FailureCycleRelistActionLogORM.feishu_record_id.in_(ids))
            .order_by(
                FailureCycleRelistActionLogORM.action_at.desc(),
                FailureCycleRelistActionLogORM.action_log_id.desc(),
            )
            .all()
        )
        latest: dict[str, FailureCycleRelistActionLogORM] = {}
        for row in rows:
            rid = str(row.feishu_record_id or "").strip()
            if rid and rid not in latest:
                session.expunge(row)
                latest[rid] = row
        return latest


def get_wecom_daily_content_row(content_date: date) -> WecomDailyContentORM | None:
    """读取指定日期的日报手动内容；无记录返回 None。"""
    if not is_database_available():
        return None
    with session_scope() as session:
        row = (
            session.query(WecomDailyContentORM)
            .filter(WecomDailyContentORM.content_date == content_date)
            .first()
        )
        if row:
            session.expunge(row)
        return row


def upsert_wecom_daily_content_row(
    *,
    content_date: date,
    pdd_in_progress: str = "",
    taobao_netdisk_materials: str = "",
    taobao_in_progress: str = "",
) -> WecomDailyContentORM | None:
    """按自然日写入日报手动内容；同一天重复保存则覆盖。"""
    if not is_database_available():
        return None
    now = datetime.now()
    with session_scope() as session:
        row = (
            session.query(WecomDailyContentORM)
            .filter(WecomDailyContentORM.content_date == content_date)
            .first()
        )
        if row:
            row.pdd_in_progress = str(pdd_in_progress or "")
            row.taobao_netdisk_materials = str(taobao_netdisk_materials or "")
            row.taobao_in_progress = str(taobao_in_progress or "")
            row.updated_at = now
        else:
            row = WecomDailyContentORM(
                record_id=uuid.uuid4().hex,
                content_date=content_date,
                pdd_in_progress=str(pdd_in_progress or ""),
                taobao_netdisk_materials=str(taobao_netdisk_materials or ""),
                taobao_in_progress=str(taobao_in_progress or ""),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def insert_wecom_daily_report_log(
    *,
    platform: str,
    report_date: date,
    message: str,
    trigger_kind: str = "manual",
    status: str = "success",
    errcode: int = 0,
    errmsg: str = "",
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    webhook_target: str = "daily_report",
) -> WecomDailyReportLogORM | None:
    if not is_database_available():
        return None
    now = datetime.now()
    row = WecomDailyReportLogORM(
        log_id=uuid.uuid4().hex,
        platform=str(platform or "pdd"),
        report_date=report_date,
        window_start=window_start,
        window_end=window_end,
        message=str(message or ""),
        trigger_kind=str(trigger_kind or "manual"),
        status=str(status or "success"),
        errcode=int(errcode or 0),
        errmsg=str(errmsg or ""),
        webhook_target=str(webhook_target or "daily_report"),
        created_at=now,
    )
    with session_scope() as session:
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def list_wecom_daily_report_logs(
    *,
    page: int = 1,
    page_size: int = 20,
    platform: str = "",
) -> tuple[list[WecomDailyReportLogORM], int]:
    if not is_database_available():
        return [], 0
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    with session_scope() as session:
        query = session.query(WecomDailyReportLogORM)
        if platform:
            query = query.filter(WecomDailyReportLogORM.platform == platform)
        total = int(query.order_by(None).count())
        rows = (
            query.order_by(
                WecomDailyReportLogORM.created_at.desc(),
                WecomDailyReportLogORM.log_id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows, total


def get_wecom_daily_report_log(log_id: str) -> WecomDailyReportLogORM | None:
    if not is_database_available():
        return None
    key = str(log_id or "").strip()
    if not key:
        return None
    with session_scope() as session:
        row = session.get(WecomDailyReportLogORM, key)
        if row:
            session.expunge(row)
        return row


def get_wecom_git_digest_cache(cache_key: str) -> WecomGitDigestCacheORM | None:
    if not is_database_available():
        return None
    key = str(cache_key or "").strip()
    if not key:
        return None
    with session_scope() as session:
        row = (
            session.query(WecomGitDigestCacheORM)
            .filter(WecomGitDigestCacheORM.cache_key == key)
            .first()
        )
        if row:
            session.expunge(row)
        return row


def upsert_wecom_git_digest_cache(
    *,
    cache_key: str,
    report_date: date,
    commit_fingerprint: str,
    window_start: datetime,
    window_end: datetime,
    summary: str,
    commit_count: int,
) -> WecomGitDigestCacheORM | None:
    if not is_database_available():
        return None
    key = str(cache_key or "").strip()
    if not key:
        return None
    now = datetime.now()
    with session_scope() as session:
        row = (
            session.query(WecomGitDigestCacheORM)
            .filter(WecomGitDigestCacheORM.cache_key == key)
            .first()
        )
        if row:
            row.summary = str(summary or "")
            row.commit_count = int(commit_count or 0)
            row.commit_fingerprint = str(commit_fingerprint or "")
            row.window_start = window_start
            row.window_end = window_end
            row.updated_at = now
        else:
            row = WecomGitDigestCacheORM(
                cache_id=uuid.uuid4().hex,
                cache_key=key,
                report_date=report_date,
                commit_fingerprint=str(commit_fingerprint or ""),
                window_start=window_start,
                window_end=window_end,
                summary=str(summary or ""),
                commit_count=int(commit_count or 0),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def create_inventory_delist_record(
    *,
    job_id: str,
    run_id: str = "",
    account_id: str,
    shop_display_name: str = "",
    product_code: str,
    merchant_code: str = "",
    mapping_id: str = "",
    pdd_product_id: str = "",
    family_code: str = "",
    image_set: str = "",
    erp_available_qty: int | None = None,
    erp_original_qty: int | None = None,
    is_test_override: bool = False,
    is_common_on_sale: bool = False,
    trigger: str = "manual",
    execution_mode: str = "parallel",
    dry_run: bool = False,
    delist_status: str = "",
    message: str = "",
    is_relisted: bool = False,
    delisted_at: datetime | None = None,
) -> InventoryDelistRecordORM | None:
    if not is_database_available():
        return None
    product_code = str(product_code or "").strip()
    if not product_code:
        return None
    now = delisted_at or datetime.now()
    with session_scope() as session:
        row = InventoryDelistRecordORM(
            record_id=uuid.uuid4().hex,
            job_id=str(job_id or "").strip(),
            run_id=str(run_id or "").strip(),
            account_id=str(account_id or "").strip(),
            shop_display_name=str(shop_display_name or "").strip(),
            product_code=product_code,
            merchant_code=str(merchant_code or "").strip(),
            mapping_id=str(mapping_id or "").strip(),
            pdd_product_id=str(pdd_product_id or "").strip(),
            family_code=str(family_code or "").strip(),
            image_set=str(image_set or "").strip(),
            erp_available_qty=erp_available_qty,
            erp_original_qty=erp_original_qty,
            is_test_override=bool(is_test_override),
            is_common_on_sale=bool(is_common_on_sale),
            trigger=str(trigger or "manual").strip() or "manual",
            execution_mode=str(execution_mode or "parallel").strip() or "parallel",
            dry_run=bool(dry_run),
            delist_status=str(delist_status or "").strip(),
            message=str(message or "").strip(),
            is_relisted=bool(is_relisted),
            delisted_at=now,
            created_at=datetime.now(),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
        return row


def list_inventory_delist_records(
    *,
    account_id: str | None = None,
    job_id: str | None = None,
    limit: int = 50,
) -> list[InventoryDelistRecordORM]:
    if not is_database_available():
        return []
    limit = max(1, min(500, limit))
    with session_scope() as session:
        query = session.query(InventoryDelistRecordORM)
        if account_id and str(account_id).strip():
            query = query.filter(InventoryDelistRecordORM.account_id == str(account_id).strip())
        if job_id and str(job_id).strip():
            query = query.filter(InventoryDelistRecordORM.job_id == str(job_id).strip())
        rows = (
            query.order_by(
                InventoryDelistRecordORM.delisted_at.desc(),
                InventoryDelistRecordORM.record_id.desc(),
            )
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows


def update_inventory_delist_record_relist(
    record_id: str,
    *,
    is_relisted: bool,
    message: str = "",
) -> bool:
    if not is_database_available():
        return False
    rid = str(record_id or "").strip()
    if not rid:
        return False
    with session_scope() as session:
        row = session.get(InventoryDelistRecordORM, rid)
        if not row:
            return False
        row.is_relisted = bool(is_relisted)
        if message:
            row.message = str(message).strip()
        session.flush()
        return True


def get_inventory_delist_record(record_id: str) -> InventoryDelistRecordORM | None:
    if not is_database_available():
        return None
    rid = str(record_id or "").strip()
    if not rid:
        return None
    with session_scope() as session:
        row = session.get(InventoryDelistRecordORM, rid)
        if row:
            session.expunge(row)
        return row


def list_pending_relist_records(
    *,
    account_ids: list[str] | None = None,
    limit: int = 500,
) -> list[InventoryDelistRecordORM]:
    """列出已下架成功、尚未重新上架的记录（不含 dry_run）。"""
    if not is_database_available():
        return []
    limit = max(1, min(2000, limit))
    with session_scope() as session:
        query = session.query(InventoryDelistRecordORM).filter(
            InventoryDelistRecordORM.delist_status == "completed",
            InventoryDelistRecordORM.is_relisted.is_(False),
            InventoryDelistRecordORM.dry_run.is_(False),
        )
        if account_ids:
            ids = [str(aid).strip() for aid in account_ids if str(aid).strip()]
            if ids:
                query = query.filter(InventoryDelistRecordORM.account_id.in_(ids))
        rows = (
            query.order_by(
                InventoryDelistRecordORM.delisted_at.desc(),
                InventoryDelistRecordORM.record_id.desc(),
            )
            .limit(limit)
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows
