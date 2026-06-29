"""店铺展示名解析：飞书日志等场景使用拼多多后台店铺名，而非登录账号。"""

from __future__ import annotations

from pdd_agent.core.config import load_yaml_settings
from pdd_agent.core.logging import get_logger
from pdd_agent.db.repositories import get_account_config, get_cached_shop_display_name

logger = get_logger(__name__)


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


def _account_id_exists(account_id: str) -> bool:
    aid = str(account_id or "").strip()
    if not aid:
        return False
    try:
        settings = load_yaml_settings()
        for acc in settings.accounts:
            if not acc.enabled:
                continue
            if str(acc.account_id or "").strip() == aid:
                return True
    except Exception:
        pass
    return False


def list_account_ids_by_display_name(display_name: str) -> list[str]:
    """按店铺展示名 / 登录名 / account_id 列出所有已启用账号（去重、稳定排序）。"""
    name = str(display_name or "").strip()
    if not name:
        return []

    matched: list[str] = []
    seen: set[str] = set()

    def _add(aid: str) -> None:
        candidate = str(aid or "").strip()
        if not candidate or candidate in seen or not _account_id_exists(candidate):
            return
        seen.add(candidate)
        matched.append(candidate)

    try:
        from pdd_agent.db.repositories import list_login_status_rows

        for row in list_login_status_rows():
            shop = str(row.shop_display_name or "").strip()
            if shop and shop == name:
                _add(str(row.account_id or ""))
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
                _add(aid)
            elif str(acc.username or "").strip() == name:
                _add(aid)
            elif aid == name:
                _add(aid)
    except Exception:
        pass

    return matched


def pick_cycle_relist_account_from_candidates(candidates: list[str]) -> str:
    """
    同名多子账号时任选一个可跑账号。

    同一拼多多店铺可有多个子账号（shop_display_name 相同）；循环上架只需
    任意一个未占用的子账号即可。优先选未跑队列/未锁 Profile 的账号。
    """
    items = [str(x).strip() for x in candidates if str(x).strip()]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]

    busy: set[str] = set()
    try:
        from pdd_agent.db.repositories import list_busy_account_ids

        busy = list_busy_account_ids()
    except Exception:
        pass

    for aid in items:
        if aid not in busy:
            logger.info(
                "cycle relist: %d accounts share shop name, picked idle %s (candidates=%s)",
                len(items),
                aid,
                items,
            )
            return aid

    picked = items[0]
    logger.info(
        "cycle relist: %d accounts share shop name, all busy, using %s (candidates=%s)",
        len(items),
        picked,
        items,
    )
    return picked


def resolve_cycle_relist_account_id(
    *,
    account_name: str = "",
    account_id: str = "",
) -> tuple[str, str]:
    """
    失败日志循环上架：按飞书「店铺」/ account_id 列解析目标店铺。

    飞书未写 account_id 且多个子账号 shop_display_name 相同时，任选一个
    未占用子账号即可（同一拼多多 店铺后台等价）。

    返回 (account_id, error_message)。成功时 error 为空。
    """
    hinted = str(account_id or "").strip()
    if hinted:
        if _account_id_exists(hinted):
            return hinted, ""
        resolved = resolve_account_id_by_display_name(hinted)
        if resolved:
            return resolved, ""

    name = str(account_name or "").strip()
    if name:
        if _account_id_exists(name):
            return name, ""
        candidates = list_account_ids_by_display_name(name)
        if candidates:
            return pick_cycle_relist_account_from_candidates(candidates), ""
        return "", f"无法识别店铺「{name}」，请确认飞书「店铺」列与系统店铺名称一致"

    if hinted:
        return "", f"无法识别店铺 ID「{hinted}」，请检查系统店铺配置"
    return "", "飞书失败日志缺少店铺信息，无法按记录重跑对应店铺"


def resolve_account_id_by_display_name(display_name: str) -> str:
    """按飞书「店铺名称」反查 account_id（展示名 / 登录名 / account_id）。"""
    return pick_cycle_relist_account_from_candidates(
        list_account_ids_by_display_name(display_name)
    )
