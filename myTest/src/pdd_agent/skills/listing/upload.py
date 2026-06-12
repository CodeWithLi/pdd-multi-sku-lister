"""多规格上架页面操作（Playwright + DrissionPage 兼容层）。"""

from __future__ import annotations

import re
import random
import time
from datetime import datetime
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.domain.models import ListingUnit
from pdd_agent.paths import PROJECT_ROOT
from pdd_agent.skills.delist.time_utils import (
    extract_product_id_from_text,
    format_datetime,
)
from pdd_agent.skills.listing.multi_spec_page import (
    _safe_exc,
    add_style_and_model_specs,
    fill_multi_spec_rows,
    wait_multi_sku_rows,
)
from pdd_agent.skills.listing.page_ai_title import apply_title_after_cover_upload
from pdd_agent.skills.listing.spec_labels import enrich_listing_unit_specs
from pdd_agent.skills.listing.title import resolve_listing_title


def _error_screenshot_path(filename: str) -> str:
    d = PROJECT_ROOT / "data" / "runs" / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / filename)


def _unit_spec_metadata(unit: ListingUnit) -> dict[str, Any]:
    return {
        "family_code": unit.family_code,
        "product_code": unit.product_code,
        "image_set": unit.image_set,
        "listing_label": unit.listing_label,
        "merchant_code": unit.merchant_code,
        "root": str(unit.root),
        "carousel_images": [str(path) for path in unit.carousel_images],
        "detail_images": [str(path) for path in unit.detail_images],
        "style_codes": list(unit.style_codes),
        "model_codes": list(unit.model_codes),
        "skus": [
            {
                "style_code": sku.style_code,
                "style_name": sku.style_name,
                "model_code": sku.model_code,
                "model_name": sku.model_name,
                "combo_folder": sku.combo_folder,
                "preview_image": str(sku.preview_image),
                "inventory": sku.inventory,
                "group_price": sku.group_price,
                "single_price": sku.single_price,
            }
            for sku in unit.skus
        ],
    }


GOODS_LIST_URLS = (
    "https://mms.pinduoduo.com/goods/goods_list",
    "https://mms.pinduoduo.com/goods/goods-list",
    "https://mms.pinduoduo.com/goods/list",
)


def _clear_beforeunload(page: DpPage) -> None:
    try:
        page.run_js("window.onbeforeunload = null;")
    except Exception:
        pass


def _listing_result(
    *,
    unit: ListingUnit,
    status: str,
    reason: str = "",
    error: str = "",
    title: str = "",
    retryable: bool = False,
    legacy_status: str = "",
) -> dict[str, Any]:
    return {
        "listing_label": unit.listing_label,
        "product_code": unit.product_code,
        "family_code": unit.family_code,
        "image_set": unit.image_set,
        "merchant_code": unit.merchant_code,
        "spec_metadata": _unit_spec_metadata(unit),
        "platform_listing_code": "",
        "pdd_product_id": "",
        "pdd_product_id_capture_status": "",
        "status": status,
        "retryable": retryable,
        "reason": reason,
        "error": error,
        "title": title,
        "legacy_status": legacy_status or status,
    }


def _normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", "", (value or "")).lower()


def _row_matches_title(row_text: str, title: str) -> bool:
    title_norm = _normalize_match_text(title)
    if not title_norm:
        return True
    row_norm = _normalize_match_text(row_text)
    if title_norm in row_norm:
        return True
    title_parts = [
        part
        for part in re.split(r"[\s,，、/|｜()（）【】\[\]_-]+", title)
        if len(part.strip()) >= 2
    ]
    if not title_parts:
        return False
    matched = sum(1 for part in title_parts if _normalize_match_text(part) in row_norm)
    return matched >= max(1, min(3, len(title_parts)))


def _classify_exception(exc: Exception) -> tuple[str, bool]:
    err = _safe_exc(exc)
    low = err.lower()
    if any(k in err for k in ("验证码", "滑块", "登录", "扫码", "短信")):
        return "needs_manual_login_or_captcha", True
    if any(k in err for k in ("分类", "类目", "SKU", "规格", "预览图", "上传")):
        return "page_or_material_changed", True
    if "timeout" in low or "超时" in err or "disconnect" in low or "连接已断开" in err:
        return "browser_transient_error", True
    return "unexpected_error", False


