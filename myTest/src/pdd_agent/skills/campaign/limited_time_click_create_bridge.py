"""
限时限量购 — 「立即创建」点击桥接。

老店：管理页顶部 button「立即创建」（沿用 limited_time._click_create）。
新号：NoCurrentActivity 落地页 div「立即创建」（limited_time_new_account_landing）。
"""

from __future__ import annotations

from collections.abc import Callable

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.skills.campaign.limited_time_new_account_landing import (
    click_new_account_landing_create,
    detect_new_account_limited_time_landing,
)


def click_create_entering_activity_settings(
    page: DpPage,
    account_id: str,
    *,
    legacy_click_create: Callable[[DpPage, str], bool],
    wait_activity_settings: Callable[[DpPage, str], bool],
    dismiss_popup: Callable[[DpPage], None] | None = None,
    switch_to_latest_tab: Callable[[DpPage], bool] | None = None,
) -> bool:
    """
    点击「立即创建」并进入活动设置页。

    已处于活动设置页则直接返回 True；识别到新号落地页时走新兜底，否则走老店逻辑。
    """
    if wait_activity_settings(page, account_id, timeout=2):
        print(f"[{account_id}] 已在活动设置页，跳过立即创建", flush=True)
        return True

    detect_result = detect_new_account_limited_time_landing(page)
    if detect_result.get("match"):
        print(
            f"[{account_id}] 识别到新号限时限量购落地页：{detect_result.get('reason')}，"
            "尝试点击中部立即创建",
            flush=True,
        )
        if not click_new_account_landing_create(
            page,
            account_id,
            dismiss_popup=dismiss_popup,
            switch_to_latest_tab=switch_to_latest_tab,
        ):
            return False
        if wait_activity_settings(page, account_id, timeout=12):
            print(f"[{account_id}] 新号落地页：已进入活动设置页", flush=True)
            return True
        print(
            f"[{account_id}] 新号落地页：点击立即创建后仍未进入活动设置页，"
            f"url={page.url}",
            flush=True,
        )
        return False

    return legacy_click_create(page, account_id)
