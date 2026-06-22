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