def _dismiss_address_required_page(page: DpPage, account_id: str, label: str) -> bool:
    """
    拼多多偶尔会在发布页弹出「请尽快填写真实有效联系/经营地址」遮罩。
    这个弹窗会挡住后续分类/上传操作；优先点击弹窗左上角的关闭 X。
    """
    try:
        result = page.run_js(
            """
            const bodyText = document.body?.innerText || '';
            const present = bodyText.includes('真实有效')
                && (bodyText.includes('联系/经营地址') || bodyText.includes('经营地址'))
                && bodyText.includes('确认补充');
            if (!present) return { present: false, clicked: false };

            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }

            function clickableParent(el) {
                let cur = el;
                for (let i = 0; i < 5 && cur && cur !== document.body; i++) {
                    const tag = (cur.tagName || '').toLowerCase();
                    const role = cur.getAttribute?.('role') || '';
                    const cls = cur.className ? String(cur.className) : '';
                    const cursor = window.getComputedStyle(cur).cursor;
                    if (tag === 'button' || tag === 'a' || role === 'button'
                        || cursor === 'pointer' || cls.toLowerCase().includes('close')) {
                        return cur;
                    }
                    cur = cur.parentElement;
                }
                return el;
            }

            const exactClose = Array.from(document.querySelectorAll(
                '[data-testid="beast-core-icon-close"], [class*="PersonalShopBusinessAddressModifyModal2_closeIcon"], [class*="closeIcon"]'
            )).find(isVisible);
            if (exactClose) {
                clickableParent(exactClose).click();
                return { present: true, clicked: true, method: 'address_close_icon' };
            }

            const candidates = [];
            for (const el of document.querySelectorAll('button,a,span,i,svg,div')) {
                if (!isVisible(el)) continue;
                const r = el.getBoundingClientRect();
                if (r.left > 130 || r.top > 190 || r.top < 20) continue;
                const text = (el.innerText || el.textContent || '').trim();
                const aria = el.getAttribute?.('aria-label') || '';
                const cls = el.className ? String(el.className) : '';
                if (
                    text === '×'
                    || text === '✕'
                    || aria.toLowerCase().includes('close')
                    || cls.toLowerCase().includes('close')
                ) {
                    candidates.push({ el, score: r.left + r.top });
                }
            }
            candidates.sort((a, b) => a.score - b.score);
            if (candidates.length) {
                clickableParent(candidates[0].el).click();
                return { present: true, clicked: true, method: 'candidate' };
            }

            for (const [x, y] of [[50, 80], [50, 110], [50, 140], [65, 80], [65, 110]]) {
                const el = document.elementFromPoint(x, y);
                if (el && isVisible(el)) {
                    clickableParent(el).click();
                    return { present: true, clicked: true, method: 'point' };
                }
            }
            return { present: true, clicked: false };
            """
        )
        if not isinstance(result, dict) or not result.get("present"):
            return False

        if result.get("clicked"):
            print(
                f"[{account_id}] [{label}] 检测到经营地址补充弹窗，已点击左上角关闭按钮",
                flush=True,
            )
            time.sleep(1)
            return True
        else:
            print(
                f"[{account_id}] [{label}] 检测到经营地址补充弹窗，但未定位到左上角关闭按钮",
                flush=True,
            )
        return False
    except Exception as exc:
        print(f"[{account_id}] [{label}] 地址弹窗处理异常：{_safe_exc(exc)}", flush=True)
        return False


