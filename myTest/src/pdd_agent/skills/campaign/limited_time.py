"""限时限量购活动初始化页面操作。"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.db.repositories import get_published_products_by_mapping_ids
from pdd_agent.skills.campaign.price_rules import (
    find_pdd_price_range,
    load_pdd_price_ranges,
    price_rule_candidates,
)

MARKETING_TOOL_URLS = (
    "https://mms.pinduoduo.com/marketing/tools",
    "https://mms.pinduoduo.com/marketing/marketing-tools",
    "https://mms.pinduoduo.com/marketing/marketing_tool",
)
LIMITED_TIME_TOOL_URLS = (
    "https://mms.pinduoduo.com/tool/promotion?tool_full_channel=10921_77271",
)
ACTIVITY_CREATE_URL_PARTS = ("/tool/promotion/create",)
PRODUCT_SEARCH_BATCH_SIZE = 30
MAX_CAMPAIGN_PRODUCTS = 40


def _safe_exc(exc: BaseException, limit: int = 300) -> str:
    msg = str(exc)
    if len(msg) > limit:
        msg = msg[:limit] + "..."
    return msg.encode("utf-8", errors="replace").decode("utf-8")


def _bind_page(page: DpPage, next_page: Any) -> bool:
    try:
        setattr(page, "_page", next_page)
        if hasattr(page, "wait"):
            setattr(page.wait, "_page", next_page)
        return True
    except Exception:
        return False


def _page_matches(raw_page: Any, preferred_url_parts: tuple[str, ...]) -> bool:
    if raw_page is None:
        return False
    if not preferred_url_parts:
        return True
    try:
        url = str(getattr(raw_page, "url", "") or "")
    except Exception:
        return False
    return any(part in url for part in preferred_url_parts)


def _live_context_pages(page: DpPage) -> list[Any]:
    try:
        raw_page = getattr(page, "_page", None)
        context = getattr(raw_page, "context", None)
        if context is None:
            return []
        return [item for item in list(context.pages) if not item.is_closed()]
    except Exception:
        return []


def _ensure_page_binding(
    page: DpPage,
    *,
    preferred_url_parts: tuple[str, ...] = (),
    timeout: int = 0,
) -> bool:
    deadline = time.time() + max(0, timeout)
    while True:
        raw_page = getattr(page, "_page", None)
        try:
            if raw_page is not None and not raw_page.is_closed() and _page_matches(raw_page, preferred_url_parts):
                return True
        except Exception:
            pass

        pages = _live_context_pages(page)
        if pages:
            matching_pages = [item for item in pages if _page_matches(item, preferred_url_parts)]
            candidates = matching_pages or pages
            target = candidates[-1]
            if _bind_page(page, target):
                try:
                    target.bring_to_front()
                except Exception:
                    pass
                try:
                    target.wait_for_load_state("domcontentloaded", timeout=5_000)
                except Exception:
                    pass
                if _page_matches(target, preferred_url_parts):
                    time.sleep(1)
                    return True

        if time.time() >= deadline:
            return False
        time.sleep(1)


def _body_text(page: DpPage) -> str:
    if not _ensure_page_binding(page):
        return ""
    try:
        return str(page.run_js("return document.body?.innerText || '';") or "")
    except Exception:
        return ""


def _switch_to_latest_tab(page: DpPage) -> bool:
    """拼多多工具入口会新开标签页；切到最新标签页继续操作。"""
    try:
        raw_page = getattr(page, "_page")
        pages = _live_context_pages(page)
        if not pages:
            return False
        latest = pages[-1]
        if latest == raw_page:
            return False
        latest.bring_to_front()
        _bind_page(page, latest)
        time.sleep(1)
        return True
    except Exception:
        return False


def _click_text(page: DpPage, text: str, timeout: float = 3) -> bool:
    ele = page.ele(f"text:{text}", timeout=timeout)
    if not ele:
        return False
    ele.click(by_js=True)
    time.sleep(1)
    return True


def _dismiss_message_popup(page: DpPage) -> None:
    """关闭右侧消息浮层，避免遮挡或抢焦点。"""
    try:
        page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            const roots = Array.from(document.querySelectorAll('div,section'))
                .filter((el) => isVisible(el))
                .filter((el) => {
                    const text = (el.innerText || el.textContent || '').trim();
                    return text.includes('新消息') && text.includes('查看全部');
                });
            if (!roots.length) return false;
            const root = roots
                .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                .sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height))[0].el;
            const rr = root.getBoundingClientRect();
            const candidates = Array.from(root.querySelectorAll('button,span,div,i,svg'))
                .filter((el) => isVisible(el))
                .map((el) => ({ el, rect: el.getBoundingClientRect(), text: (el.innerText || el.textContent || '').trim() }))
                .filter((x) => x.text === '×' || x.text === '✕' || (x.rect.top < rr.top + 55 && x.rect.left > rr.right - 90))
                .sort((a, b) => b.rect.left - a.rect.left);
            if (!candidates.length) return false;
            candidates[0].el.click();
            return true;
            """
        )
        time.sleep(0.5)
    except Exception:
        pass


def _open_marketing_tools(page: DpPage, account_id: str) -> bool:
    """进入后台左侧「营销工具」页面。"""
    for url in MARKETING_TOOL_URLS:
        try:
            page.get(url)
            time.sleep(3)
            if "login" in page.url:
                return False
            text = _body_text(page)
            if "营销工具" in text and "限时限量购" in text:
                return True
        except Exception:
            continue

    print(f"[{account_id}] 直接打开营销工具失败，尝试从菜单点击", flush=True)
    try:
        page.get("https://mms.pinduoduo.com/home/")
        time.sleep(2)
        if _click_text(page, "营销工具", timeout=5):
            time.sleep(3)
            text = _body_text(page)
            return "营销工具" in text and "限时限量购" in text
    except Exception:
        return False
    return False


def _is_limited_time_page(page: DpPage) -> bool:
    """确认已经进入限时限量购工具页，而不是营销工具总览页。"""
    if "/tool/promotion" in page.url and "tool_full_channel=10921_77271" in page.url:
        return True
    text = _body_text(page)
    if "限时限量购" not in text:
        return False
    return "立即创建" in text or "活动商品" in text or "创建限时限量购" in text


def _wait_limited_time_page(page: DpPage, timeout: int = 10) -> bool:
    for _ in range(timeout):
        if _is_limited_time_page(page):
            return True
        time.sleep(1)
    return False


def _open_limited_time_tool(page: DpPage, account_id: str) -> bool:
    """在营销工具页点击「限时限量购」。"""
    if _is_limited_time_page(page):
        return True

    for url in LIMITED_TIME_TOOL_URLS:
        try:
            page.get(url)
            time.sleep(3)
            if "login" in page.url:
                return False
            if _is_limited_time_page(page):
                print(f"[{account_id}] 已通过固定入口进入限时限量购", flush=True)
                return True
        except Exception as exc:
            print(f"[{account_id}] 固定入口打开限时限量购异常：{_safe_exc(exc)}", flush=True)

    try:
        result = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }

            function isInMarketingData(el) {
                let cur = el;
                for (let i = 0; i < 8 && cur && cur !== document.body; i++, cur = cur.parentElement) {
                    const text = (cur.innerText || cur.textContent || '').replace(/\\s+/g, '');
                    if (
                        text.includes('营销数据')
                        || text.includes('统计时间')
                        || text.includes('生效中的券')
                        || text.includes('已失效的券')
                        || text.includes('领取量')
                    ) {
                        return true;
                    }
                }
                return false;
            }

            function cardRoot(el) {
                let cur = el;
                let best = null;
                for (let i = 0; i < 8 && cur && cur !== document.body; i++) {
                    const text = (cur.innerText || cur.textContent || '').trim();
                    const r = cur.getBoundingClientRect();
                    if (
                        text.includes('限时限量购')
                        && r.width >= 160
                        && r.height >= 70
                        && r.left < window.innerWidth * 0.78
                        && !isInMarketingData(cur)
                    ) {
                        best = cur;
                    }
                    cur = cur.parentElement;
                }
                return best || el;
            }

            function clickableTarget(card) {
                const link = card.closest?.('a[href]') || card.querySelector?.('a[href]');
                if (link) return link;
                const button = card.closest?.('button') || card.querySelector?.('button');
                if (button) return button;
                let cur = card;
                for (let i = 0; i < 6 && cur && cur !== document.body; i++, cur = cur.parentElement) {
                    const role = cur.getAttribute?.('role') || '';
                    const cursor = window.getComputedStyle(cur).cursor;
                    if (role === 'button' || cursor === 'pointer') return cur;
                }
                return card;
            }

            function clickLikeUser(el) {
                const r = el.getBoundingClientRect();
                const x = r.left + Math.min(Math.max(20, r.width / 2), Math.max(20, r.width - 20));
                const y = r.top + Math.min(Math.max(20, r.height / 2), Math.max(20, r.height - 20));
                const target = document.elementFromPoint(x, y) || el;
                for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    target.dispatchEvent(new MouseEvent(ev, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y,
                    }));
                }
                if (target !== el) el.click();
            }

            const nodes = Array.from(document.querySelectorAll('a,button,div,span'));
            const candidates = [];
            for (const el of nodes) {
                if (!isVisible(el)) continue;
                const text = (el.innerText || el.textContent || '').trim();
                if (!text.includes('限时限量购')) continue;
                if (isInMarketingData(el)) continue;
                const root = cardRoot(el);
                const rect = root.getBoundingClientRect();
                if (rect.width < 160 || rect.height < 70) continue;
                const rootText = (root.innerText || root.textContent || '').trim();
                let score = rect.top * 10 + rect.left;
                if (rootText.includes('商品优势价促销')) score -= 100000;
                if (rootText.includes('爆款商品必备')) score -= 50000;
                if (rootText.includes('查看教程')) score -= 10000;
                candidates.push({ el: clickableTarget(root), root, score, text: rootText });
            }
            candidates.sort((a, b) => a.score - b.score);
            if (!candidates.length) return { clicked: false, reason: 'card_not_found' };
            const selected = candidates[0];
            const href = selected.el.href || selected.el.getAttribute?.('href') || '';
            if (href) {
                selected.el.click();
            } else {
                clickLikeUser(selected.el);
            }
            return {
                clicked: true,
                href,
                text: selected.text.slice(0, 120),
                rect: {
                    left: Math.round(selected.root.getBoundingClientRect().left),
                    top: Math.round(selected.root.getBoundingClientRect().top),
                    width: Math.round(selected.root.getBoundingClientRect().width),
                    height: Math.round(selected.root.getBoundingClientRect().height),
                },
            };
            """
        )
        if isinstance(result, dict) and result.get("clicked"):
            print(f"[{account_id}] 已点击限时限量购卡片：{result}", flush=True)
            if _switch_to_latest_tab(page):
                print(f"[{account_id}] 检测到新标签页，已切换到最新标签", flush=True)
            if _wait_limited_time_page(page, timeout=12):
                print(f"[{account_id}] 已进入限时限量购", flush=True)
                return True
            print(f"[{account_id}] 点击后未进入限时限量购页，继续兜底尝试", flush=True)
        else:
            print(f"[{account_id}] 未定位到限时限量购卡片：{result}", flush=True)
    except Exception as exc:
        print(f"[{account_id}] 点击限时限量购异常：{_safe_exc(exc)}", flush=True)

    if _click_text(page, "限时限量购", timeout=3):
        _switch_to_latest_tab(page)
        if _wait_limited_time_page(page, timeout=8):
            return True
    return False


def _click_create(page: DpPage, account_id: str) -> bool:
    """点击限时限量购页的「立即创建」。"""
    _dismiss_message_popup(page)

    for attempt in range(1, 4):
        try:
            raw_page = getattr(page, "_page")
            locator = raw_page.locator(
                'button[data-tracking-click-viewid="ele-create"]:has-text("立即创建"), '
                'button[data-testid="beast-core-button"]:has-text("立即创建"), '
                'button:has-text("立即创建")'
            ).first
            try:
                locator.wait_for(state="visible", timeout=5_000)
            except Exception:
                pass

            target = locator.evaluate(
                """
                (node) => {
                    const r = node.getBoundingClientRect();
                    return {
                        href: node.href || node.getAttribute?.('href') || '',
                        disabled: Boolean(node.disabled)
                            || node.getAttribute?.('aria-disabled') === 'true'
                            || String(node.className || '').includes('disabled'),
                        rect: {
                            left: r.left,
                            top: r.top,
                            width: r.width,
                            height: r.height,
                            cx: r.left + r.width / 2,
                            cy: r.top + r.height / 2,
                        },
                        html: (node.outerHTML || '').slice(0, 260),
                    };
                }
                """,
                timeout=5_000,
            )
            if not isinstance(target, dict):
                print(f"[{account_id}] 未找到立即创建按钮 (第{attempt}次)", flush=True)
                time.sleep(1)
                continue

            print(
                f"[{account_id}] 准备点击立即创建 (第{attempt}次)："
                f"rect={target.get('rect')} href={target.get('href')}",
                flush=True,
            )
            href = str(target.get("href") or "")
            if href and not href.startswith("javascript"):
                raw_page.goto(href, wait_until="domcontentloaded")
            else:
                try:
                    locator.click(timeout=5_000, force=True)
                except Exception as click_exc:
                    print(
                        f"[{account_id}] Playwright 点击立即创建失败，改用坐标兜底："
                        f"{_safe_exc(click_exc)}",
                        flush=True,
                    )
                    rect = target.get("rect") or {}
                    x = float(rect.get("cx") or 0)
                    y = float(rect.get("cy") or 0)
                    if x <= 0 or y <= 0:
                        time.sleep(1)
                        continue
                    raw_page.mouse.move(x, y)
                    time.sleep(0.2)
                    raw_page.mouse.down()
                    time.sleep(0.1)
                    raw_page.mouse.up()

            time.sleep(2)
            _switch_to_latest_tab(page)
            try:
                getattr(page, "_page").wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            if _wait_activity_settings(page, account_id, timeout=8):
                print(f"[{account_id}] 已点击立即创建并进入活动设置页", flush=True)
                return True
            print(
                f"[{account_id}] 点击立即创建后仍未进入活动设置页，当前 URL：{page.url}",
                flush=True,
            )
        except Exception as exc:
            print(f"[{account_id}] 点击立即创建异常 (第{attempt}次)：{_safe_exc(exc)}", flush=True)
        time.sleep(1)

    return False


def _wait_activity_settings(page: DpPage, account_id: str, timeout: int = 20) -> bool:
    for _ in range(timeout):
        text = _body_text(page)
        if "活动设置" in text and (
            "活动类型" in text or "活动名称" in text or "选择商品" in text or "自动创建" in text
        ):
            return True
        time.sleep(1)
    print(f"[{account_id}] 未确认进入活动设置页", flush=True)
    return False


def _chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _modal_match_condition_js(var_name: str = "el") -> str:
    return f"""
        (() => {{
            const text = {var_name}.innerText || '';
            const hasProductInput = Array.from({var_name}.querySelectorAll('input'))
                .some((input) => ((input.getAttribute('placeholder') || '').includes('商品ID')));
            const hasConfirm = Array.from({var_name}.querySelectorAll('button,[role="button"],span,div'))
                .some((node) => ((node.innerText || node.textContent || '').trim()) === '确认选择');
            return text.includes('选择商品') || (hasProductInput && hasConfirm);
        }})()
    """


def _wait_product_modal(page: DpPage, timeout: int = 10) -> bool:
    for _ in range(timeout):
        try:
            visible = page.run_js(
                """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 80 && r.height > 80
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                return Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                    .some((el) => isVisible(el) && (
                """
                + _modal_match_condition_js("el")
                + """
                    ));
                """
            )
            if visible:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _open_product_modal(page: DpPage, account_id: str) -> dict[str, Any]:
    try:
        result = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function clickLikeUser(el) {
                el.scrollIntoView({ block: 'center', inline: 'nearest' });
                const r = el.getBoundingClientRect();
                const x = r.left + r.width / 2;
                const y = r.top + r.height / 2;
                const target = document.elementFromPoint(x, y) || el;
                for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    target.dispatchEvent(new MouseEvent(ev, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y,
                    }));
                }
                if (target !== el) el.click();
            }
            const buttons = Array.from(document.querySelectorAll('button,a,[role="button"],span,div'))
                .filter((el) => isVisible(el))
                .filter((el) => {
                    const text = (el.innerText || el.textContent || '').trim();
                    const viewid = el.getAttribute?.('data-tracking-viewid') || '';
                    const clickViewid = el.getAttribute?.('data-tracking-click-viewid') || '';
                    return viewid === 'l_event_merchandise'
                        || clickViewid === 'l_event_merchandise'
                        || text === '+ 选择商品'
                        || text === '选择商品';
                })
                .map((el) => {
                    let target = el.closest?.('button,a,[role="button"]') || el;
                    const button = el.querySelector?.('button');
                    if (button) target = button;
                    const r = target.getBoundingClientRect();
                    return { target, text: (target.innerText || target.textContent || '').trim(), rect: r };
                })
                .filter((item) => item.rect.width > 20 && item.rect.height > 10)
                .sort((a, b) => {
                    const scoreA = (a.text.includes('选择商品') ? 0 : 10000) + a.rect.top * 10 + a.rect.left;
                    const scoreB = (b.text.includes('选择商品') ? 0 : 10000) + b.rect.top * 10 + b.rect.left;
                    return scoreA - scoreB;
                });
            if (!buttons.length) return { clicked: false, reason: 'button_not_found' };
            const selected = buttons[0];
            clickLikeUser(selected.target);
            return {
                clicked: true,
                text: selected.text,
                rect: {
                    left: Math.round(selected.rect.left),
                    top: Math.round(selected.rect.top),
                    width: Math.round(selected.rect.width),
                    height: Math.round(selected.rect.height),
                },
            };
            """
        )
    except Exception as exc:
        return {"clicked": False, "reason": _safe_exc(exc)}

    if isinstance(result, dict):
        print(f"[{account_id}] 点击选择商品结果：{result}", flush=True)
        return result
    return {"clicked": False, "reason": str(result)}


