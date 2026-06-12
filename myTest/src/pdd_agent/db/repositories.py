"""数据库仓储函数。"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pdd_agent.core.config import AccountConfig, YamlSettings
from pdd_agent.db.models import (
    AccountLockORM,
    AccountORM,
    FailureItemORM,
    LoginStatusORM,
    PublishedProductORM,
    QueueControlORM,
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
        for row in rows:
            row.status = "queued"
            row.error = "requeued after worker restart"
            row.started_at = None
            row.scheduled_at = now
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
    if not is_database_available():
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(TaskQueueORM.status, func.count()).group_by(TaskQueueORM.status)
        ).all()
        return {str(status): int(count) for status, count in rows}


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

        running_accounts = set(
            session.scalars(
                select(TaskQueueORM.account_id).where(TaskQueueORM.status == "running")
            ).all()
        )

        stmt = (
            select(TaskQueueORM)
            .where(TaskQueueORM.status == "queued")
            .where(TaskQueueORM.scheduled_at <= datetime.now())
            .order_by(TaskQueueORM.scheduled_at.asc(), TaskQueueORM.created_at.asc())
            .limit(20)
        )
        for row in session.scalars(stmt).all():
            if row.account_id in running_accounts:
                continue
            account_control = session.get(QueueControlORM, ("account", row.account_id))
            if account_control and account_control.paused:
                continue
            row.status = "running"
            row.started_at = datetime.now()
            row.attempts += 1
            row.error = ""
            session.flush()
            session.expunge(row)
            return row
        return None


def finish_queue_task(task_id: str, *, success: bool, error: str = "") -> None:
    if not is_database_available():
        return
    with session_scope() as session:
        row = session.get(TaskQueueORM, task_id)
        if not row:
            return
        row.status = "success" if success else "failed"
        row.finished_at = datetime.now()
        row.error = error


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
        else:
            row = PublishedProductORM(mapping_id=mapping_id, **data)
            session.add(row)
        session.flush()
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
        session.flush()
        session.expunge(row)
        return row


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
            if row and row.expires_at > now:
                return row.owner == owner
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
