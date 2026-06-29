"""分支 C 分类页：等待渲染 + 点击「下一步」（支持演示用随机连点 workaround）。"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

# 演示/workaround：20–45s，步长 5
CATEGORY_RENDER_WAIT_OPTIONS = (20, 25, 30, 35, 40, 45)
DEFAULT_SIMPLE_RENDER_WAIT = 10
DEFAULT_CATEGORY_ADVANCE_WAIT_BURST = 30
DEFAULT_CATEGORY_ADVANCE_WAIT_SIMPLE = 15


def random_category_render_wait_seconds() -> int:
    """分类区块渲染等待上限（秒），20–45 且为 5 的倍数。"""
    return random.choice(CATEGORY_RENDER_WAIT_OPTIONS)


def resolve_category_render_wait(*, burst_demo: bool) -> int:
    if burst_demo:
        return random_category_render_wait_seconds()
    return DEFAULT_SIMPLE_RENDER_WAIT


def wait_category_section_ready(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    burst_demo: bool,
) -> bool:
    from pdd_agent.skills.listing import upload as listing_upload

    max_wait = resolve_category_render_wait(burst_demo=burst_demo)
    if burst_demo:
        print(
            f"[{account_id}] [{label}] 分类页 workaround：随机等待分类渲染最多 {max_wait}s",
            flush=True,
        )
    return listing_upload._wait_for_category_section_ready(
        page, account_id, label, max_wait=max_wait
    )


def click_category_next_and_advance(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    ui_type: str = "C",
    burst_demo: bool,
) -> tuple[bool, Literal["", "not_found", "no_advance"]]:
    """点击下一步并等待跳转；burst_demo 开启时随机连点 + 长监听。"""
    from pdd_agent.skills.listing import upload as listing_upload

    if burst_demo:
        print(
            f"[{account_id}] [{label}] 分类页 workaround：首次点击后未跳转将随机连点 3–5 次",
            flush=True,
        )
        if not listing_upload._click_category_next_step_burst(
            page, ui_type=ui_type, account_id=account_id, label=label
        ):
            return False, "not_found"
        if not listing_upload._wait_for_category_page_advance(
            page,
            account_id,
            label,
            max_wait=DEFAULT_CATEGORY_ADVANCE_WAIT_BURST,
        ):
            return False, "no_advance"
        return True, ""

    if not listing_upload._click_category_next_step(
        page, ui_type=ui_type, account_id=account_id, label=label
    ):
        return False, "not_found"
    if not listing_upload._wait_for_category_page_advance(
        page,
        account_id,
        label,
        max_wait=DEFAULT_CATEGORY_ADVANCE_WAIT_SIMPLE,
    ):
        return False, "no_advance"
    return True, ""