def _confirm_leave_publish_page(page: DpPage) -> None:
    """关闭发布页时如出现离开确认，自动确认。"""
    try:
        page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            const keywords = ['确定', '确认', '离开', '放弃', '继续退出'];
            for (const el of document.querySelectorAll('button,a,span,div')) {
                if (!isVisible(el)) continue;
                const text = (el.innerText || el.textContent || '').trim();
                if (keywords.includes(text)) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
        time.sleep(0.5)
    except Exception:
        pass


def _click_submit(page: DpPage, account_id: str, label: str) -> tuple[bool, datetime | None]:
    print(f"[{account_id}] [{label}] 点击提交并上架...", flush=True)
    try:
        submit_btn = page.ele("text:提交并上架", timeout=3)
        if not submit_btn:
            print(f"[{account_id}] [{label}] 未找到「提交并上架」按钮", flush=True)
            return False, None
        submitted_at = datetime.now()
        submit_btn.click(by_js=True)
        time.sleep(2)
        if page.ele("css:.success-title", timeout=8):
            print(
                f"[{account_id}] [{label}] 提交成功，开始回到商品列表核验最终状态",
                flush=True,
            )
            return True, submitted_at
        if page.ele("text:请上传预览图", timeout=1):
            print(f"[{account_id}] [{label}] 提交被拦截：仍有预览图未上传", flush=True)
            return False, submitted_at
        print(f"[{account_id}] [{label}] 未检测到成功标志，请手动核查", flush=True)
        return False, submitted_at
    except Exception as exc:
        print(f"[{account_id}] [{label}] 提交异常：{_safe_exc(exc)}", flush=True)
        return False, None


def _open_goods_list(page: DpPage, account_id: str, tab_text: str = "在售中") -> bool:
    for url in GOODS_LIST_URLS:
        try:
            page.get(url)
            time.sleep(3)
            if "login" in page.url:
                return False
            if page.ele("text:商品列表", timeout=2) or page.ele("text:商品ID", timeout=2):
                break
        except Exception:
            continue

    try:
        tab = page.ele(f"text:{tab_text}", timeout=3)
        if tab:
            tab.click()
            time.sleep(1.5)
    except Exception:
        pass
    return True


def _reset_goods_list_filters(page: DpPage) -> None:
    try:
        reset_btn = page.ele("text:重置", timeout=1.5)
        if reset_btn:
            reset_btn.click()
            time.sleep(1)
    except Exception:
        pass


def _set_goods_filter(page: DpPage, label: str, value: str) -> bool:
    if not value:
        return False
    try:
        ok = page.run_js(
            """
            const [labelText, value] = arguments;
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            const nodes = Array.from(document.querySelectorAll('label, span, div'));
            for (const node of nodes) {
                const text = (node.innerText || node.textContent || '').trim();
                if (text !== labelText || !isVisible(node)) continue;
                let cur = node;
                for (let depth = 0; depth < 6 && cur; depth++, cur = cur.parentElement) {
                    const input = cur.querySelector?.('input');
                    if (input && isVisible(input)) {
                        input.focus();
                        input.value = '';
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.value = value;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
            }
            return false;
            """,
            label,
            value,
        )
        return bool(ok)
    except Exception:
        return False


def _click_goods_search(page: DpPage) -> bool:
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
            for (const el of document.querySelectorAll('button, span, a, div')) {
                const text = (el.innerText || el.textContent || '').trim();
                if (text === '查询' && isVisible(el)) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
        if clicked:
            time.sleep(2)
            return True
    except Exception:
        pass
    return False


def _fill_global_product_code(page: DpPage, account_id: str, label: str, value: str) -> bool:
    """填写页面底部全局「商品编码」，避开规格表里的 SKU/规格编码输入。"""
    code = (value or "").strip()
    if not code:
        return False
    try:
        result = page.run_js(
            """
            const code = arguments[0];

            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }

            function fireMouse(el) {
                const rect = el.getBoundingClientRect();
                const opts = {
                    bubbles: true,
                    cancelable: true,
                    clientX: rect.left + rect.width / 2,
                    clientY: rect.top + rect.height / 2,
                };
                el.dispatchEvent(new MouseEvent('mousedown', opts));
                el.dispatchEvent(new MouseEvent('mouseup', opts));
                el.dispatchEvent(new MouseEvent('click', opts));
            }

            function setInput(input) {
                input.scrollIntoView({ block: 'center', inline: 'nearest' });
                fireMouse(input);
                input.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype,
                    'value'
                )?.set;
                if (setter) setter.call(input, code);
                else input.value = code;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: code.slice(-1) || '0' }));
                input.dispatchEvent(new Event('blur', { bubbles: true }));
                return input.value === code;
            }

            function candidateFromLabel(node) {
                let cur = node;
                for (let depth = 0; depth < 8 && cur; depth++, cur = cur.parentElement) {
                    const inputs = Array.from(cur.querySelectorAll?.('input') || [])
                        .filter(isVisible);
                    if (inputs.length) {
                        const labelRect = node.getBoundingClientRect();
                        const input = inputs
                            .map((i) => ({ input: i, rect: i.getBoundingClientRect() }))
                            .filter((x) => x.rect.left > labelRect.left)
                            .sort((a, b) => Math.abs(a.rect.top - labelRect.top) - Math.abs(b.rect.top - labelRect.top))[0]?.input
                            || inputs[0];
                        return { input, rect: input.getBoundingClientRect(), labelRect };
                    }
                }
                return null;
            }

            function findByGeometry() {
                const labels = Array.from(document.querySelectorAll('label,span,div'))
                    .filter(isVisible)
                    .map((node) => ({
                        node,
                        text: (node.innerText || node.textContent || '').trim(),
                        rect: node.getBoundingClientRect(),
                    }))
                    .filter((x) => x.text === '商品编码');
                const inputs = Array.from(document.querySelectorAll('input'))
                    .filter(isVisible)
                    .map((input) => ({ input, rect: input.getBoundingClientRect() }))
                    .filter((x) => !((x.input.closest('tr,table')?.innerText || '').includes('规格编码')));

                const pairs = [];
                for (const label of labels) {
                    for (const input of inputs) {
                        if (input.rect.left <= label.rect.right) continue;
                        const dy = Math.abs((input.rect.top + input.rect.height / 2) - (label.rect.top + label.rect.height / 2));
                        if (dy > 40) continue;
                        pairs.push({
                            input: input.input,
                            rect: input.rect,
                            score: dy - input.rect.top / 10000,
                        });
                    }
                }
                pairs.sort((a, b) => a.score - b.score);
                return pairs.map((p) => ({ input: p.input, rect: p.rect }));
            }

            const candidates = [];
            candidates.push(...findByGeometry());
            for (const node of document.querySelectorAll('label,span,div')) {
                if (!isVisible(node)) continue;
                const text = (node.innerText || node.textContent || '').trim();
                if (text !== '商品编码') continue;
                const cand = candidateFromLabel(node);
                if (!cand || !isVisible(cand.input)) continue;
                const parentText = (cand.input.closest('tr,table')?.innerText || '');
                if (parentText.includes('规格编码')) continue;
                candidates.push(cand);
            }

            candidates.sort((a, b) => {
                const bottomA = a.rect.top > window.innerHeight * 0.45 ? 0 : 1;
                const bottomB = b.rect.top > window.innerHeight * 0.45 ? 0 : 1;
                if (bottomA !== bottomB) return bottomA - bottomB;
                return b.rect.top - a.rect.top;
            });
            for (const cand of candidates) {
                if (setInput(cand.input)) {
                    const visibleValue = cand.input.value;
                    return { ok: visibleValue === code, value: visibleValue, top: cand.rect.top };
                }
            }
            return { ok: false, value: '' };
            """,
            code,
        )
        if isinstance(result, dict) and result.get("ok"):
            print(f"[{account_id}] [{label}] 已填写底部商品编码：{code}", flush=True)
            return True
        print(f"[{account_id}] [{label}] 底部商品编码填写失败，未提交", flush=True)
        return False
    except Exception as exc:
        print(f"[{account_id}] [{label}] 填写底部商品编码异常：{_safe_exc(exc)}", flush=True)
        return False


def _read_global_product_code(page: DpPage) -> str:
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
            const labels = Array.from(document.querySelectorAll('label,span,div'))
                .filter(isVisible)
                .map((node) => ({
                    node,
                    text: (node.innerText || node.textContent || '').trim(),
                    rect: node.getBoundingClientRect(),
                }))
                .filter((x) => x.text === '商品编码');
            const inputs = Array.from(document.querySelectorAll('input'))
                .filter(isVisible)
                .map((input) => ({ input, rect: input.getBoundingClientRect() }))
                .filter((x) => !((x.input.closest('tr,table')?.innerText || '').includes('规格编码')));
            const pairs = [];
            for (const label of labels) {
                for (const input of inputs) {
                    if (input.rect.left <= label.rect.right) continue;
                    const dy = Math.abs((input.rect.top + input.rect.height / 2) - (label.rect.top + label.rect.height / 2));
                    if (dy <= 40) pairs.push({ input: input.input, rect: input.rect, dy });
                }
            }
            pairs.sort((a, b) => {
                const bottomA = a.rect.top > window.innerHeight * 0.45 ? 0 : 1;
                const bottomB = b.rect.top > window.innerHeight * 0.45 ? 0 : 1;
                if (bottomA !== bottomB) return bottomA - bottomB;
                if (a.dy !== b.dy) return a.dy - b.dy;
                return b.rect.top - a.rect.top;
            });
            return pairs[0]?.input?.value || '';
            """
        )
        return str(result or "").strip()
    except Exception:
        return ""


def _parse_goods_list_matches(
    page: DpPage,
    merchant_code: str,
    title: str,
) -> list[dict[str, Any]]:
    try:
        rows = page.eles("css:tbody tr", timeout=3)
    except Exception:
        rows = []
    matches: list[dict[str, Any]] = []
    for row in rows:
        text = row.text or ""
        if merchant_code and merchant_code not in text:
            continue
        if not _row_matches_title(text, title):
            continue
        product_id = extract_product_id_from_text(text)
        if not product_id:
            continue
        matches.append(
            {
                "pdd_product_id": product_id or "",
                "row_text": text.strip(),
                "title_matched": True,
            }
        )
    return matches


def _capture_result(
    *,
    status: str,
    tab: str = "",
    pdd_product_id: str = "",
    matched_created_at: str = "",
    matched_row_text: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "tab": tab,
        "pdd_product_id": pdd_product_id,
        "matched_created_at": matched_created_at,
        "matched_row_text": matched_row_text,
        "message": message,
    }


def _search_goods_tab(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    *,
    tab_text: str,
    tab_key: str,
    merchant_code: str,
    title: str,
) -> dict[str, Any]:
    if not _open_goods_list(page, account_id, tab_text):
        return _capture_result(status="open_goods_list_failed", tab=tab_key)
    _reset_goods_list_filters(page)
    filter_ok = _set_goods_filter(page, "商品编码", merchant_code)
    if filter_ok:
        _click_goods_search(page)

    matches = _parse_goods_list_matches(page, merchant_code, title)
    if not matches:
        return _capture_result(status="not_found", tab=tab_key)

    selected = matches[0]
    return _capture_result(
        status="captured",
        tab=tab_key,
        pdd_product_id=str(selected.get("pdd_product_id") or ""),
        matched_row_text=str(selected.get("row_text") or ""),
    )


def _capture_publish_outcome(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    merchant_code: str,
    title: str,
) -> dict[str, Any]:
    try:
        on_sale = _search_goods_tab(
            page,
            account_id,
            unit,
            tab_text="在售中",
            tab_key="on_sale",
            merchant_code=merchant_code,
            title=title,
        )
        if on_sale["status"] == "captured" and on_sale.get("pdd_product_id"):
            print(
                f"[{account_id}] [{unit.listing_label}] 已在在售中抓取商品ID={on_sale['pdd_product_id']}",
                flush=True,
            )
            return on_sale

        rejected = _search_goods_tab(
            page,
            account_id,
            unit,
            tab_text="已驳回",
            tab_key="rejected",
            merchant_code=merchant_code,
            title=title,
        )
        if rejected["status"] == "captured":
            rejected["status"] = "rejected"
            print(
                f"[{account_id}] [{unit.listing_label}] 商品发布后进入已驳回，按失败处理",
                flush=True,
            )
            return rejected

        status = "not_found"
        if on_sale["status"] == "open_goods_list_failed" or rejected["status"] == "open_goods_list_failed":
            status = "open_goods_list_failed"
        print(
            f"[{account_id}] [{unit.listing_label}] 提交后未在在售中/已驳回匹配到本次商品",
            flush=True,
        )
        return _capture_result(
            status=status,
            message="提交成功页已出现，但商品列表未匹配到本次发布记录",
        )
    except Exception as exc:
        err = _safe_exc(exc)
        print(f"[{account_id}] [{unit.listing_label}] 抓取商品ID异常：{err}", flush=True)
        return _capture_result(status="capture_error", message=err)


def _attach_capture_fields(result: dict[str, Any], capture: dict[str, Any]) -> dict[str, Any]:
    result["pdd_product_id"] = capture.get("pdd_product_id") or ""
    result["pdd_product_id_capture_status"] = capture.get("status") or ""
    result["pdd_product_matched_tab"] = capture.get("tab") or ""
    result["pdd_product_matched_created_at"] = capture.get("matched_created_at") or ""
    result["pdd_product_matched_row_text"] = capture.get("matched_row_text") or ""
    if capture.get("message"):
        result["pdd_product_capture_message"] = capture["message"]
    return result


def upload_one_listing(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    product_info: dict[str, Any],
    defaults: dict[str, str],
    platform_listing_code: str = "",
) -> dict[str, Any]:
    """对单个上架单元执行完整发布流程。"""
    label = unit.listing_label
    enrich_listing_unit_specs(unit, account_id=account_id)
    covers = [str(p.resolve()) for p in unit.carousel_images]
    details = [str(p.resolve()) for p in unit.detail_images]
    style_names = list(dict.fromkeys(sku.style_name for sku in unit.skus))
    size_names = list(dict.fromkeys(sku.model_name for sku in unit.skus))

    listing_info = dict(product_info)
    listing_info["title"] = resolve_listing_title(product_info, account_id)
    time.sleep(random.uniform(1.0, 2.0))

    print(f"[{account_id}] [{label}] 正在跳转商品分类界面...")
    page.get("https://mms.pinduoduo.com/goods/category")
    time.sleep(5)
    if _dismiss_address_required_page(page, account_id, label):
        time.sleep(2)

    ui_type = "A"
    if page.ele("css:.goodsCarousel_btns__22KMn", timeout=1) or page.ele(
        'css:input[data-tracking-click-viewid="local_upload"]', timeout=1
    ):
        ui_type = "C"
    elif page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]', timeout=1):
        ui_type = "B"
    print(f"[{account_id}] [{label}] 路由判定：分支 {ui_type}")

    if ui_type == "C":
        section_ele = page.ele("css:.goodsCarousel_btns__22KMn")
        if section_ele:
            page.run_js('arguments[0].style.display = "flex";', section_ele)
        time.sleep(1)
        cover_input = page.ele('css:input[data-tracking-click-viewid="local_upload"]')
        if cover_input:
            cover_input.input(covers)
        time.sleep(random.uniform(1.5, 2.5))
        listing_info["title"] = apply_title_after_cover_upload(
            page, account_id, product_info, listing_info.get("title", "")
        )
        time.sleep(2)
        next_btn = page.ele("#bottomSubmitBtnId")
        if next_btn:
            next_btn.click()
        time.sleep(5)
        page.wait.load_start()
    else:
        if ui_type == "B":
            tab = page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]')
            if tab:
                page.run_js("arguments[0].click();", tab)
                time.sleep(3)

        search_input = page.ele('css:input[placeholder="请输入关键词搜索分类"]')
        if search_input:
            search_input.click()
            time.sleep(0.5)
            search_input.input(listing_info.get("category_keyword", "玩偶"), clear=True)
        time.sleep(2)
        first_cat = page.ele("css:li.SPP_searchItem_5-188-0")
        if first_cat:
            first_cat.click()
        time.sleep(1)
        confirm = page.ele("text:下一步, 完善商品信息") if ui_type == "B" else page.ele(
            "text:确认发布该类商品"
        )
        if confirm:
            confirm.click()
        time.sleep(5)
        page.wait.load_start()
        if _dismiss_address_required_page(page, account_id, label):
            time.sleep(2)

        section_ele = page.ele("css:.uploadImgEnter.uploadImgEnterNew")
        if section_ele:
            page.run_js('arguments[0].style.display = "flex";', section_ele)
        time.sleep(1)
        cover_input = page.ele(
            'css:input[type="file"]:not([data-tracking-click-viewid="detail_img_localfile_upload"])'
        )
        if cover_input:
            cover_input.input(covers)
        time.sleep(random.uniform(1.5, 2.5))
        listing_info["title"] = apply_title_after_cover_upload(
            page, account_id, product_info, listing_info.get("title", "")
        )
        time.sleep(1)

    print(f"[{account_id}] [{label}] 正在上传详情图...")
    detail_input = page.ele('css:input[data-tracking-click-viewid="detail_img_localfile_upload"]')
    if detail_input and details:
        detail_input.input(details)
    time.sleep(2)

    print(f"[{account_id}] [{label}] 正在录入多规格（款式 + 型号）...")
    add_style_and_model_specs(page, account_id, style_names, size_names)
    time.sleep(1)
    sku_rows = wait_multi_sku_rows(page, account_id, unit.skus)

    print(f"[{account_id}] [{label}] 开始填写价格表...")
    previews_ok = fill_multi_spec_rows(page, account_id, unit.skus, defaults, rows=sku_rows)

    pcode = (platform_listing_code or "").strip() or unit.merchant_code
    if not _fill_global_product_code(page, account_id, label, pcode):
        _clear_beforeunload(page)
        result = _listing_result(
            unit=unit,
            status="retryable",
            reason="platform_listing_code_not_filled",
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="skipped",
        )
        result["platform_listing_code"] = pcode
        return result

    time.sleep(random.uniform(1.0, 2.0))
    visible_global_code = _read_global_product_code(page)
    if visible_global_code != pcode:
        print(
            f"[{account_id}] [{label}] 提交前校验失败：底部商品编码={visible_global_code or '<空>'}，期望={pcode}",
            flush=True,
        )
        _clear_beforeunload(page)
        result = _listing_result(
            unit=unit,
            status="retryable",
            reason="platform_listing_code_verify_failed",
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="skipped",
        )
        result["platform_listing_code"] = pcode
        return result

    if not previews_ok:
        print(f"[{account_id}] [{label}] 预览图未全部就绪，跳过提交", flush=True)
        _clear_beforeunload(page)
        return _listing_result(
            unit=unit,
            status="retryable",
            reason="preview_not_ready",
            retryable=True,
            legacy_status="skipped",
        )

    ok, submitted_at = _click_submit(page, account_id, label)
    _clear_beforeunload(page)
    if ok:
        print(f"[{account_id}] [{label}] 等待 30 秒后核验在售/驳回状态", flush=True)
        time.sleep(30)
        capture = _capture_publish_outcome(
            page,
            account_id,
            unit,
            pcode,
            listing_info.get("title", ""),
        )
        if capture["status"] == "captured" and capture.get("pdd_product_id"):
            result = _listing_result(
                unit=unit,
                status="success",
                reason="listed",
                title=listing_info.get("title", ""),
                legacy_status="listed",
            )
            result["platform_listing_code"] = pcode
            result["publish_submitted_at"] = format_datetime(submitted_at) if submitted_at else ""
            return _attach_capture_fields(result, capture)
        if capture["status"] == "rejected":
            result = _listing_result(
                unit=unit,
                status="failed",
                reason="rejected_after_publish",
                title=listing_info.get("title", ""),
                retryable=False,
                legacy_status="failed",
            )
            result["platform_listing_code"] = pcode
            result["publish_submitted_at"] = format_datetime(submitted_at) if submitted_at else ""
            return _attach_capture_fields(result, capture)

        result = _listing_result(
            unit=unit,
            status="retryable",
            reason="published_but_not_found_in_on_sale_or_rejected",
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="submit_uncertain",
        )
        result["platform_listing_code"] = pcode
        result["publish_submitted_at"] = format_datetime(submitted_at) if submitted_at else ""
        return _attach_capture_fields(result, capture)
    return _listing_result(
        unit=unit,
        status="retryable",
        reason="submit_uncertain",
        title=listing_info.get("title", ""),
        retryable=True,
        legacy_status="submit_uncertain",
    )


def run_listing_uploads(
    page: DpPage,
    account_id: str,
    units: list[ListingUnit],
    *,
    category_keyword: str = "玩偶",
    title_mode: str = "page_ai",
    platform_listing_code: str = "",
    defaults: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """顺序上架多个单元。"""
    product_info = {
        "category_keyword": category_keyword,
        "title_mode": title_mode,
        "title": "",
    }
    defaults = defaults or {}
    results: list[dict[str, Any]] = []

    for idx, unit in enumerate(units):
        if idx > 0:
            print(f"\n[{account_id}] 等待 5 秒后上架下一单元 [{unit.listing_label}]...\n")
            time.sleep(5)
        try:
            results.append(
                upload_one_listing(
                    page,
                    account_id,
                    unit,
                    product_info,
                    defaults,
                    platform_listing_code=platform_listing_code,
                )
            )
        except Exception as e:
            err = _safe_exc(e)
            reason, retryable = _classify_exception(e)
            print(f"[{account_id}] [{unit.listing_label}] 业务运行报错: {err}")
            results.append(
                _listing_result(
                    unit=unit,
                    status="retryable" if retryable else "failed",
                    reason=reason,
                    error=err,
                    retryable=retryable,
                    legacy_status="failed",
                )
            )
            if "连接已断开" in err or "disconnect" in err.lower():
                break
            try:
                safe_set = (unit.image_set or "default").replace("/", "_")
                shot = _error_screenshot_path(
                    f"error_listing_{account_id}_{unit.product_code}_{safe_set}.png"
                )
                page.get_screenshot(path=shot)
                print(f"[{account_id}] 已保存报错截图：{shot}", flush=True)
            except Exception:
                pass
    return results
