"""营销活动大厅：打开页面并按活动 ID 搜索。"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.browser.sync_login import ensure_session_sync, is_login_url
from pdd_agent.core.config import AccountConfig
from pdd_agent.skills.campaign.activity_price_validate import (
    _expand_all_specs_on_page,
    _pause_for_manual_review,
    filter_price_confirm_page,
    lookup_spec_codes_on_price_page,
)
from pdd_agent.skills.campaign.limited_time import (
    _bind_page,
    _body_text,
    _click_text,
    _dismiss_message_popup,
    _live_context_pages,
    _safe_exc,
)

MARKETING_ACTIVITIES_URLS = (
    "https://mms.pinduoduo.com/act/index",
    "https://mms.pinduoduo.com/act/signup/index",
    "https://mms.pinduoduo.com/act/signup",
)

# 前端可选活动列表（后续可扩展为配置或接口拉取）
# entry: goto_detail=同标签打开详情页；go_register=活动列表点「去报名」打开详情弹窗
# stop_after: submit=完整提交流程；price_page_prepared=选品后处理价格确认页；confirm_selection=仅确认选择（旧）
KNOWN_MARKETING_ACTIVITIES: tuple[dict[str, str], ...] = (
    {
        "activity_id": "20981",
        "name": "【618大促】20981长期报名入口",
        "entry": "goto_detail",
        "stop_after": "submit",
    },
    {
        "activity_id": "21365",
        "name": "限量7折100件",
        "entry": "go_register",
        "stop_after": "submit",
    },
)


def _get_activity_profile(activity_id: str) -> dict[str, str]:
    for item in KNOWN_MARKETING_ACTIVITIES:
        if str(item.get("activity_id") or "") == activity_id:
            return dict(item)
    return {
        "activity_id": activity_id,
        "name": activity_id,
        "entry": "goto_detail",
        "stop_after": "submit",
    }

# F12 实测：beast-core Input + placeholder 组合最稳；class 后缀会随版本变化。
ACTIVITY_SEARCH_INPUT_SELECTORS = (
    'input[data-testid="beast-core-input-nativeInput"][placeholder*="活动名称或ID"]',
    'input[data-testid="beast-core-input-nativeInput"][placeholder*="ID搜索"]',
    'input[data-testid="beast-core-input-nativeInput"][placeholder*="活动名称"][placeholder*="ID"]',
    'div[class*="IPT_inputBlockCell"] input[data-testid="beast-core-input-nativeInput"]',
    'input[placeholder*="活动名称或ID"]',
    'input[placeholder*="活动名称"][placeholder*="ID"]',
    'input[placeholder*="ID搜索"]',
)


def _read_marketing_phone_popup(page: DpPage) -> dict[str, Any]:
    """检测「设置营销联系电话」提示浮层（含立即设置按钮）是否展开。"""
    return page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 8 && r.height > 8
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }

        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }

        function rectOf(el) {
            const r = el.getBoundingClientRect();
            return {
                top: r.top,
                left: r.left,
                right: r.right,
                bottom: r.bottom,
                width: r.width,
                height: r.height,
            };
        }

        function isPhonePopoverText(text) {
            if (!text.includes('改价电话提醒')) return false;
            return text.includes('立即设置')
                || text.includes('活动流量骤减')
                || text.includes('活动提报审核');
        }

        function findPopoverFromButton() {
            const buttons = Array.from(document.querySelectorAll('button, a, span, div'))
                .filter(isVisible)
                .filter((el) => norm(el.innerText || el.textContent || '') === '立即设置');
            for (const btn of buttons) {
                let cur = btn;
                for (let depth = 0; depth < 12 && cur; depth += 1) {
                    const text = norm(cur.innerText || cur.textContent || '');
                    const rect = cur.getBoundingClientRect();
                    if (isPhonePopoverText(text) && rect.height >= 36 && rect.width >= 120) {
                        return { el: cur, text, rect, source: 'from_button' };
                    }
                    cur = cur.parentElement;
                }
            }
            return null;
        }

        function findPopoverContainer() {
            const selectors = [
                '[class*="popover"]',
                '[class*="Popover"]',
                '[class*="tooltip"]',
                '[class*="Tooltip"]',
                '[role="tooltip"]',
            ];
            const roots = [];
            selectors.forEach((selector) => {
                document.querySelectorAll(selector).forEach((el) => {
                    if (!isVisible(el)) return;
                    const text = norm(el.innerText || el.textContent || '');
                    if (!isPhonePopoverText(text)) return;
                    const rect = el.getBoundingClientRect();
                    roots.push({ el, text, rect, area: rect.width * rect.height, source: 'container' });
                });
            });
            if (!roots.length) return null;
            roots.sort((a, b) => b.area - a.area);
            return roots[0];
        }

        function findLargestTextPopover() {
            const roots = Array.from(document.querySelectorAll('div,section,article'))
                .filter(isVisible)
                .map((el) => {
                    const text = norm(el.innerText || el.textContent || '');
                    const rect = el.getBoundingClientRect();
                    return { el, text, rect, area: rect.width * rect.height };
                })
                .filter((item) => isPhonePopoverText(item.text))
                .filter((item) => item.rect.height >= 36 && item.rect.width >= 120);

            if (!roots.length) return null;
            roots.sort((a, b) => b.area - a.area);
            return { ...roots[0], source: 'largest_text' };
        }

        const popover = findPopoverFromButton() || findPopoverContainer() || findLargestTextPopover();
        if (!popover) {
            return { visible: false, reason: 'popover_not_open' };
        }

        return {
            visible: true,
            kind: 'phone_popover',
            source: popover.source,
            text: (popover.text || '').replace(/\\s+/g, ' ').trim().slice(0, 220),
            rect: rectOf(popover.el),
        };
        """
    ) or {"visible": False, "reason": "read_popup_js_failed"}


def _find_marketing_header_blank_point(page: DpPage) -> dict[str, Any]:
    """定位「营销活动报名」标题右侧、搜索框上方那块空白（用户红框区域）。"""
    return page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 8 && r.height > 8
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }

        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }

        function findExactText(text) {
            return Array.from(document.querySelectorAll('div,span,h1,h2,h3,p,label'))
                .filter(isVisible)
                .map((el) => ({
                    el,
                    text: norm(el.innerText || el.textContent || ''),
                    rect: el.getBoundingClientRect(),
                }))
                .filter((item) => item.text === text)
                .sort((a, b) => a.rect.top - b.rect.top);
        }

        function findSearchInput() {
            return Array.from(document.querySelectorAll('input[data-testid="beast-core-input-nativeInput"], input'))
                .filter(isVisible)
                .find((el) => {
                    const ph = (el.getAttribute('placeholder') || '').trim();
                    return ph.includes('活动名称或ID') || ph.includes('ID搜索')
                        || (ph.includes('活动名称') && ph.includes('ID'));
                }) || null;
        }

        const titles = findExactText('营销活动报名');
        const phoneLinks = findExactText('设置营销联系电话');
        const shopLinks = findExactText('开启全店报名');
        const title = titles[0] || null;
        const rightLink = phoneLinks[0] || shopLinks[0] || null;
        const searchInput = findSearchInput();

        if (title && rightLink) {
            const gap = rightLink.rect.left - title.rect.right;
            if (gap >= 50) {
                return {
                    found: true,
                    x: title.rect.right + Math.max(24, gap * 0.42),
                    y: title.rect.top + title.rect.height / 2,
                    method: 'header_blank_between_title_and_links',
                };
            }
        }

        if (title && searchInput) {
            const sr = searchInput.getBoundingClientRect();
            return {
                found: true,
                x: Math.min(title.rect.right + 110, Math.max(title.rect.right + 40, sr.left - 120)),
                y: title.rect.bottom + Math.max(10, (sr.top - title.rect.bottom) * 0.42),
                method: 'header_blank_above_search',
            };
        }

        if (title) {
            return {
                found: true,
                x: title.rect.right + 96,
                y: title.rect.top + title.rect.height / 2,
                method: 'header_blank_near_title',
            };
        }

        return { found: false, reason: 'header_blank_not_found' };
        """
    ) or {"found": False, "reason": "header_blank_js_failed"}


def _collect_blank_click_points(popup_rect: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """根据浮层位置生成可点击的空白坐标。"""
    rect = popup_rect or {}
    top = float(rect.get("top") or 0)
    left = float(rect.get("left") or 0)
    right = float(rect.get("right") or left)
    bottom = float(rect.get("bottom") or top)
    width = float(rect.get("width") or max(0, right - left))
    height = float(rect.get("height") or max(0, bottom - top))

    points: list[tuple[str, float, float]] = [
        ("left_content", max(220, left - 180), max(260, top + height + 80)),
        ("below_popover", max(240, left - 60), max(320, bottom + 90)),
        ("activity_list", 360, max(420, bottom + 140)),
        ("left_sidebar", 110, max(320, top + 120)),
        ("filter_area", 300, max(220, top - 40)),
        ("far_left", 180, 360),
        ("search_left", max(180, left - 260), max(210, top - 20)),
    ]
    if width < 180 or height < 40:
        points.insert(0, ("near_trigger", max(220, left - 220), max(300, bottom + 120)))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for name, x, y in points:
        key = (int(x), int(y))
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"name": name, "x": x, "y": y})
    return deduped


def _playwright_mouse_click(page: DpPage, x: float, y: float) -> dict[str, Any]:
    try:
        raw_page = getattr(page, "_page", None)
        if raw_page is None:
            return {"clicked": False, "reason": "page_unavailable", "x": x, "y": y}
        raw_page.mouse.click(x, y)
        return {"clicked": True, "method": "playwright_mouse", "x": x, "y": y}
    except Exception as exc:
        return {"clicked": False, "method": "playwright_mouse", "x": x, "y": y, "error": _safe_exc(exc)}


def _press_escape(page: DpPage) -> dict[str, Any]:
    try:
        raw_page = getattr(page, "_page", None)
        if raw_page is None:
            return {"pressed": False, "reason": "page_unavailable"}
        raw_page.keyboard.press("Escape")
        return {"pressed": True, "method": "escape"}
    except Exception as exc:
        return {"pressed": False, "method": "escape", "error": _safe_exc(exc)}


def _click_filter_tab(page: DpPage) -> dict[str, Any]:
    return page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 8 && r.height > 8
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }
        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }
        const tabs = Array.from(document.querySelectorAll('button, span, div, a'))
            .filter(isVisible)
            .map((el) => ({
                el,
                text: norm(el.innerText || el.textContent || ''),
                rect: el.getBoundingClientRect(),
            }))
            .filter((item) => item.text === '全部活动' || item.text === '我能参加的活动')
            .sort((a, b) => a.rect.top - b.rect.top);
        if (!tabs.length) {
            return { clicked: false, reason: 'filter_tab_not_found' };
        }
        tabs[0].el.click();
        return { clicked: true, method: 'click_filter_tab', text: tabs[0].text };
        """
    ) or {"clicked": False, "reason": "click_filter_tab_js_failed"}


def _click_blank_to_dismiss_popup(page: DpPage, popup_rect: dict[str, Any] | None = None) -> dict[str, Any]:
    """点击「营销活动报名」右侧空白处，关闭设置营销电话提示浮层。"""
    actions: list[dict[str, Any]] = []

    header_blank = _find_marketing_header_blank_point(page)
    actions.append({"probe": header_blank})
    if header_blank.get("found"):
        primary = _playwright_mouse_click(page, float(header_blank["x"]), float(header_blank["y"]))
        actions.append({**primary, "target": header_blank.get("method", "header_blank")})
        if primary.get("clicked"):
            time.sleep(0.45)
            for offset_name, dx, dy in (
                ("header_blank_offset_left", -28, 0),
                ("header_blank_offset_down", 0, 18),
                ("header_blank_offset_right", 24, 0),
            ):
                offset_click = _playwright_mouse_click(
                    page,
                    float(header_blank["x"]) + dx,
                    float(header_blank["y"]) + dy,
                )
                actions.append({**offset_click, "target": offset_name})
                if offset_click.get("clicked"):
                    time.sleep(0.25)

    escape_result = _press_escape(page)
    actions.append(escape_result)
    if escape_result.get("pressed"):
        time.sleep(0.35)

    for point in _collect_blank_click_points(popup_rect):
        click_result = _playwright_mouse_click(page, point["x"], point["y"])
        actions.append({**click_result, "target": point["name"]})
        if click_result.get("clicked"):
            time.sleep(0.35)

    tab_result = _click_filter_tab(page)
    actions.append(tab_result)

    clicked_actions = [item for item in actions if item.get("clicked") or item.get("pressed")]
    return {
        "clicked": bool(clicked_actions),
        "actions": actions,
    }


def _dismiss_marketing_phone_popup(page: DpPage, account_id: str = "", max_attempts: int = 4) -> dict[str, Any]:
    """若出现营销电话提示浮层，则点击空白处关闭。"""
    attempts: list[dict[str, Any]] = []
    for _ in range(max_attempts):
        state = _read_marketing_phone_popup(page)
        if not state.get("visible"):
            return {
                "dismissed": True,
                "already_closed": not attempts,
                "attempts": attempts,
            }

        click_result = _click_blank_to_dismiss_popup(page, state.get("rect") or {})
        attempts.append({"before": state, "click": click_result})
        time.sleep(0.9)

        after = _read_marketing_phone_popup(page)
        if not after.get("visible"):
            if account_id:
                print(f"[{account_id}] 已关闭营销联系电话提示浮层", flush=True)
            return {
                "dismissed": True,
                "attempts": attempts,
                "after": after,
            }

    final = _read_marketing_phone_popup(page)
    return {
        "dismissed": not final.get("visible"),
        "attempts": attempts,
        "after": final,
    }


def _ensure_session(
    page: DpPage,
    account: AccountConfig | None,
    account_id: str,
) -> dict[str, Any]:
    """检测到登录页时复用 sync_login 自动登录。"""
    try:
        result = ensure_session_sync(page, account)
        result = dict(result)
    except Exception as exc:
        result = {
            "logged_in": False,
            "relogin": True,
            "reason": _safe_exc(exc),
            "url": str(page.url or ""),
        }
    if result.get("relogin"):
        status = "成功" if result.get("logged_in") else "失败"
        print(f"[{account_id}] 中途重新登录{status}: {result}", flush=True)
    return result


def _require_logged_in(
    page: DpPage,
    account: AccountConfig | None,
    account_id: str,
) -> dict[str, Any] | None:
    """未登录则尝试重新登录；仍失败则返回错误 dict。"""
    session = _ensure_session(page, account, account_id)
    if session.get("logged_in"):
        return None
    return {
        "status": "failed",
        "step": "session_expired",
        "error": "会话已跳转登录页，重新登录失败" if account else "会话已跳转登录页",
        "session": session,
        "current_url": page.url,
    }


def _is_marketing_activities_page(page: DpPage) -> bool:
    text = _body_text(page)
    if is_login_url(str(page.url or "")):
        return False
    markers = ("营销活动", "活动大厅", "我能参加的活动", "全部活动", "报名记录")
    return any(item in text for item in markers)


def _open_marketing_activities_page(
    page: DpPage,
    account_id: str,
    account: AccountConfig | None = None,
) -> bool:
    """进入商家后台「店铺营销 → 营销活动」页面。"""
    _ensure_session(page, account, account_id)

    for url in MARKETING_ACTIVITIES_URLS:
        try:
            page.get(url)
            time.sleep(3)
            if is_login_url(str(page.url or "")):
                relogin = _ensure_session(page, account, account_id)
                if not relogin.get("logged_in"):
                    return False
                page.get(url)
                time.sleep(3)
            _dismiss_message_popup(page)
            _dismiss_marketing_phone_popup(page, account_id)
            if _is_marketing_activities_page(page):
                print(f"[{account_id}] 已打开营销活动页: {page.url}", flush=True)
                return True
        except Exception as exc:
            print(f"[{account_id}] 打开营销活动页异常: {_safe_exc(exc)}", flush=True)

    print(f"[{account_id}] 直接打开营销活动失败，尝试从菜单点击", flush=True)
    try:
        page.get("https://mms.pinduoduo.com/home/")
        time.sleep(2)
        if is_login_url(str(page.url or "")):
            relogin = _ensure_session(page, account, account_id)
            if not relogin.get("logged_in"):
                return False
        _dismiss_message_popup(page)
        if _click_text(page, "营销活动", timeout=6):
            time.sleep(3)
            _dismiss_message_popup(page)
            _dismiss_marketing_phone_popup(page, account_id)
            return _is_marketing_activities_page(page)
    except Exception as exc:
        print(f"[{account_id}] 菜单进入营销活动失败: {_safe_exc(exc)}", flush=True)
    return False


def _is_activity_search_placeholder(placeholder: str) -> bool:
    ph = (placeholder or "").strip()
    if not ph:
        return False
    if "活动名称或ID" in ph or "ID搜索" in ph:
        return True
    return "活动名称" in ph and "ID" in ph


def _activity_search_input_locator(page: DpPage):
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return None
    for selector in ACTIVITY_SEARCH_INPUT_SELECTORS:
        loc = raw_page.locator(selector).first
        try:
            if not loc.count() or not loc.is_visible():
                continue
            placeholder = str(loc.get_attribute("placeholder") or "")
            if _is_activity_search_placeholder(placeholder):
                return loc
        except Exception:
            continue
    return None


def _read_activity_search_input_value(page: DpPage) -> str:
    loc = _activity_search_input_locator(page)
    if loc is not None:
        try:
            return str(loc.input_value(timeout=2_000) or "").strip()
        except Exception:
            pass
    state = _find_activity_search_input(page)
    return str(state.get("value") or "").strip()


