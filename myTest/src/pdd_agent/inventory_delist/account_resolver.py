"""库存下架 — 店铺 ID 解析（与 /api/config/accounts 同源：DB 优先）。"""

from __future__ import annotations

from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.repositories import list_account_configs


def list_enabled_account_ids() -> list[str]:
    settings = load_yaml_settings()
    return [
        str(acc.account_id).strip()
        for acc in list_account_configs(settings, enabled_only=True)
        if str(acc.account_id).strip()
    ]


def resolve_enabled_account_ids(account_ids: list[str] | None) -> tuple[list[str], list[str]]:
    """
    解析有效店铺 ID。

    与 config_service.list_accounts(enabled_only=True) 使用同一数据源，
    避免 YAML 与数据库不一致时前端可选、后端却报「不在可用列表」。
    """
    allowed = set(list_enabled_account_ids())
    selected = [str(aid).strip() for aid in (account_ids or []) if str(aid).strip()]
    if selected:
        resolved = [aid for aid in selected if aid in allowed]
        rejected = [aid for aid in selected if aid not in allowed]
        return resolved, rejected
    return sorted(allowed), []