def _search_product_ids_in_modal(page: DpPage, account_id: str, product_ids: list[str]) -> dict[str, Any]:
    query = " ".join(product_ids)
    try:
        result = page.run_js(
            """
                const query = arguments[0];
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function modalRoot() {
                    const roots = Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                        .filter((el) => isVisible(el))
                        .filter((el) => (
            """
            + _modal_match_condition_js("el")
            + """
                        ));
                    return roots[roots.length - 1] || null;
                }
                function setInputValue(input, value) {
                    input.focus();
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                    if (setter) {
                        setter.call(input, '');
                    } else {
                        input.value = '';
                    }
                    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
                    if (setter) {
                        setter.call(input, value);
                    } else {
                        input.value = value;
                    }
                    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
                    input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
                    input.blur();
                }
                function clickLikeUser(el) {
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                function clickQueryButton(el) {
                    clickLikeUser(el);
                    if (el.isConnected) el.click();
                    const suffix = el.closest?.('[class*="suffix"], [class*="Suffix"], [data-testid*="suffix"]');
                    if (suffix && suffix !== el) {
                        clickLikeUser(suffix);
                        if (suffix.isConnected) suffix.click();
                    }
                }
                const root = modalRoot();
                if (!root) return { searched: false, reason: 'modal_not_found' };
                const input = Array.from(root.querySelectorAll('input'))
                    .filter((el) => isVisible(el))
                    .find((el) => {
                        const placeholder = el.getAttribute('placeholder') || '';
                        return placeholder.includes('商品ID') || placeholder.includes('商品');
                    });
                if (!input) return { searched: false, reason: 'input_not_found' };
                setInputValue(input, query);
                const buttons = Array.from(root.querySelectorAll('button,[role="button"],span,div'))
                    .filter((el) => isVisible(el))
                    .filter((el) => ((el.innerText || el.textContent || '').trim()) === '查询')
                    .map((el) => el.closest?.('button,[role="button"]') || el);
                if (!buttons.length) return { searched: false, reason: 'query_button_not_found' };
                clickQueryButton(buttons[0]);
                return { searched: true, query, input_value: input.value };
            """,
            query,
        )
    except Exception as exc:
        return {"searched": False, "reason": _safe_exc(exc), "query": query}

    if isinstance(result, dict):
        print(f"[{account_id}] 商品弹窗查询：{result}", flush=True)
        return result
    return {"searched": False, "reason": str(result), "query": query}


def _fallback_search_product_ids_in_modal(
    page: DpPage,
    account_id: str,
    product_ids: list[str],
) -> dict[str, Any]:
    query = " ".join(product_ids)
    try:
        raw_page = getattr(page, "_page")
        modal = raw_page.locator(
            '[data-testid="beast-core-modal"]:has-text("选择商品"), [class*="MDL_modal"]:has-text("选择商品")'
        ).last
        input_locator = modal.locator(
            'input[placeholder*="商品ID"], input[placeholder*="商品"]'
        ).first
        input_locator.wait_for(state="visible", timeout=5_000)
        input_locator.click(timeout=3_000, force=True)
        input_locator.fill(query, timeout=5_000)
        try:
            input_locator.press("Enter", timeout=1_000)
        except Exception:
            pass

        query_button = modal.locator(
            'button:has-text("查询"), [role="button"]:has-text("查询"), '
            '[class*="suffix"]:has-text("查询"), [class*="Suffix"]:has-text("查询"), '
            'span:has-text("查询"), div:has-text("查询")'
        ).last
        try:
            query_button.wait_for(state="visible", timeout=3_000)
            query_button.click(timeout=3_000, force=True)
        except Exception:
            box = query_button.bounding_box(timeout=1_000)
            if box:
                raw_page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            else:
                raise
        result = {"searched": True, "query": query, "method": "playwright_fallback"}
    except Exception as exc:
        result = {"searched": False, "reason": _safe_exc(exc), "query": query, "method": "playwright_fallback"}
    print(f"[{account_id}] 商品弹窗查询兜底：{result}", flush=True)
    return result


def _wait_modal_table_after_search(page: DpPage, product_ids: list[str], timeout: int = 12) -> dict[str, Any]:
    for _ in range(timeout):
        try:
            result = page.run_js(
                """
                    const ids = arguments[0];
                    function isVisible(el) {
                        if (!el || !el.getBoundingClientRect) return false;
                        const r = el.getBoundingClientRect();
                        const s = window.getComputedStyle(el);
                        return r.width > 2 && r.height > 2
                            && s.display !== 'none'
                            && s.visibility !== 'hidden'
                            && parseFloat(s.opacity || '1') > 0.05;
                    }
                    const roots = Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                        .filter((el) => isVisible(el))
                        .filter((el) => (
                """
                + _modal_match_condition_js("el")
                + """
                        ));
                    const root = roots[roots.length - 1];
                    if (!root) return { ready: false, reason: 'modal_not_found', row_count: 0, found_ids: [] };
                    const rows = Array.from(root.querySelectorAll('tbody tr,[data-testid="beast-core-table-body"] tr'))
                        .filter((el) => isVisible(el));
                    const rowTexts = rows.map((row) => (row.innerText || row.textContent || '').trim());
                    const foundIds = ids.filter((id) => rowTexts.some((text) => text.includes(`ID: ${id}`) || text.includes(id)));
                    const hasLoading = (root.innerText || '').includes('加载中');
                    const rootText = root.innerText || '';
                    const totalMatch = rootText.match(/共有\\s*(\\d+)\\s*条/);
                    const total = totalMatch ? Number(totalMatch[1]) : null;
                    const inputValue = Array.from(root.querySelectorAll('input'))
                        .map((input) => input.value || '')
                        .find((value) => ids.some((id) => value.includes(id))) || '';
                    return {
                        ready: !hasLoading && (foundIds.length > 0 || rows.length === 0),
                        row_count: rows.length,
                        found_ids: foundIds,
                        total,
                        input_value: inputValue,
                        query_not_applied: !hasLoading && foundIds.length === 0 && rows.length > 0,
                    };
                """,
                product_ids,
            )
            if isinstance(result, dict) and (result.get("ready") or result.get("query_not_applied")):
                return result
        except Exception:
            pass
        time.sleep(1)
    return {"ready": False, "reason": "search_result_timeout", "found_ids": [], "row_count": 0}


