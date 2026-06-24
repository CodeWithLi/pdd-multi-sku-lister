"""店铺展示名解析：飞书日志等场景使用拼多多后台店铺名，而非登录账号。"""

from __future__ import annotations

from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.repositories import get_account_config, get_cached_shop_display_name


def resolve_account_display_name(account_id: str) -> str:
    """
    返回写入飞书「店铺名称」的展示名。

    优先使用登录后缓存的拼多多店铺名（如「兔兔潮玩屋」），
    无缓存时回退登录账号（如「多多青提2601」），最后回退 account_id。
    """
    aid = str(account_id or "").strip()
    if not aid:
        return ""

    cached = get_cached_shop_display_name(aid)
    if cached:
        return cached

    try:
        settings = load_yaml_settings()
        account = get_account_config(settings, aid)
        if account and str(account.username or "").strip():
            return str(account.username).strip()
    except Exception:
        pass
    return aid


def resolve_account_id_by_display_name(display_name: str) -> str:
    """按飞书「店铺名称」反查 account_id（展示名 / 登录名 / account_id）。"""
    name = str(display_name or "").strip()
    if not name:
        return ""

    try:
        from pdd_agent.db.repositories import list_login_status_rows

        for row in list_login_status_rows():
            shop = str(row.shop_display_name or "").strip()
            if shop and shop == name:
                return str(row.account_id or "").strip()
    except Exception:
        pass

    try:
        settings = load_yaml_settings()
        for acc in settings.accounts:
            if not acc.enabled:
                continue
            aid = str(acc.account_id or "").strip()
            if not aid:
                continue
            if resolve_account_display_name(aid) == name:
                return aid
            if str(acc.username or "").strip() == name:
                return aid
            if aid == name:
                return aid
    except Exception:
        pass
    return ""
