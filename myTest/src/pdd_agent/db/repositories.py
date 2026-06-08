"""数据库仓储函数。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pdd_agent.core.config import AccountConfig, YamlSettings
from pdd_agent.db.models import AccountLockORM, AccountORM, LoginStatusORM, TaskQueueORM
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


def claim_due_task(max_concurrent: int) -> TaskQueueORM | None:
    if not is_database_available():
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