def _select_product_rows_in_modal(page: DpPage, account_id: str, product_ids: list[str]) -> dict[str, Any]:
    def inspect_state() -> dict[str, Any]:
        return page.run_js(
            """
                const ids = arguments[0].map((id) => String(id));
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function rectInfo(el) {
                    if (!el || !el.getBoundingClientRect) return null;
                    const r = el.getBoundingClientRect();
                    return {
                        left: r.left,
                        top: r.top,
                        width: r.width,
                        height: r.height,
                        x: r.left + r.width / 2,
                        y: r.top + r.height / 2,
                    };
                }
                function parseSelectedCounter(root) {
                    const text = root.innerText || '';
                    const match = text.match(/已选商品\\s*\\((\\d+)\\s*\\/\\s*(\\d+)\\)/);
                    if (!match) return { selected: null, limit: null, text: '' };
                    return {
                        selected: Number(match[1]),
                        limit: Number(match[2]),
                        text: match[0],
                    };
                }
                function positiveClass(el) {
                    const cls = String(el?.className || '').toLowerCase();
                    if (!cls || cls.includes('unselected')) return false;
                    return cls.includes('checked')
                        || cls.includes('is-checked')
                        || cls.includes('selected')
                        || cls.includes('active');
                }
                function checkedState(row) {
                    const inputs = Array.from(row.querySelectorAll('input[type="checkbox"]'));
                    const input = inputs.find((el) => !el.disabled);
                    if (input) return Boolean(input.checked);
                    const ariaNodes = Array.from(row.querySelectorAll('[role="checkbox"], [aria-checked]'));
                    for (const box of ariaNodes) {
                        const aria = box.getAttribute?.('aria-checked');
                        if (aria === 'true') return true;
                        if (aria === 'false') return false;
                    }
                    const cells = Array.from(row.querySelectorAll('td,[data-testid="beast-core-table-td"]'))
                        .filter((el) => isVisible(el));
                    const firstCell = cells[0] || null;
                    const classNodes = [
                        row,
                        firstCell,
                        ...Array.from((firstCell || row).querySelectorAll('*')),
                    ].filter(Boolean);
                    return classNodes.some((el) => positiveClass(el));
                }
                function findCheckCell(row) {
                    const rowRect = row.getBoundingClientRect();
                    const cells = Array.from(row.querySelectorAll('td,[data-testid="beast-core-table-td"]'))
                        .filter((el) => isVisible(el));
                    return cells.find((el) => {
                        const cls = String(el.className || '').toLowerCase();
                        const r = el.getBoundingClientRect();
                        return cls.includes('checkcell')
                            || cls.includes('checkbox')
                            || (r.width <= 70 && r.left <= rowRect.left + 90);
                    }) || cells[0] || row;
                }
                function findCheckTarget(row) {
                    const cell = findCheckCell(row);
                    const controls = Array.from(cell.querySelectorAll(
                        'input[type="checkbox"],[role="checkbox"],label,[aria-checked],'
                        + '[data-testid*="checkbox"],[class*="checkbox"],[class*="Checkbox"],'
                        + '[class*="checkBox"],[class*="check"],[class*="Check"]'
                    )).filter((el) => isVisible(el));
                    controls.sort((a, b) => {
                        const ar = a.getBoundingClientRect();
                        const br = b.getBoundingClientRect();
                        return (ar.width * ar.height) - (br.width * br.height);
                    });
                    return { cell, target: controls[0] || cell };
                }
                function addPoint(points, el, label, x, y) {
                    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
                    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) return;
                    if (points.some((point) => Math.abs(point.x - x) < 1 && Math.abs(point.y - y) < 1)) return;
                    points.push({
                        label,
                        x,
                        y,
                        tag: el?.tagName || '',
                        class_name: String(el?.className || '').slice(0, 160),
                    });
                }
                function clickPoints(row, cell, target) {
                    const points = [];
                    const rowRect = row.getBoundingClientRect();
                    const cellRect = cell.getBoundingClientRect();
                    const targetRect = target.getBoundingClientRect();
                    addPoint(points, target, 'target_center', targetRect.left + targetRect.width / 2, targetRect.top + targetRect.height / 2);
                    addPoint(points, cell, 'check_cell_center', cellRect.left + cellRect.width / 2, cellRect.top + cellRect.height / 2);
                    addPoint(points, cell, 'check_cell_left', cellRect.left + Math.min(18, Math.max(8, cellRect.width / 2)), rowRect.top + rowRect.height / 2);
                    addPoint(points, row, 'row_left', rowRect.left + Math.min(18, Math.max(8, rowRect.width / 20)), rowRect.top + rowRect.height / 2);
                    return points;
                }

                const roots = Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                    .filter((el) => isVisible(el))
                    .filter((el) => (
            """
            + _modal_match_condition_js("el")
            + """
                    ));
                const root = roots[roots.length - 1];
                if (!root) return { selected_ids: [], missing_ids: ids, row_count: 0, reason: 'modal_not_found' };
                const rows = Array.from(root.querySelectorAll('tbody tr,[data-testid="beast-core-table-body"] tr'))
                    .filter((el) => isVisible(el));
                const counter = parseSelectedCounter(root);
                const rowDetails = [];
                for (const id of ids) {
                    const row = rows.find((candidate) => {
                        const text = (candidate.innerText || candidate.textContent || '').trim();
                        return text.includes(`ID: ${id}`) || text.includes(id);
                    });
                    if (!row) {
                        rowDetails.push({ id, found: false, selected: false, text: '' });
                        continue;
                    }
                    const { cell, target } = findCheckTarget(row);
                    rowDetails.push({
                        id,
                        found: true,
                        selected: checkedState(row),
                        text: (row.innerText || row.textContent || '').trim().slice(0, 180),
                        row_class: String(row.className || '').slice(0, 160),
                        cell_class: String(cell.className || '').slice(0, 160),
                        target_class: String(target.className || '').slice(0, 160),
                        row_rect: rectInfo(row),
                        cell_rect: rectInfo(cell),
                        target_rect: rectInfo(target),
                        click_points: clickPoints(row, cell, target),
                    });
                }
                return {
                    selected_ids: rowDetails.filter((item) => item.found && item.selected).map((item) => item.id),
                    missing_ids: rowDetails.filter((item) => !item.found || !item.selected).map((item) => item.id),
                    found_ids: rowDetails.filter((item) => item.found).map((item) => item.id),
                    row_count: rows.length,
                    row_details: rowDetails,
                    selected_counter: counter,
                    selected_counter_text: counter.text,
                };
            """,
            product_ids,
        )

    def counter_value(state: dict[str, Any] | None) -> int | None:
        if not isinstance(state, dict):
            return None
        counter = state.get("selected_counter")
        if not isinstance(counter, dict):
            return None
        value = counter.get("selected")
        return value if isinstance(value, int) else None

    def infer_from_counter(state: dict[str, Any], initial_count: int | None, clicked_ids: list[str]) -> dict[str, Any]:
        final_count = counter_value(state)
        if initial_count is None or final_count is None:
            return state
        if final_count < initial_count + len(clicked_ids):
            return state
        found_ids = [str(item) for item in state.get("found_ids") or []]
        inferred_ids = [item for item in clicked_ids if item in found_ids]
        selected_ids = list(dict.fromkeys([*(state.get("selected_ids") or []), *inferred_ids]))
        state["selected_ids"] = selected_ids
        state["missing_ids"] = [str(item) for item in product_ids if str(item) not in selected_ids]
        state["selection_inferred_from_counter"] = True
        return state

    def click_point(raw_page: Any, point: dict[str, Any], product_id: str, phase: str) -> dict[str, Any]:
        x = float(point.get("x") or 0)
        y = float(point.get("y") or 0)
        if x <= 0 or y <= 0:
            return {"id": product_id, "clicked": False, "phase": phase, "reason": "invalid_point", "point": point}
        raw_page.mouse.move(x, y)
        time.sleep(0.05)
        raw_page.mouse.down()
        time.sleep(0.05)
        raw_page.mouse.up()
        return {"id": product_id, "clicked": True, "phase": phase, "point": point}

    try:
        raw_page = getattr(page, "_page")
        initial = inspect_state()
        if not isinstance(initial, dict):
            return {"selected_ids": [], "missing_ids": product_ids, "reason": str(initial), "row_count": 0}
        if initial.get("reason"):
            return initial

        initial_count = counter_value(initial)
        pending = [
            detail
            for detail in initial.get("row_details") or []
            if detail.get("found") and not detail.get("selected")
        ]
        clicked_ids = [str(detail.get("id")) for detail in pending if detail.get("id")]
        click_results: list[dict[str, Any]] = []

        for detail in pending:
            points = detail.get("click_points") or []
            if not points:
                continue
            click_results.append(click_point(raw_page, points[0], str(detail.get("id")), "primary"))
            time.sleep(0.35)

        result = inspect_state()
        if not isinstance(result, dict):
            return {"selected_ids": [], "missing_ids": product_ids, "reason": str(result), "row_count": 0}
        result = infer_from_counter(result, initial_count, clicked_ids)

        if result.get("missing_ids") and not result.get("selection_inferred_from_counter"):
            for detail in result.get("row_details") or []:
                product_id = str(detail.get("id") or "")
                if product_id not in result.get("missing_ids", []) or not detail.get("found"):
                    continue
                for point in (detail.get("click_points") or [])[1:]:
                    before_count = counter_value(result)
                    click_results.append(click_point(raw_page, point, product_id, "retry"))
                    time.sleep(0.3)
                    next_state = inspect_state()
                    if not isinstance(next_state, dict):
                        continue
                    result = infer_from_counter(next_state, initial_count, clicked_ids)
                    after_count = counter_value(result)
                    if product_id in (result.get("selected_ids") or []):
                        break
                    if before_count is not None and after_count is not None and after_count > before_count:
                        break

        result["initial_state"] = initial
        result["click_results"] = click_results
    except Exception as exc:
        return {"selected_ids": [], "missing_ids": product_ids, "reason": _safe_exc(exc), "row_count": 0}

    if isinstance(result, dict):
        print(f"[{account_id}] 商品弹窗勾选：{result}", flush=True)
        return result
    return {"selected_ids": [], "missing_ids": product_ids, "reason": str(result), "row_count": 0}


def _confirm_product_selection(page: DpPage, account_id: str) -> dict[str, Any]:
    try:
        result = page.run_js(
            """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function isDisabled(el) {
                    return Boolean(el.disabled)
                        || el.getAttribute?.('aria-disabled') === 'true'
                        || String(el.className || '').toLowerCase().includes('disabled');
                }
                function clickLikeUser(el) {
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                const roots = Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                    .filter((el) => isVisible(el))
                    .filter((el) => (
            """
            + _modal_match_condition_js("el")
            + """
                    ));
                const root = roots[roots.length - 1];
                if (!root) return { clicked: false, reason: 'modal_not_found' };
                const buttons = Array.from(root.querySelectorAll('button,[role="button"]'))
                    .filter((el) => isVisible(el))
                    .filter((el) => ((el.innerText || el.textContent || '').trim()) === '确认选择');
                if (!buttons.length) return { clicked: false, reason: 'confirm_button_not_found' };
                const button = buttons[0];
                if (isDisabled(button)) return { clicked: false, reason: 'confirm_button_disabled' };
                clickLikeUser(button);
                return { clicked: true };
            """
        )
    except Exception as exc:
        return {"clicked": False, "reason": _safe_exc(exc)}

    if isinstance(result, dict):
        print(f"[{account_id}] 确认选择商品：{result}", flush=True)
        return result
    return {"clicked": False, "reason": str(result)}


def _wait_product_modal_closed(page: DpPage, timeout: int = 10) -> bool:
    for _ in range(timeout):
        try:
            visible = page.run_js(
                """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 80 && r.height > 80
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                return Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                    .some((el) => isVisible(el) && (
                """
                + _modal_match_condition_js("el")
                + """
                    ));
                """
            )
            if not visible:
                return True
        except Exception:
            return True
        time.sleep(1)
    return False


def _read_product_modal_state(page: DpPage) -> dict[str, Any]:
    try:
        result = page.run_js(
            """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function isDisabled(el) {
                    return Boolean(el?.disabled)
                        || el?.getAttribute?.('aria-disabled') === 'true'
                        || String(el?.className || '').toLowerCase().includes('disabled');
                }
                const roots = Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                    .filter((el) => isVisible(el))
                    .filter((el) => (
            """
            + _modal_match_condition_js("el")
            + """
                    ));
                const root = roots[roots.length - 1];
                if (!root) return {
                    visible: false,
                    selected_count: 0,
                    selected_limit: 0,
                    loading: false,
                    confirm_enabled: false,
                    close_visible: false,
                    text: '',
                };
                const text = root.innerText || '';
                const selectedMatch = text.match(/已选商品\\s*\\((\\d+)\\s*\\/\\s*(\\d+)\\)/);
                const selectedCount = selectedMatch ? Number(selectedMatch[1]) : 0;
                const selectedLimit = selectedMatch ? Number(selectedMatch[2]) : 0;
                const confirmButton = Array.from(root.querySelectorAll('button,[role="button"]'))
                    .filter((el) => isVisible(el))
                    .find((el) => ((el.innerText || el.textContent || '').trim()) === '确认选择');
                const rr = root.getBoundingClientRect();
                const closeButton = Array.from(root.querySelectorAll('button,[role="button"],span,div,i,svg'))
                    .filter((el) => isVisible(el))
                    .map((el) => ({ el, rect: el.getBoundingClientRect(), text: ((el.innerText || el.textContent || '').trim()) }))
                    .find((item) => (
                        item.text === '×'
                        || item.text === '✕'
                        || item.text === 'x'
                        || item.text === 'X'
                        || (item.rect.top < rr.top + 80 && item.rect.left > rr.right - 100)
                    ));
                return {
                    visible: true,
                    selected_count: selectedCount,
                    selected_limit: selectedLimit,
                    loading: text.includes('加载中'),
                    confirm_enabled: Boolean(confirmButton) && !isDisabled(confirmButton),
                    close_visible: Boolean(closeButton),
                    text: text.slice(0, 220),
                };
            """
        )
    except Exception as exc:
        return {
            "visible": False,
            "selected_count": 0,
            "selected_limit": 0,
            "loading": False,
            "confirm_enabled": False,
            "close_visible": False,
            "error": _safe_exc(exc),
            "text": "",
        }
    if isinstance(result, dict):
        return result
    return {
        "visible": False,
        "selected_count": 0,
        "selected_limit": 0,
        "loading": False,
        "confirm_enabled": False,
        "close_visible": False,
        "raw": result,
        "text": "",
    }


def _close_product_modal(page: DpPage, account_id: str) -> dict[str, Any]:
    try:
        result = page.run_js(
            """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function clickLikeUser(el) {
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                const roots = Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                    .filter((el) => isVisible(el))
                    .filter((el) => (
            """
            + _modal_match_condition_js("el")
            + """
                    ));
                const root = roots[roots.length - 1];
                if (!root) return { clicked: false, reason: 'modal_not_found' };
                const rr = root.getBoundingClientRect();
                const candidates = Array.from(root.querySelectorAll('button,[role="button"],span,div,i,svg'))
                    .filter((el) => isVisible(el))
                    .map((el) => ({
                        el,
                        rect: el.getBoundingClientRect(),
                        text: ((el.innerText || el.textContent || '').trim()),
                    }))
                    .filter((item) => (
                        item.text === '×'
                        || item.text === '✕'
                        || item.text === 'x'
                        || item.text === 'X'
                        || (item.rect.top < rr.top + 80 && item.rect.left > rr.right - 100)
                    ))
                    .sort((a, b) => {
                        const scoreA = Math.abs(a.rect.top - rr.top) + Math.abs((rr.right - 20) - a.rect.left);
                        const scoreB = Math.abs(b.rect.top - rr.top) + Math.abs((rr.right - 20) - b.rect.left);
                        return scoreA - scoreB;
                    });
                if (!candidates.length) return { clicked: false, reason: 'close_button_not_found' };
                const selected = candidates[0];
                clickLikeUser(selected.el);
                return {
                    clicked: true,
                    text: selected.text,
                    rect: {
                        left: Math.round(selected.rect.left),
                        top: Math.round(selected.rect.top),
                        width: Math.round(selected.rect.width),
                        height: Math.round(selected.rect.height),
                    },
                };
            """
        )
    except Exception as exc:
        return {"clicked": False, "reason": _safe_exc(exc)}

    if isinstance(result, dict):
        print(f"[{account_id}] 关闭选择商品弹窗：{result}", flush=True)
        return result
    return {"clicked": False, "reason": str(result)}


