"""限时限量购活动初始化页面操作。"""

from __future__ import annotations

import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage

MARKETING_TOOL_URLS = (
    "https://mms.pinduoduo.com/marketing/tools",
    "https://mms.pinduoduo.com/marketing/marketing-tools",
    "https://mms.pinduoduo.com/marketing/marketing_tool",
)


def _safe_exc(exc: BaseException, limit: int = 300) -> str:
    msg = str(exc)
    if len(msg) > limit:
        msg = msg[:limit] + "..."
    return msg.encode("utf-8", errors="replace").decode("utf-8")


def _body_text(page: DpPage) -> str:
    try:
        return str(page.run_js("return document.body?.innerText || '';") or "")
    except Exception:
        return ""


def _click_text(page: DpPage, text: str, timeout: float = 3) -> bool:
    ele = page.ele(f"text:{text}", timeout=timeout)
    if not ele:
        return False
    ele.click(by_js=True)
    time.sleep(1)
    return True


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


def _open_limited_time_tool(page: DpPage, account_id: str) -> bool:
    """在营销工具页点击「限时限量购」。"""
    try:
        clicked = page.run_js(
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
            function clickableParent(el) {
                let cur = el;
                for (let i = 0; i < 8 && cur && cur !== document.body; i++) {
                    const tag = (cur.tagName || '').toLowerCase();
                    const role = cur.getAttribute?.('role') || '';
                    const cursor = window.getComputedStyle(cur).cursor;
                    if (tag === 'a' || tag === 'button' || role === 'button' || cursor === 'pointer') {
                        return cur;
                    }
                    cur = cur.parentElement;
                }
                return el;
            }
            const nodes = Array.from(document.querySelectorAll('a,button,div,span'));
            const candidates = [];
            for (const el of nodes) {
                if (!isVisible(el)) continue;
                const text = (el.innerText || el.textContent || '').trim();
                if (!text.includes('限时限量购')) continue;
                const root = clickableParent(el);
                const rect = root.getBoundingClientRect();
                candidates.push({ el: root, score: rect.top * 10 + rect.left });
            }
            candidates.sort((a, b) => a.score - b.score);
            if (!candidates.length) return false;
            candidates[0].el.click();
            return true;
            """
        )
        if clicked:
            time.sleep(3)
            print(f"[{account_id}] 已进入限时限量购", flush=True)
            return True
    except Exception as exc:
        print(f"[{account_id}] 点击限时限量购异常：{_safe_exc(exc)}", flush=True)
    return _click_text(page, "限时限量购", timeout=3)


def _click_create(page: DpPage, account_id: str) -> bool:
    """点击限时限量购页的「立即创建」。"""
    try:
        clicked = page.run_js(
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
            const nodes = Array.from(document.querySelectorAll('button,a,span,div'));
            const candidates = [];
            for (const el of nodes) {
                if (!isVisible(el)) continue;
                const text = (el.innerText || el.textContent || '').trim();
                if (text !== '立即创建') continue;
                let cur = el;
                for (let i = 0; i < 5 && cur && cur !== document.body; i++) {
                    const tag = (cur.tagName || '').toLowerCase();
                    const role = cur.getAttribute?.('role') || '';
                    const cursor = window.getComputedStyle(cur).cursor;
                    if (tag === 'button' || tag === 'a' || role === 'button' || cursor === 'pointer') {
                        break;
                    }
                    cur = cur.parentElement;
                }
                const target = cur && cur !== document.body ? cur : el;
                const r = target.getBoundingClientRect();
                candidates.push({ el: target, score: r.top * 10 + r.left });
            }
            candidates.sort((a, b) => a.score - b.score);
            if (!candidates.length) return false;
            candidates[0].el.click();
            return true;
            """
        )
        if clicked:
            time.sleep(4)
            print(f"[{account_id}] 已点击立即创建", flush=True)
            return True
    except Exception as exc:
        print(f"[{account_id}] 点击立即创建异常：{_safe_exc(exc)}", flush=True)
    return _click_text(page, "立即创建", timeout=5)


def _wait_activity_settings(page: DpPage, account_id: str, timeout: int = 20) -> bool:
    for _ in range(timeout):
        text = _body_text(page)
        if "活动设置" in text and ("同步设置惊喜优惠" in text or "惊喜优惠" in text):
            return True
        time.sleep(1)
    print(f"[{account_id}] 未确认进入活动设置页", flush=True)
    return False


def _uncheck_surprise_discount(page: DpPage, account_id: str) -> dict[str, Any]:
    """
    取消底部「同步设置惊喜优惠」复选框。

    返回 checked=false 才算成功；没有找到该控件按失败处理，避免误以为完成。
    """
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
            function eventClick(el) {
                el.scrollIntoView({ block: 'center', inline: 'nearest' });
                el.click();
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
                if (cls.includes('checked') || cls.includes('is-checked')) return true;
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
        print(
            f"[{account_id}] 同步设置惊喜优惠：found={result.get('found')} "
            f"before={result.get('before')} after={result.get('after')}",
            flush=True,
        )
        return result
    return {"found": False, "unchecked": False, "raw": result}


def setup_limited_time_campaign(page: DpPage, account_id: str) -> dict[str, Any]:
    """进入限时限量购创建页，并取消「同步设置惊喜优惠」。"""
    try:
        if not _open_marketing_tools(page, account_id):
            return {
                "status": "failed",
                "step": "open_marketing_tools",
                "error": "未能打开营销工具页或会话已跳转登录",
                "current_url": page.url,
            }
        if not _open_limited_time_tool(page, account_id):
            return {
                "status": "failed",
                "step": "open_limited_time_tool",
                "error": "未找到或无法点击限时限量购",
                "current_url": page.url,
            }
        if not _click_create(page, account_id):
            return {
                "status": "failed",
                "step": "click_create",
                "error": "未找到或无法点击立即创建",
                "current_url": page.url,
            }
        if not _wait_activity_settings(page, account_id):
            return {
                "status": "failed",
                "step": "wait_activity_settings",
                "error": "未进入活动设置页或未出现惊喜优惠设置",
                "current_url": page.url,
            }

        checkbox = _uncheck_surprise_discount(page, account_id)
        if not checkbox.get("found"):
            return {
                "status": "failed",
                "step": "uncheck_surprise_discount",
                "error": "未找到同步设置惊喜优惠复选框",
                "checkbox": checkbox,
                "current_url": page.url,
            }
        if not checkbox.get("unchecked"):
            return {
                "status": "failed",
                "step": "uncheck_surprise_discount",
                "error": "同步设置惊喜优惠仍处于勾选状态",
                "checkbox": checkbox,
                "current_url": page.url,
            }

        return {
            "status": "success",
            "step": "ready_for_next",
            "message": "已进入限时限量购活动设置页，并取消勾选同步设置惊喜优惠",
            "checkbox": checkbox,
            "current_url": page.url,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "step": "unexpected",
            "error": _safe_exc(exc),
            "current_url": page.url,
        }