def _find_activity_search_input(page: DpPage) -> dict[str, Any]:
    return page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 40 && r.height > 10
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }

        const inputs = Array.from(document.querySelectorAll('input'))
            .filter(isVisible)
            .map((el) => ({
                el,
                placeholder: (el.getAttribute('placeholder') || '').trim(),
                type: (el.getAttribute('type') || '').toLowerCase(),
                rect: el.getBoundingClientRect(),
            }))
            .filter((item) => {
                const ph = item.placeholder;
                if (ph.includes('活动名称或ID') || ph.includes('ID搜索')) return true;
                return ph.includes('活动名称') && ph.includes('ID');
            });

        if (!inputs.length) {
            return { found: false, reason: 'search_input_not_found' };
        }

        inputs.sort((a, b) => a.rect.top - b.rect.top);
        const target = inputs[0].el;
        target.scrollIntoView({ block: 'center', inline: 'nearest' });
        target.focus();
        return {
            found: true,
            placeholder: inputs[0].placeholder,
            value: target.value || '',
        };
        """
    ) or {"found": False, "reason": "search_input_js_failed"}


def _fill_activity_search_input(page: DpPage, activity_id: str) -> dict[str, Any]:
    safe_id = str(activity_id or "").strip()
    if not safe_id:
        return {"filled": False, "reason": "empty_activity_id"}

    loc = _activity_search_input_locator(page)
    if loc is not None:
        try:
            loc.scroll_into_view_if_needed(timeout=3_000)
            loc.click(timeout=3_000)
            loc.fill("", timeout=3_000)
            loc.fill(safe_id, timeout=5_000)
            time.sleep(0.3)
            actual = str(loc.input_value(timeout=2_000) or "").strip()
            if actual == safe_id:
                return {
                    "filled": True,
                    "value": actual,
                    "method": "playwright_fill",
                    "visible": True,
                }
        except Exception as exc:
            playwright_error = _safe_exc(exc)
        else:
            playwright_error = ""
    else:
        playwright_error = "search_input_locator_not_found"

    js_result = page.run_js(
        f"""
        function isVisible(el) {{
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 40 && r.height > 10
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }}

        function setInputValue(input, value) {{
            input.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
            if (setter) {{
                setter.call(input, '');
            }} else {{
                input.value = '';
            }}
            input.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'deleteContentBackward', data: null }}));
            if (setter) {{
                setter.call(input, value);
            }} else {{
                input.value = value;
            }}
            input.dispatchEvent(new InputEvent('input', {{ bubbles: true, inputType: 'insertText', data: value }}));
            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
            input.blur();
        }}

        const activityId = {safe_id!r};
        const inputs = Array.from(document.querySelectorAll(
            'input[data-testid="beast-core-input-nativeInput"], input'
        ))
            .filter(isVisible)
            .filter((el) => {{
                const ph = (el.getAttribute('placeholder') || '').trim();
                if (ph.includes('活动名称或ID') || ph.includes('ID搜索')) return true;
                return ph.includes('活动名称') && ph.includes('ID');
            }});

        if (!inputs.length) {{
            return {{ filled: false, reason: 'search_input_not_found' }};
        }}

        const input = inputs[0];
        input.scrollIntoView({{ block: 'center', inline: 'nearest' }});
        setInputValue(input, activityId);
        return {{
            filled: true,
            value: input.value || '',
            placeholder: input.getAttribute('placeholder') || '',
            method: 'react_input_setter',
        }};
        """
    ) or {"filled": False, "reason": "fill_search_input_js_failed"}

    actual = _read_activity_search_input_value(page)
    if js_result.get("filled") and actual == safe_id:
        js_result["value"] = actual
        js_result["visible"] = True
        return js_result

    return {
        "filled": False,
        "reason": "search_input_value_not_visible",
        "expected": safe_id,
        "actual": actual,
        "playwright_error": playwright_error,
        "js_result": js_result,
    }


def _click_activity_search_button(page: DpPage) -> dict[str, Any]:
    loc = _activity_search_input_locator(page)
    raw_page = getattr(page, "_page", None)
    if loc is not None and raw_page is not None:
        click_attempts = (
            (
                "playwright_query_button_near_input",
                loc.locator(
                    'xpath=ancestor::div[contains(@class,"IPT_inputBlockCell")][1]'
                    '/following-sibling::button[contains(@data-testid,"beast-core-button")]'
                ),
            ),
            (
                "playwright_query_button_input_row",
                loc.locator(
                    'xpath=ancestor::div[contains(@class,"IPT_inputBlockCell")][1]'
                    '/parent::*//button[@data-testid="beast-core-button" and contains(normalize-space(.), "查询")]'
                ),
            ),
            (
                "playwright_query_button_role",
                loc.locator(
                    'xpath=ancestor::div[contains(@class,"IPT_inputBlockCell")][1]/..'
                ).get_by_role("button", name="查询"),
            ),
        )
        for method, query_btn in click_attempts:
            try:
                if query_btn.count():
                    query_btn.first.click(timeout=3_000)
                    return {"clicked": True, "text": "查询", "method": method}
            except Exception:
                continue
        try:
            raw_page.locator('button[data-testid="beast-core-button"]:has-text("查询")').first.click(
                timeout=3_000
            )
            return {"clicked": True, "text": "查询", "method": "playwright_query_button_global"}
        except Exception:
            pass

    return page.run_js(
        """
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 && r.height > 16
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }

        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }

        const searchInputs = Array.from(document.querySelectorAll(
            'input[data-testid="beast-core-input-nativeInput"], input'
        ))
            .filter(isVisible)
            .filter((el) => {
                const ph = (el.getAttribute('placeholder') || '').trim();
                if (ph.includes('活动名称或ID') || ph.includes('ID搜索')) return true;
                return ph.includes('活动名称') && ph.includes('ID');
            });

        const inputRect = searchInputs.length ? searchInputs[0].getBoundingClientRect() : null;
        const buttons = Array.from(document.querySelectorAll('button, span, div, a'))
            .filter(isVisible)
            .map((el) => ({
                el,
                text: norm(el.innerText || el.textContent || ''),
                rect: el.getBoundingClientRect(),
            }))
            .filter((item) => item.text === '查询' || item.text === '搜索');

        if (!buttons.length) {
            return { clicked: false, reason: 'search_button_not_found' };
        }

        let target = buttons[0];
        if (inputRect) {
            const nearby = buttons
                .filter((item) => Math.abs(item.rect.top - inputRect.top) < 80)
                .sort((a, b) => a.rect.left - b.rect.left);
            if (nearby.length) {
                target = nearby[nearby.length - 1];
            }
        }

        target.el.scrollIntoView({ block: 'center', inline: 'nearest' });
        target.el.click();
        return { clicked: true, text: target.text };
        """
    ) or {"clicked": False, "reason": "click_search_button_js_failed"}


def _read_activity_search_results(page: DpPage, activity_id: str) -> dict[str, Any]:
    safe_id = str(activity_id or "").strip()
    return page.run_js(
        f"""
        function isVisible(el) {{
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 40 && r.height > 20
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }}

        const activityId = {safe_id!r};
        const cards = Array.from(document.querySelectorAll('div,section,article,li'))
            .filter(isVisible)
            .map((el) => {{
                const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                return {{ el, text }};
            }})
            .filter((item) => item.text.includes(activityId))
            .filter((item) => item.text.includes('ID') || item.text.includes('去报名') || item.text.includes('报名'));

        if (!cards.length) {{
            return {{
                matched: false,
                activity_id: activityId,
                card_count: 0,
                titles: [],
            }};
        }}

        cards.sort((a, b) => a.text.length - b.text.length);
        const best = cards[0];
        const title = best.text.split('ID')[0].trim().slice(0, 120);
        return {{
            matched: true,
            activity_id: activityId,
            card_count: cards.length,
            title,
            sample_text: best.text.slice(0, 240),
        }};
        """
    ) or {
        "matched": False,
        "activity_id": safe_id,
        "card_count": 0,
        "titles": [],
        "reason": "read_results_js_failed",
    }


def _wait_activity_search_results(page: DpPage, activity_id: str, timeout: int = 12) -> dict[str, Any]:
    last: dict[str, Any] = {"matched": False, "activity_id": activity_id}
    for _ in range(timeout):
        last = _read_activity_search_results(page, activity_id)
        if last.get("matched"):
            return last
        time.sleep(1)
    return last


def search_marketing_activity(
    page: DpPage,
    account_id: str,
    activity_id: str,
    account: AccountConfig | None = None,
) -> dict[str, Any]:
    """打开营销活动页，搜索指定活动 ID 并点击查询。"""
    activity_id = str(activity_id or "").strip()
    if not activity_id:
        return {
            "status": "failed",
            "step": "validate_activity_id",
            "error": "activity_id 不能为空",
            "activity_id": activity_id,
        }

    try:
        if session_err := _require_logged_in(page, account, account_id):
            return {**session_err, "activity_id": activity_id}

        _install_multi_quick_tab_blocker(page, account_id)
        if not _open_marketing_activities_page(page, account_id, account=account):
            return {
                "status": "failed",
                "step": "open_marketing_activities",
                "error": "未能打开营销活动页或会话已跳转登录",
                "activity_id": activity_id,
                "current_url": page.url,
            }

        phone_popup = _dismiss_marketing_phone_popup(page, account_id)

        search_input = _find_activity_search_input(page)
        if not search_input.get("found"):
            return {
                "status": "failed",
                "step": "find_search_input",
                "error": "未找到活动名称/ID 搜索框",
                "activity_id": activity_id,
                "current_url": page.url,
                "search_input": search_input,
            }

        fill_result = _fill_activity_search_input(page, activity_id)
        if not fill_result.get("filled"):
            return {
                "status": "failed",
                "step": "fill_search_input",
                "error": "未能填入活动 ID",
                "activity_id": activity_id,
                "current_url": page.url,
                "fill_result": fill_result,
            }

        phone_popup_after_fill = _dismiss_marketing_phone_popup(page, account_id)

        click_result = _click_activity_search_button(page)
        if not click_result.get("clicked"):
            if not _click_text(page, "查询", timeout=3):
                return {
                    "status": "failed",
                    "step": "click_search_button",
                    "error": "未找到或无法点击查询按钮",
                    "activity_id": activity_id,
                    "current_url": page.url,
                    "click_result": click_result,
                }
            click_result = {"clicked": True, "text": "查询", "fallback": "text_click"}

        time.sleep(2)
        _dismiss_message_popup(page)
        phone_popup_after_search = _dismiss_marketing_phone_popup(page, account_id, max_attempts=6)
        results = _wait_activity_search_results(page, activity_id, timeout=12)

        if not results.get("matched"):
            return {
                "status": "failed",
                "step": "verify_search_results",
                "error": f"查询后未找到活动 ID {activity_id}",
                "activity_id": activity_id,
                "current_url": page.url,
                "search_input": search_input,
                "fill_result": fill_result,
                "click_result": click_result,
                "results": results,
            }

        _close_multi_quick_channel_tabs(page, account_id)

        print(
            f"[{account_id}] 营销活动搜索成功: id={activity_id} title={results.get('title', '')}",
            flush=True,
        )
        return {
            "status": "success",
            "step": "search_completed",
            "activity_id": activity_id,
            "current_url": page.url,
            "search_input": search_input,
            "fill_result": fill_result,
            "click_result": click_result,
            "phone_popup": phone_popup,
            "phone_popup_after_fill": phone_popup_after_fill,
            "phone_popup_after_search": phone_popup_after_search,
            "results": results,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "step": "search_marketing_activity",
            "error": _safe_exc(exc),
            "activity_id": activity_id,
            "current_url": getattr(page, "url", ""),
        }


WRONG_REGISTRATION_URL_PARTS = ("multi-quick-channel", "MMSMultiQuickCard")
WRONG_REGISTRATION_TEXT_MARKERS = ("潜力商品报名",)
EXPECTED_PRODUCT_PICK_MARKERS = ("选择活动商品", "确认选择")
REGISTRATION_TAB_URL_PARTS = ("act/detail", "act/signup")
STALE_REGISTRATION_TAB_URL_PARTS = (
    "/act/index",
    "actHomeActivityType",
    "/act/home",
)
MULTI_QUICK_CHANNEL_URL = (
    "https://mms.pinduoduo.com/act/multi-quick-channel"
    "?SourceType=PROMO-MMSMultiQuickCard&SceneType=ActivityCard"
)
MULTI_QUICK_SEARCH_INPUT_SELECTORS = (
    'input[data-testid="beast-core-input-nativeInput"][placeholder*="商品ID"]',
    'input[data-testid="beast-core-input-htmlInput"][placeholder*="商品ID"]',
    'input[placeholder*="输入商品ID搜索商品"]',
    'input[placeholder*="多个ID以逗号隔开"]',
)
ACTIVITY_CARD_TITLE_SELECTORS = (
    '[class*="activity-item_title"]',
    '[class*="activity-item_name"]',
    '[class*="activity-item_header"] a',
    'a[class*="activity"]',
)


def _activity_detail_url(activity_id: str) -> str:
    return f"https://mms.pinduoduo.com/act/detail?id={activity_id}"


def _page_url_is_multi_quick(url: str) -> bool:
    return any(part in str(url or "") for part in WRONG_REGISTRATION_URL_PARTS)


def _page_url_is_activity_detail(url: str, activity_id: str) -> bool:
    safe_url = str(url or "")
    return "act/detail" in safe_url and str(activity_id) in safe_url


def _is_multi_quick_channel_page(page: DpPage) -> bool:
    """仅按 URL 判断，避免活动大厅列表里出现「潜力商品报名」文案导致误判。"""
    return _page_url_is_multi_quick(str(page.url or ""))


def _is_activity_detail_ready(
    page: DpPage,
    activity_id: str,
    *,
    require_activity_id: bool = True,
) -> bool:
    """判断活动详情是否就绪：详情页或列表页上的「活动详情」弹窗。"""
    url = str(page.url or "")
    if _page_url_is_multi_quick(url):
        return False
    text = _body_text(page)
    has_detail_modal = "活动详情" in text and "立即报名" in text
    if "act/index" in url or "actHomeActivityType" in url:
        if not has_detail_modal:
            return False
        if not require_activity_id:
            return True
        return activity_id in text
    if _page_url_is_activity_detail(url, activity_id):
        if not require_activity_id:
            return has_detail_modal or activity_id in text
        return ("活动详情" in text or "立即报名" in text) and activity_id in text
    if not has_detail_modal:
        return False
    if not require_activity_id:
        return True
    return activity_id in text


def _wait_activity_detail_ready(
    page: DpPage,
    activity_id: str,
    account_id: str,
    timeout: int = 12,
    *,
    require_activity_id: bool = True,
    poll_interval: float = 0.25,
) -> bool:
    deadline = time.monotonic() + max(timeout, 1)
    while time.monotonic() < deadline:
        _close_multi_quick_channel_tabs(page, account_id)
        if _is_activity_detail_ready(page, activity_id, require_activity_id=require_activity_id):
            return True
        time.sleep(poll_interval)
    return False


def _install_multi_quick_tab_blocker(page: DpPage, account_id: str) -> None:
    """新开标签若是潜力商品快捷通道或无关活动列表页，立即关闭。"""
    if getattr(page, "_multi_quick_blocker_installed", False):
        return
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return
    context = getattr(raw_page, "context", None)
    if context is None or not callable(getattr(context, "on", None)):
        return

    def _should_block_new_tab(url: str) -> bool:
        if _page_url_is_multi_quick(url):
            return True
        if not getattr(page, "_campaign_close_stale_tabs", False):
            return False
        return _page_url_is_stale_registration_tab(url, "")

    def _on_new_page(new_page: Any) -> None:
        for _ in range(8):
            try:
                if new_page.is_closed():
                    return
                url = str(new_page.url or "")
                if url and url not in ("about:blank", "chrome://newtab/"):
                    if _should_block_new_tab(url):
                        label = "潜力商品" if _page_url_is_multi_quick(url) else "无关活动页"
                        print(f"[{account_id}] 拦截新开{label}标签: {url}", flush=True)
                        new_page.close()
                    return
            except Exception:
                pass
            time.sleep(0.5)
        try:
            url = str(new_page.url or "")
            if _should_block_new_tab(url):
                label = "潜力商品" if _page_url_is_multi_quick(url) else "无关活动页"
                print(f"[{account_id}] 拦截新开{label}标签: {url}", flush=True)
                new_page.close()
        except Exception:
            pass

    context.on("page", _on_new_page)
    setattr(page, "_multi_quick_blocker_installed", True)


def _open_activity_detail_via_card_link(page: DpPage, activity_id: str, account_id: str) -> dict[str, Any]:
    """在当前页强制同标签打开详情链接，避免 target=_blank 新开潜力商品页。"""
    return page.run_js(
        f"""
        function isVisible(el) {{
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 8 && r.height > 8
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }}
        const activityId = {activity_id!r};
        const links = Array.from(document.querySelectorAll('a[href]'))
            .filter(isVisible)
            .map((el) => ({{
                el,
                href: el.href || '',
                text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(),
            }}))
            .filter((item) => item.href.includes('act/detail') && item.href.includes(activityId))
            .filter((item) => !item.text.includes('潜力商品报名'));
        if (!links.length) {{
            return {{ clicked: false, reason: 'detail_link_not_found' }};
        }}
        const target = links[0].el;
        target.target = '_self';
        target.removeAttribute('target');
        target.rel = '';
        target.click();
        return {{ clicked: true, method: 'card_detail_link', href: links[0].href }};
        """
    ) or {"clicked": False, "reason": "card_detail_link_js_failed"}


def _dismiss_wrong_tabs_and_focus_product_pick(
    page: DpPage, activity_id: str, account_id: str
) -> dict[str, Any]:
    """关闭误开的潜力商品标签，并切回「选择活动商品」页。"""
    close_result = _close_multi_quick_channel_tabs(page, account_id)
    switch_result = _switch_to_product_pick_tab(page, activity_id, account_id)
    return {"close_result": close_result, "switch_result": switch_result}


def _switch_to_product_pick_tab(page: DpPage, activity_id: str, account_id: str) -> dict[str, Any]:
    """切到「选择活动商品」页，跳过潜力商品快捷通道。"""
    close_result = _close_multi_quick_channel_tabs(page, account_id)
    for item in reversed(_live_context_pages(page)):
        url = str(item.url or "")
        if _page_url_is_multi_quick(url):
            continue
        _bind_page(page, item)
        try:
            item.bring_to_front()
        except Exception:
            pass
        text = _body_text(page)
        if any(marker in text for marker in EXPECTED_PRODUCT_PICK_MARKERS):
            return {"switched": True, "method": "product_pick_text", "url": url, "close_result": close_result}
        if "搜索商品" in text and (not activity_id or activity_id in text):
            return {"switched": True, "method": "product_pick_modal_page", "url": url, "close_result": close_result}
        if _is_price_confirm_url(url):
            continue
        if any(part in url for part in ("signup", "enroll", "choose", "goods", "product")):
            return {"switched": True, "method": "product_pick_url", "url": url, "close_result": close_result}
    return {"switched": False, "method": "not_found", "url": page.url, "close_result": close_result}


def _close_multi_quick_channel_tabs(page: DpPage, account_id: str) -> dict[str, Any]:
    """关闭误开的「潜力商品报名」标签页，避免脚本切过去操作。"""
    closed_urls: list[str] = []
    raw_page = getattr(page, "_page", None)
    pages = _live_context_pages(page)
    if not pages:
        return {"closed": closed_urls, "reason": "no_pages"}

    for item in list(pages):
        if item is raw_page:
            continue
        try:
            url = str(item.url or "")
            if not _page_url_is_multi_quick(url):
                continue
            item.close()
            closed_urls.append(url)
            print(f"[{account_id}] 已关闭潜力商品快捷通道标签页: {url}", flush=True)
        except Exception:
            continue

    pages = _live_context_pages(page)
    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        try:
            if not raw_page.is_closed() and _page_url_is_multi_quick(str(raw_page.url or "")):
                good_pages = [
                    item
                    for item in pages
                    if item is not raw_page and not _page_url_is_multi_quick(str(item.url or ""))
                ]
                if good_pages:
                    closed_urls.append(str(raw_page.url or ""))
                    raw_page.close()
                    target = good_pages[-1]
                    _bind_page(page, target)
                    target.bring_to_front()
                    print(f"[{account_id}] 当前标签为潜力商品页，已切回: {target.url}", flush=True)
        except Exception:
            pass

    return {"closed": closed_urls}


def _page_url_is_stale_registration_tab(url: str, body_text: str = "") -> bool:
    """活动报名流程中应关闭的无关标签（活动大厅/详情，非选品/价格确认）。"""
    safe_url = str(url or "")
    text = str(body_text or "")
    if _page_url_is_multi_quick(safe_url):
        return True
    if _is_price_confirm_url(safe_url):
        return False
    if any(marker in text for marker in ("确认商品价格信息", "填写报名信息")):
        return False
    if any(marker in text for marker in EXPECTED_PRODUCT_PICK_MARKERS):
        return False
    if any(part in safe_url for part in STALE_REGISTRATION_TAB_URL_PARTS):
        return True
    if "act/detail" in safe_url and "goods_price" not in safe_url:
        return True
    if "立即报名" in text and "活动详情" in text and "确认选择" not in text:
        return True
    return False


def _close_irrelevant_registration_tabs(
    page: DpPage,
    account_id: str,
    *,
    keep_product_pick: bool = False,
) -> dict[str, Any]:
    """关闭误开的活动大厅/详情/潜力商品标签，保留价格确认与（可选）选品页。"""
    multi_quick_result = _close_multi_quick_channel_tabs(page, account_id)
    closed_urls: list[str] = []
    raw_page = getattr(page, "_page", None)
    pages = _live_context_pages(page)
    if not pages:
        return {"closed": closed_urls, "multi_quick": multi_quick_result}

    keep_pages: list[Any] = []
    stale_pages: list[Any] = []
    for item in pages:
        try:
            url = str(item.url or "")
        except Exception:
            continue
        try:
            _bind_page(page, item)
            text = _body_text(page)
        except Exception:
            text = ""
        if _is_price_confirm_page(page) or _is_price_confirm_url(url):
            keep_pages.append(item)
            continue
        if keep_product_pick and any(marker in text for marker in EXPECTED_PRODUCT_PICK_MARKERS):
            keep_pages.append(item)
            continue
        if _page_url_is_stale_registration_tab(url, text):
            stale_pages.append(item)

    if not stale_pages:
        return {"closed": closed_urls, "multi_quick": multi_quick_result, "kept": len(keep_pages)}

    for item in stale_pages:
        pages_now = _live_context_pages(page)
        if len(pages_now) <= 1:
            break
        try:
            url = str(item.url or "")
        except Exception:
            url = ""
        try:
            if item is raw_page:
                fallback = next((p for p in keep_pages if p is not item), None)
                if fallback is None:
                    fallback = next((p for p in pages_now if p is not item), None)
                if fallback is None:
                    break
                _bind_page(page, fallback)
                fallback.bring_to_front()
            if not item.is_closed():
                item.close()
            closed_urls.append(url)
            print(f"[{account_id}] 已关闭无关活动标签页: {url}", flush=True)
        except Exception:
            continue

    return {"closed": closed_urls, "multi_quick": multi_quick_result, "kept": len(keep_pages)}


def _switch_to_registration_tab(page: DpPage, activity_id: str, account_id: str) -> dict[str, Any]:
    """切到活动详情/报名页，明确跳过潜力商品快捷通道标签。"""
    close_result = _close_multi_quick_channel_tabs(page, account_id)
    pages = _live_context_pages(page)

    for item in reversed(pages):
        url = str(item.url or "")
        if _page_url_is_multi_quick(url):
            continue
        if _page_url_is_activity_detail(url, activity_id):
            _bind_page(page, item)
            item.bring_to_front()
            time.sleep(1)
            return {"switched": True, "method": "detail_tab", "url": url, "close_result": close_result}

    for item in reversed(pages):
        url = str(item.url or "")
        if _page_url_is_multi_quick(url):
            continue
        if any(part in url for part in REGISTRATION_TAB_URL_PARTS):
            _bind_page(page, item)
            item.bring_to_front()
            time.sleep(1)
            return {"switched": True, "method": "registration_tab", "url": url, "close_result": close_result}

    raw_page = getattr(page, "_page", None)
    current_url = str(getattr(page, "url", "") or "")
    if not _page_url_is_multi_quick(current_url):
        return {"switched": False, "method": "stay_current", "url": current_url, "close_result": close_result}

    if raw_page is not None:
        try:
            raw_page.go_back(wait_until="domcontentloaded")
            time.sleep(1.5)
        except Exception:
            pass
    current_url = str(getattr(page, "url", "") or "")
    return {"switched": False, "method": "go_back", "url": current_url, "close_result": close_result}


def _try_leave_multi_quick_channel(page: DpPage, account_id: str, activity_id: str = "") -> dict[str, Any]:
    if not _is_multi_quick_channel_page(page):
        return {"left": False, "reason": "not_multi_quick_channel"}

    before_url = page.url
    close_result = _close_multi_quick_channel_tabs(page, account_id)
    if not _is_multi_quick_channel_page(page):
        return {
            "left": True,
            "method": "close_tab",
            "before_url": before_url,
            "after_url": page.url,
            "close_result": close_result,
            "still_wrong_page": False,
        }

    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        try:
            raw_page.go_back(wait_until="domcontentloaded")
            time.sleep(1.5)
            if not _is_multi_quick_channel_page(page):
                return {
                    "left": True,
                    "method": "go_back",
                    "before_url": before_url,
                    "after_url": page.url,
                    "still_wrong_page": False,
                }
        except Exception as exc:
            go_back_error = _safe_exc(exc)
        else:
            go_back_error = ""
    else:
        go_back_error = "page_unavailable"

    safe_id = str(activity_id or "").strip()
    if safe_id:
        try:
            page.get(_activity_detail_url(safe_id))
            time.sleep(2)
            if not _is_multi_quick_channel_page(page):
                return {
                    "left": True,
                    "method": "direct_detail_url",
                    "before_url": before_url,
                    "after_url": page.url,
                    "still_wrong_page": False,
                    "go_back_error": go_back_error,
                }
        except Exception as exc:
            return {
                "left": False,
                "reason": _safe_exc(exc),
                "before_url": before_url,
                "after_url": page.url,
                "go_back_error": go_back_error,
            }

    return {
        "left": False,
        "reason": go_back_error or "still_on_multi_quick_channel",
        "before_url": before_url,
        "after_url": page.url,
        "still_wrong_page": _is_multi_quick_channel_page(page),
        "close_result": close_result,
    }


def _reject_multi_quick_channel(
    page: DpPage,
    account_id: str,
    step: str,
    activity_id: str = "",
    **extra: Any,
) -> dict[str, Any] | None:
    if not _is_multi_quick_channel_page(page):
        return None
    leave_result = _try_leave_multi_quick_channel(page, account_id, activity_id=activity_id)
    return _fail(
        step,
        "拼多多打开了「潜力商品报名」快捷通道，不是 20981 活动的标准报名页（选择活动商品 + 搜索弹窗）；已停止后续操作",
        current_url=page.url,
        page_kind="multi_quick_channel",
        leave_result=leave_result,
        **extra,
    )


def _fail(step: str, error: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "failed", "step": step, "error": error}
    payload.update(extra)
    return payload


ACTIVITY_CARD_SELECTORS = (
    '[class*="activity-list_gridItem"]',
    '[class*="gridItem"]',
    'div[class*="activity-item"]',
)


def _click_activity_card_title(page: DpPage, activity_id: str, account_id: str) -> dict[str, Any]:
    """点击活动卡片标题进入详情，避免点「去报名」打开潜力商品快捷通道。"""
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return {"clicked": False, "reason": "page_unavailable"}

    for card_selector in ACTIVITY_CARD_SELECTORS:
        try:
            cards = raw_page.locator(card_selector).filter(has_text=activity_id)
            count = cards.count()
            if not count:
                continue
            for index in range(count):
                card = cards.nth(index)
                if not card.is_visible():
                    continue
                card_text = card.inner_text(timeout=2_000)
                if "潜力商品报名" in card_text:
                    continue
                for title_selector in ACTIVITY_CARD_TITLE_SELECTORS:
                    title = card.locator(title_selector).first
                    if title.count() and title.is_visible():
                        title.scroll_into_view_if_needed(timeout=3_000)
                        time.sleep(0.3)
                        title.click(timeout=8_000)
                        print(f"[{account_id}] 已点击活动 {activity_id} 卡片标题", flush=True)
                        return {
                            "clicked": True,
                            "method": f"card_title_{title_selector}",
                            "card_index": index,
                        }
                try:
                    card.scroll_into_view_if_needed(timeout=3_000)
                    box = card.bounding_box()
                    if box:
                        raw_page.mouse.click(box["x"] + min(80, box["width"] * 0.25), box["y"] + 24)
                        print(f"[{account_id}] 已点击活动 {activity_id} 卡片左侧区域", flush=True)
                        return {
                            "clicked": True,
                            "method": "card_left_click",
                            "card_index": index,
                        }
                except Exception:
                    continue
        except Exception:
            continue

    js_result = page.run_js(
        f"""
        function isVisible(el) {{
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 && r.height > 16
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }}
        const activityId = {activity_id!r};
        const cardSelectors = [
            '[class*="activity-list_gridItem"]',
            '[class*="gridItem"]',
            'div[class*="activity-item"]',
        ];
        let cards = [];
        for (const selector of cardSelectors) {{
            const found = Array.from(document.querySelectorAll(selector))
                .filter(isVisible)
                .map((el) => ({{
                    el,
                    text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(),
                    area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
                }}))
                .filter((item) => item.text.includes(activityId))
                .filter((item) => !item.text.includes('潜力商品报名'));
            if (found.length) {{
                cards = found;
                break;
            }}
        }}
        if (!cards.length) {{
            return {{ clicked: false, reason: 'activity_card_not_found' }};
        }}
        cards.sort((a, b) => a.area - b.area || a.text.length - b.text.length);
        const card = cards[0].el;
        const titleSelectors = [
            '[class*="activity-item_title"]',
            '[class*="activity-item_name"]',
            '[class*="activity-item_header"] a',
            'a[class*="activity"]',
        ];
        for (const selector of titleSelectors) {{
            const target = card.querySelector(selector);
            if (target && isVisible(target)) {{
                target.scrollIntoView({{ block: 'center', inline: 'nearest' }});
                target.click();
                return {{ clicked: true, method: 'js_card_title', selector }};
            }}
        }}
        const rect = card.getBoundingClientRect();
        const x = rect.left + Math.min(80, rect.width * 0.25);
        const y = rect.top + 24;
        const target = document.elementFromPoint(x, y);
        if (target) {{
            target.click();
            return {{ clicked: true, method: 'js_card_left_click', x, y }};
        }}
        return {{ clicked: false, reason: 'card_title_not_found', sample_text: cards[0].text.slice(0, 240) }};
        """
    ) or {"clicked": False, "reason": "click_card_title_js_failed"}
    if js_result.get("clicked"):
        print(f"[{account_id}] 已点击活动 {activity_id} 卡片（JS）", flush=True)
    return js_result


def _open_activity_detail_page(page: DpPage, activity_id: str, account_id: str) -> dict[str, Any]:
    """进入活动详情页。20981 点「去报名/卡片」会新开潜力商品页，只用同标签导航。"""
    _install_multi_quick_tab_blocker(page, account_id)
    attempts: list[dict[str, Any]] = []
    detail_url = _activity_detail_url(activity_id)
    raw_page = getattr(page, "_page", None)

    if raw_page is not None:
        try:
            raw_page.goto(detail_url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(2)
            _dismiss_message_popup(page)
            _dismiss_marketing_phone_popup(page, account_id)
            _close_multi_quick_channel_tabs(page, account_id)
            if _page_url_is_multi_quick(page.url):
                attempts.append({"method": "goto_detail", "url": page.url, "wrong_page": True})
                try:
                    raw_page.go_back(wait_until="domcontentloaded")
                    time.sleep(1.5)
                except Exception:
                    pass
            elif _wait_activity_detail_ready(page, activity_id, account_id, timeout=12):
                print(f"[{account_id}] 已通过详情链接打开活动 {activity_id}", flush=True)
                return {"opened": True, "method": "goto_detail", "url": page.url, "attempts": attempts}
            else:
                attempts.append(
                    {
                        "method": "goto_detail",
                        "url": page.url,
                        "reason": "detail_markers_not_found",
                    }
                )
        except Exception as exc:
            attempts.append({"method": "goto_detail", "error": _safe_exc(exc)})
    else:
        try:
            page.get(detail_url)
            time.sleep(2)
            _dismiss_message_popup(page)
            _dismiss_marketing_phone_popup(page, account_id)
            _close_multi_quick_channel_tabs(page, account_id)
            if not _page_url_is_multi_quick(page.url) and _wait_activity_detail_ready(
                page, activity_id, account_id, timeout=12
            ):
                print(f"[{account_id}] 已通过详情链接打开活动 {activity_id}", flush=True)
                return {"opened": True, "method": "page_get_detail", "url": page.url, "attempts": attempts}
            attempts.append({"method": "page_get_detail", "url": page.url})
        except Exception as exc:
            attempts.append({"method": "page_get_detail", "error": _safe_exc(exc)})

    link_result = _open_activity_detail_via_card_link(page, activity_id, account_id)
    attempts.append(link_result)
    if link_result.get("clicked"):
        time.sleep(2)
        _close_multi_quick_channel_tabs(page, account_id)
        _dismiss_message_popup(page)
        _dismiss_marketing_phone_popup(page, account_id)
        if not _page_url_is_multi_quick(page.url) and _wait_activity_detail_ready(
            page, activity_id, account_id, timeout=12
        ):
            return {
                "opened": True,
                "method": link_result.get("method", "card_detail_link"),
                "url": page.url,
                "attempts": attempts,
            }
        attempts.append(
            {
                "method": "card_detail_link",
                "url": page.url,
                "wrong_page": _page_url_is_multi_quick(page.url),
            }
        )

    return {
        "opened": False,
        "reason": "activity_detail_not_opened",
        "url": page.url,
        "attempts": attempts,
    }


def _open_activity_for_registration(
    page: DpPage,
    activity_id: str,
    account_id: str,
    *,
    entry: str,
) -> dict[str, Any]:
    """按活动配置进入报名流程：goto_detail 或 go_register。"""
    if entry == "go_register":
        _install_multi_quick_tab_blocker(page, account_id)
        go_register = _click_activity_go_register(page, activity_id, account_id)
        if not go_register.get("clicked"):
            return {
                "opened": False,
                "reason": "go_register_not_clicked",
                "entry": entry,
                **go_register,
            }
        time.sleep(0.4)
        _close_multi_quick_channel_tabs(page, account_id)
        _dismiss_message_popup(page)
        _dismiss_marketing_phone_popup(page, account_id)
        if _wait_activity_detail_ready(
            page,
            activity_id,
            account_id,
            timeout=6,
            require_activity_id=False,
        ):
            print(f"[{account_id}] 已通过去报名打开活动 {activity_id} 详情", flush=True)
            return {
                "opened": True,
                "method": "go_register_modal",
                "url": page.url,
                "go_register": go_register,
            }
        return {
            "opened": False,
            "reason": "activity_detail_modal_not_ready",
            "entry": entry,
            "url": page.url,
            "go_register": go_register,
        }
    return _open_activity_detail_page(page, activity_id, account_id)


def _click_activity_go_register(page: DpPage, activity_id: str, account_id: str) -> dict[str, Any]:
    """在活动列表卡片上点击「去报名」——只点包含目标活动 ID 的最小卡片。"""
    raw_page = getattr(page, "_page", None)
    playwright_error = ""
    if raw_page is not None:
        for card_selector in ACTIVITY_CARD_SELECTORS:
            try:
                cards = (
                    raw_page.locator(card_selector)
                    .filter(has_text=activity_id)
                    .filter(has=raw_page.locator('button[data-testid="beast-core-button"]:has-text("去报名")'))
                )
                count = cards.count()
                if not count:
                    continue
                for index in range(count):
                    card = cards.nth(index)
                    if not card.is_visible():
                        continue
                    card_text = card.inner_text(timeout=2_000) if card.count() else ""
                    if "潜力商品报名" in card_text:
                        continue
                    btn = card.locator(
                        'div[class*="activity-item_action"] button[data-testid="beast-core-button"]:has-text("去报名")'
                    ).first
                    if not btn.count() or not btn.is_visible():
                        btn = card.locator(
                            'button[data-testid="beast-core-button"]:has-text("去报名")'
                        ).first
                    if not btn.count() or not btn.is_visible():
                        continue
                    btn.scroll_into_view_if_needed(timeout=3_000)
                    time.sleep(0.2)
                    btn.click(timeout=8_000)
                    time.sleep(0.5)
                    wrong_page = _reject_multi_quick_channel(
                        page,
                        account_id,
                        "click_go_register_wrong_page",
                        activity_id=activity_id,
                    )
                    if wrong_page:
                        wrong_page["clicked"] = False
                        wrong_page["method"] = f"playwright_{card_selector}"
                        return wrong_page
                    print(f"[{account_id}] 已点击活动 {activity_id} 的去报名", flush=True)
                    return {
                        "clicked": True,
                        "text": "去报名",
                        "method": f"playwright_{card_selector}",
                        "card_index": index,
                    }
            except Exception as exc:
                playwright_error = _safe_exc(exc)
        if not playwright_error:
            playwright_error = "activity_card_not_found"
    else:
        playwright_error = "page_unavailable"

    js_result = page.run_js(
        f"""
        function isVisible(el) {{
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 && r.height > 16
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }}
        function norm(text) {{
            return (text || '').replace(/\\s+/g, '').trim();
        }}
        function cardMatches(text) {{
            if (!text.includes(activityId)) return false;
            if (text.includes('潜力商品报名')) return false;
            return text.includes('去报名')
                || text.includes('长期报名')
                || text.includes('ID');
        }}
        const activityId = {activity_id!r};
        const cardSelectors = [
            '[class*="activity-list_gridItem"]',
            '[class*="gridItem"]',
            'div[class*="activity-item"]',
            'div',
            'section',
            'article',
            'li',
        ];
        let cards = [];
        for (const selector of cardSelectors) {{
            const found = Array.from(document.querySelectorAll(selector))
                .filter(isVisible)
                .map((el) => ({{
                    el,
                    text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(),
                    area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
                }}))
                .filter((item) => cardMatches(item.text));
            if (found.length) {{
                cards = found;
                break;
            }}
        }}
        if (!cards.length) {{
            return {{ clicked: false, reason: 'activity_card_not_found' }};
        }}
        cards.sort((a, b) => a.area - b.area || a.text.length - b.text.length);
        const card = cards[0].el;
        const buttons = Array.from(
            card.querySelectorAll('div[class*="activity-item_action"] button, button[data-testid="beast-core-button"], button,a,span,div')
        )
            .filter(isVisible)
            .filter((el) => norm(el.innerText || el.textContent || '') === '去报名');
        if (!buttons.length) {{
            return {{ clicked: false, reason: 'go_register_button_not_found', sample_text: cards[0].text.slice(0, 240) }};
        }}
        buttons[0].scrollIntoView({{ block: 'center', inline: 'nearest' }});
        buttons[0].click();
        return {{ clicked: true, text: '去报名', method: 'js_card_button', sample_text: cards[0].text.slice(0, 240) }};
        """
    ) or {"clicked": False, "reason": "click_go_register_js_failed"}
    if js_result.get("clicked"):
        time.sleep(1.5)
        wrong_page = _reject_multi_quick_channel(
            page,
            account_id,
            "click_go_register_wrong_page",
            activity_id=activity_id,
        )
        if wrong_page:
            wrong_page["clicked"] = False
            wrong_page.update(js_result)
            return wrong_page
    if not js_result.get("clicked"):
        js_result["playwright_error"] = playwright_error
    return js_result


def _wait_page_contains(
    page: DpPage,
    markers: tuple[str, ...],
    timeout: int = 15,
    *,
    poll_interval: float = 0.25,
) -> bool:
    deadline = time.monotonic() + max(timeout, 1)
    while time.monotonic() < deadline:
        text = _body_text(page)
        if any(marker in text for marker in markers):
            return True
        time.sleep(poll_interval)
    return False


def _click_register_now(page: DpPage, account_id: str, activity_id: str) -> dict[str, Any]:
    """在活动详情页点击「立即报名」——只在包含活动 ID 的详情区域内点击。"""
    _install_multi_quick_tab_blocker(page, account_id)

    js_result = page.run_js(
        f"""
        function norm(text) {{
            return (text || '').replace(/\\s+/g, '').trim();
        }}
        function isVisible(el) {{
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 && r.height > 16
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }}
        function findRegisterButton(requireActivityId) {{
            const activityId = {activity_id!r};
            const roots = Array.from(document.querySelectorAll(
                '[data-testid="beast-core-modal"], [class*="MDL_modal"], body'
            ))
                .filter(isVisible)
                .filter((el) => {{
                    const text = (el.innerText || el.textContent || '');
                    if (!text.includes('活动详情') || !text.includes('立即报名')) return false;
                    if (requireActivityId && !text.includes(activityId)) return false;
                    return true;
                }});
            const root = roots.length ? roots[roots.length - 1] : document.body;
            const buttons = Array.from(root.querySelectorAll('button[data-testid="beast-core-button"], button'))
                .filter(isVisible)
                .filter((el) => norm(el.innerText || el.textContent || '') === '立即报名');
            return buttons.length ? buttons[buttons.length - 1] : null;
        }}
        let target = findRegisterButton(true);
        let method = 'js_activity_detail_modal';
        if (!target) {{
            target = findRegisterButton(false);
            method = 'js_activity_detail_modal_no_id';
        }}
        if (!target) {{
            return {{ clicked: false, reason: 'register_now_button_not_found' }};
        }}
        target.scrollIntoView({{ block: 'center', inline: 'nearest' }});
        target.click();
        return {{ clicked: true, text: '立即报名', method }};
        """
    ) or {"clicked": False, "reason": "register_now_js_failed"}
    if js_result.get("clicked"):
        time.sleep(1)
        _close_multi_quick_channel_tabs(page, account_id)
        _switch_to_product_pick_tab(page, activity_id, account_id)
        wrong_page = _reject_multi_quick_channel(
            page,
            account_id,
            "click_register_now_wrong_page",
            activity_id=activity_id,
        )
        if wrong_page:
            wrong_page["clicked"] = False
            wrong_page.update(js_result)
            return wrong_page
        print(f"[{account_id}] 已点击立即报名（{js_result.get('method', 'js')}）", flush=True)
        return js_result

    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        scoped_selectors = (
            'div:has-text("活动详情"):has(button:has-text("立即报名"))',
            f'div:has-text("{activity_id}"):has(button:has-text("立即报名"))',
        )
        for scope_selector in scoped_selectors:
            try:
                scope = raw_page.locator(scope_selector)
                count = scope.count()
                for index in range(min(count, 5)):
                    block = scope.nth(index)
                    btn = block.locator('button[data-testid="beast-core-button"]:has-text("立即报名")').first
                    if btn.count() and btn.is_visible():
                        btn.scroll_into_view_if_needed(timeout=3_000)
                        btn.click(timeout=8_000)
                        time.sleep(1)
                        _close_multi_quick_channel_tabs(page, account_id)
                        _switch_to_product_pick_tab(page, activity_id, account_id)
                        wrong_page = _reject_multi_quick_channel(
                            page,
                            account_id,
                            "click_register_now_wrong_page",
                            activity_id=activity_id,
                        )
                        if wrong_page:
                            wrong_page["clicked"] = False
                            wrong_page["method"] = scope_selector
                            return wrong_page
                        print(f"[{account_id}] 已点击立即报名", flush=True)
                        return {"clicked": True, "text": "立即报名", "method": scope_selector}
            except Exception:
                continue

    return js_result


def _product_pick_page_search_locator(page: DpPage):
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return None
    selectors = (
        'input[data-testid="beast-core-input-htmlInput"][placeholder*="搜索商品"]',
        'input[data-testid="beast-core-input-nativeInput"][placeholder*="搜索商品"]',
        'input[placeholder*="输入商品名称或ID搜索商品"]',
    )
    for selector in selectors:
        loc = raw_page.locator(selector).first
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _product_search_modal_locator(page: DpPage):
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return None
    selectors = (
        '[data-testid="beast-core-modal"]:has-text("搜索商品")',
        '[class*="MDL_modal"]:has-text("搜索商品")',
    )
    for selector in selectors:
        loc = raw_page.locator(selector).last
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _open_product_search_modal(page: DpPage, account_id: str) -> dict[str, Any]:
    """在选择活动商品页点击搜索框，打开「搜索商品」弹窗。"""
    existing = _product_search_modal_locator(page)
    if existing is not None:
        return {"opened": True, "method": "search_modal_already_open"}

    loc = _product_pick_page_search_locator(page)
    if loc is None:
        return {"opened": False, "reason": "product_pick_search_input_not_found"}

    try:
        loc.scroll_into_view_if_needed(timeout=3_000)
        loc.click(timeout=5_000)
        time.sleep(1.2)
    except Exception as exc:
        return {"opened": False, "reason": "click_product_pick_search_failed", "error": _safe_exc(exc)}

    for _ in range(8):
        modal = _product_search_modal_locator(page)
        if modal is not None:
            print(f"[{account_id}] 已打开搜索商品弹窗", flush=True)
            return {"opened": True, "method": "click_product_pick_search_input"}
        time.sleep(0.8)
    return {"opened": False, "reason": "product_search_modal_not_opened"}


def _modal_contains_products(modal, product_ids: list[str]) -> bool:
    eligible = _modal_eligible_product_ids(modal, product_ids)
    return all(product_id in eligible for product_id in product_ids)


_TIME_REQUIREMENT_MARKERS: tuple[str, ...] = (
    "需等待1天",
    "等待1天",
    "1天后再试",
    "等待该时间",
    "近期有更新规格",
)


def _modal_eligible_product_ids(modal, product_ids: list[str]) -> list[str]:
    try:
        found = modal.evaluate(
            """
            (root, ids) => {
                const table = root.querySelector('table[data-testid="beast-core-table"]') || root.querySelector('table');
                if (!table) return [];
                const found = [];
                for (const row of table.querySelectorAll('tbody tr')) {
                    const text = (row.innerText || row.textContent || '').replace(/\\s+/g, ' ');
                    for (const id of ids) {
                        if (text.includes(id) && !found.includes(id)) found.push(id);
                    }
                }
                return found;
            }
            """,
            product_ids,
        )
    except Exception:
        return []
    if not isinstance(found, list):
        return []
    return [str(item).strip() for item in found if str(item).strip()]


def _analyze_modal_product_eligibility(modal, product_ids: list[str]) -> dict[str, Any]:
    """检查搜索弹窗内可报名/不可报名商品，识别「需等待1天」等时间限制。"""
    try:
        result = modal.evaluate(
            """
            (root, ids, timeMarkers) => {
                function norm(text) {
                    return (text || '').replace(/\\s+/g, ' ').trim();
                }
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function tableIds(table) {
                    const found = [];
                    if (!table) return found;
                    for (const row of table.querySelectorAll('tbody tr')) {
                        if (!isVisible(row)) continue;
                        const text = norm(row.innerText || row.textContent || '');
                        for (const id of ids) {
                            if (text.includes(id) && !found.includes(id)) found.push(id);
                        }
                    }
                    return found;
                }
                function clickTab(labelPart) {
                    const nodes = Array.from(root.querySelectorAll('[role="tab"], span, div, a, button'))
                        .filter(isVisible)
                        .filter((el) => norm(el.innerText || el.textContent || '').includes(labelPart));
                    if (!nodes.length) return false;
                    nodes[0].click();
                    return true;
                }
                function rowReason(rowText) {
                    const text = norm(rowText);
                    for (const marker of timeMarkers) {
                        if (text.includes(marker)) return marker;
                    }
                    return '';
                }

                const eligibleIds = tableIds(
                    root.querySelector('table[data-testid="beast-core-table"]') || root.querySelector('table')
                );

                const timeBlocked = [];
                const otherIneligible = [];
                const missing = [];

                clickTab('不可报名');
                const ineligibleTable = root.querySelector('table[data-testid="beast-core-table"]') || root.querySelector('table');
                const ineligibleRows = ineligibleTable
                    ? Array.from(ineligibleTable.querySelectorAll('tbody tr')).filter(isVisible)
                    : [];
                const bodyText = norm(root.innerText || root.textContent || '');

                for (const id of ids) {
                    if (eligibleIds.includes(id)) continue;
                    let matched = false;
                    for (const row of ineligibleRows) {
                        const rowText = norm(row.innerText || row.textContent || '');
                        if (!rowText.includes(id)) continue;
                        matched = true;
                        const reason = rowReason(rowText);
                        const entry = { product_id: id, reason_text: reason || rowText.slice(0, 120) };
                        if (reason) {
                            timeBlocked.push(entry);
                        } else {
                            otherIneligible.push(entry);
                        }
                        break;
                    }
                    if (matched) continue;
                    const idx = bodyText.indexOf(id);
                    if (idx >= 0) {
                        const snippet = bodyText.slice(Math.max(0, idx - 20), idx + 160);
                        const reason = rowReason(snippet);
                        if (reason) {
                            timeBlocked.push({ product_id: id, reason_text: reason });
                            matched = true;
                        }
                    }
                    if (!matched) missing.push(id);
                }

                clickTab('可报名');

                return {
                    eligible_ids: eligibleIds,
                    time_blocked: timeBlocked,
                    other_ineligible: otherIneligible,
                    missing_ids: missing,
                };
            }
            """,
            product_ids,
            list(_TIME_REQUIREMENT_MARKERS),
        )
    except Exception as exc:
        return {
            "eligible_ids": _modal_eligible_product_ids(modal, product_ids),
            "time_blocked": [],
            "other_ineligible": [],
            "missing_ids": product_ids,
            "error": str(exc),
        }
    if not isinstance(result, dict):
        return {
            "eligible_ids": [],
            "time_blocked": [],
            "other_ineligible": [],
            "missing_ids": product_ids,
        }
    result["eligible_ids"] = [
        str(item).strip()
        for item in (result.get("eligible_ids") or [])
        if str(item).strip()
    ]
    return result


def _format_modal_eligibility_failure(eligibility: dict[str, Any], product_ids: list[str]) -> dict[str, Any]:
    time_blocked = [
        item for item in (eligibility.get("time_blocked") or []) if isinstance(item, dict)
    ]
    if time_blocked:
        parts = [
            f"{item.get('product_id')}（{item.get('reason_text') or '需等待1天'}）"
            for item in time_blocked
        ]
        return {
            "status": "failed",
            "step": "product_time_requirement_not_met",
            "error": "当前商品未满足时间要求，已取消报名：" + "；".join(parts),
            "eligibility": eligibility,
        }

    missing = [
        str(item).strip()
        for item in (eligibility.get("missing_ids") or [])
        if str(item).strip()
    ]
    other = [
        item for item in (eligibility.get("other_ineligible") or []) if isinstance(item, dict)
    ]
    eligible = eligibility.get("eligible_ids") or []
    if len(eligible) < len(product_ids):
        blocked_ids = missing or [
            str(item.get("product_id") or "").strip()
            for item in other
            if str(item.get("product_id") or "").strip()
        ]
        detail = "；".join(
            f"{item.get('product_id')}（{item.get('reason_text') or '不可报名'}）"
            for item in other
        ) if other else ", ".join(blocked_ids)
        return {
            "status": "failed",
            "step": "product_not_eligible_for_activity",
            "error": f"部分商品不可报名活动，已取消操作：{detail or ', '.join(product_ids)}",
            "eligibility": eligibility,
        }
    return {}


def _click_modal_cancel_button(modal) -> dict[str, Any]:
    selectors = (
        'button[data-testid="beast-core-button"]:has-text("取消")',
        'button:has-text("取消")',
    )
    for selector in selectors:
        try:
            buttons = modal.locator(selector)
            for index in range(buttons.count() - 1, -1, -1):
                btn = buttons.nth(index)
                if btn.is_visible():
                    btn.click(timeout=3_000)
                    return {"clicked": True, "method": selector}
        except Exception:
            continue
    return {"clicked": False, "reason": "modal_cancel_button_not_found"}


def _close_product_search_modal_if_open(page: DpPage) -> None:
    modal = _product_search_modal_locator(page)
    if modal is None:
        return
    _click_modal_cancel_button(modal)
    time.sleep(0.5)


def _fill_product_search_modal_input(modal, product_ids: list[str]) -> dict[str, Any]:
    query = ",".join(product_ids)
    input_selectors = (
        'input[data-testid="beast-core-input-htmlInput"]',
        'input[data-testid="beast-core-input-nativeInput"]',
        'input[placeholder*="多个ID以逗号隔开"]',
    )
    for selector in input_selectors:
        loc = modal.locator(selector).first
        try:
            if not loc.count() or not loc.is_visible():
                continue
            loc.click(timeout=3_000)
            loc.fill("", timeout=3_000)
            loc.fill(query, timeout=5_000)
            actual = str(loc.input_value(timeout=2_000) or "").strip()
            if actual == query:
                return {"filled": True, "value": actual, "method": "playwright_fill", "selector": selector}
        except Exception:
            continue
    return {"filled": False, "reason": "modal_search_input_fill_failed", "expected": query}


def _click_modal_query_button(modal) -> dict[str, Any]:
    """点击搜索框右侧「查询」后缀按钮（图一）。"""
    suffix_selectors = (
        'div[data-testid="beast-core-input-suffix"]',
        'div[class*="IPT_suffixCell"][class*="IPT_pointerCell"]',
        'div[class*="IPT_pointerCell"]:has-text("查询")',
    )
    for selector in suffix_selectors:
        try:
            suffix = modal.locator(selector).first
            if suffix.count() and suffix.is_visible():
                suffix.click(timeout=5_000)
                return {"clicked": True, "text": "查询", "method": selector}
        except Exception:
            continue

    selectors = (
        'button[data-testid="beast-core-button"]:has-text("查询")',
        'span:has-text("查询")',
        'button:has-text("查询")',
        'div[class*="BTN"]:has-text("查询")',
    )
    for selector in selectors:
        try:
            buttons = modal.locator(selector)
            count = buttons.count()
            for index in range(count):
                btn = buttons.nth(index)
                if btn.is_visible():
                    btn.click(timeout=5_000)
                    return {"clicked": True, "text": "查询", "method": selector, "index": index}
        except Exception:
            continue

    js_result = modal.evaluate(
        """
        (root) => {
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 8 && r.height > 8
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function norm(text) {
                return (text || '').replace(/\\s+/g, '').trim();
            }
            const inputs = Array.from(root.querySelectorAll('input'))
                .filter(isVisible)
                .filter((el) => {
                    const ph = el.getAttribute('placeholder') || '';
                    return ph.includes('ID') || ph.includes('商品');
                });
            const input = inputs[0];
            const buttons = Array.from(root.querySelectorAll('button, span, div'))
                .filter(isVisible)
                .map((el) => ({
                    el,
                    text: norm(el.innerText || el.textContent || ''),
                    rect: el.getBoundingClientRect(),
                }))
                .filter((item) => item.text === '查询');
            if (!buttons.length) {
                return { clicked: false, reason: 'modal_query_button_not_found' };
            }
            let target = buttons[0].el;
            if (input) {
                const inputRect = input.getBoundingClientRect();
                const nearby = buttons
                    .filter((item) => Math.abs(item.rect.top - inputRect.top) < 60)
                    .sort((a, b) => Math.abs(a.rect.left - inputRect.right) - Math.abs(b.rect.left - inputRect.right));
                if (nearby.length) {
                    target = nearby[0].el;
                }
            }
            target.click();
            return { clicked: true, text: '查询', method: 'js_modal_query' };
        }
        """
    )
    if isinstance(js_result, dict) and js_result.get("clicked"):
        return js_result
    return {"clicked": False, "reason": "modal_query_button_not_found"}


def _trigger_modal_product_search(modal, product_ids: list[str]) -> dict[str, Any]:
    try:
        rows = modal.locator('table[data-testid="beast-core-table"] tbody tr')
        if rows.count() > 0 and _modal_contains_products(modal, product_ids):
            return {"clicked": True, "text": "查询", "method": "results_already_visible", "skipped": True}
    except Exception:
        pass

    query_result = _click_modal_query_button(modal)
    if query_result.get("clicked"):
        return query_result

    input_selectors = (
        'input[data-testid="beast-core-input-htmlInput"]',
        'input[data-testid="beast-core-input-nativeInput"]',
        'input[placeholder*="多个ID以逗号隔开"]',
        'input[placeholder*="商品"]',
    )
    for selector in input_selectors:
        try:
            loc = modal.locator(selector).first
            if loc.count() and loc.is_visible():
                loc.press("Enter", timeout=3_000)
                time.sleep(1.5)
                if _modal_contains_products(modal, product_ids):
                    return {"clicked": True, "text": "查询", "method": "press_enter", "selector": selector}
        except Exception:
            continue

    if _modal_contains_products(modal, product_ids):
        return {"clicked": True, "text": "查询", "method": "results_visible_after_enter", "skipped": True}

    return query_result


def _wait_modal_products_loaded(modal, product_ids: list[str], timeout: int = 15) -> dict[str, Any]:
    for _ in range(timeout):
        try:
            eligible = _modal_eligible_product_ids(modal, product_ids)
            if eligible and all(pid in eligible for pid in product_ids):
                rows = modal.locator('table[data-testid="beast-core-table"] tbody tr')
                if rows.count() > 0:
                    return {
                        "loaded": True,
                        "product_ids": product_ids,
                        "eligible_ids": eligible,
                        "row_count": rows.count(),
                    }
        except Exception:
            pass
        time.sleep(1)
    eligible = _modal_eligible_product_ids(modal, product_ids)
    missing = [pid for pid in product_ids if pid not in eligible]
    return {
        "loaded": False,
        "missing_product_ids": missing or product_ids,
        "eligible_ids": eligible,
    }


def _read_modal_selection_state(modal) -> dict[str, Any]:
    return modal.evaluate(
        """
        (root) => {
            function beastChecked(input) {
                if (!input) return false;
                return input.checked || input.getAttribute('data-checked') === 'true';
            }
            const table = root.querySelector('table[data-testid="beast-core-table"]') || root.querySelector('table');
            const text = (root.innerText || root.textContent || '').replace(/\\s+/g, ' ');
            const needSelectWarning = text.includes('请至少勾选一个商品');
            if (!table) {
                return { has_table: false, need_select_warning: needSelectWarning };
            }
            const headInput = table.querySelector('thead input[type="checkbox"]');
            const bodyInputs = Array.from(table.querySelectorAll('tbody input[type="checkbox"]'));
            const checkedBody = bodyInputs.filter((item) => beastChecked(item)).length;
            return {
                has_table: true,
                head_checked: beastChecked(headInput),
                body_total: bodyInputs.length,
                body_checked: checkedBody,
                need_select_warning: needSelectWarning,
                selected: checkedBody > 0 || beastChecked(headInput),
            };
        }
        """
    ) or {"selected": False, "reason": "selection_state_js_failed"}


def _modal_selection_verified(modal) -> bool:
    state = _read_modal_selection_state(modal)
    if not isinstance(state, dict):
        return False
    if state.get("need_select_warning"):
        return False
    return bool(state.get("selected"))


def _click_beast_checkbox_target(target) -> dict[str, Any]:
    label_selectors = (
        'label[class*="CBX_checkbox"]',
        'label[class*="CBX_outerWrapper"]',
        'label[class*="CBX"]',
    )
    for selector in label_selectors:
        try:
            label = target.locator(selector).first
            if label.count():
                label.scroll_into_view_if_needed(timeout=2_000)
                label.click(timeout=5_000)
                return {"clicked": True, "method": selector}
        except Exception:
            continue
    try:
        box = target.locator('input[type="checkbox"]').first
        if box.count():
            box.click(force=True, timeout=5_000)
            return {"clicked": True, "method": "force_input_click"}
    except Exception:
        pass
    return {"clicked": False, "reason": "beast_checkbox_click_failed"}


def _click_modal_select_all_checkbox(modal) -> dict[str, Any]:
    """点击表头全选复选框（图二/图三 label.CBX_checkbox）。"""
    head_selectors = (
        'table[data-testid="beast-core-table"] thead th[class*="checkCell"]',
        'table[data-testid="beast-core-table"] thead th[class*="CheckCell"]',
        'thead th[class*="checkCell"]',
        'thead th[class*="CheckCell"]',
    )
    for head_selector in head_selectors:
        try:
            head_cell = modal.locator(head_selector).first
            if not head_cell.count():
                continue
            click_result = _click_beast_checkbox_target(head_cell)
            if click_result.get("clicked"):
                time.sleep(0.5)
                if _modal_selection_verified(modal):
                    return {"checked": True, "method": f"playwright_{head_selector}", **click_result}
        except Exception:
            continue

    js_result = modal.evaluate(
        """
        (root) => {
            function beastChecked(input) {
                if (!input) return false;
                return input.checked || input.getAttribute('data-checked') === 'true';
            }
            function clickBeastCheckbox(container) {
                if (!container) return false;
                const label = container.querySelector('label[class*="CBX_checkbox"], label[class*="CBX"]');
                if (label) {
                    label.click();
                    return true;
                }
                const input = container.querySelector('input[type="checkbox"]');
                if (input) {
                    input.click();
                    return true;
                }
                return false;
            }
            const table = root.querySelector('table[data-testid="beast-core-table"]') || root.querySelector('table');
            if (!table) {
                return { checked: false, reason: 'modal_table_not_found' };
            }
            const headCell = table.querySelector('thead th[class*="checkCell"], thead th[class*="CheckCell"]');
            if (!headCell) {
                return { checked: false, reason: 'thead_check_cell_not_found' };
            }
            if (!clickBeastCheckbox(headCell)) {
                return { checked: false, reason: 'thead_checkbox_click_failed' };
            }
            const headInput = table.querySelector('thead input[type="checkbox"]');
            const bodyInputs = Array.from(table.querySelectorAll('tbody input[type="checkbox"]'));
            const selected = beastChecked(headInput) || bodyInputs.some((item) => beastChecked(item));
            return {
                checked: selected,
                method: 'js_thead_label_click',
                head_checked: beastChecked(headInput),
                body_checked: bodyInputs.filter((item) => beastChecked(item)).length,
            };
        }
        """
    )
    if isinstance(js_result, dict) and js_result.get("checked"):
        return js_result
    return js_result if isinstance(js_result, dict) else {"checked": False, "reason": "select_all_js_failed"}


def _click_modal_product_row_checkboxes(modal, product_ids: list[str]) -> dict[str, Any]:
    """逐行点击 beast-core 复选框 label（图三）。"""
    js_result = modal.evaluate(
        f"""
        (root) => {{
            const productIds = {product_ids!r};
            function beastChecked(input) {{
                if (!input) return false;
                return input.checked || input.getAttribute('data-checked') === 'true';
            }}
            function clickBeastCheckbox(container) {{
                if (!container) return false;
                const label = container.querySelector('label[class*="CBX_checkbox"], label[class*="CBX"]');
                if (label) {{
                    label.click();
                    return true;
                }}
                const input = container.querySelector('input[type="checkbox"]');
                if (input) {{
                    input.click();
                    return true;
                }}
                return false;
            }}
            const table = root.querySelector('table[data-testid="beast-core-table"]') || root.querySelector('table');
            if (!table) {{
                return {{ checked: false, reason: 'modal_table_not_found' }};
            }}
            const rows = Array.from(table.querySelectorAll('tbody tr'))
                .filter((row) => {{
                    const text = (row.innerText || row.textContent || '').replace(/\\s+/g, ' ');
                    return productIds.some((id) => text.includes(id));
                }});
            if (!rows.length) {{
                return {{ checked: false, reason: 'product_rows_not_found' }};
            }}
            let clicked = 0;
            for (const row of rows) {{
                const cell = row.querySelector('td[class*="checkCell"], td[class*="CheckCell"]') || row;
                const input = row.querySelector('input[type="checkbox"]');
                if (beastChecked(input)) {{
                    clicked += 1;
                    continue;
                }}
                if (clickBeastCheckbox(cell)) {{
                    clicked += 1;
                }}
            }}
            const bodyInputs = Array.from(table.querySelectorAll('tbody input[type="checkbox"]'));
            const bodyChecked = bodyInputs.filter((item) => beastChecked(item)).length;
            return {{
                checked: bodyChecked > 0,
                clicked,
                body_checked: bodyChecked,
                method: 'js_row_label_click',
            }};
        }}
        """
    )
    return js_result if isinstance(js_result, dict) else {"checked": False, "reason": "row_checkbox_js_failed"}


def _ensure_modal_products_selected(modal, product_ids: list[str]) -> dict[str, Any]:
    """查询后勾选商品：先表头全选，再逐行勾选，并校验不再提示「请至少勾选一个商品」。"""
    attempts: list[dict[str, Any]] = []

    for method_name, action in (
        ("select_all", lambda: _click_modal_select_all_checkbox(modal)),
        ("row_checkboxes", lambda: _click_modal_product_row_checkboxes(modal, product_ids)),
        ("select_all_retry", lambda: _click_modal_select_all_checkbox(modal)),
    ):
        result = action()
        attempts.append({"method": method_name, **result})
        time.sleep(0.6)
        if _modal_selection_verified(modal):
            state = _read_modal_selection_state(modal)
            return {
                "checked": True,
                "method": method_name,
                "attempts": attempts,
                "selection_state": state,
                **result,
            }

    state = _read_modal_selection_state(modal)
    return {
        "checked": False,
        "reason": "modal_products_not_selected",
        "attempts": attempts,
        "selection_state": state,
    }


def _ensure_modal_product_rows_checked(modal, product_ids: list[str]) -> dict[str, Any]:
    """兼容旧调用：转调 beast-core 勾选逻辑。"""
    return _ensure_modal_products_selected(modal, product_ids)


def _click_modal_confirm_button(modal) -> dict[str, Any]:
    """点击弹窗底部「确认」按钮（图三红框）。"""
    selectors = (
        'button[data-tracking-viewid="add_goods_modal_confirm_clicked"]',
        'button[data-tracking-viewid="add_goods_modal_confirm_shared"]',
        'button[data-testid="beast-core-button"]:has-text("确认")',
        'button:has-text("确认")',
    )
    for selector in selectors:
        try:
            buttons = modal.locator(selector)
            count = buttons.count()
            for index in range(count - 1, -1, -1):
                btn = buttons.nth(index)
                if not btn.is_visible():
                    continue
                text = str(btn.inner_text(timeout=1_000) or "").strip()
                if text == "确认":
                    btn.scroll_into_view_if_needed(timeout=3_000)
                    btn.click(timeout=5_000)
                    return {"clicked": True, "text": "确认", "method": selector, "index": index}
        except Exception:
            continue
    return {"clicked": False, "reason": "modal_confirm_button_not_found"}


def _is_price_confirm_url(url: str) -> bool:
    return "goods_price/confirm" in url or "goods/price" in url


def _find_price_confirm_page(
    page: DpPage,
    activity_id: str,
) -> tuple[Any | None, str]:
    if _is_price_confirm_page(page):
        return getattr(page, "_page", None), str(page.url or "")

    candidates: list[tuple[str, Any]] = []
    for item in _live_context_pages(page):
        try:
            url = str(item.url or "")
        except Exception:
            continue
        if not _is_price_confirm_url(url):
            continue
        if activity_id and activity_id not in url:
            continue
        candidates.append((url, item))

    for url, item in reversed(candidates):
        try:
            _bind_page(page, item)
            item.bring_to_front()
            time.sleep(0.4)
            if _is_price_confirm_page(page):
                return item, url
        except Exception:
            continue
    return None, ""


def _ensure_price_confirm_page(
    page: DpPage,
    activity_id: str,
    account_id: str,
    *,
    timeout: int = 25,
    keep_product_pick: bool = True,
) -> dict[str, Any]:
    """轮询并切到价格确认页，同时关闭误开的活动大厅/详情标签。"""
    deadline = time.monotonic() + max(timeout, 1)
    close_history: list[str] = []
    last_diagnosis: dict[str, Any] = {}

    while time.monotonic() < deadline:
        target, url = _find_price_confirm_page(page, activity_id)
        if target is not None:
            print(f"[{account_id}] 已进入价格确认页: {url}", flush=True)
            return {
                "ready": True,
                "switched": True,
                "method": "price_confirm_tab",
                "url": url,
                "closed_tabs": close_history,
            }

        close_result = _close_irrelevant_registration_tabs(
            page,
            account_id,
            keep_product_pick=keep_product_pick,
        )
        close_history.extend(close_result.get("closed") or [])

        target, url = _find_price_confirm_page(page, activity_id)
        if target is not None:
            print(f"[{account_id}] 清理标签后进入价格确认页: {url}", flush=True)
            return {
                "ready": True,
                "switched": True,
                "method": "price_confirm_tab_after_cleanup",
                "url": url,
                "closed_tabs": close_history,
            }

        if _is_price_confirm_page(page):
            return {
                "ready": True,
                "switched": True,
                "method": "current_page",
                "url": str(page.url or ""),
                "closed_tabs": close_history,
            }

        last_diagnosis = _describe_campaign_page(page)
        time.sleep(0.35)

    return {
        "ready": False,
        "switched": False,
        "reason": "price_confirm_page_not_ready",
        "url": str(page.url or ""),
        "closed_tabs": close_history,
        "diagnosis": last_diagnosis,
    }


def _describe_campaign_page(page: DpPage) -> dict[str, Any]:
    """当前页面/标签页诊断信息，便于排查流程跳页。"""
    tabs: list[str] = []
    for item in _live_context_pages(page):
        try:
            tabs.append(str(item.url or ""))
        except Exception:
            continue
    body = _body_text(page)
    return {
        "current_url": str(page.url or ""),
        "is_login_page": is_login_url(str(page.url or "")),
        "is_price_confirm": _is_price_confirm_page(page),
        "open_tab_count": len(tabs),
        "open_tab_urls": tabs,
        "body_sample": body[:500],
        "has_traffic_protection": "开启流量保护" in body,
        "has_confirm_submit": "确认提交" in body,
        "has_price_confirm_title": "确认商品价格信息" in body or "填写报名信息" in body,
    }


def _switch_to_price_confirm_tab(
    page: DpPage,
    activity_id: str,
    account_id: str,
) -> dict[str, Any]:
    """切到价格确认页标签（goods_price/confirm），并关闭无关活动页。"""
    ensure_result = _ensure_price_confirm_page(
        page,
        activity_id,
        account_id,
        timeout=3,
        keep_product_pick=True,
    )
    if ensure_result.get("ready"):
        return {
            "switched": True,
            "method": ensure_result.get("method"),
            "url": ensure_result.get("url"),
            "closed_tabs": ensure_result.get("closed_tabs") or [],
        }

    diagnosis = ensure_result.get("diagnosis") or _describe_campaign_page(page)
    print(f"[{account_id}] 未找到价格确认页标签: {diagnosis}", flush=True)
    return {
        "switched": False,
        "method": "price_confirm_tab_not_found",
        "url": str(page.url or ""),
        "diagnosis": diagnosis,
        "closed_tabs": ensure_result.get("closed_tabs") or [],
    }


def _is_price_confirm_page(page: DpPage) -> bool:
    url = str(page.url or "")
    if "goods_price/confirm" in url or "goods/price" in url:
        return True
    text = _body_text(page)
    return any(marker in text for marker in ("确认商品价格信息", "填写报名信息"))


def _scroll_page_to_bottom(page: DpPage) -> None:
    raw_page = getattr(page, "_page", None)
    try:
        if raw_page is not None:
            raw_page.evaluate(
                """
                () => {
                    window.scrollTo(0, document.body.scrollHeight);
                    const nodes = Array.from(document.querySelectorAll('div, main, section'))
                        .filter((el) => el.scrollHeight > el.clientHeight + 40);
                    nodes.forEach((el) => { el.scrollTop = el.scrollHeight; });
                }
                """
            )
        else:
            page.run_js(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
    except Exception:
        pass
    time.sleep(0.8)


def _wait_price_confirm_page(
    page: DpPage,
    timeout: int = 25,
    poll_interval: float = 0.25,
) -> bool:
    deadline = time.monotonic() + max(timeout, 1)
    while time.monotonic() < deadline:
        if _is_price_confirm_page(page):
            return True
        time.sleep(poll_interval)
    return False


def _wait_price_confirm_content_ready(page: DpPage, *, timeout: int = 20) -> bool:
    """等待价格确认页表格/按钮渲染完成（避免未展开就抓取规格）。"""
    deadline = time.monotonic() + max(timeout, 1)
    while time.monotonic() < deadline:
        if not _is_price_confirm_page(page):
            time.sleep(0.4)
            continue
        text = _body_text(page)
        if any(
            marker in text
            for marker in ("确认提交", "确认商品价格信息", "填写报名信息", "展开更多规格", "活动价")
        ):
            return True
        time.sleep(0.45)
    return False


def _shop_wide_promotion_find_js() -> str:
    return """
        function beastChecked(input) {
            if (!input) return false;
            return input.checked || input.getAttribute('data-checked') === 'true';
        }
        function norm(text) {
            return (text || '').replace(/\\s+/g, ' ').trim();
        }
        function isShopWideCheckboxText(text) {
            const value = norm(text);
            if (!value.includes('全店报名')) return false;
            if (value.includes('开启流量保护')) return false;
            if (value.includes('分口两流')) return false;
            if (value.includes('我已阅读并同意')) return false;
            if (value.includes('开启全店报名')) return false;
            return true;
        }
        function findShopWideBlock() {
            const labels = Array.from(document.querySelectorAll(
                '[data-testid="beast-core-checkbox"], label[class*="CBX"], label[class*="ICE"]'
            ));
            for (const label of labels) {
                const text = norm(label.innerText || label.textContent || '');
                if (!isShopWideCheckboxText(text)) continue;
                return label.closest('[data-testid="beast-core-checkbox"]') || label;
            }
            const blocks = Array.from(document.querySelectorAll('div, section, label, span'))
                .filter((el) => isShopWideCheckboxText(el.innerText || el.textContent || ''));
            if (!blocks.length) return null;
            blocks.sort((a, b) => {
                const ta = norm(a.innerText || a.textContent || '').length;
                const tb = norm(b.innerText || b.textContent || '').length;
                return ta - tb;
            });
            return blocks[0];
        }
    """


def _read_shop_wide_promotion_checked(page: DpPage) -> dict[str, Any]:
    script = (
        _shop_wide_promotion_find_js()
        + """
        const block = findShopWideBlock();
        if (!block) {
            return { found: false, reason: 'shop_wide_promotion_not_found' };
        }
        const input = block.querySelector('input[type="checkbox"]')
            || block.closest('label')?.querySelector('input[type="checkbox"]')
            || block.parentElement?.querySelector('input[type="checkbox"]');
        const activeIcon = block.querySelector('[class*="CBX_active"], [class*="CBX_iconCheck"][class*="active"]');
        const checked = beastChecked(input) || Boolean(activeIcon);
        return {
            found: true,
            checked,
            text: norm(block.innerText || block.textContent || '').slice(0, 180),
        };
        """
    )
    return page.run_js(script) or {"found": False, "reason": "shop_wide_promotion_state_js_failed"}


def _uncheck_shop_wide_promotion(page: DpPage, account_id: str) -> dict[str, Any]:
    """价格确认页取消勾选「全店报名官方大促…」复选框（部分活动页无此项）。"""
    for _ in range(3):
        _scroll_page_to_bottom(page)
        before = _read_shop_wide_promotion_checked(page)
        if before.get("found"):
            break
        try:
            page.run_js("window.scrollTo(0, 0);")
        except Exception:
            pass
        time.sleep(0.4)
    else:
        before = _read_shop_wide_promotion_checked(page)
    if not before.get("found"):
        return {"unchecked": False, "reason": "shop_wide_promotion_not_found", "before": before}
    if not before.get("checked"):
        print(f"[{account_id}] 全店报名已是未勾选状态", flush=True)
        return {"unchecked": True, "method": "already_unchecked", "before": before}

    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        playwright_selectors = (
            '[data-testid="beast-core-checkbox"]:has-text("全店报名")',
            'label:has-text("全店报名官方大促")',
            'label:has-text("全店报名")',
        )
        for selector in playwright_selectors:
            try:
                target = raw_page.locator(selector).first
                if not target.count() or not target.is_visible():
                    continue
                target.scroll_into_view_if_needed(timeout=3_000)
                label = target.locator('label[class*="CBX"], label[class*="ICE"]').first
                click_target = label if label.count() and label.is_visible() else target
                click_target.click(timeout=5_000)
                time.sleep(0.6)
                after = _read_shop_wide_promotion_checked(page)
                if not after.get("checked"):
                    print(f"[{account_id}] 已取消勾选全店报名", flush=True)
                    return {
                        "unchecked": True,
                        "method": f"playwright_{selector}",
                        "before": before,
                        "after": after,
                    }
            except Exception:
                continue

    js_result = page.run_js(
        _shop_wide_promotion_find_js()
        + """
        const block = findShopWideBlock();
        if (!block) {
            return { unchecked: false, reason: 'shop_wide_promotion_block_not_found' };
        }
        const input = block.querySelector('input[type="checkbox"]')
            || block.closest('label')?.querySelector('input[type="checkbox"]')
            || block.parentElement?.querySelector('input[type="checkbox"]');
        const activeIcon = block.querySelector('[class*="CBX_active"], [class*="CBX_iconCheck"][class*="active"]');
        if (!beastChecked(input) && !activeIcon) {
            return { unchecked: true, method: 'js_already_unchecked' };
        }
        const label = block.querySelector('label[class*="CBX"], label[class*="ICE"]')
            || (block.tagName === 'LABEL' ? block : null);
        if (label) {
            label.click();
        } else if (input) {
            input.click();
        } else {
            block.click();
        }
        const afterInput = block.querySelector('input[type="checkbox"]') || input;
        const afterActive = block.querySelector('[class*="CBX_active"], [class*="CBX_iconCheck"][class*="active"]');
        return {
            unchecked: !beastChecked(afterInput) && !afterActive,
            method: label ? 'js_label_click' : 'js_input_click',
        };
        """
    ) or {"unchecked": False, "reason": "shop_wide_promotion_js_failed"}

    after = _read_shop_wide_promotion_checked(page)
    if js_result.get("unchecked") or not after.get("checked"):
        print(f"[{account_id}] 已取消勾选全店报名", flush=True)
        return {
            "unchecked": True,
            "method": js_result.get("method", "js_uncheck"),
            "before": before,
            "after": after,
            "js_result": js_result,
        }
    return {
        "unchecked": False,
        "reason": "shop_wide_promotion_still_checked",
        "before": before,
        "after": after,
        "js_result": js_result,
    }


def _expand_price_confirm_specs(page: DpPage, account_id: str) -> dict[str, Any]:
    """价格确认页点击「展开更多规格」（每个商品各点一次，直到页面上无剩余链接）。"""
    expand_result = _expand_all_specs_on_page(page)
    clicked_count = int(expand_result.get("clicked_count") or 0)
    remaining = int(expand_result.get("remaining_links") or 0)

    if clicked_count > 0:
        print(f"[{account_id}] 已展开更多规格 x{clicked_count}", flush=True)

    if remaining <= 0:
        return {
            "expanded": True,
            "clicked_count": clicked_count,
            "remaining_links": 0,
            **expand_result,
        }

    return {
        "expanded": False,
        "reason": "expand_specs_link_not_clicked",
        "clicked_count": clicked_count,
        "remaining_links": remaining,
        **expand_result,
    }


def _prepare_price_confirm_page(page: DpPage, account_id: str, activity_id: str) -> dict[str, Any]:
    """确认选择后：进入填写报名信息页 → 展开规格 → 取消全店报名/流量保护勾选。"""
    time.sleep(0.8)
    setattr(page, "_campaign_close_stale_tabs", True)
    try:
        ensure_price = _ensure_price_confirm_page(
            page,
            activity_id,
            account_id,
            timeout=25,
            keep_product_pick=False,
        )
    finally:
        setattr(page, "_campaign_close_stale_tabs", False)

    if not ensure_price.get("ready"):
        return {
            "status": "failed",
            "step": "wait_price_confirm_page",
            "reason": ensure_price.get("reason") or "price_confirm_page_not_ready",
            "url": str(page.url or ""),
            "ensure_price": ensure_price,
        }

    expand_result = _expand_price_confirm_specs(page, account_id)
    if not expand_result.get("expanded"):
        return {
            "status": "failed",
            "step": "expand_price_specs",
            "error": "未能点击展开更多规格",
            "expand_result": expand_result,
            "url": page.url,
        }

    uncheck_result = _uncheck_shop_wide_promotion(page, account_id)
    if not uncheck_result.get("unchecked"):
        not_present = (
            uncheck_result.get("reason") == "shop_wide_promotion_not_found"
            or not (uncheck_result.get("before") or {}).get("found")
        )
        if not_present:
            print(f"[{account_id}] 本页未找到全店报名勾选项，跳过", flush=True)
            uncheck_result = {
                **uncheck_result,
                "unchecked": True,
                "method": "skipped_not_present",
            }
        else:
            return {
                "status": "failed",
                "step": "uncheck_shop_wide_promotion",
                "error": uncheck_result.get("reason") or "未能取消全店报名勾选",
                "expand_result": expand_result,
                "shop_wide_promotion": uncheck_result,
                "url": page.url,
            }

    traffic_result = _uncheck_traffic_protection(page, account_id, activity_id)
    if not traffic_result.get("unchecked"):
        return {
            "status": "failed",
            "step": "uncheck_traffic_protection",
            "error": traffic_result.get("reason") or "未能取消开启流量保护勾选",
            "expand_result": expand_result,
            "shop_wide_promotion": uncheck_result,
            "traffic_protection": traffic_result,
            "url": page.url,
        }

    return {
        "status": "success",
        "step": "price_page_prepared",
        "expand_result": expand_result,
        "shop_wide_promotion": uncheck_result,
        "traffic_protection": traffic_result,
        "current_url": page.url,
    }


def _wait_traffic_protection_visible(page: DpPage, timeout: int = 20) -> bool:
    for _ in range(timeout):
        _scroll_page_to_bottom(page)
        state = _read_traffic_protection_checked(page)
        if state.get("found"):
            return True
        text = _body_text(page)
        if "开启流量保护" in text:
            return True
        time.sleep(1)
    return False


def _traffic_protection_find_js() -> str:
    return """
        function beastChecked(input) {
            if (!input) return false;
            return input.checked || input.getAttribute('data-checked') === 'true';
        }
        function norm(text) {
            return (text || '').replace(/\\s+/g, ' ').trim();
        }
        function isTrafficText(text) {
            const value = norm(text);
            if (!value.includes('开启流量保护')) return false;
            if (value.includes('我已阅读并同意')) return false;
            if (value.includes('降价补差')) return false;
            return true;
        }
        function findTrafficBlock() {
            const labels = Array.from(document.querySelectorAll(
                'label[class*="CBX"], label[class*="ICE"], [data-testid="beast-core-checkbox"], div[class*="traffic_protect"]'
            ));
            for (const label of labels) {
                const text = norm(label.innerText || label.textContent || '');
                if (isTrafficText(text)) {
                    return label;
                }
            }
            const blocks = Array.from(document.querySelectorAll('div, section, label, span'))
                .filter((el) => isTrafficText(el.innerText || el.textContent || ''));
            if (blocks.length) {
                blocks.sort((a, b) => {
                    const ta = norm(a.innerText || a.textContent || '').length;
                    const tb = norm(b.innerText || b.textContent || '').length;
                    return ta - tb;
                });
                return blocks[0];
            }
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
                if (!node.textContent || !node.textContent.includes('开启流量保护')) continue;
                let el = node.parentElement;
                for (let depth = 0; depth < 10 && el; depth += 1) {
                    const input = el.querySelector && el.querySelector('input[type="checkbox"]');
                    if (input) return el;
                    el = el.parentElement;
                }
            }
            return null;
        }
    """


def _read_traffic_protection_checked(page: DpPage) -> dict[str, Any]:
    script = (
        _traffic_protection_find_js()
        + """
        const block = findTrafficBlock();
        if (!block) {
            return { found: false, reason: 'traffic_protection_block_not_found' };
        }
        const input = block.querySelector('input[type="checkbox"]')
            || block.closest('label')?.querySelector('input[type="checkbox"]')
            || block.parentElement?.querySelector('input[type="checkbox"]');
        const label = block.querySelector('label[class*="CBX"], label[class*="ICE"]')
            || (block.tagName === 'LABEL' ? block : null);
        return {
            found: true,
            checked: beastChecked(input),
            has_label: Boolean(label),
            text: norm(block.innerText || block.textContent || '').slice(0, 160),
        };
        """
    )
    return page.run_js(script) or {"found": False, "reason": "traffic_protection_state_js_failed"}


def _uncheck_traffic_protection(page: DpPage, account_id: str, activity_id: str = "") -> dict[str, Any]:
    """确认商品价格信息页取消勾选「开启流量保护」（图四红框）。"""
    ensure_result = _ensure_price_confirm_page(page, activity_id, account_id, timeout=10)
    if not ensure_result.get("ready"):
        return {
            "unchecked": False,
            "reason": "price_confirm_page_not_ready",
            "url": page.url,
            "ensure_result": ensure_result,
            "page_diagnosis": ensure_result.get("diagnosis") or _describe_campaign_page(page),
        }

    if not _wait_traffic_protection_visible(page, timeout=20):
        return {
            "unchecked": False,
            "reason": "traffic_protection_not_found",
            "url": page.url,
            "body_sample": _body_text(page)[:300],
        }

    _scroll_page_to_bottom(page)
    before = _read_traffic_protection_checked(page)
    if not before.get("found"):
        return {"unchecked": False, "reason": "traffic_protection_not_found", "before": before}
    if not before.get("checked"):
        print(f"[{account_id}] 流量保护已是未勾选状态", flush=True)
        return {"unchecked": True, "method": "already_unchecked", "before": before}

    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        playwright_selectors = (
            'div[class*="traffic_protect"] label[class*="CBX"]',
            'div[class*="traffic_protect"]',
            '[data-testid="beast-core-checkbox"]:has-text("开启流量保护")',
            'label:has-text("开启流量保护")',
        )
        for selector in playwright_selectors:
            try:
                target = raw_page.locator(selector).first
                if not target.count() or not target.is_visible():
                    continue
                target.scroll_into_view_if_needed(timeout=3_000)
                label = target.locator('label[class*="CBX"], label[class*="ICE"]').first
                click_target = label if label.count() and label.is_visible() else target
                click_target.click(timeout=5_000)
                time.sleep(0.6)
                after = _read_traffic_protection_checked(page)
                if not after.get("checked"):
                    print(f"[{account_id}] 已取消勾选开启流量保护", flush=True)
                    return {
                        "unchecked": True,
                        "method": f"playwright_{selector}",
                        "before": before,
                        "after": after,
                    }
            except Exception:
                continue

    js_result = page.run_js(
        _traffic_protection_find_js()
        + """
        const block = findTrafficBlock();
        if (!block) {
            return { unchecked: false, reason: 'traffic_protection_block_not_found' };
        }
        const input = block.querySelector('input[type="checkbox"]')
            || block.closest('label')?.querySelector('input[type="checkbox"]')
            || block.parentElement?.querySelector('input[type="checkbox"]');
        if (!beastChecked(input)) {
            return { unchecked: true, method: 'js_already_unchecked' };
        }
        const label = block.querySelector('label[class*="CBX"], label[class*="ICE"]')
            || (block.tagName === 'LABEL' ? block : null);
        if (label) {
            label.click();
        } else if (input) {
            input.click();
        } else {
            block.click();
        }
        const afterInput = block.querySelector('input[type="checkbox"]') || input;
        return {
            unchecked: !beastChecked(afterInput),
            method: label ? 'js_label_click' : 'js_input_click',
            checked_after: beastChecked(afterInput),
        };
        """
    ) or {"unchecked": False, "reason": "traffic_protection_js_failed"}

    after = _read_traffic_protection_checked(page)
    if js_result.get("unchecked") or not after.get("checked"):
        print(f"[{account_id}] 已取消勾选开启流量保护", flush=True)
        return {
            "unchecked": True,
            "method": js_result.get("method", "js_uncheck"),
            "before": before,
            "after": after,
            "js_result": js_result,
        }
    return {
        "unchecked": False,
        "reason": "traffic_protection_still_checked",
        "before": before,
        "after": after,
        "js_result": js_result,
    }


def _click_confirm_submit(page: DpPage, account_id: str) -> dict[str, Any]:
    """价格确认页点击「确认提交」。"""
    _scroll_page_to_bottom(page)
    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        selectors = (
            'button[data-testid="beast-core-button"]:has-text("确认提交")',
            'button:has-text("确认提交")',
        )
        for selector in selectors:
            try:
                buttons = raw_page.locator(selector)
                count = buttons.count()
                for index in range(count - 1, -1, -1):
                    btn = buttons.nth(index)
                    if not btn.is_visible():
                        continue
                    text = str(btn.inner_text(timeout=1_000) or "").strip()
                    if text != "确认提交":
                        continue
                    btn.scroll_into_view_if_needed(timeout=3_000)
                    btn.click(timeout=8_000)
                    print(f"[{account_id}] 已点击确认提交", flush=True)
                    return {"clicked": True, "text": "确认提交", "method": selector, "index": index}
            except Exception:
                continue

    js_result = page.run_js(
        """
        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 && r.height > 16
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }
        const buttons = Array.from(document.querySelectorAll('button'))
            .filter(isVisible)
            .filter((el) => norm(el.innerText || el.textContent || '') === '确认提交');
        if (!buttons.length) {
            return { clicked: false, reason: 'confirm_submit_button_not_found' };
        }
        const target = buttons[buttons.length - 1];
        target.scrollIntoView({ block: 'center', inline: 'nearest' });
        target.click();
        return { clicked: true, text: '确认提交', method: 'js_confirm_submit' };
        """
    ) or {"clicked": False, "reason": "confirm_submit_js_failed"}
    if js_result.get("clicked"):
        print(f"[{account_id}] 已点击确认提交（JS）", flush=True)
    return js_result


def _verify_registration_submit(page: DpPage, account_id: str, *, timeout: int = 18) -> dict[str, Any]:
    """确认提交后校验拼多多是否受理（不能只看按钮有没有点到）。"""
    time.sleep(1.2)
    deadline = time.monotonic() + max(timeout, 1)
    last_url = str(page.url or "")
    last_text = ""

    while time.monotonic() < deadline:
        _dismiss_message_popup(page)
        last_url = str(page.url or "")
        last_text = _body_text(page)

        success_markers = ("活动报名成功", "报名成功", "提交成功", "报名提交成功", "已成功报名", "报名已提交")
        if any(marker in last_text for marker in success_markers):
            print(f"[{account_id}] 报名提交校验通过：页面出现成功提示", flush=True)
            return {"verified": True, "method": "success_text", "url": last_url}

        if not _is_price_confirm_page(page) and "goods_price/confirm" not in last_url:
            if "确认提交" not in last_text:
                print(f"[{account_id}] 报名提交校验通过：已离开价格确认页 url={last_url}", flush=True)
                return {"verified": True, "method": "left_price_confirm", "url": last_url}

        error_markers = (
            "活动价须高于",
            "价格不符合",
            "请修改后",
            "无法提交",
            "存在不符合报名要求的商品",
            "高于活动底价",
            "请调整活动价",
        )
        if any(marker in last_text for marker in error_markers):
            return {
                "verified": False,
                "reason": "submit_rejected_on_page",
                "url": last_url,
                "body_sample": last_text[:400],
            }

        time.sleep(0.45)

    if _is_price_confirm_page(page) or "确认提交" in last_text:
        return {
            "verified": False,
            "reason": "still_on_price_confirm_page",
            "url": last_url,
            "body_sample": last_text[:400],
        }

    return {
        "verified": False,
        "reason": "submit_result_unknown",
        "url": last_url,
        "body_sample": last_text[:400],
    }


def _wait_product_pick_page_ready(page: DpPage, timeout: int = 15) -> bool:
    for _ in range(timeout):
        _dismiss_message_popup(page)
        text = _body_text(page)
        if ("选择活动商品" in text or "选择商品" in text) and "确认选择" in text:
            return True
        time.sleep(1)
    return False


def _click_confirm_product_selection(page: DpPage, account_id: str, activity_id: str) -> dict[str, Any]:
    """选择活动商品页点击底部「确认选择」（图二）。"""
    _dismiss_wrong_tabs_and_focus_product_pick(page, activity_id, account_id)
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return {"clicked": False, "reason": "page_unavailable"}

    if not _wait_product_pick_page_ready(page, timeout=12):
        return {"clicked": False, "reason": "product_pick_page_not_ready", "url": page.url}

    selectors = (
        'button[data-tracking-viewid*="el_confirm_selection"]',
        'button[data-testid="beast-core-button"]:has-text("确认选择")',
        'button:has-text("确认选择")',
    )
    for selector in selectors:
        try:
            buttons = raw_page.locator(selector)
            count = buttons.count()
            for index in range(count - 1, -1, -1):
                btn = buttons.nth(index)
                if not btn.is_visible():
                    continue
                text = str(btn.inner_text(timeout=1_000) or "").strip()
                if text != "确认选择":
                    continue
                btn.scroll_into_view_if_needed(timeout=3_000)
                btn.click(timeout=8_000)
                print(f"[{account_id}] 已点击确认选择", flush=True)
                return {"clicked": True, "text": "确认选择", "method": selector, "index": index}
        except Exception:
            continue

    js_result = page.run_js(
        """
        function norm(text) {
            return (text || '').replace(/\\s+/g, '').trim();
        }
        function isVisible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 20 && r.height > 16
                && s.display !== 'none'
                && s.visibility !== 'hidden'
                && parseFloat(s.opacity || '1') > 0.05;
        }
        const buttons = Array.from(document.querySelectorAll('button'))
            .filter(isVisible)
            .filter((el) => norm(el.innerText || el.textContent || '') === '确认选择');
        if (!buttons.length) {
            return { clicked: false, reason: 'confirm_selection_button_not_found' };
        }
        const target = buttons[buttons.length - 1];
        target.scrollIntoView({ block: 'center', inline: 'nearest' });
        target.click();
        return { clicked: true, text: '确认选择', method: 'js_confirm_selection' };
        """
    ) or {"clicked": False, "reason": "confirm_selection_js_failed"}
    if js_result.get("clicked"):
        print(f"[{account_id}] 已点击确认选择（JS）", flush=True)
    return js_result


def _complete_product_pick_confirmation(
    page: DpPage,
    account_id: str,
    activity_id: str,
) -> dict[str, Any]:
    """搜索弹窗选品后，在选择商品页点击「确认选择」。"""
    time.sleep(1.5)
    _dismiss_wrong_tabs_and_focus_product_pick(page, activity_id, account_id)
    confirm_selection = _click_confirm_product_selection(page, account_id, activity_id)
    if not confirm_selection.get("clicked"):
        return {"status": "failed", "step": "click_confirm_selection", **confirm_selection}

    setattr(page, "_campaign_close_stale_tabs", True)
    try:
        ensure_price = _ensure_price_confirm_page(
            page,
            activity_id,
            account_id,
            timeout=20,
            keep_product_pick=False,
        )
    finally:
        setattr(page, "_campaign_close_stale_tabs", False)

    if not ensure_price.get("ready"):
        return {
            "status": "failed",
            "step": "wait_price_confirm_page",
            "error": ensure_price.get("reason") or "price_confirm_page_not_ready",
            "confirm_selection": confirm_selection,
            "ensure_price": ensure_price,
            "current_url": str(page.url or ""),
        }

    return {
        "status": "success",
        "step": "product_pick_confirmed",
        "confirm_selection": confirm_selection,
        "ensure_price": ensure_price,
        "current_url": ensure_price.get("url") or str(page.url or ""),
    }


def _finalize_standard_registration(
    page: DpPage,
    account_id: str,
    activity_id: str,
    pdd_product_ids: list[str] | None = None,
    account: AccountConfig | None = None,
) -> dict[str, Any]:
    """弹窗确认后：确认选择 → 价格筛选删除 → 取消流量保护 → 确认提交。"""
    product_ids = list(dict.fromkeys(str(item).strip() for item in (pdd_product_ids or []) if str(item).strip()))
    steps: list[dict[str, Any]] = []

    def _log_step(name: str, result: dict[str, Any]) -> None:
        entry = {"step": name, **result, "page": _describe_campaign_page(page)}
        steps.append(entry)
        print(f"[{account_id}] finalize.{name}: {entry.get('status', result.get('reason', 'ok'))} url={page.url}", flush=True)

    if session_err := _require_logged_in(page, account, account_id):
        return {**session_err, "steps": steps}

    setattr(page, "_campaign_close_stale_tabs", True)
    try:
        return _finalize_standard_registration_impl(
            page,
            account_id,
            activity_id,
            product_ids=product_ids,
            account=account,
            steps=steps,
            _log_step=_log_step,
        )
    finally:
        setattr(page, "_campaign_close_stale_tabs", False)


def _finalize_standard_registration_impl(
    page: DpPage,
    account_id: str,
    activity_id: str,
    *,
    product_ids: list[str],
    account: AccountConfig | None,
    steps: list[dict[str, Any]],
    _log_step,
) -> dict[str, Any]:
    time.sleep(1.5)
    _dismiss_wrong_tabs_and_focus_product_pick(page, activity_id, account_id)

    confirm_selection = _click_confirm_product_selection(page, account_id, activity_id)
    _log_step("confirm_selection", {"status": "success" if confirm_selection.get("clicked") else "failed", **confirm_selection})
    if not confirm_selection.get("clicked"):
        return {"status": "failed", "step": "click_confirm_selection", "steps": steps, **confirm_selection}

    time.sleep(1.5)
    ensure_price = _ensure_price_confirm_page(
        page,
        activity_id,
        account_id,
        timeout=25,
        keep_product_pick=False,
    )
    switch_after_confirm = {
        "switched": bool(ensure_price.get("ready")),
        "method": ensure_price.get("method") or ensure_price.get("reason"),
        "url": ensure_price.get("url"),
        "closed_tabs": ensure_price.get("closed_tabs") or [],
    }
    _log_step(
        "switch_price_confirm_after_confirm",
        {"status": "success" if ensure_price.get("ready") else "failed", **switch_after_confirm},
    )

    if not ensure_price.get("ready"):
        if session_err := _require_logged_in(page, account, account_id):
            return {**session_err, "steps": steps}
        return {
            "status": "failed",
            "step": "wait_price_confirm_page",
            "reason": ensure_price.get("reason") or "price_confirm_page_not_ready",
            "url": page.url,
            "steps": steps,
            "confirm_selection": confirm_selection,
            "ensure_price": ensure_price,
            "page_diagnosis": ensure_price.get("diagnosis") or _describe_campaign_page(page),
        }

    if session_err := _require_logged_in(page, account, account_id):
        return {**session_err, "steps": steps}

    if not _wait_price_confirm_content_ready(page, timeout=22):
        _pause_for_manual_review(page, account_id, reason="价格确认页内容未加载完成")
        return {
            "status": "failed",
            "step": "wait_price_confirm_content",
            "error": "价格确认页未加载完成（未看到活动价/确认提交）",
            "url": page.url,
            "steps": steps,
            "confirm_selection": confirm_selection,
            "page_diagnosis": _describe_campaign_page(page),
        }

    time.sleep(1.2)
    expand_result = _expand_price_confirm_specs(page, account_id)
    _log_step(
        "expand_price_specs",
        {
            "status": "success" if expand_result.get("expanded") else "failed",
            **expand_result,
        },
    )
    if not expand_result.get("expanded"):
        _pause_for_manual_review(page, account_id, reason="未能展开全部规格")
        return {
            "status": "failed",
            "step": "expand_price_specs",
            "error": expand_result.get("error") or expand_result.get("reason") or "未能点击展开全部规格",
            "expand_result": expand_result,
            "url": page.url,
            "steps": steps,
            "confirm_selection": confirm_selection,
            "page_diagnosis": _describe_campaign_page(page),
        }

    shop_wide_result = _uncheck_shop_wide_promotion(page, account_id)
    if not shop_wide_result.get("unchecked"):
        not_present = (
            shop_wide_result.get("reason") == "shop_wide_promotion_not_found"
            or not (shop_wide_result.get("before") or {}).get("found")
        )
        if not_present:
            shop_wide_result = {**shop_wide_result, "unchecked": True, "method": "skipped_not_present"}
    _log_step(
        "uncheck_shop_wide_promotion",
        {"status": "success" if shop_wide_result.get("unchecked") else "failed", **shop_wide_result},
    )
    if not shop_wide_result.get("unchecked"):
        _pause_for_manual_review(page, account_id, reason="未能取消全店报名勾选")
        return {
            "status": "failed",
            "step": "uncheck_shop_wide_promotion",
            "error": shop_wide_result.get("reason") or "未能取消全店报名勾选",
            "shop_wide_promotion": shop_wide_result,
            "expand_result": expand_result,
            "url": page.url,
            "steps": steps,
            "confirm_selection": confirm_selection,
            "page_diagnosis": _describe_campaign_page(page),
        }

    price_filter = filter_price_confirm_page(page, account_id, product_ids)
    _log_step(
        "filter_activity_prices",
        {
            "status": price_filter.get("status"),
            "action": price_filter.get("action"),
            "remove_count": price_filter.get("remove_count"),
            "remaining_count": price_filter.get("remaining_count"),
            "failed_count": price_filter.get("failed_count"),
            "spec_count": price_filter.get("spec_count"),
        },
    )
    if price_filter.get("status") == "all_products_removed":
        _pause_for_manual_review(page, account_id, reason="全部商品不符合价格条件")
        return {
            "status": "cancelled",
            "step": "filter_activity_prices",
            "error": price_filter.get("error") or "所有商品均不符合价格条件，已删除并关闭页面",
            "price_filter": price_filter,
            "confirm_selection": confirm_selection,
            "steps": steps,
            "current_url": page.url,
        }
    if price_filter.get("status") != "success":
        _pause_for_manual_review(
            page,
            account_id,
            reason=str(price_filter.get("error") or price_filter.get("reason") or "价格校验未通过"),
        )
        return {
            "status": "failed",
            "step": price_filter.get("step", "filter_activity_prices"),
            "error": price_filter.get("error") or price_filter.get("reason") or "价格确认页筛选失败",
            "price_filter": price_filter,
            "confirm_selection": confirm_selection,
            "steps": steps,
            "page_diagnosis": _describe_campaign_page(page),
        }

    switch_after_filter = _switch_to_price_confirm_tab(page, activity_id, account_id)
    _log_step(
        "switch_price_confirm_after_filter",
        {"status": "success" if switch_after_filter.get("switched") else "failed", **switch_after_filter},
    )
    if not switch_after_filter.get("switched"):
        return {
            "status": "failed",
            "step": "switch_price_confirm_after_filter",
            "error": "价格筛选后已离开价格确认页，无法继续取消流量保护",
            "price_filter": price_filter,
            "confirm_selection": confirm_selection,
            "steps": steps,
            "page_diagnosis": _describe_campaign_page(page),
        }

    if session_err := _require_logged_in(page, account, account_id):
        return {**session_err, "steps": steps}

    traffic_result = _uncheck_traffic_protection(page, account_id, activity_id)
    _log_step("uncheck_traffic_protection", {"status": "success" if traffic_result.get("unchecked") else "failed", **traffic_result})
    if not traffic_result.get("unchecked"):
        return {
            "status": "failed",
            "step": "uncheck_traffic_protection",
            "error": traffic_result.get("reason") or "未能取消开启流量保护",
            "price_filter": price_filter,
            "confirm_selection": confirm_selection,
            "steps": steps,
            "page_diagnosis": _describe_campaign_page(page),
            **traffic_result,
        }

    submit_result = _click_confirm_submit(page, account_id)
    _log_step("confirm_submit", {"status": "success" if submit_result.get("clicked") else "failed", **submit_result})
    if not submit_result.get("clicked"):
        return {"status": "failed", "step": "click_confirm_submit", "steps": steps, **submit_result}

    submit_verify = _verify_registration_submit(page, account_id)
    _log_step(
        "verify_submit",
        {"status": "success" if submit_verify.get("verified") else "failed", **submit_verify},
    )
    if not submit_verify.get("verified"):
        _pause_for_manual_review(page, account_id, reason="拼多多未确认报名成功")
        return {
            "status": "failed",
            "step": "verify_registration_submit",
            "error": submit_verify.get("reason") or "拼多多未确认报名成功，可能仍有不合格规格未处理",
            "price_filter": price_filter,
            "confirm_selection": confirm_selection,
            "confirm_submit": submit_result,
            "submit_verification": submit_verify,
            "steps": steps,
            "page_diagnosis": _describe_campaign_page(page),
        }

    return {
        "status": "success",
        "step": "register_submitted",
        "confirm_selection": confirm_selection,
        "price_filter": price_filter,
        "traffic_protection": traffic_result,
        "confirm_submit": submit_result,
        "submit_verification": submit_verify,
        "steps": steps,
        "current_url": page.url,
    }


def _is_multi_quick_product_page(page: DpPage) -> bool:
    if not _page_url_is_multi_quick(str(page.url or "")):
        return False
    text = _body_text(page)
    return any(
        marker in text
        for marker in ("潜力商品报名", "输入商品ID", "批量设置活动价", "确认报名")
    )


def _multi_quick_search_input_locator(page: DpPage):
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return None
    for selector in MULTI_QUICK_SEARCH_INPUT_SELECTORS:
        loc = raw_page.locator(selector).first
        try:
            if loc.count() and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _navigate_current_tab(page: DpPage, url: str) -> None:
    raw_page = getattr(page, "_page", None)
    if raw_page is not None and hasattr(raw_page, "goto"):
        raw_page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    else:
        page.get(url)


def _open_multi_quick_channel_in_current_tab(page: DpPage, account_id: str) -> dict[str, Any]:
    """在当前标签打开潜力商品报名页（20981 常只能走此通道）。"""
    try:
        _navigate_current_tab(page, MULTI_QUICK_CHANNEL_URL)
        time.sleep(2.5)
        _dismiss_message_popup(page)
        _dismiss_marketing_phone_popup(page, account_id)
        for _ in range(15):
            if _is_multi_quick_product_page(page):
                print(f"[{account_id}] 已进入潜力商品报名页: {page.url}", flush=True)
                return {"opened": True, "method": "current_tab_navigate", "url": page.url}
            time.sleep(1)
        return {
            "opened": False,
            "reason": "multi_quick_page_not_ready",
            "url": page.url,
        }
    except Exception as exc:
        return {"opened": False, "reason": _safe_exc(exc), "url": getattr(page, "url", "")}


def _fill_multi_quick_product_search(page: DpPage, product_ids: list[str]) -> dict[str, Any]:
    query = ",".join(product_ids)
    loc = _multi_quick_search_input_locator(page)
    if loc is None:
        return {"filled": False, "reason": "multi_quick_search_input_not_found", "expected": query}
    try:
        loc.scroll_into_view_if_needed(timeout=3_000)
        loc.click(timeout=3_000)
        loc.fill("", timeout=3_000)
        loc.fill(query, timeout=8_000)
        actual = str(loc.input_value(timeout=2_000) or "").strip()
        if actual == query:
            return {"filled": True, "value": actual, "method": "playwright_fill"}
    except Exception as exc:
        return {"filled": False, "reason": _safe_exc(exc), "expected": query}
    return {"filled": False, "reason": "multi_quick_search_value_mismatch", "expected": query}


def _click_page_query_button(page: DpPage) -> dict[str, Any]:
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return {"clicked": False, "reason": "page_unavailable"}
    selectors = (
        'button[data-testid="beast-core-button"]:has-text("查询")',
        'button:has-text("查询")',
    )
    for selector in selectors:
        try:
            btn = raw_page.locator(selector).filter(has_not=raw_page.locator('[data-testid="beast-core-modal"]')).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=5_000)
                return {"clicked": True, "text": "查询", "method": selector}
        except Exception:
            continue
    return {"clicked": False, "reason": "page_query_button_not_found"}


def _wait_multi_quick_products_loaded(page: DpPage, product_ids: list[str], timeout: int = 15) -> dict[str, Any]:
    missing: list[str] = list(product_ids)
    for _ in range(timeout):
        text = _body_text(page)
        missing = [item for item in product_ids if item not in text]
        if not missing:
            return {"loaded": True, "product_ids": product_ids}
        time.sleep(1)
    return {"loaded": False, "missing_product_ids": missing}


def _accept_multi_quick_agreement(page: DpPage) -> dict[str, Any]:
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return {"checked": False, "reason": "page_unavailable"}
    selectors = (
        'label:has-text("我已阅读并同意") input[type="checkbox"]',
        'input[type="checkbox"]',
    )
    for selector in selectors:
        try:
            boxes = raw_page.locator(selector)
            count = boxes.count()
            for index in range(count):
                box = boxes.nth(index)
                if not box.is_visible():
                    continue
                if not box.is_checked():
                    box.check(timeout=3_000)
                return {"checked": True, "method": selector}
        except Exception:
            continue
    return {"checked": False, "reason": "agreement_checkbox_not_found"}


def _click_multi_quick_confirm_register(page: DpPage, account_id: str) -> dict[str, Any]:
    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return {"clicked": False, "reason": "page_unavailable"}
    selectors = (
        'button[data-testid="beast-core-button"]:has-text("确认报名")',
        'button:has-text("确认报名")',
    )
    for selector in selectors:
        try:
            btn = raw_page.locator(selector).last
            if btn.count() and btn.is_visible():
                btn.scroll_into_view_if_needed(timeout=3_000)
                btn.click(timeout=8_000)
                print(f"[{account_id}] 已点击潜力商品页确认报名", flush=True)
                return {"clicked": True, "text": "确认报名", "method": selector}
        except Exception:
            continue
    return {"clicked": False, "reason": "confirm_register_button_not_found"}


def _select_products_in_multi_quick_channel(
    page: DpPage,
    account_id: str,
    activity_id: str,
    pdd_product_ids: list[str],
) -> dict[str, Any]:
    """潜力商品快捷通道：搜索商品 ID → 查询 → 勾选协议 → 确认报名。"""
    product_ids = list(dict.fromkeys(str(item).strip() for item in pdd_product_ids if str(item).strip()))
    if not product_ids:
        return {"status": "failed", "step": "validate_product_ids", "error": "pdd_product_ids 不能为空"}

    open_result = _open_multi_quick_channel_in_current_tab(page, account_id)
    if not open_result.get("opened"):
        return {"status": "failed", "step": "open_multi_quick_channel", **open_result}

    fill_result = _fill_multi_quick_product_search(page, product_ids)
    if not fill_result.get("filled"):
        return {"status": "failed", "step": "fill_multi_quick_search", **fill_result}

    query_result = _click_page_query_button(page)
    if not query_result.get("clicked"):
        return {"status": "failed", "step": "click_multi_quick_query", **query_result}

    time.sleep(2)
    load_result = _wait_multi_quick_products_loaded(page, product_ids, timeout=15)
    if not load_result.get("loaded"):
        return {"status": "failed", "step": "wait_multi_quick_products", **load_result}

    agreement_result = _accept_multi_quick_agreement(page)
    confirm_result = _click_multi_quick_confirm_register(page, account_id)
    if not confirm_result.get("clicked"):
        return {
            "status": "failed",
            "step": "click_multi_quick_confirm",
            "registration_path": "multi_quick_channel",
            "activity_id": activity_id,
            "open_result": open_result,
            "fill_result": fill_result,
            "query_result": query_result,
            "load_result": load_result,
            "agreement_result": agreement_result,
            **confirm_result,
        }

    time.sleep(2)
    print(
        f"[{account_id}] 潜力商品快捷通道报名完成: activity={activity_id} products={len(product_ids)}",
        flush=True,
    )
    return {
        "status": "success",
        "step": "multi_quick_products_confirmed",
        "registration_path": "multi_quick_channel",
        "activity_id": activity_id,
        "product_ids": product_ids,
        "open_result": open_result,
        "fill_result": fill_result,
        "query_result": query_result,
        "load_result": load_result,
        "agreement_result": agreement_result,
        "confirm_result": confirm_result,
    }


def _select_products_in_search_modal(
    page: DpPage,
    account_id: str,
    pdd_product_ids: list[str],
    activity_id: str = "",
) -> dict[str, Any]:
    """在搜索商品弹窗里输入商品 ID、查询并确认。"""
    product_ids = list(dict.fromkeys(str(item).strip() for item in pdd_product_ids if str(item).strip()))
    if not product_ids:
        return {"status": "failed", "step": "validate_product_ids", "error": "pdd_product_ids 不能为空"}

    _dismiss_wrong_tabs_and_focus_product_pick(page, activity_id or "", account_id)
    _close_product_search_modal_if_open(page)

    open_result = _open_product_search_modal(page, account_id)
    if not open_result.get("opened"):
        return {"status": "failed", "step": "open_product_search_modal", **open_result}

    modal = _product_search_modal_locator(page)
    if modal is None:
        _dismiss_wrong_tabs_and_focus_product_pick(page, activity_id or "", account_id)
        modal = _product_search_modal_locator(page)
    if modal is None:
        return {"status": "failed", "step": "find_product_search_modal", "error": "搜索商品弹窗未找到"}

    fill_result = _fill_product_search_modal_input(modal, product_ids)
    if not fill_result.get("filled"):
        return {"status": "failed", "step": "fill_modal_search_input", **fill_result}

    _dismiss_wrong_tabs_and_focus_product_pick(page, activity_id or "", account_id)
    modal = _product_search_modal_locator(page)
    if modal is None:
        return {"status": "failed", "step": "find_product_search_modal", "error": "关闭误开标签后未找到搜索商品弹窗"}

    query_result = _trigger_modal_product_search(modal, product_ids)
    if not query_result.get("clicked"):
        return {"status": "failed", "step": "click_modal_query", **query_result}

    time.sleep(1.2)
    modal = _product_search_modal_locator(page)
    if modal is None:
        return {"status": "failed", "step": "find_product_search_modal", "error": "查询后搜索商品弹窗消失"}

    eligibility = _analyze_modal_product_eligibility(modal, product_ids)
    failure = _format_modal_eligibility_failure(eligibility, product_ids)
    if failure:
        _click_modal_cancel_button(modal)
        return failure

    eligible_ids = list(eligibility.get("eligible_ids") or product_ids)
    if not eligible_ids:
        _click_modal_cancel_button(modal)
        return {
            "status": "failed",
            "step": "product_not_eligible_for_activity",
            "error": "未找到可报名商品，已取消操作",
            "eligibility": eligibility,
        }

    load_result = _wait_modal_products_loaded(modal, eligible_ids, timeout=15)
    if not load_result.get("loaded"):
        eligibility = _analyze_modal_product_eligibility(modal, product_ids)
        failure = _format_modal_eligibility_failure(eligibility, product_ids)
        if failure:
            _click_modal_cancel_button(modal)
            return failure
        return {"status": "failed", "step": "wait_modal_products", **load_result}

    select_all_result = _ensure_modal_products_selected(modal, eligible_ids)
    if not select_all_result.get("checked"):
        return {"status": "failed", "step": "click_modal_select_all", **select_all_result}

    confirm_result = _click_modal_confirm_button(modal)
    if not confirm_result.get("clicked"):
        return {
            "status": "failed",
            "step": "click_modal_confirm",
            "select_all_result": select_all_result,
            **confirm_result,
        }

    time.sleep(1.5)
    print(f"[{account_id}] 已在搜索商品弹窗确认选择 {len(eligible_ids)} 个商品", flush=True)
    return {
        "status": "success",
        "step": "modal_products_confirmed",
        "product_ids": eligible_ids,
        "requested_product_ids": product_ids,
        "eligibility": eligibility,
        "open_result": open_result,
        "fill_result": fill_result,
        "query_result": query_result,
        "load_result": load_result,
        "select_all_result": select_all_result,
        "confirm_result": confirm_result,
    }


def register_marketing_activity(
    page: DpPage,
    account_id: str,
    activity_id: str,
    pdd_product_ids: list[str] | None = None,
    account: AccountConfig | None = None,
) -> dict[str, Any]:
    """搜索活动 → 活动详情/潜力商品通道 → 选品并确认报名。"""
    activity_id = str(activity_id or "").strip()
    product_ids = list(dict.fromkeys(str(item).strip() for item in (pdd_product_ids or []) if str(item).strip()))
    if not activity_id:
        return _fail("validate_activity_id", "activity_id 不能为空", activity_id=activity_id)
    if not product_ids:
        return _fail("validate_product_ids", "请先选择已发布商品", activity_id=activity_id)

    if session_err := _require_logged_in(page, account, account_id):
        return {**session_err, "activity_id": activity_id}

    def _finish_multi_quick_fallback(standard_attempt: dict[str, Any] | None = None) -> dict[str, Any]:
        multi_result = _select_products_in_multi_quick_channel(page, account_id, activity_id, product_ids)
        if multi_result.get("status") == "success":
            return {
                **multi_result,
                "step": "register_completed",
                "current_url": page.url,
                "search_result": search_result,
                "standard_attempt": standard_attempt,
            }
        return _fail(
            multi_result.get("step", "multi_quick_fallback"),
            multi_result.get("error") or "标准流程与潜力商品快捷通道均未能完成报名",
            activity_id=activity_id,
            current_url=page.url,
            search_result=search_result,
            standard_attempt=standard_attempt,
            multi_quick_attempt=multi_result,
        )

    profile = _get_activity_profile(activity_id)
    entry = str(profile.get("entry") or "goto_detail")
    stop_after = str(profile.get("stop_after") or "submit")

    try:
        _install_multi_quick_tab_blocker(page, account_id)
        search_result = search_marketing_activity(page, account_id, activity_id, account=account)
        if search_result.get("status") != "success":
            return search_result

        _close_multi_quick_channel_tabs(page, account_id)

        open_detail = _open_activity_for_registration(
            page, activity_id, account_id, entry=entry
        )
        if not open_detail.get("opened"):
            return _finish_multi_quick_fallback(
                {"step": "open_activity_detail", "open_detail": open_detail},
            )

        if entry != "go_register":
            time.sleep(0.5)
            tab_result = _switch_to_registration_tab(page, activity_id, account_id)
        else:
            tab_result = {"switched": False, "method": "modal_already_open"}
        _dismiss_message_popup(page)
        _dismiss_marketing_phone_popup(page, account_id)

        if wrong := _reject_multi_quick_channel(
            page, account_id, "after_open_detail", activity_id=activity_id
        ):
            return _finish_multi_quick_fallback({**wrong, "open_detail": open_detail, "tab_result": tab_result})

        detail_ready = _is_activity_detail_ready(page, activity_id, require_activity_id=False)
        if not detail_ready and not _wait_page_contains(
            page, ("立即报名", "活动详情"), timeout=5
        ):
            if wrong := _reject_multi_quick_channel(
                page, account_id, "wait_activity_detail_wrong_page", activity_id=activity_id
            ):
                return _finish_multi_quick_fallback(
                    {**wrong, "open_detail": open_detail, "tab_result": tab_result},
                )
            return _finish_multi_quick_fallback(
                {
                    "step": "wait_activity_detail",
                    "error": "未进入活动详情页",
                    "open_detail": open_detail,
                    "tab_result": tab_result,
                },
            )

        register_now = _click_register_now(page, account_id, activity_id)
        if register_now.get("status") == "failed":
            return _finish_multi_quick_fallback(
                {"step": "click_register_now", "register_now": register_now, "open_detail": open_detail},
            )
        if not register_now.get("clicked"):
            return _finish_multi_quick_fallback(
                {
                    "step": "click_register_now",
                    "error": "未找到或无法点击立即报名",
                    "register_now": register_now,
                    "open_detail": open_detail,
                },
            )

        time.sleep(2)
        _dismiss_wrong_tabs_and_focus_product_pick(page, activity_id, account_id)
        _dismiss_message_popup(page)

        if wrong := _reject_multi_quick_channel(
            page, account_id, "after_register_now", activity_id=activity_id
        ):
            return _finish_multi_quick_fallback(
                {**wrong, "open_detail": open_detail, "register_now": register_now},
            )

        if not _wait_page_contains(page, ("选择活动商品", "选择商品", "确认选择"), timeout=18):
            if wrong := _reject_multi_quick_channel(
                page, account_id, "wait_product_pick_wrong_page", activity_id=activity_id
            ):
                return _finish_multi_quick_fallback(
                    {**wrong, "open_detail": open_detail, "register_now": register_now},
                )
            return _finish_multi_quick_fallback(
                {
                    "step": "wait_product_pick_page",
                    "error": "未进入选择活动商品页",
                    "open_detail": open_detail,
                    "register_now": register_now,
                },
            )

        product_selection = _select_products_in_search_modal(
            page, account_id, product_ids, activity_id=activity_id
        )
        if product_selection.get("status") != "success":
            step = str(product_selection.get("step") or "")
            if step not in {
                "product_time_requirement_not_met",
                "product_not_eligible_for_activity",
            }:
                _dismiss_wrong_tabs_and_focus_product_pick(page, activity_id, account_id)
                time.sleep(1.5)
                product_selection = _select_products_in_search_modal(
                    page, account_id, product_ids, activity_id=activity_id
                )
        if product_selection.get("status") != "success":
            return _fail(
                product_selection.get("step", "standard_product_selection"),
                product_selection.get("error") or "搜索商品弹窗选品失败（已关闭误开的潜力商品标签）",
                activity_id=activity_id,
                current_url=page.url,
                search_result=search_result,
                open_detail=open_detail,
                register_now=register_now,
                product_selection=product_selection,
            )

        if stop_after in {"confirm_selection", "price_page_prepared"}:
            pick_confirm_result = _complete_product_pick_confirmation(page, account_id, activity_id)
            if pick_confirm_result.get("status") != "success":
                return _fail(
                    pick_confirm_result.get("step", "click_confirm_selection"),
                    pick_confirm_result.get("error") or "确认选择失败",
                    activity_id=activity_id,
                    current_url=page.url,
                    search_result=search_result,
                    open_detail=open_detail,
                    register_now=register_now,
                    product_selection=product_selection,
                    pick_confirm_result=pick_confirm_result,
                )

            if stop_after == "confirm_selection":
                print(
                    f"[{account_id}] 营销活动选品完成（至确认选择）: activity={activity_id} products={len(product_ids)}",
                    flush=True,
                )
                return {
                    "status": "success",
                    "step": "product_pick_confirmed",
                    "registration_path": "standard",
                    "activity_id": activity_id,
                    "product_ids": product_ids,
                    "activity_profile": profile,
                    "current_url": page.url,
                    "search_result": search_result,
                    "open_detail": open_detail,
                    "register_now": register_now,
                    "product_selection": product_selection,
                    "pick_confirm_result": pick_confirm_result,
                }

            price_prep = _prepare_price_confirm_page(page, account_id, activity_id)
            if price_prep.get("status") != "success":
                return _fail(
                    price_prep.get("step", "prepare_price_confirm_page"),
                    price_prep.get("error") or price_prep.get("reason") or "价格确认页处理失败",
                    activity_id=activity_id,
                    current_url=page.url,
                    search_result=search_result,
                    open_detail=open_detail,
                    register_now=register_now,
                    product_selection=product_selection,
                    pick_confirm_result=pick_confirm_result,
                    price_prep=price_prep,
                )

            print(
                f"[{account_id}] 营销活动价格确认页已处理: activity={activity_id} products={len(product_ids)}",
                flush=True,
            )
            spec_lookup = lookup_spec_codes_on_price_page(page, account_id, product_ids)
            print(
                f"[{account_id}] 活动规格反查: matched={spec_lookup.get('matched_count')}/{spec_lookup.get('spec_count')}",
                flush=True,
            )
            return {
                "status": "success",
                "step": "price_page_prepared",
                "registration_path": "standard",
                "activity_id": activity_id,
                "product_ids": product_ids,
                "activity_profile": profile,
                "current_url": page.url,
                "search_result": search_result,
                "open_detail": open_detail,
                "register_now": register_now,
                "product_selection": product_selection,
                "pick_confirm_result": pick_confirm_result,
                "price_prep": price_prep,
                "spec_lookup": spec_lookup,
            }

        finalize_result = _finalize_standard_registration(
            page, account_id, activity_id, pdd_product_ids=product_ids, account=account
        )
        if finalize_result.get("status") == "cancelled":
            return {
                "status": "cancelled",
                "step": finalize_result.get("step", "filter_activity_prices"),
                "registration_path": "standard",
                "activity_id": activity_id,
                "product_ids": product_ids,
                "current_url": page.url,
                "error": finalize_result.get("error") or "无符合价格条件的商品，已关闭价格确认页",
                "message": finalize_result.get("error") or "无符合价格条件的商品，已关闭价格确认页",
                "search_result": search_result,
                "open_detail": open_detail,
                "register_now": register_now,
                "product_selection": product_selection,
                "finalize_result": finalize_result,
            }
        if finalize_result.get("status") != "success":
            return _fail(
                finalize_result.get("step", "finalize_standard_registration"),
                finalize_result.get("error") or "确认选择与价格确认页处理失败",
                activity_id=activity_id,
                current_url=page.url,
                search_result=search_result,
                open_detail=open_detail,
                register_now=register_now,
                product_selection=product_selection,
                finalize_result=finalize_result,
                price_filter=finalize_result.get("price_filter"),
            )

        print(
            f"[{account_id}] 营销活动报名选品完成: activity={activity_id} products={len(product_ids)}",
            flush=True,
        )
        return {
            "status": "success",
            "step": "register_completed",
            "registration_path": "standard",
            "activity_id": activity_id,
            "product_ids": product_ids,
            "activity_profile": profile,
            "current_url": page.url,
            "search_result": search_result,
            "open_detail": open_detail,
            "register_now": register_now,
            "product_selection": product_selection,
            "finalize_result": finalize_result,
        }
    except Exception as exc:
        return _fail(
            "register_marketing_activity",
            _safe_exc(exc),
            activity_id=activity_id,
            current_url=getattr(page, "url", ""),
        )