def _dismiss_product_modal_after_confirm(
    page: DpPage,
    account_id: str,
    target_ids: list[str],
    timeout: int = 18,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for tick in range(timeout):
        if _wait_product_modal_closed(page, timeout=1):
            return {"closed": True, "attempts": attempts, "final_state": _read_product_modal_state(page)}

        modal_state = _read_product_modal_state(page)
        background_state = _read_selected_products_on_activity_page(page)
        background_ready = _activity_has_selected_products(
            background_state,
            target_ids,
            allow_count_fallback=True,
        )
        attempt: dict[str, Any] = {
            "tick": tick,
            "modal_state": modal_state,
            "background_ready": background_ready,
            "background_state": background_state,
        }

        action: dict[str, Any] | None = None
        if modal_state.get("close_visible") and background_ready and tick >= 1:
            action = _close_product_modal(page, account_id)
            attempt["action"] = "close_modal_after_background_ready"
        elif modal_state.get("confirm_enabled") and (
            modal_state.get("selected_count", 0) > 0 or background_ready
        ):
            action = _confirm_product_selection(page, account_id)
            attempt["action"] = "confirm_retry"
        elif modal_state.get("close_visible") and background_ready:
            action = _close_product_modal(page, account_id)
            attempt["action"] = "close_modal"
        elif modal_state.get("close_visible") and tick >= 6 and modal_state.get("selected_count", 0) > 0:
            action = _close_product_modal(page, account_id)
            attempt["action"] = "close_modal_after_wait"

        if action is not None:
            attempt["result"] = action
            attempts.append(attempt)
            if action.get("clicked"):
                time.sleep(1.5)
                continue
        else:
            attempts.append(attempt)

        time.sleep(1)

    closed = _wait_product_modal_closed(page, timeout=1)
    return {"closed": closed, "attempts": attempts, "final_state": _read_product_modal_state(page)}


def _read_selected_products_on_activity_page(page: DpPage) -> dict[str, Any]:
    if not _ensure_page_binding(page, preferred_url_parts=ACTIVITY_CREATE_URL_PARTS, timeout=2):
        return {"ids": [], "selected_count": 0, "error": "activity_page_unavailable", "selected_text": ""}
    try:
        result = page.run_js(
            """
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]').forEach((el) => el.remove());
                const text = clone.innerText || '';
                const ids = Array.from(new Set(
                    Array.from(text.matchAll(/ID[:：]\\s*(\\d{6,})/g)).map((m) => m[1])
                ));
                const selectedCountMatch = text.match(/已选择\\s*(\\d+)\\s*个商品/);
                const selectedCount = selectedCountMatch ? Number(selectedCountMatch[1]) : 0;
                const selectedTextMatch = text.match(/活动商品[\\s\\S]{0,500}/);
                return {
                    ids,
                    selected_count: selectedCount,
                    selected_text: selectedTextMatch ? selectedTextMatch[0] : '',
                };
            """
        )
    except Exception as exc:
        return {"ids": [], "selected_count": 0, "error": _safe_exc(exc), "selected_text": ""}
    if isinstance(result, dict):
        return result
    return {"ids": [], "selected_count": 0, "raw": result, "selected_text": ""}


def _activity_has_selected_products(
    activity_selected: dict[str, Any],
    target_ids: list[str],
    *,
    allow_count_fallback: bool = False,
) -> bool:
    visible_ids = [str(item) for item in activity_selected.get("ids") or []]
    if target_ids and all(item in visible_ids for item in target_ids):
        return True
    if not allow_count_fallback:
        return False
    selected_count = activity_selected.get("selected_count")
    return isinstance(selected_count, int) and selected_count >= max(1, len(target_ids))


def _wait_activity_selected_products(
    page: DpPage,
    target_ids: list[str],
    timeout: int = 15,
) -> dict[str, Any]:
    last: dict[str, Any] = {"ids": [], "selected_count": 0, "selected_text": ""}
    for _ in range(timeout):
        _ensure_page_binding(page, preferred_url_parts=ACTIVITY_CREATE_URL_PARTS, timeout=1)
        last = _read_selected_products_on_activity_page(page)
        if _activity_has_selected_products(last, target_ids, allow_count_fallback=True):
            return last
        time.sleep(1)
    return last


def _read_activity_product_rows_summary(page: DpPage) -> dict[str, Any]:
    if not _ensure_page_binding(page, preferred_url_parts=ACTIVITY_CREATE_URL_PARTS, timeout=2):
        return {"row_count": 0, "rows": [], "has_rows": False, "error": "activity_page_unavailable"}
    try:
        result = page.run_js(
            """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                const clone = document.body.cloneNode(true);
                clone.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]').forEach((el) => el.remove());
                const roots = Array.from(clone.querySelectorAll(
                    '[data-testid="beast-core-table"], table, [class*="TB_outerWrapper"], [class*="TB_table"]'
                ))
                    .filter((el) => {
                        const text = el.innerText || el.textContent || '';
                        return text.includes('活动库存')
                            && text.includes('促销维度')
                            && text.includes('规格信息')
                            && text.includes('折扣');
                    });
                const rows = [];
                for (const root of roots) {
                    const tableRows = Array.from(root.querySelectorAll('tbody tr,[data-testid="beast-core-table-body"] tr'));
                    for (const row of tableRows) {
                        const text = (row.innerText || row.textContent || '').trim();
                        if (!text.includes('ID:') && !text.includes('拼单价')) continue;
                        rows.push({
                            text: text.slice(0, 220),
                            ids: Array.from(text.matchAll(/ID[:：]\\s*(\\d{6,})/g)).map((m) => m[1]),
                            dimension: text.includes('规格级') ? '规格级' : (text.includes('商品级') ? '商品级' : ''),
                        });
                    }
                }
                return {
                    row_count: rows.length,
                    rows,
                    has_rows: rows.length > 0,
                };
            """
        )
    except Exception as exc:
        return {"row_count": 0, "rows": [], "has_rows": False, "error": _safe_exc(exc)}
    if isinstance(result, dict):
        return result
    return {"row_count": 0, "rows": [], "has_rows": False, "raw": result}


def _select_campaign_products(
    page: DpPage,
    account_id: str,
    product_ids: list[str],
) -> dict[str, Any]:
    """在活动设置页选择商品弹窗中按拼多多商品 ID 搜索、勾选并确认。"""
    target_ids = list(dict.fromkeys(str(value).strip() for value in product_ids if str(value).strip()))
    if not target_ids:
        return {"status": "skipped", "selected_ids": [], "missing_ids": [], "reason": "no_product_ids"}
    if len(target_ids) > MAX_CAMPAIGN_PRODUCTS:
        return {
            "status": "failed",
            "selected_ids": [],
            "missing_ids": target_ids,
            "error": f"最多只能选择 {MAX_CAMPAIGN_PRODUCTS} 个活动商品，当前 {len(target_ids)} 个",
        }

    existing_rows = _read_activity_product_rows_summary(page)
    if existing_rows.get("has_rows"):
        existing_ids = [
            str(item)
            for row in existing_rows.get("rows") or []
            for item in row.get("ids", [])
        ]
        return {
            "status": "success",
            "step": "product_already_selected_on_page",
            "target_ids": target_ids,
            "selected_ids": existing_ids or target_ids,
            "missing_ids": [],
            "batches": [],
            "modal_closed": True,
            "activity_selected": _read_selected_products_on_activity_page(page),
            "activity_product_rows": existing_rows,
            "selected_visible_on_page": all(item in existing_ids for item in target_ids) if existing_ids else False,
            "error": "",
        }

    existing_selection = _read_selected_products_on_activity_page(page)
    if _activity_has_selected_products(existing_selection, target_ids):
        return {
            "status": "success",
            "step": "product_already_selected",
            "target_ids": target_ids,
            "selected_ids": target_ids,
            "missing_ids": [],
            "batches": [],
            "modal_closed": True,
            "activity_selected": existing_selection,
            "selected_visible_on_page": True,
            "error": "",
        }

    open_result = _open_product_modal(page, account_id)
    if not open_result.get("clicked") or not _wait_product_modal(page, timeout=10):
        return {
            "status": "failed",
            "step": "open_product_modal",
            "error": open_result.get("reason") or "未打开选择商品弹窗",
            "open_result": open_result,
            "target_ids": target_ids,
        }

    selected_ids: list[str] = []
    missing_ids: list[str] = []
    batches: list[dict[str, Any]] = []
    for batch in _chunked(target_ids, PRODUCT_SEARCH_BATCH_SIZE):
        search_result = _search_product_ids_in_modal(page, account_id, batch)
        if not search_result.get("searched"):
            missing_ids.extend(batch)
            batches.append({"batch": batch, "search": search_result})
            continue
        ready = _wait_modal_table_after_search(page, batch, timeout=12)
        if ready.get("query_not_applied"):
            fallback_search = _fallback_search_product_ids_in_modal(page, account_id, batch)
            fallback_ready = _wait_modal_table_after_search(page, batch, timeout=12)
            batches.append(
                {
                    "batch": batch,
                    "search": search_result,
                    "ready": ready,
                    "fallback_search": fallback_search,
                    "fallback_ready": fallback_ready,
                    "reason": "query_not_applied_retry",
                }
            )
            search_result = fallback_search
            ready = fallback_ready
        if not ready.get("ready"):
            missing_ids.extend(batch)
            reason = "query_not_applied" if ready.get("query_not_applied") else "search_result_timeout"
            batches.append({"batch": batch, "search": search_result, "ready": ready, "reason": reason})
            continue
        select_result = _select_product_rows_in_modal(page, account_id, batch)
        selected_ids.extend(str(item) for item in select_result.get("selected_ids") or [])
        missing_ids.extend(str(item) for item in select_result.get("missing_ids") or [])
        batches.append(
            {
                "batch": batch,
                "search": search_result,
                "ready": ready,
                "select": select_result,
            }
        )

    selected_ids = list(dict.fromkeys(selected_ids))
    missing_ids = [item for item in list(dict.fromkeys(missing_ids)) if item not in selected_ids]
    if missing_ids:
        return {
            "status": "failed",
            "step": "select_product_rows",
            "error": f"未能勾选商品ID：{', '.join(missing_ids)}",
            "target_ids": target_ids,
            "selected_ids": selected_ids,
            "missing_ids": missing_ids,
            "batches": batches,
        }

    confirm = _confirm_product_selection(page, account_id)
    if not confirm.get("clicked"):
        return {
            "status": "failed",
            "step": "confirm_product_selection",
            "error": confirm.get("reason") or "无法点击确认选择",
            "target_ids": target_ids,
            "selected_ids": selected_ids,
            "missing_ids": missing_ids,
            "batches": batches,
            "confirm": confirm,
        }
    modal_dismissal = _dismiss_product_modal_after_confirm(
        page,
        account_id,
        target_ids,
        timeout=24,
    )
    closed = bool(modal_dismissal.get("closed"))
    time.sleep(10)
    activity_page_ready = _ensure_page_binding(
        page,
        preferred_url_parts=ACTIVITY_CREATE_URL_PARTS,
        timeout=15,
    )
    if activity_page_ready:
        _wait_activity_settings(page, account_id, timeout=6)
    activity_selected = _wait_activity_selected_products(page, target_ids, timeout=15)
    visible_selected_ids = [str(item) for item in activity_selected.get("ids") or []]
    selected_visible_on_page = all(item in visible_selected_ids for item in target_ids)
    selected_count_done = _activity_has_selected_products(
        activity_selected,
        target_ids,
        allow_count_fallback=True,
    )
    selected_done = selected_visible_on_page or selected_count_done
    product_selection_done = closed and selected_done
    if not closed:
        error = "确认选择后选择商品弹窗未关闭"
    elif not selected_done:
        error = "确认选择后未在活动页看到已选商品"
    else:
        error = ""
    return {
        "status": "success" if product_selection_done else "failed",
        "step": "product_selected" if product_selection_done else "wait_product_modal_closed",
        "target_ids": target_ids,
        "selected_ids": selected_ids,
        "missing_ids": missing_ids,
        "batches": batches,
        "confirm": confirm,
        "modal_closed": closed,
        "modal_dismissal": modal_dismissal,
        "activity_page_ready": activity_page_ready,
        "activity_selected": activity_selected,
        "selected_visible_on_page": selected_visible_on_page,
        "selected_count_done": selected_count_done,
        "selected_done": selected_done,
        "error": error,
    }


def _read_activity_product_dimension_rows(page: DpPage, product_ids: list[str]) -> dict[str, Any]:
    if not _ensure_page_binding(page, preferred_url_parts=ACTIVITY_CREATE_URL_PARTS, timeout=2):
        return {"rows": [], "row_count": 0, "error": "activity_page_unavailable"}
    try:
        result = page.run_js(
            """
                const targetIds = (arguments[0] || []).map((id) => String(id));
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function textOf(el) {
                    if (!el) return '';
                    const tag = (el.tagName || '').toLowerCase();
                    if (tag === 'input' || tag === 'textarea') return el.value || '';
                    return (el.innerText || el.textContent || '').trim();
                }
                function rectInfo(el) {
                    const r = el.getBoundingClientRect();
                    return {
                        left: r.left,
                        top: r.top,
                        width: r.width,
                        height: r.height,
                        x: r.left + r.width / 2,
                        y: r.top + r.height / 2,
                    };
                }
                function clickRoot(el) {
                    return el.closest?.(
                        '[data-testid="beast-core-select-header"], [data-testid*="select-header"],'
                        + '[role="combobox"],button,[role="button"],[class*="ST_head"],'
                        + '[class*="select"],[class*="Select"]'
                    ) || el;
                }
                function findDimensionTarget(row) {
                    const candidates = Array.from(row.querySelectorAll(
                        'input,button,[role="button"],[role="combobox"],div,span'
                    ))
                        .filter((el) => isVisible(el))
                        .map((el) => ({ el, text: textOf(el).replace(/\\s+/g, '') }))
                        .filter((item) => item.text === '商品级' || item.text === '规格级');
                    candidates.sort((a, b) => {
                        const ar = a.el.getBoundingClientRect();
                        const br = b.el.getBoundingClientRect();
                        return (ar.width * ar.height) - (br.width * br.height);
                    });
                    const selected = candidates[0];
                    if (!selected) return null;
                    return clickRoot(selected.el);
                }
                function readRow(row) {
                    const text = (row.innerText || row.textContent || '').trim();
                    const ids = Array.from(text.matchAll(/ID[:：]\\s*(\\d{6,})/g)).map((m) => m[1]);
                    const id = ids.find((item) => targetIds.includes(item)) || ids[0] || '';
                    const target = findDimensionTarget(row);
                    const targetText = target ? textOf(target).replace(/\\s+/g, '') : '';
                    let dimension = '';
                    if (targetText.includes('规格级')) {
                        dimension = '规格级';
                    } else if (targetText.includes('商品级')) {
                        dimension = '商品级';
                    }
                    return {
                        id,
                        ids,
                        found: Boolean(id),
                        dimension,
                        text: text.slice(0, 220),
                        has_target: Boolean(target),
                        rect: target ? rectInfo(target) : null,
                        target_text: targetText,
                        target_class: target ? String(target.className || '').slice(0, 160) : '',
                    };
                }
                const roots = Array.from(document.querySelectorAll(
                    '[data-testid="beast-core-table"], table, [class*="TB_outerWrapper"], [class*="TB_table"]'
                ))
                    .filter((el) => isVisible(el))
                    .filter((el) => {
                        const text = (el.innerText || el.textContent || '');
                        return text.includes('促销维度') && text.includes('商品信息') && text.includes('活动库存');
                    })
                    .map((el) => ({
                        el,
                        rect: el.getBoundingClientRect(),
                        row_count: Array.from(el.querySelectorAll('tbody tr,[data-testid="beast-core-table-body"] tr'))
                            .filter((row) => isVisible(row)).length,
                    }))
                    .filter((item) => item.row_count > 0)
                    .sort((a, b) => {
                        if (b.row_count !== a.row_count) return b.row_count - a.row_count;
                        return (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height);
                    });
                const root = roots.length ? roots[0].el : null;
                if (!root) return { rows: [], reason: 'activity_product_table_not_found' };
                const rows = Array.from(root.querySelectorAll('tbody tr,[data-testid="beast-core-table-body"] tr'))
                    .filter((el) => isVisible(el))
                    .map(readRow)
                    .filter((row) => row.has_target && (row.id || row.dimension));
                const targetRows = targetIds.length
                    ? rows.filter((row) => targetIds.includes(row.id))
                    : [];
                return {
                    rows: targetRows.length ? targetRows : rows,
                    all_rows: rows,
                    target_ids: targetIds,
                };
            """,
            product_ids,
        )
    except Exception as exc:
        return {"rows": [], "reason": _safe_exc(exc)}
    if isinstance(result, dict):
        return result
    return {"rows": [], "reason": str(result)}


def _click_spec_level_option(page: DpPage) -> dict[str, Any]:
    last_result: dict[str, Any] = {"clicked": False, "reason": "spec_option_not_found"}
    for _ in range(8):
        try:
            result = page.run_js(
                """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function textOf(el) {
                    return ((el.innerText || el.textContent || '').trim()).replace(/\\s+/g, '');
                }
                function insideActivityTable(el) {
                    const root = el.closest?.('[data-testid="beast-core-table"], table, [class*="TB_outerWrapper"], [class*="TB_table"]');
                    if (!root) return false;
                    const text = root.innerText || root.textContent || '';
                    return text.includes('促销维度') && text.includes('活动库存');
                }
                function clickLikeUser(el) {
                    el.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                const candidates = Array.from(document.querySelectorAll('[role="option"],li,div,span'))
                    .filter((el) => isVisible(el))
                    .map((el) => ({ el, text: textOf(el), rect: el.getBoundingClientRect() }))
                    .filter((item) => item.text.includes('规格级'))
                    .sort((a, b) => {
                        const aExact = a.text === '规格级' ? 0 : 1;
                        const bExact = b.text === '规格级' ? 0 : 1;
                        if (aExact !== bExact) return aExact - bExact;
                        return (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height);
                    });
                const outsideTable = candidates.filter((item) => !insideActivityTable(item.el));
                const pool = outsideTable.length ? outsideTable : candidates;
                const selected = pool[0]?.el;
                if (!selected) {
                    const visibleOptions = Array.from(document.querySelectorAll('[role="option"],li,div,span'))
                        .filter((el) => isVisible(el))
                        .map((el) => textOf(el))
                        .filter((text) => text === '商品级' || text === '规格级' || text.includes('商品级') || text.includes('规格级'))
                        .slice(0, 20);
                    return { clicked: false, reason: 'spec_option_not_found', visible_options: visibleOptions };
                }
                const rect = selected.getBoundingClientRect();
                selected.focus?.();
                return {
                    clicked: true,
                    prepared: true,
                    text: textOf(selected),
                    rect: {
                        left: Math.round(rect.left),
                        top: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                    },
                };
                """
            )
        except Exception as exc:
            result = {"clicked": False, "reason": _safe_exc(exc)}
        if isinstance(result, dict):
            last_result = result
            if result.get("clicked"):
                return result
        else:
            last_result = {"clicked": False, "reason": str(result)}
        time.sleep(0.35)
    return last_result


def _open_promotion_dimension_dropdown(
    page: DpPage,
    row: dict[str, Any],
    product_ids: list[str],
) -> dict[str, Any]:
    try:
        result = page.run_js(
            """
                const targetIds = (arguments[0] || []).map((id) => String(id));
                const preferredId = String(arguments[1] || '');
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function textOf(el) {
                    if (!el) return '';
                    const tag = (el.tagName || '').toLowerCase();
                    if (tag === 'input' || tag === 'textarea') return el.value || '';
                    return (el.innerText || el.textContent || '').trim();
                }
                function clickRoot(el) {
                    return el.closest?.(
                        '[data-testid="beast-core-select-header"], [data-testid*="select-header"],'
                        + '[role="combobox"],button,[role="button"],[class*="ST_head"],'
                        + '[class*="select"],[class*="Select"]'
                    ) || el;
                }
                function clickLikeUser(el) {
                    el.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                    el.focus?.();
                }
                function findDimensionTarget(row) {
                    const candidates = Array.from(row.querySelectorAll(
                        'input,button,[role="button"],[role="combobox"],div,span'
                    ))
                        .filter((el) => isVisible(el))
                        .map((el) => ({ el, text: textOf(el).replace(/\\s+/g, '') }))
                        .filter((item) => item.text === '商品级' || item.text === '规格级');
                    candidates.sort((a, b) => {
                        const ar = a.el.getBoundingClientRect();
                        const br = b.el.getBoundingClientRect();
                        return (ar.width * ar.height) - (br.width * br.height);
                    });
                    const selected = candidates[0];
                    return selected ? clickRoot(selected.el) : null;
                }
                const roots = Array.from(document.querySelectorAll(
                    '[data-testid="beast-core-table"], table, [class*="TB_outerWrapper"], [class*="TB_table"]'
                ))
                    .filter((el) => isVisible(el))
                    .filter((el) => {
                        const text = el.innerText || el.textContent || '';
                        return text.includes('促销维度') && text.includes('商品信息') && text.includes('活动库存');
                    });
                const rows = roots.flatMap((root) => Array.from(root.querySelectorAll(
                    'tbody tr,[data-testid="beast-core-table-body"] tr'
                )))
                    .filter((el) => isVisible(el))
                    .map((el) => {
                        const text = el.innerText || el.textContent || '';
                        const ids = Array.from(text.matchAll(/ID[:：]\\s*(\\d{6,})/g)).map((m) => m[1]);
                        return { el, text, ids };
                    })
                    .filter((item) => item.ids.length || item.text.includes('拼单价'));
                let rowItem = rows.find((item) => preferredId && item.ids.includes(preferredId));
                if (!rowItem && targetIds.length) {
                    rowItem = rows.find((item) => item.ids.some((id) => targetIds.includes(id)));
                }
                rowItem = rowItem || rows[0];
                if (!rowItem) return { clicked: false, reason: 'activity_product_row_not_found' };
                const target = findDimensionTarget(rowItem.el);
                if (!target) {
                    return {
                        clicked: false,
                        reason: 'dimension_dropdown_not_found',
                        row_text: rowItem.text.slice(0, 220),
                        ids: rowItem.ids,
                    };
                }
                rowItem.el.scrollIntoView({ block: 'center', inline: 'nearest' });
                target.scrollIntoView({ block: 'center', inline: 'nearest' });
                const before = textOf(target).replace(/\\s+/g, '');
                target.focus?.();
                const rect = target.getBoundingClientRect();
                return {
                    clicked: true,
                    prepared: true,
                    before_text: before,
                    ids: rowItem.ids,
                    row_text: rowItem.text.slice(0, 220),
                    rect: {
                        left: Math.round(rect.left),
                        top: Math.round(rect.top),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        x: rect.left + rect.width / 2,
                        y: rect.top + rect.height / 2,
                    },
                };
            """,
            product_ids,
            row.get("id") or "",
        )
    except Exception as exc:
        return {"clicked": False, "reason": _safe_exc(exc)}
    if isinstance(result, dict):
        return result
    return {"clicked": False, "reason": str(result)}


def _wait_spec_modal(page: DpPage, timeout: int = 8) -> bool:
    for _ in range(timeout):
        try:
            visible = page.run_js(
                """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 80 && r.height > 80
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                return Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                    .some((el) => {
                        const text = el.innerText || el.textContent || '';
                        return isVisible(el) && text.includes('选择规格') && text.includes('确认选择');
                    });
                """
            )
            if visible:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _confirm_all_specs_in_modal(page: DpPage, account_id: str) -> dict[str, Any]:
    if not _wait_spec_modal(page, timeout=8):
        return {"handled": True, "modal_found": False, "reason": "spec_modal_not_opened"}
    try:
        result = page.run_js(
            """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function clickLikeUser(el) {
                    el.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                function checkedState(box) {
                    if (!box) return null;
                    if ((box.tagName || '').toLowerCase() === 'input') return Boolean(box.checked);
                    const input = box.querySelector?.('input[type="checkbox"]');
                    if (input) return Boolean(input.checked);
                    const aria = box.getAttribute?.('aria-checked');
                    if (aria === 'true') return true;
                    if (aria === 'false') return false;
                    const cls = String(box.className || '').toLowerCase();
                    if (cls.includes('checked') || cls.includes('is-checked') || cls.includes('selected')) return true;
                    return false;
                }
                function findControlNear(node) {
                    let cur = node;
                    for (let depth = 0; depth < 8 && cur; depth++, cur = cur.parentElement) {
                        const label = cur.closest?.('label');
                        if (label && label.querySelector?.('input[type="checkbox"]')) return label;
                        const input = cur.querySelector?.('input[type="checkbox"]');
                        if (input) {
                            const inputLabel = input.closest?.('label');
                            if (inputLabel) return inputLabel;
                            return input;
                        }
                        const roleBox = cur.querySelector?.('[role="checkbox"],[aria-checked]');
                        if (roleBox) return roleBox;
                        const classBox = cur.querySelector?.('[class*="checkbox"],[class*="Checkbox"],[class*="checkBox"]');
                        if (classBox) return classBox;
                    }
                    return null;
                }
                function findSmallestCheckboxControl(rootNode) {
                    const controls = Array.from(rootNode.querySelectorAll(
                        'input[type="checkbox"],[role="checkbox"],label,[aria-checked],'
                        + '[data-testid*="checkbox"],[class*="checkbox"],[class*="Checkbox"],'
                        + '[class*="checkBox"],[class*="check"],[class*="Check"]'
                    ))
                        .filter((el) => isVisible(el))
                        .map((el) => {
                            const label = el.closest?.('label');
                            const target = label && isVisible(label) ? label : el;
                            const r = target.getBoundingClientRect();
                            return { target, rect: r };
                        })
                        .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
                    return controls[0]?.target || null;
                }
                function findHeaderSelectAllControl(rootNode) {
                    const table = Array.from(rootNode.querySelectorAll('[data-testid="beast-core-table"], table, [class*="TB_outerWrapper"], [class*="TB_table"]'))
                        .filter((el) => isVisible(el))[0] || rootNode;
                    const headerCell = Array.from(table.querySelectorAll('thead th,[data-testid="beast-core-table-th"],th'))
                        .filter((el) => isVisible(el))
                        .sort((a, b) => {
                            const ar = a.getBoundingClientRect();
                            const br = b.getBoundingClientRect();
                            return ar.left - br.left;
                        })[0];
                    if (!headerCell) return null;
                    return findSmallestCheckboxControl(headerCell) || headerCell;
                }
                function findFooterSelectAllControl(rootNode) {
                    const selectAllNode = Array.from(rootNode.querySelectorAll('label,span,div,p'))
                        .filter((el) => isVisible(el))
                        .find((el) => ((el.innerText || el.textContent || '').trim()).includes('选全部规格'));
                    if (!selectAllNode) return null;
                    const nearby = findControlNear(selectAllNode);
                    if (nearby) return nearby;
                    const row = selectAllNode.parentElement || selectAllNode;
                    return findSmallestCheckboxControl(row);
                }
                const roots = Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                    .filter((el) => {
                        const text = el.innerText || el.textContent || '';
                        return isVisible(el) && text.includes('选择规格') && text.includes('确认选择');
                    });
                const root = roots[roots.length - 1];
                if (!root) return { handled: false, modal_found: false, reason: 'spec_modal_not_found' };

                const headerSelectAllControl = findHeaderSelectAllControl(root);
                const footerSelectAllControl = findFooterSelectAllControl(root);
                const selectAllControl = headerSelectAllControl || footerSelectAllControl;
                const before = checkedState(selectAllControl);
                let after = before;
                if (selectAllControl && before !== true) {
                    clickLikeUser(selectAllControl);
                    selectAllControl.dispatchEvent?.(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                    after = checkedState(selectAllControl);
                }
                let row_click_count = 0;
                if (after !== true) {
                    const rows = Array.from(root.querySelectorAll('tbody tr,[data-testid="beast-core-table-body"] tr'))
                        .filter((el) => isVisible(el));
                    for (const row of rows) {
                        const control = findControlNear(row);
                        if (!control || checkedState(control) === true) continue;
                        clickLikeUser(control);
                        row_click_count += 1;
                    }
                }

                const buttons = Array.from(root.querySelectorAll('button,[role="button"]'))
                    .filter((el) => isVisible(el))
                    .filter((el) => ((el.innerText || el.textContent || '').trim()) === '确认选择');
                if (!buttons.length) return {
                    handled: false,
                    modal_found: true,
                    reason: 'spec_confirm_button_not_found',
                    select_all_before: before,
                    select_all_after: after,
                };
                clickLikeUser(buttons[0]);
                const selectedText = (root.innerText || '').match(/已选规格\\s*[（(][^）)]*[）)]/)?.[0] || '';
                return {
                    handled: true,
                    modal_found: true,
                    select_all_found: Boolean(selectAllControl),
                    header_select_all_found: Boolean(headerSelectAllControl),
                    footer_select_all_found: Boolean(footerSelectAllControl),
                    select_all_before: before,
                    select_all_after: after,
                    row_click_count,
                    selected_text: selectedText,
                    confirm_clicked: true,
                };
            """
        )
    except Exception as exc:
        return {"handled": False, "modal_found": True, "reason": _safe_exc(exc)}

    if isinstance(result, dict):
        print(f"[{account_id}] 选择规格弹窗：{result}", flush=True)
        return result
    return {"handled": False, "modal_found": True, "reason": str(result)}


def _wait_no_spec_modal(page: DpPage, timeout: int = 8) -> bool:
    for _ in range(timeout):
        if not _wait_spec_modal(page, timeout=1):
            return True
        time.sleep(1)
    return False


def _set_promotion_dimension_to_spec_level(
    page: DpPage,
    account_id: str,
    product_ids: list[str],
) -> dict[str, Any]:
    target_ids = list(dict.fromkeys(str(value).strip() for value in product_ids if str(value).strip()))
    row_state = _read_activity_product_dimension_rows(page, target_ids)
    rows = row_state.get("rows") or []
    if not rows:
        return {
            "status": "failed",
            "step": "read_activity_product_rows",
            "error": row_state.get("reason") or "未找到活动商品表格行",
            "target_ids": target_ids,
            "row_state": row_state,
        }

    raw_page = getattr(page, "_page")
    results: list[dict[str, Any]] = []
    max_rounds = max(1, len(rows)) + 3
    for _ in range(max_rounds):
        row_state = _read_activity_product_dimension_rows(page, target_ids)
        rows = row_state.get("rows") or []
        pending = [
            row
            for row in rows
            if row.get("dimension") != "规格级"
        ]
        if not pending:
            return {
                "status": "success",
                "step": "promotion_dimension_spec_level",
                "target_ids": target_ids,
                "rows": rows,
                "results": results,
            }

        row = pending[0]
        open_result = _open_promotion_dimension_dropdown(page, row, target_ids)
        if open_result.get("clicked") and open_result.get("rect"):
            try:
                rect = open_result.get("rect") or {}
                left = float(rect.get("left") or 0)
                top = float(rect.get("top") or 0)
                width = float(rect.get("width") or 0)
                height = float(rect.get("height") or 0)
                if left > 0 and top > 0 and width > 0 and height > 0:
                    click_x = left + max(8, width - 12)
                    click_y = top + height / 2
                    raw_page.mouse.move(click_x, click_y)
                    time.sleep(0.1)
                    raw_page.mouse.click(click_x, click_y)
                    open_result["trusted_click"] = {"x": click_x, "y": click_y}
            except Exception as exc:
                open_result["trusted_click_error"] = _safe_exc(exc)
        if not open_result.get("clicked"):
            rect = row.get("rect") or {}
            x = float(rect.get("x") or 0)
            y = float(rect.get("y") or 0)
            if x > 0 and y > 0:
                raw_page.mouse.move(x, y)
                time.sleep(0.1)
                raw_page.mouse.down()
                time.sleep(0.05)
                raw_page.mouse.up()
                open_result = {
                    "clicked": True,
                    "method": "rect_fallback",
                    "initial": open_result,
                    "rect": rect,
                }
            else:
                results.append({"row": row, "status": "failed", "open": open_result})
                break

        time.sleep(0.8)

        option = _click_spec_level_option(page)
        if not option.get("clicked") and open_result.get("rect"):
            try:
                rect = open_result.get("rect") or {}
                left = float(rect.get("left") or 0)
                top = float(rect.get("top") or 0)
                width = float(rect.get("width") or 0)
                height = float(rect.get("height") or 0)
                if left > 0 and top > 0 and width > 0 and height > 0:
                    click_x = left + width / 2
                    click_y = top + height / 2
                    raw_page.mouse.move(click_x, click_y)
                    time.sleep(0.1)
                    raw_page.mouse.click(click_x, click_y)
                    time.sleep(0.8)
                    retry_option = _click_spec_level_option(page)
                    option["retry_after_center_click"] = {
                        "x": click_x,
                        "y": click_y,
                        "result": retry_option,
                    }
                    if retry_option.get("clicked"):
                        option = retry_option
            except Exception as exc:
                option["retry_after_center_click_error"] = _safe_exc(exc)
        if not option.get("clicked"):
            keyboard_result: dict[str, Any] = {"attempted": False}
            try:
                raw_page.keyboard.press("ArrowDown")
                time.sleep(0.2)
                raw_page.keyboard.press("Enter")
                keyboard_result = {"attempted": True}
                time.sleep(1)
            except Exception as exc:
                keyboard_result = {"attempted": True, "error": _safe_exc(exc)}

            fallback_state = _read_activity_product_dimension_rows(page, target_ids)
            fallback_rows = fallback_state.get("rows") or []
            fallback_row = next(
                (
                    item
                    for item in fallback_rows
                    if item.get("id") and item.get("id") == row.get("id")
                ),
                fallback_rows[0] if len(fallback_rows) == 1 else {},
            )
            if fallback_row.get("dimension") == "规格级":
                results.append(
                    {
                        "row_id": row.get("id"),
                        "before_dimension": row.get("dimension"),
                        "after_dimension": fallback_row.get("dimension"),
                        "option": option,
                        "open": open_result,
                        "keyboard": keyboard_result,
                        "reason": "already_spec_level_after_dropdown_click",
                    }
                )
                continue
            if _wait_spec_modal(page, timeout=3):
                modal = _confirm_all_specs_in_modal(page, account_id)
                if modal.get("modal_found"):
                    _wait_no_spec_modal(page, timeout=8)
                results.append(
                    {
                        "row_id": row.get("id"),
                        "before_dimension": row.get("dimension"),
                        "after_dimension": "规格级",
                        "option": option,
                        "open": open_result,
                        "keyboard": keyboard_result,
                        "modal": modal,
                    }
                )
                continue
            results.append(
                {
                    "row": row,
                    "status": "failed",
                    "open": open_result,
                    "option": option,
                    "keyboard": keyboard_result,
                    "fallback_row": fallback_row,
                }
            )
            break

        if option.get("rect"):
            try:
                rect = option.get("rect") or {}
                left = float(rect.get("left") or 0)
                top = float(rect.get("top") or 0)
                width = float(rect.get("width") or 0)
                height = float(rect.get("height") or 0)
                if width > 0 and height > 0:
                    click_x = left + width / 2
                    click_y = top + height / 2
                    raw_page.mouse.move(click_x, click_y)
                    time.sleep(0.1)
                    raw_page.mouse.click(click_x, click_y)
                    option["trusted_click"] = {"x": click_x, "y": click_y}
                    time.sleep(1)
            except Exception as exc:
                option["trusted_click_error"] = _safe_exc(exc)

        modal = _confirm_all_specs_in_modal(page, account_id)
        if modal.get("modal_found"):
            _wait_no_spec_modal(page, timeout=8)
        time.sleep(1)

        after_state = _read_activity_product_dimension_rows(page, target_ids)
        after_rows = after_state.get("rows") or []
        after_row = next(
            (
                item
                for item in after_rows
                if item.get("id") and item.get("id") == row.get("id")
            ),
            after_rows[0] if len(after_rows) == 1 else {},
        )
        results.append(
            {
                "row_id": row.get("id"),
                "before_dimension": row.get("dimension"),
                "after_dimension": after_row.get("dimension"),
                "open": open_result,
                "option": option,
                "modal": modal,
            }
        )

    final_state = _read_activity_product_dimension_rows(page, target_ids)
    final_rows = final_state.get("rows") or []
    unfinished = [row for row in final_rows if row.get("dimension") != "规格级"]
    return {
        "status": "failed" if unfinished else "success",
        "step": "promotion_dimension_spec_level",
        "error": "" if not unfinished else "仍有活动商品促销维度未切换到规格级",
        "target_ids": target_ids,
        "rows": final_rows,
        "unfinished": unfinished,
        "results": results,
    }


def _select_batch_reduction_mode(page: DpPage, account_id: str) -> dict[str, Any]:
    try:
        result = page.run_js(
            """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function textOf(el) {
                    return ((el.innerText || el.textContent || '').trim()).replace(/\\s+/g, '');
                }
                function clickLikeUser(el) {
                    el.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                function batchRoot() {
                    const nodes = Array.from(document.querySelectorAll('div,section,form'))
                        .filter((el) => isVisible(el))
                        .map((el) => {
                            const text = el.innerText || el.textContent || '';
                            const r = el.getBoundingClientRect();
                            return { el, text, rect: r, area: r.width * r.height };
                        })
                        .filter((item) => (
                            item.text.includes('批量设置')
                            && item.text.includes('确认设置')
                            && item.el.querySelector('input')
                            && item.rect.width > 200
                            && item.rect.height < 180
                        ))
                        .sort((a, b) => a.area - b.area);
                    return nodes[0]?.el || null;
                }
                const root = batchRoot();
                if (!root) return { clicked: false, reason: 'batch_setting_root_not_found' };
                const candidates = Array.from(root.querySelectorAll('[role="combobox"],button,[role="button"],div,span'))
                    .filter((el) => isVisible(el))
                    .map((el) => ({ el, text: textOf(el), rect: el.getBoundingClientRect() }))
                    .filter((item) => item.text === '折扣' || item.text === '立减')
                    .sort((a, b) => {
                        const aScore = (a.text === '折扣' ? 0 : 10) + a.rect.left / 1000 + a.rect.top / 10000;
                        const bScore = (b.text === '折扣' ? 0 : 10) + b.rect.left / 1000 + b.rect.top / 10000;
                        return aScore - bScore;
                    });
                const selected = candidates[0];
                if (!selected) return { clicked: false, reason: 'batch_mode_dropdown_not_found' };
                clickLikeUser(selected.el);
                return {
                    clicked: true,
                    before_text: selected.text,
                    rect: {
                        left: Math.round(selected.rect.left),
                        top: Math.round(selected.rect.top),
                        width: Math.round(selected.rect.width),
                        height: Math.round(selected.rect.height),
                    },
                };
            """
        )
    except Exception as exc:
        return {"clicked": False, "reason": _safe_exc(exc)}
    if isinstance(result, dict):
        print(f"[{account_id}] 批量设置下拉框：{result}", flush=True)
        return result
    return {"clicked": False, "reason": str(result)}


def _click_batch_reduction_option(page: DpPage, account_id: str) -> dict[str, Any]:
    try:
        result = page.run_js(
            """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function textOf(el) {
                    return ((el.innerText || el.textContent || '').trim()).replace(/\\s+/g, '');
                }
                function clickLikeUser(el) {
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                const candidates = Array.from(document.querySelectorAll('[role="option"],li,div,span'))
                    .filter((el) => isVisible(el))
                    .map((el) => ({ el, text: textOf(el), rect: el.getBoundingClientRect() }))
                    .filter((item) => item.text === '立减')
                    .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
                const selected = candidates[0];
                if (!selected) return { clicked: false, reason: 'reduction_option_not_found' };
                clickLikeUser(selected.el);
                return {
                    clicked: true,
                    text: selected.text,
                    rect: {
                        left: Math.round(selected.rect.left),
                        top: Math.round(selected.rect.top),
                        width: Math.round(selected.rect.width),
                        height: Math.round(selected.rect.height),
                    },
                };
            """
        )
    except Exception as exc:
        return {"clicked": False, "reason": _safe_exc(exc)}
    if isinstance(result, dict):
        print(f"[{account_id}] 批量设置选择立减：{result}", flush=True)
        return result
    return {"clicked": False, "reason": str(result)}


def _fill_batch_reduction_value_and_confirm(page: DpPage, account_id: str, value: str = "5") -> dict[str, Any]:
    try:
        result = page.run_js(
            """
                const value = String(arguments[0] || '');
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 4 && r.height > 4
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function textOf(el) {
                    return ((el.innerText || el.textContent || '').trim()).replace(/\\s+/g, '');
                }
                function clickLikeUser(el) {
                    el.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                function setInputValue(input, nextValue) {
                    input.focus();
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                    const tracker = input._valueTracker;
                    if (tracker) tracker.setValue(input.value || '');
                    if (setter) {
                        setter.call(input, '');
                    } else {
                        input.value = '';
                    }
                    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward', data: null }));
                    if (tracker) tracker.setValue('');
                    if (setter) {
                        setter.call(input, nextValue);
                    } else {
                        input.value = nextValue;
                    }
                    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: nextValue }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.blur();
                }
                function batchRoot() {
                    const nodes = Array.from(document.querySelectorAll('div,section,form'))
                        .filter((el) => isVisible(el))
                        .map((el) => {
                            const text = el.innerText || el.textContent || '';
                            const r = el.getBoundingClientRect();
                            return { el, text, rect: r, area: r.width * r.height };
                        })
                        .filter((item) => (
                            item.text.includes('批量设置')
                            && item.text.includes('确认设置')
                            && item.el.querySelector('input')
                            && item.rect.width > 200
                            && item.rect.height < 180
                        ))
                        .sort((a, b) => a.area - b.area);
                    return nodes[0]?.el || null;
                }
                const root = batchRoot();
                if (!root) return { confirmed: false, reason: 'batch_setting_root_not_found' };
                const input = Array.from(root.querySelectorAll('input'))
                    .filter((el) => isVisible(el))
                    .filter((el) => {
                        const testid = el.getAttribute('data-testid') || '';
                        const placeholder = el.getAttribute('placeholder') || '';
                        return testid.includes('inputNumber')
                            || placeholder.includes('立减金额')
                            || placeholder.includes('立减');
                    })
                    .filter((el) => !el.readOnly && !el.disabled)
                    .sort((a, b) => {
                        const ar = a.getBoundingClientRect();
                        const br = b.getBoundingClientRect();
                        const aScore = ((a.getAttribute('data-testid') || '').includes('inputNumber') ? 0 : 10)
                            + ((a.getAttribute('placeholder') || '').includes('立减金额') ? 0 : 5)
                            + ar.left / 1000;
                        const bScore = ((b.getAttribute('data-testid') || '').includes('inputNumber') ? 0 : 10)
                            + ((b.getAttribute('placeholder') || '').includes('立减金额') ? 0 : 5)
                            + br.left / 1000;
                        return aScore - bScore;
                    })[0];
                if (!input) return { confirmed: false, reason: 'batch_value_input_not_found' };
                setInputValue(input, value);
                input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: value, code: 'Digit' + value, keyCode: value.charCodeAt(0), which: value.charCodeAt(0) }));
                input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, cancelable: true, key: value, code: 'Digit' + value, keyCode: value.charCodeAt(0), which: value.charCodeAt(0) }));
                const buttons = Array.from(root.querySelectorAll('button,[role="button"],div,span'))
                    .filter((el) => isVisible(el))
                    .map((el) => ({ el, text: textOf(el), rect: el.getBoundingClientRect() }))
                    .filter((item) => item.text === '确认设置')
                    .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
                const button = buttons[0]?.el;
                if (!button) return { confirmed: false, reason: 'confirm_batch_setting_button_not_found', input_value: input.value };
                clickLikeUser(button);
                return {
                    confirmed: true,
                    input_value: input.value,
                    placeholder: input.getAttribute('placeholder') || '',
                    testid: input.getAttribute('data-testid') || '',
                    button_text: textOf(button),
                };
            """,
            value,
        )
    except Exception as exc:
        return {"confirmed": False, "reason": _safe_exc(exc)}
    if isinstance(result, dict):
        print(f"[{account_id}] 批量设置立减金额：{result}", flush=True)
        return result
    return {"confirmed": False, "reason": str(result)}


def _set_batch_reduction_discount(page: DpPage, account_id: str, value: str = "5") -> dict[str, Any]:
    dropdown = _select_batch_reduction_mode(page, account_id)
    if not dropdown.get("clicked"):
        return {
            "status": "failed",
            "step": "batch_reduction_discount",
            "error": dropdown.get("reason") or "无法点击批量设置下拉框",
            "dropdown": dropdown,
        }

    option = {"clicked": True, "reason": "already_reduction"}
    if str(dropdown.get("before_text") or "") != "立减":
        time.sleep(0.5)
        option = _click_batch_reduction_option(page, account_id)
        if not option.get("clicked"):
            return {
                "status": "failed",
                "step": "batch_reduction_discount",
                "error": option.get("reason") or "无法选择批量设置立减",
                "dropdown": dropdown,
                "option": option,
            }
    time.sleep(0.5)

    confirm = _fill_batch_reduction_value_and_confirm(page, account_id, value)
    if not confirm.get("confirmed"):
        return {
            "status": "failed",
            "step": "batch_reduction_discount",
            "error": confirm.get("reason") or "无法填写立减金额并确认设置",
            "dropdown": dropdown,
            "option": option,
            "confirm": confirm,
        }
    if str(confirm.get("input_value") or "") != str(value):
        return {
            "status": "failed",
            "step": "batch_reduction_discount",
            "error": f"立减金额输入后不是 {value}，当前为 {confirm.get('input_value')!r}",
            "dropdown": dropdown,
            "option": option,
            "confirm": confirm,
        }

    time.sleep(1)
    return {
        "status": "success",
        "step": "batch_reduction_discount",
        "value": value,
        "dropdown": dropdown,
        "option": option,
        "confirm": confirm,
    }


def _campaign_price_candidates(row: Any) -> dict[str, Any]:
    meta = row.spec_metadata or {}
    skus = meta.get("skus") if isinstance(meta, dict) else []
    first_sku = skus[0] if isinstance(skus, list) and skus else {}
    if not isinstance(first_sku, dict):
        first_sku = {}
    raw_candidates: list[str] = []
    if isinstance(skus, list):
        for sku in skus:
            if not isinstance(sku, dict):
                continue
            raw_candidates.extend(
                [
                    str(sku.get("combo_folder") or ""),
                    str(sku.get("model_code") or ""),
                    str(sku.get("style_code") or ""),
                ]
            )
    raw_candidates.extend([str(row.product_code or ""), str(row.family_code or "")])
    candidates: list[str] = []
    for item in raw_candidates:
        candidates.extend(price_rule_candidates(item))
    return {
        "mapping_id": row.mapping_id,
        "pdd_product_id": str(row.pdd_product_id or "").strip(),
        "product_code": str(row.product_code or "").strip(),
        "family_code": str(row.family_code or "").strip(),
        "image_set": str(row.image_set or "").strip(),
        "first_sku": first_sku,
        "price_rule_candidates": list(dict.fromkeys(candidates)),
    }


def _load_campaign_price_targets(mapping_ids: list[str]) -> dict[str, Any]:
    ids = [str(item).strip() for item in mapping_ids if str(item).strip()]
    if not ids:
        return {"status": "skipped", "reason": "no_published_mapping_ids", "targets": []}
    rows = get_published_products_by_mapping_ids(ids)
    price_ranges = load_pdd_price_ranges()
    targets: list[dict[str, Any]] = []
    for row in rows:
        target = _campaign_price_candidates(row)
        rule = find_pdd_price_range(price_ranges, target["price_rule_candidates"])
        target["price_rule"] = (
            {
                "code": rule.code,
                "min_price": rule.min_price,
                "max_price": rule.max_price,
            }
            if rule
            else None
        )
        targets.append(target)
    missing_ids = [item for item in ids if item not in {target["mapping_id"] for target in targets}]
    return {
        "status": "success",
        "targets": targets,
        "missing_mapping_ids": missing_ids,
        "price_rule_count": len(price_ranges),
    }


def _read_activity_discount_price_rows(page: DpPage) -> dict[str, Any]:
    try:
        result = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function textOf(el) {
                return (el.innerText || el.textContent || '').trim();
            }
            const roots = Array.from(document.querySelectorAll(
                '[data-testid="beast-core-table"], table, [class*="TB_outerWrapper"], [class*="TB_table"]'
            ))
                .filter((el) => isVisible(el))
                .filter((el) => {
                    const text = textOf(el);
                    return text.includes('活动库存')
                        && text.includes('促销维度')
                        && (text.includes('折后价') || text.includes('拼单价') || text.includes('立减'));
                });
            const rows = [];
            for (const root of roots) {
                const tableRows = Array.from(root.querySelectorAll(
                    'tbody tr,[data-testid="beast-core-table-body"] tr'
                )).filter(isVisible);
                for (const row of tableRows) {
                    const text = textOf(row);
                    if (!text.includes('ID:') && !text.includes('拼单价')) continue;
                    const ids = Array.from(text.matchAll(/ID[:：]?\\s*(\\d{6,})/g)).map((m) => m[1]);
                    const prices = Array.from(text.matchAll(/¥\\s*([0-9]+(?:\\.[0-9]+)?)/g))
                        .map((m) => Number(m[1]))
                        .filter((n) => Number.isFinite(n) && n > 0);
                    const cells = Array.from(row.querySelectorAll('td,[role="cell"],[data-testid="beast-core-table-td"]'))
                        .filter(isVisible)
                        .map((cell) => textOf(cell));
                    rows.push({
                        ids,
                        prices,
                        check_price: prices.length ? Math.min(...prices) : null,
                        text: text.slice(0, 500),
                        cells: cells.slice(0, 16),
                    });
                }
            }
            return { rows, row_count: rows.length };
            """
        )
    except Exception as exc:
        return {"rows": [], "row_count": 0, "error": _safe_exc(exc)}
    if isinstance(result, dict):
        return result
    return {"rows": [], "row_count": 0, "raw": result}


def _collect_activity_discount_price_rows(page: DpPage, max_scrolls: int = 10) -> dict[str, Any]:
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    snapshots: list[dict[str, Any]] = []
    try:
        page.run_js("window.scrollTo(0, 0);")
        time.sleep(0.5)
    except Exception:
        pass
    for _ in range(max_scrolls):
        state = _read_activity_discount_price_rows(page)
        snapshots.append(
            {
                "row_count": state.get("row_count"),
                "error": state.get("error"),
                "raw": state.get("raw"),
            }
        )
        for row in state.get("rows") or []:
            ids = ",".join(str(item) for item in row.get("ids") or [])
            key = ids or str(row.get("text") or "")[:120]
            if not key or key in seen:
                continue
            seen.add(key)
            collected.append(row)
        try:
            scroll_state = page.run_js(
                """
                const before = window.scrollY || document.documentElement.scrollTop || 0;
                const step = Math.max(500, Math.floor(window.innerHeight * 0.75));
                window.scrollBy(0, step);
                const after = window.scrollY || document.documentElement.scrollTop || 0;
                const maxY = Math.max(
                    document.body.scrollHeight,
                    document.documentElement.scrollHeight
                ) - window.innerHeight;
                return { before, after, maxY };
                """
            )
            if isinstance(scroll_state, dict) and (
                float(scroll_state.get("after") or 0) >= float(scroll_state.get("maxY") or 0) - 5
                or float(scroll_state.get("after") or 0) == float(scroll_state.get("before") or 0)
            ):
                break
            time.sleep(0.5)
        except Exception:
            break
    return {"rows": collected, "row_count": len(collected), "snapshots": snapshots}


def _delete_activity_product_by_id(page: DpPage, product_id: str) -> dict[str, Any]:
    try:
        page.run_js("window.scrollTo(0, 0);")
        time.sleep(0.3)
    except Exception:
        pass

    last_result: dict[str, Any] = {"deleted": False, "reason": "not_attempted", "product_id": product_id}
    for _ in range(10):
        try:
            result = page.run_js(
                """
                const productId = String(arguments[0] || '');
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && parseFloat(s.opacity || '1') > 0.05;
                }
                function textOf(el) {
                    return (el.innerText || el.textContent || '').trim();
                }
                function clickLikeUser(el) {
                    el.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const r = el.getBoundingClientRect();
                    const x = r.left + r.width / 2;
                    const y = r.top + r.height / 2;
                    const target = document.elementFromPoint(x, y) || el;
                    for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                        target.dispatchEvent(new MouseEvent(ev, {
                            bubbles: true,
                            cancelable: true,
                            view: window,
                            clientX: x,
                            clientY: y,
                        }));
                    }
                    if (target !== el) el.click();
                }
                const rows = Array.from(document.querySelectorAll(
                    'tbody tr,[data-testid="beast-core-table-body"] tr'
                ))
                    .filter(isVisible)
                    .map((row) => ({ row, text: textOf(row) }))
                    .filter((item) => item.text.includes(productId));
                const rowItem = rows[0];
                if (!rowItem) return { deleted: false, reason: 'activity_row_not_found', product_id: productId };
                const controls = Array.from(rowItem.row.querySelectorAll(
                    '[data-tracking-viewid="el_deleting_element"],[data-testid="beast-core-button-link"],button,a,span,div'
                ))
                    .filter(isVisible)
                    .map((el) => ({ el, text: textOf(el), rect: el.getBoundingClientRect() }))
                    .filter((item) => item.text === '删除商品' || item.text === '删除')
                    .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
                if (!controls.length) {
                    return { deleted: false, reason: 'delete_button_not_found', product_id: productId, row_text: rowItem.text.slice(0, 300) };
                }
                clickLikeUser(controls[0].el);
                return { deleted: true, product_id: productId, button_text: controls[0].text };
                """,
                product_id,
            )
        except Exception as exc:
            result = {"deleted": False, "reason": _safe_exc(exc), "product_id": product_id}
        if not isinstance(result, dict):
            result = {"deleted": False, "reason": str(result), "product_id": product_id}
        last_result = result
        if result.get("deleted") or result.get("reason") != "activity_row_not_found":
            break
        try:
            scroll_state = page.run_js(
                """
                const before = window.scrollY || document.documentElement.scrollTop || 0;
                const step = Math.max(500, Math.floor(window.innerHeight * 0.75));
                window.scrollBy(0, step);
                const after = window.scrollY || document.documentElement.scrollTop || 0;
                const maxY = Math.max(
                    document.body.scrollHeight,
                    document.documentElement.scrollHeight
                ) - window.innerHeight;
                return { before, after, maxY };
                """
            )
            if isinstance(scroll_state, dict) and (
                float(scroll_state.get("after") or 0) >= float(scroll_state.get("maxY") or 0) - 5
                or float(scroll_state.get("after") or 0) == float(scroll_state.get("before") or 0)
            ):
                break
            time.sleep(0.4)
        except Exception:
            break

    result = last_result
    if not result.get("deleted"):
        return result

    try:
        time.sleep(0.8)
        confirm = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function textOf(el) {
                return (el.innerText || el.textContent || '').trim();
            }
            function clickLikeUser(el) {
                const r = el.getBoundingClientRect();
                const x = r.left + r.width / 2;
                const y = r.top + r.height / 2;
                const target = document.elementFromPoint(x, y) || el;
                for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    target.dispatchEvent(new MouseEvent(ev, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y,
                    }));
                }
                if (target !== el) el.click();
            }
            const modals = Array.from(document.querySelectorAll('[data-testid="beast-core-modal"], [class*="MDL_modal"]'))
                .filter(isVisible);
            if (!modals.length) return { clicked: false, reason: 'confirm_modal_not_found' };
            const root = modals[modals.length - 1];
            const buttons = Array.from(root.querySelectorAll('button,[role="button"],a,span,div'))
                .filter(isVisible)
                .map((el) => ({ el, text: textOf(el), rect: el.getBoundingClientRect() }))
                .filter((item) => ['确认', '确定', '删除', '确认删除'].includes(item.text))
                .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
            if (!buttons.length) return { clicked: false, reason: 'confirm_not_found' };
            clickLikeUser(buttons[0].el);
            return { clicked: true, text: buttons[0].text };
            """
        )
        result["confirm"] = confirm
        time.sleep(1)
    except Exception as exc:
        result["confirm_error"] = _safe_exc(exc)
    return result


