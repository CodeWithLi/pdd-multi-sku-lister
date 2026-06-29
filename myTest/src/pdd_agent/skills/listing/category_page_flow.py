"""分类页三种模式：direct_next（已选类目直接下一步）、render_wait、manual_picker。"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pdd_agent.browser.dp_compat_sync import DpPage

CategoryPageMode = Literal["direct_next", "render_wait", "manual_picker"]

# 演示/workaround：20–45s，步长 5
CATEGORY_RENDER_WAIT_OPTIONS = (20, 25, 30, 35, 40, 45)
DEFAULT_SIMPLE_RENDER_WAIT = 10
DEFAULT_CATEGORY_ADVANCE_WAIT_BURST = 30
DEFAULT_CATEGORY_ADVANCE_WAIT_SIMPLE = 15
DEFAULT_MANUAL_PICKER_ADVANCE_WAIT = 45


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


def prepare_category_before_next(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    mode: CategoryPageMode,
    burst_demo: bool,
) -> None:
    """分类页点「下一步」前的准备：按模式分流。"""
    from pdd_agent.skills.listing import upload as listing_upload

    if mode == "direct_next":
        print(
            f"[{account_id}] [{label}] 分类页直通模式：已识别为可直接点击下一步",
            flush=True,
        )
        listing_upload._dismiss_category_search_overlay(page, account_id, label)
        return

    if mode == "render_wait":
        # 兼容多链路场景：若按钮已就绪，直接进入下一步点击，不改变 20-45s 规则本身。
        submit_state = listing_upload._read_category_submit_state(page)
        if submit_state.get("ready"):
            print(
                f"[{account_id}] [{label}] 分类下一步已就绪，跳过渲染等待并直接尝试点击",
                flush=True,
            )
            listing_upload._dismiss_category_search_overlay(page, account_id, label)
            return
        wait_category_section_ready(page, account_id, label, burst_demo=burst_demo)
        listing_upload._click_category_section_blank(page)
        listing_upload._dismiss_category_search_overlay(page, account_id, label)
        if burst_demo:
            print(
                f"[{account_id}] [{label}] 分类页 workaround：已点击空白失焦，准备点推荐类目",
                flush=True,
            )
        return

    listing_upload._confirm_category_picker_selection(page, account_id, label)
    listing_upload._dismiss_category_search_overlay(page, account_id, label)


def click_category_next_and_advance(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    ui_type: str = "C",
    mode: CategoryPageMode = "render_wait",
    burst_demo: bool = True,
) -> tuple[bool, Literal["", "not_found", "no_advance"]]:
    """点击下一步并等待跳转。"""
    from pdd_agent.skills.listing import upload as listing_upload

    if mode == "manual_picker":
        print(
            f"[{account_id}] [{label}] 分类选手动模式：确认选类后点击下一步",
            flush=True,
        )
        listing_upload._confirm_category_picker_selection(page, account_id, label)
        listing_upload._dismiss_category_search_overlay(page, account_id, label)
        listing_upload._wait_category_submit_ready(
            page, account_id, label, click_recommendation=False
        )
        if not listing_upload._click_category_next_step_burst(
            page, ui_type=ui_type, account_id=account_id, label=label
        ):
            return False, "not_found"
        if not listing_upload._wait_for_category_page_advance(
            page,
            account_id,
            label,
            max_wait=DEFAULT_MANUAL_PICKER_ADVANCE_WAIT,
            mode="manual_picker",
            ui_type=ui_type,
        ):
            return False, "no_advance"
        return True, ""

    if mode == "direct_next":
        print(
            f"[{account_id}] [{label}] 分类页直通模式：直接点击下一步",
            flush=True,
        )
        if not listing_upload._click_category_next_step(
            page, ui_type=ui_type, account_id=account_id, label=label
        ):
            return False, "not_found"
        if not listing_upload._wait_for_category_page_advance(
            page,
            account_id,
            label,
            max_wait=DEFAULT_CATEGORY_ADVANCE_WAIT_SIMPLE,
            mode="render_wait",
            ui_type=ui_type,
        ):
            return False, "no_advance"
        return True, ""

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
            mode="render_wait",
            ui_type=ui_type,
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
        mode="render_wait",
        ui_type=ui_type,
    ):
        return False, "no_advance"
    return True, ""
