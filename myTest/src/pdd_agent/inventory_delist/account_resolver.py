"""库存下架 — 店铺 ID 解析（与 /api/config/accounts 同源：DB 优先）。"""

from __future__ import annotations

from pdd_agent.core.account_display import list_account_ids_by_display_name, resolve_account_display_name
from pdd_agent.core.config import load_yaml_settings
from pdd_agent.db.repositories import get_cached_shop_display_name, list_account_configs


def list_enabled_account_ids() -> list[str]:
    settings = load_yaml_settings()
    return [
        str(acc.account_id).strip()
        for acc in list_account_configs(settings, enabled_only=True)
        if str(acc.account_id).strip()
    ]


def _build_enabled_account_alias_map() -> dict[str, str]:
    """alias（account_id / 登录名 / 店铺名）-> 规范 account_id。"""
    settings = load_yaml_settings()
    alias_map: dict[str, str] = {}
    for acc in list_account_configs(settings, enabled_only=True):
        aid = str(acc.account_id).strip()
        if not aid:
            continue
        aliases = {aid}
        username = str(getattr(acc, "username", "") or "").strip()
        if username:
            aliases.add(username)
        shop = get_cached_shop_display_name(aid)
        if shop:
            aliases.add(shop)
        display = resolve_account_display_name(aid)
        if display:
            aliases.add(display)
        for alias in aliases:
            if alias not in alias_map:
                alias_map[alias] = aid
    return alias_map


def _resolve_one_account_id(
    raw: str,
    *,
    allowed: set[str],
    alias_map: dict[str, str],
) -> str | None:
    key = str(raw or "").strip()
    if not key:
        return None
    if key in allowed:
        return key
    if key in alias_map and alias_map[key] in allowed:
        return alias_map[key]
    candidates = [c for c in list_account_ids_by_display_name(key) if c in allowed]
    if candidates:
        return candidates[0]
    return None


def resolve_enabled_account_ids(account_ids: list[str] | None) -> tuple[list[str], list[str]]:
    """
    解析有效店铺 ID。

    与 config_service.list_accounts(enabled_only=True) 使用同一数据源，
    并支持按登录账号名、拼多多店铺展示名反查 account_id。
    """
    allowed = set(list_enabled_account_ids())
    alias_map = _build_enabled_account_alias_map()
    selected = [str(aid).strip() for aid in (account_ids or []) if str(aid).strip()]
    if not selected:
        return sorted(allowed), []

    resolved: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for raw in selected:
        canon = _resolve_one_account_id(raw, allowed=allowed, alias_map=alias_map)
        if canon:
            if canon not in seen:
                seen.add(canon)
                resolved.append(canon)
        else:
            rejected.append(raw)
    return resolved, rejected