def _filter_activity_products_by_price(
    page: DpPage,
    account_id: str,
    mapping_ids: list[str],
) -> dict[str, Any]:
    target_state = _load_campaign_price_targets(mapping_ids)
    if target_state.get("status") == "skipped":
        return target_state

    time.sleep(2)
    row_state = _collect_activity_discount_price_rows(page)
    rows = row_state.get("rows") or []
    decisions: list[dict[str, Any]] = []
    kept: list[str] = []
    deleted: list[str] = []

    for target in target_state.get("targets") or []:
        product_id = str(target.get("pdd_product_id") or "").strip()
        row = next(
            (
                item
                for item in rows
                if product_id and product_id in [str(pid) for pid in item.get("ids") or []]
            ),
            {},
        )
        rule = target.get("price_rule")
        check_price = row.get("check_price") if isinstance(row, dict) else None
        ok = (
            isinstance(rule, dict)
            and isinstance(check_price, (int, float))
            and float(rule["min_price"]) <= float(check_price) <= float(rule["max_price"])
        )
        decision: dict[str, Any] = {
            "product_id": product_id,
            "mapping_id": target.get("mapping_id"),
            "product_code": target.get("product_code"),
            "family_code": target.get("family_code"),
            "first_sku": target.get("first_sku"),
            "price_rule_candidates": target.get("price_rule_candidates"),
            "price_rule": rule,
            "check_price": check_price,
            "row_found": bool(row),
            "keep": ok,
            "reason": "price_in_range" if ok else "price_out_of_range_or_missing_rule",
        }
        if ok:
            kept.append(product_id)
        else:
            delete_result = _delete_activity_product_by_id(page, product_id) if product_id else {
                "deleted": False,
                "reason": "missing_product_id",
            }
            decision["delete"] = delete_result
            if delete_result.get("deleted"):
                deleted.append(product_id)
        decisions.append(decision)

    print(
        f"[{account_id}] 活动价格筛选：保留 {len(kept)} 个，删除 {len(deleted)} 个",
        flush=True,
    )
    return {
        "status": "success" if kept else "no_eligible_products",
        "step": "campaign_price_filter",
        "kept_product_ids": kept,
        "deleted_product_ids": deleted,
        "decisions": decisions,
        "targets": target_state,
        "activity_rows": row_state,
    }


