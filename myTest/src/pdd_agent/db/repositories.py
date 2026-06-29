"""数据库仓储函数。"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
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
    LoginStatusORM,
    ProductStyleColorORM,
    PublishedProductORM,
    QueueControlORM,
    ListedAssetFolderORM,
    TaskQueueORM,
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
    with session_scope() as session:
        rows = session.scalars(
            select(TaskQueueORM).where(TaskQueueORM.status == "running")
        ).all()
        now = datetime.now()
        account_ids = {row.account_id for row in rows if row.account_id}
        for row in rows:
            row.status = "queued"
            row.error = "requeued after worker restart"
            row.started_at = None
            row.scheduled_at = now
        for account_id in account_ids:
            lock = session.get(AccountLockORM, account_id)
            if lock:
                session.delete(lock)
        return len(rows)


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


def delete_published_product(mapping_id: str) -> bool:
    if not is_database_available():
        return False
    with session_scope() as session:
        row = session.get(PublishedProductORM, mapping_id)
        if not row:
            return False
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
