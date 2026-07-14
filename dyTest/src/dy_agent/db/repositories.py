"""数据库仓储：店铺账号 + 运行记录查询。"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import select

from dy_agent.core.config import AccountConfig, YamlSettings
from dy_agent.db.models import AccountORM, LoginStatusORM, PublishedProductORM
from dy_agent.db.session import is_database_available, session_scope


def db_accounts_enabled() -> bool:
    return is_database_available()


def _to_account_config(row: AccountORM) -> AccountConfig:
    return AccountConfig(
        account_id=row.account_id,
        enabled=row.enabled,
        phone=row.phone or "",
        username=row.username or "",
        password=row.password or "",
        login_mode=row.login_mode or "sms",
        product_codes=list(row.product_codes or []),
    )


def seed_accounts_from_yaml(settings: YamlSettings) -> None:
    """数据库 accounts 为空时，用 settings.yaml 做一次初始导入，导入后清空 yaml 避免重复回填。"""
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
                    phone=acc.phone,
                    username=acc.username,
                    password=acc.password,
                    login_mode=acc.login_mode,
                    product_codes=list(acc.product_codes),
                )
            )
    from dy_agent.core.config import save_yaml_settings

    settings.accounts = []
    save_yaml_settings(settings)


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
                phone=acc.phone,
                username=acc.username,
                password=acc.password,
                login_mode=acc.login_mode,
                product_codes=list(acc.product_codes),
            )
        )
    return acc


def update_account_config(
    account_id: str, data: AccountConfig, *, keep_empty_password: bool
) -> AccountConfig | None:
    with session_scope() as session:
        row = session.get(AccountORM, account_id)
        if not row:
            return None
        row.enabled = data.enabled
        row.phone = data.phone
        row.username = data.username
        row.login_mode = data.login_mode
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
        login_row = session.get(LoginStatusORM, account_id)
        if login_row:
            session.delete(login_row)
        return True


def get_shop_display_name(account_id: str) -> str:
    return get_cached_shop_display_name(account_id)


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
    if not aid or not name or not is_database_available():
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
    dy_product_id: str,
    list_status: str = "",
    platform_status: str = "on_sale",
    product_link: str = "",
    listed_at: datetime | None = None,
    published_at: datetime | None = None,
    capture_meta: dict | None = None,
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
            "dy_product_id": dy_product_id,
            "list_status": list_status,
            "platform_status": platform_status,
            "product_link": product_link,
            "listed_at": listed_at,
            "published_at": published_at or listed_at or datetime.now(),
            "capture_meta": capture_meta or {},
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


def list_published_products(
    *,
    account_id: str = "",
    limit: int = 100,
) -> list[PublishedProductORM]:
    if not is_database_available():
        return []
    with session_scope() as session:
        stmt = select(PublishedProductORM).order_by(
            PublishedProductORM.listed_at.desc(),
            PublishedProductORM.updated_at.desc(),
        )
        if account_id:
            stmt = stmt.where(PublishedProductORM.account_id == account_id)
        rows = list(session.scalars(stmt.limit(max(1, limit))).all())
        for row in rows:
            session.expunge(row)
        return rows