def _uncheck_surprise_discount(page: DpPage, account_id: str) -> dict[str, Any]:
    """
    取消底部「同步设置惊喜优惠」复选框。

    返回 checked=false 才算成功；没有找到该控件按失败处理，避免误以为完成。
    """
    try:
        page.run_js("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)
        result = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function eventClick(el) {
                el.scrollIntoView({ block: 'center', inline: 'nearest' });
                const r = el.getBoundingClientRect();
                const x = r.left + Math.min(Math.max(6, r.width / 2), Math.max(6, r.width - 6));
                const y = r.top + Math.min(Math.max(6, r.height / 2), Math.max(6, r.height - 6));
                const target = document.elementFromPoint(x, y) || el;
                for (const ev of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
                    target.dispatchEvent(new MouseEvent(ev, {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y,
                    }));
                }
                if (target !== el) el.click();
            }
            function checkedState(box) {
                if (!box) return null;
                const dataChecked = box.getAttribute?.('data-checked');
                if (dataChecked === 'true') return true;
                if (dataChecked === 'false') return false;
                const cls = String(box.className || '').toLowerCase();
                if (
                    cls.includes('active')
                    || cls.includes('checked')
                    || cls.includes('is-checked')
                    || cls.includes('haschecksquare')
                ) {
                    return true;
                }
                if ((box.tagName || '').toLowerCase() === 'input') return Boolean(box.checked);
                const input = box.querySelector?.('input[type="checkbox"]');
                if (input) return Boolean(input.checked);
                const aria = box.getAttribute?.('aria-checked');
                if (aria === 'true') return true;
                if (aria === 'false') return false;
                return false;
            }
            function findControlNear(node) {
                let cur = node;
                for (let depth = 0; depth < 8 && cur; depth++, cur = cur.parentElement) {
                    const label = cur.closest?.('label');
                    if (label && label.querySelector?.('input[type="checkbox"]')) return label;
                    const input = cur.querySelector?.('input[type="checkbox"]');
                    if (input) {
                        const inputLabel = input.closest?.('label');
                        if (inputLabel) return inputLabel;
                        const wrap = input.closest?.(
                            '[class*="checkbox"], [class*="Checkbox"], [class*="checkBox"]'
                        );
                        if (wrap) return wrap;
                        return input;
                    }
                    const roleBox = cur.querySelector?.('[role="checkbox"]');
                    if (roleBox) return roleBox;
                    const classBox = cur.querySelector?.(
                        '[class*="checkbox"], [class*="Checkbox"], [class*="checkBox"]'
                    );
                    if (classBox) return classBox;
                }
                return null;
            }
            const directRoot = document.querySelector('#surpriseCouponCheck');
            const directBox = directRoot?.querySelector?.('[data-testid="beast-core-checkbox"]')
                || directRoot?.querySelector?.('label,input[type="checkbox"],[role="checkbox"]');
            if (directBox && isVisible(directBox)) {
                const before = checkedState(directBox);
                const directClickTarget = directBox.querySelector?.(
                    '[data-testid="beast-core-checkbox-checkIcon"], [class*="CBX_square"], svg'
                ) || directBox;
                if (before === true) {
                    eventClick(directClickTarget);
                    let after = checkedState(directBox);
                    if (after === true && directClickTarget !== directBox) {
                        eventClick(directBox);
                        after = checkedState(directBox);
                    }
                    return {
                        found: true,
                        unchecked: after === false,
                        before,
                        after,
                        method: 'direct_surprise_coupon_checkbox',
                        rect: (() => {
                            const r = directClickTarget.getBoundingClientRect();
                            return {
                                left: r.left,
                                top: r.top,
                                width: r.width,
                                height: r.height,
                                x: r.left + r.width / 2,
                                y: r.top + r.height / 2,
                            };
                        })(),
                        text: (directRoot.innerText || directRoot.textContent || '').trim(),
                    };
                }
                return {
                    found: true,
                    unchecked: true,
                    before,
                    after: before,
                    method: 'direct_surprise_coupon_checkbox',
                    text: (directRoot.innerText || directRoot.textContent || '').trim(),
                };
            }
            const nodes = Array.from(document.querySelectorAll('label,span,div,p'));
            const matches = nodes
                .filter((el) => isVisible(el))
                .filter((el) => ((el.innerText || el.textContent || '').trim()).includes('同步设置惊喜优惠'))
                .map((el) => ({
                    el,
                    rect: el.getBoundingClientRect(),
                    text: (el.innerText || el.textContent || '').trim(),
                }))
                .sort((a, b) => b.rect.top - a.rect.top);

            for (const item of matches) {
                const control = findControlNear(item.el);
                if (!control) continue;
                const before = checkedState(control);
                if (before === true) {
                    eventClick(control);
                    const after = checkedState(control);
                    return { found: true, unchecked: after === false, before, after, text: item.text };
                }
                return { found: true, unchecked: true, before, after: before, text: item.text };
            }
            return { found: false, unchecked: false, before: null, after: null, text: '' };
            """
        )
    except Exception as exc:
        return {
            "found": False,
            "unchecked": False,
            "error": _safe_exc(exc),
        }

    if isinstance(result, dict):
        if result.get("found") and not result.get("unchecked") and result.get("rect"):
            try:
                raw_page = getattr(page, "_page")
                rect = result.get("rect") or {}
                x = float(rect.get("x") or 0)
                y = float(rect.get("y") or 0)
                if x > 0 and y > 0:
                    raw_page.mouse.move(x, y)
                    time.sleep(0.1)
                    raw_page.mouse.click(x, y)
                    time.sleep(0.5)
                    verify = page.run_js(
                        """
                        function isVisible(el) {
                            if (!el || !el.getBoundingClientRect) return false;
                            const r = el.getBoundingClientRect();
                            const s = window.getComputedStyle(el);
                            return r.width > 2 && r.height > 2
                                && s.display !== 'none'
                                && s.visibility !== 'hidden'
                                && parseFloat(s.opacity || '1') > 0.05;
                        }
                        function checkedState(box) {
                            if (!box) return null;
                            const dataChecked = box.getAttribute?.('data-checked');
                            if (dataChecked === 'true') return true;
                            if (dataChecked === 'false') return false;
                            const cls = String(box.className || '').toLowerCase();
                            if (
                                cls.includes('active')
                                || cls.includes('checked')
                                || cls.includes('is-checked')
                                || cls.includes('haschecksquare')
                            ) return true;
                            if ((box.tagName || '').toLowerCase() === 'input') return Boolean(box.checked);
                            const input = box.querySelector?.('input[type="checkbox"]');
                            if (input) return Boolean(input.checked);
                            return false;
                        }
                        const directRoot = document.querySelector('#surpriseCouponCheck');
                        const directBox = directRoot?.querySelector?.('[data-testid="beast-core-checkbox"]')
                            || directRoot?.querySelector?.('label,input[type="checkbox"],[role="checkbox"]');
                        const checked = checkedState(directBox);
                        return {
                            found: Boolean(directBox && isVisible(directBox)),
                            checked,
                            unchecked: checked === false,
                            text: (directRoot?.innerText || directRoot?.textContent || '').trim(),
                        };
                        """
                    )
                    result["trusted_click"] = {"x": x, "y": y, "verify": verify}
                    if isinstance(verify, dict) and verify.get("found"):
                        result["after"] = verify.get("checked")
                        result["unchecked"] = bool(verify.get("unchecked"))
                        if verify.get("text"):
                            result["text"] = verify.get("text")
            except Exception as exc:
                result["trusted_click_error"] = _safe_exc(exc)
        print(
            f"[{account_id}] 同步设置惊喜优惠：found={result.get('found')} "
            f"before={result.get('before')} after={result.get('after')}",
            flush=True,
        )
        return result
    return {"found": False, "unchecked": False, "raw": result}


def setup_limited_time_campaign(
    page: DpPage,
    account_id: str,
    *,
    pdd_product_ids: list[str] | None = None,
    published_mapping_ids: list[str] | None = None,
) -> dict[str, Any]:
    """进入限时限量购创建页，并取消「同步设置惊喜优惠」。"""
    selected_pdd_product_ids = list(dict.fromkeys(pdd_product_ids or []))
    selected_mapping_ids = list(dict.fromkeys(published_mapping_ids or []))
    try:
        if not _open_marketing_tools(page, account_id):
            return {
                "status": "failed",
                "step": "open_marketing_tools",
                "error": "未能打开营销工具页或会话已跳转登录",
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }
        if not _open_limited_time_tool(page, account_id):
            return {
                "status": "failed",
                "step": "open_limited_time_tool",
                "error": "未找到或无法点击限时限量购",
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }
        if not _click_create(page, account_id):
            return {
                "status": "failed",
                "step": "click_create",
                "error": "未找到或无法点击立即创建",
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }
        if not _wait_activity_settings(page, account_id):
            return {
                "status": "failed",
                "step": "wait_activity_settings",
                "error": "未进入活动设置页或未出现惊喜优惠设置",
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }

        product_selection = _select_campaign_products(page, account_id, selected_pdd_product_ids)
        if product_selection.get("status") != "success":
            return {
                "status": "failed",
                "step": product_selection.get("step") or "select_campaign_products",
                "error": product_selection.get("error") or "选择活动商品失败",
                "product_selection": product_selection,
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }

        promotion_dimension = _set_promotion_dimension_to_spec_level(
            page,
            account_id,
            selected_pdd_product_ids,
        )
        if promotion_dimension.get("status") != "success":
            return {
                "status": "failed",
                "step": promotion_dimension.get("step") or "promotion_dimension_spec_level",
                "error": promotion_dimension.get("error") or "促销维度未切换到规格级",
                "promotion_dimension": promotion_dimension,
                "product_selection": product_selection,
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }

        batch_reduction = _set_batch_reduction_discount(page, account_id, value="5")
        if batch_reduction.get("status") != "success":
            return {
                "status": "failed",
                "step": batch_reduction.get("step") or "batch_reduction_discount",
                "error": batch_reduction.get("error") or "批量设置立减失败",
                "batch_reduction": batch_reduction,
                "promotion_dimension": promotion_dimension,
                "product_selection": product_selection,
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }

        price_filter = _filter_activity_products_by_price(page, account_id, selected_mapping_ids)
        if price_filter.get("status") == "no_eligible_products":
            return {
                "status": "failed",
                "step": "campaign_price_filter",
                "error": "没有符合 pdd.xls 价格区间的活动商品，已删除不符合商品，不继续创建活动",
                "price_filter": price_filter,
                "batch_reduction": batch_reduction,
                "promotion_dimension": promotion_dimension,
                "product_selection": product_selection,
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }

        checkbox = _uncheck_surprise_discount(page, account_id)
        if not checkbox.get("found"):
            return {
                "status": "failed",
                "step": "uncheck_surprise_discount",
                "error": "未找到同步设置惊喜优惠复选框",
                "checkbox": checkbox,
                "price_filter": price_filter,
                "batch_reduction": batch_reduction,
                "promotion_dimension": promotion_dimension,
                "product_selection": product_selection,
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }
        if not checkbox.get("unchecked"):
            return {
                "status": "failed",
                "step": "uncheck_surprise_discount",
                "error": "同步设置惊喜优惠仍处于勾选状态",
                "checkbox": checkbox,
                "price_filter": price_filter,
                "batch_reduction": batch_reduction,
                "promotion_dimension": promotion_dimension,
                "product_selection": product_selection,
                "current_url": page.url,
                "selected_pdd_product_ids": selected_pdd_product_ids,
                "published_mapping_ids": selected_mapping_ids,
            }

        return {
            "status": "success",
            "step": "ready_for_next",
            "message": "已进入限时限量购活动设置页，选择活动商品，促销维度切换为规格级，并取消勾选同步设置惊喜优惠",
            "checkbox": checkbox,
            "price_filter": price_filter,
            "batch_reduction": batch_reduction,
            "promotion_dimension": promotion_dimension,
            "product_selection": product_selection,
            "current_url": page.url,
            "selected_pdd_product_ids": selected_pdd_product_ids,
            "published_mapping_ids": selected_mapping_ids,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "step": "unexpected",
            "error": _safe_exc(exc),
            "current_url": page.url,
            "selected_pdd_product_ids": selected_pdd_product_ids,
            "published_mapping_ids": selected_mapping_ids,
        }
