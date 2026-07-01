"""多规格上架页面操作（Playwright + DrissionPage 兼容层）。"""

from __future__ import annotations

import re
import random
import time
from datetime import datetime
from typing import Any, Literal

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.domain.models import ListingUnit
from pdd_agent.paths import PROJECT_ROOT
from pdd_agent.skills.delist.time_utils import (
    extract_product_id_from_text,
    format_datetime,
)
from pdd_agent.skills.listing.goods_list_capture import (
    enrich_capture_from_goods_list,
    extract_merchant_code_from_row_text,
    extract_total_inventory_from_row_text,
    merchant_code_matches_query,
    parse_goods_list_row_meta,
    resolve_row_merchant_code,
)
from pdd_agent.skills.listing.multi_spec_page import (
    _safe_exc,
    add_style_and_model_specs,
    fill_multi_spec_rows,
    wait_multi_sku_rows,
)
from pdd_agent.skills.listing.category_branch_c_flow import run_branch_c_category_after_covers
from pdd_agent.skills.listing.category_branch_title import (
    apply_title_after_branch_c_category_advance,
)
from pdd_agent.skills.listing.category_page_flow import (
    CategoryPageMode,
    click_category_next_and_advance,
    prepare_category_before_next,
)
from pdd_agent.skills.listing.listing_publish_settings import apply_listing_publish_settings
from pdd_agent.skills.listing.listing_spec_pipeline import apply_unit_listing_specs
from pdd_agent.skills.listing.pdd_page_image_errors import (
    BranchCCoverImageRejected,
    PddImageDimensionRejected,
    raise_if_pdd_image_dimension_rejected,
    read_pdd_image_dimension_error,
)
from pdd_agent.skills.listing.page_ai_title import apply_title_after_cover_upload
from pdd_agent.skills.listing.spec_labels import is_forbidden_spec_code_label, ordered_style_names
from pdd_agent.skills.listing.title import resolve_listing_title
from pdd_agent.skills.published.pdd_spec_format import listing_unit_sku_metadata


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
        "material_image": str(unit.material_image) if unit.material_image else "",
        "style_codes": list(unit.style_codes),
        "model_codes": list(unit.model_codes),
        "skus": [listing_unit_sku_metadata(sku) for sku in unit.skus],
    }


def _log_unit_spec_snapshot(account_id: str, unit: ListingUnit) -> None:
    label = unit.listing_label
    style_names = ordered_style_names(unit)
    size_names = list(unit.model_codes or [])
    forbidden: list[str] = []
    for sku in unit.skus or []:
        if is_forbidden_spec_code_label(sku.style_name, style_code=sku.style_code):
            forbidden.append(f"款式={sku.style_name}")
        if is_forbidden_spec_code_label(sku.model_name, model_code=sku.model_code):
            forbidden.append(f"尺寸={sku.model_name}")
    if forbidden:
        print(
            f"[{account_id}] [{label}] [警告] 规格名仍含商品编码（禁止）：{', '.join(dict.fromkeys(forbidden))}",
            flush=True,
        )
    print(
        f"[{account_id}] [{label}] 规格快照：style_codes={list(unit.style_codes or [])} | "
        f"style_names={style_names} | model_codes={size_names}",
        flush=True,
    )
    for idx, sku in enumerate(unit.skus or [], start=1):
        print(
            f"[{account_id}] [{label}]  SKU#{idx}: combo={sku.combo_folder} | "
            f"style_code={sku.style_code} -> style_name={sku.style_name} | "
            f"model_code={sku.model_code} -> model_name={sku.model_name}",
            flush=True,
        )


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


def _listing_unit_succeeded(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").strip().lower()
    product_id = str(item.get("pdd_product_id") or "").strip()
    return status in {"success", "listed"} and bool(product_id or status == "listed")


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


def _finish_listing(
    run_id: str,
    account_id: str,
    unit: ListingUnit,
    *,
    status: str,
    reason: str = "",
    error: str = "",
    title: str = "",
    retryable: bool = False,
    legacy_status: str = "",
    extra: dict[str, Any] | None = None,
    phase: str = "upload",
    step: str = "final",
    screenshot_path: str = "",
    page_url: str = "",
) -> dict[str, Any]:
    result = _listing_result(
        unit=unit,
        status=status,
        reason=reason,
        error=error,
        title=title,
        retryable=retryable,
        legacy_status=legacy_status,
    )
    if extra:
        result.update(extra)
    if run_id and status not in {"success", "listed"}:
        from pdd_agent.api.services.listing_failure_log import record_from_listing_result

        record_from_listing_result(
            source_run_id=run_id,
            account_id=account_id,
            result=result,
            phase=phase,
            step=step,
            screenshot_path=screenshot_path,
            page_url=page_url,
        )
    return result


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
    if any(
        k in low
        for k in (
            "target closed",
            "browser has been closed",
            "context or browser has been closed",
            "target page, context or browser has been closed",
            "page closed",
            "browser closed",
            "browser context closed",
        )
    ):
        return "browser_manually_closed", False
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
            const addressModal = Array.from(document.querySelectorAll(
                '[class*="PersonalShopBusinessAddressModifyModal"], [data-testid="beast-core-modal"]'
            )).find((el) => {
                const t = el.innerText || el.textContent || '';
                return t.includes('经营地址') || t.includes('联系/经营地址') || t.includes('确认补充');
            });
            const present = !!addressModal
                || (bodyText.includes('真实有效')
                    && (bodyText.includes('联系/经营地址') || bodyText.includes('经营地址'))
                    && bodyText.includes('确认补充'));
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

            const exactClose = (addressModal
                ? Array.from(addressModal.querySelectorAll(
                    '[data-testid="beast-core-icon-close"], [class*="PersonalShopBusinessAddressModifyModal2_closeIcon"], [class*="closeIcon"]'
                )).find(isVisible)
                : null)
                || Array.from(document.querySelectorAll(
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


def _click_visible_button(page: DpPage, texts: list[str], timeout: float = 0.4) -> bool:
    for text in texts:
        try:
            btn = page.ele(f"text:{text}", timeout=timeout)
            if btn:
                btn.click(by_js=True)
                return True
        except Exception:
            continue
    return False


def _detect_submit_blocked(page: DpPage) -> str:
    if page.ele("text:请上传预览图", timeout=0.4):
        return ListingErrorCode.PREVIEW_MISSING
    for selector, reason in ListingErrors.SUBMIT_BLOCK_DETECTORS:
        try:
            if page.ele(selector, timeout=0.4):
                return reason
        except Exception:
            continue
    return ""


def _detect_submit_success(page: DpPage, *, max_wait: float = 18.0) -> bool:
    success_selectors = [
        "css:.success-title",
        "text:提交成功",
        "text:发布成功",
        "text:商品发布成功",
        "text:上架成功",
        "text:已提交审核",
    ]
    confirm_texts = ["确认提交", "确认上架", "确定", "我知道了", "知道了"]
    deadline = time.time() + max_wait
    while time.time() < deadline:
        url = (page.url or "").lower()
        if "goods_list" in url or "/goods/list" in url:
            return True
        for selector in success_selectors:
            try:
                if page.ele(selector, timeout=0.4):
                    return True
            except Exception:
                continue
        _click_visible_button(page, confirm_texts, timeout=0.25)
        time.sleep(0.6)
    return False


def _click_submit(page: DpPage, account_id: str, label: str) -> tuple[bool, datetime | None, str]:
    """点击提交；返回 (成功标志是否出现, 点击时间, 拦截原因)。"""
    print(f"[{account_id}] [{label}] 点击提交并上架...", flush=True)
    try:
        submit_btn = page.ele("text:提交并上架", timeout=3)
        if not submit_btn:
            print(f"[{account_id}] [{label}] 未找到「提交并上架」按钮", flush=True)
            return False, None, ListingErrorCode.SUBMIT_BUTTON_MISSING
        submitted_at = datetime.now()
        submit_btn.click(by_js=True)
        time.sleep(1.5)
        blocked = _detect_submit_blocked(page)
        if blocked:
            reason_map = {
                ListingErrorCode.PREVIEW_MISSING: "提交被拦截：仍有预览图未上传",
                **ListingErrors.SUBMIT_BLOCK_LOG,
            }
            print(f"[{account_id}] [{label}] {reason_map.get(blocked, blocked)}", flush=True)
            return False, submitted_at, blocked
        if _detect_submit_success(page):
            print(
                f"[{account_id}] [{label}] 提交成功，开始回到商品列表核验最终状态",
                flush=True,
            )
            return True, submitted_at, ""
        print(
            f"[{account_id}] [{label}] 未检测到成功页（可能已提交或页面改版），将改去商品列表核验",
            flush=True,
        )
        return False, submitted_at, ""
    except Exception as exc:
        print(f"[{account_id}] [{label}] 提交异常：{_safe_exc(exc)}", flush=True)
        return False, None, "submit_exception"


def _open_goods_list(page: DpPage, account_id: str, tab_text: str = "在售中") -> bool:
    from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
        ensure_post_publish_modals_cleared,
    )

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

    ensure_post_publish_modals_cleared(page, account_id, "", max_attempts=3)

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


def _read_goods_id_filter(page: DpPage) -> str:
    try:
        value = page.run_js(
            """
            const selectors = [
                '.goods-search-wrap input[placeholder*="商品ID"]',
                'input[placeholder*="商品ID"]',
                'input[placeholder*="多个商品ID"]',
            ];
            for (const sel of selectors) {
                const input = document.querySelector(sel);
                if (!input) continue;
                return String(input.value || '').trim();
            }
            return '';
            """
        )
        return str(value or "").strip()
    except Exception:
        return ""


def _fill_goods_id_filter(page: DpPage, product_id: str) -> dict[str, Any]:
    """填写商品列表「商品ID」筛选框，并校验值已写入。"""
    product_id = str(product_id or "").strip()
    if not product_id:
        return {"filled": False, "method": "", "value": ""}

    raw = page._page
    playwright_selectors = (
        '.goods-search-wrap input[placeholder*="商品ID"]',
        '.goods-search-wrap input[data-testid="beast-core-input-htmlInput"]',
        'input[placeholder*="商品ID"]',
        'input[placeholder*="多个商品ID"]',
    )
    for selector in playwright_selectors:
        try:
            loc = raw.locator(selector).first
            if not loc.is_visible(timeout=1500):
                continue
            loc.scroll_into_view_if_needed(timeout=3000)
            loc.click(timeout=3000)
            loc.fill("", timeout=3000)
            loc.fill(product_id, timeout=3000)
            time.sleep(0.3)
            current = str(loc.input_value(timeout=1000) or "").strip()
            if product_id in current:
                return {"filled": True, "method": f"playwright_{selector}", "value": current}
        except Exception:
            continue

    if _set_goods_filter(page, "商品ID", product_id):
        current = _read_goods_id_filter(page)
        if product_id in current:
            return {"filled": True, "method": "set_goods_filter", "value": current}

    try:
        ok = page.run_js(
            """
            const productId = String(arguments[0] || '').trim();
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function fillInput(input, value) {
                input.focus();
                input.value = '';
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.value = value;
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            const selectors = [
                '.goods-search-wrap input[placeholder*="商品ID"]',
                'input[placeholder*="商品ID"]',
                'input[placeholder*="多个商品ID"]',
            ];
            for (const sel of selectors) {
                for (const input of document.querySelectorAll(sel)) {
                    if (!isVisible(input)) continue;
                    fillInput(input, productId);
                    return true;
                }
            }
            return false;
            """,
            product_id,
        )
        if ok:
            current = _read_goods_id_filter(page)
            if product_id in current:
                return {"filled": True, "method": "js_fill", "value": current}
    except Exception:
        pass

    return {"filled": False, "method": "", "value": _read_goods_id_filter(page)}


def _read_goods_merchant_code_filter(page: DpPage) -> str:
    """读取商品列表筛选区「商品编码」输入框（仅限 .goods-search-wrap）。"""
    try:
        value = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden';
            }
            const wrap = document.querySelector('.goods-search-wrap');
            if (!wrap) return '';
            for (const node of wrap.querySelectorAll('label, span, div')) {
                const text = (node.innerText || node.textContent || '').trim();
                if (text !== '商品编码' || !isVisible(node)) continue;
                let cur = node;
                for (let depth = 0; depth < 7 && cur; depth++, cur = cur.parentElement) {
                    const input = Array.from(cur.querySelectorAll?.('input') || []).find(isVisible);
                    if (input) return String(input.value || '').trim();
                }
            }
            return '';
            """
        )
        return str(value or "").strip()
    except Exception:
        return ""


def _fill_goods_merchant_code_filter(page: DpPage, merchant_code: str) -> dict[str, Any]:
    """填写商品列表筛选区「商品编码」，并校验值已写入。"""
    merchant_code = str(merchant_code or "").strip()
    if not merchant_code:
        return {"filled": False, "method": "", "value": ""}

    raw = page._page
    try:
        wrap = raw.locator(".goods-search-wrap")
        if wrap.count() > 0:
            label = wrap.get_by_text("商品编码", exact=True).first
            if label.is_visible(timeout=1500):
                container = label.locator("xpath=ancestor::*[contains(@class,'form') or contains(@class,'Form') or contains(@class,'item') or contains(@class,'Item')][1]")
                if container.count() <= 0:
                    container = label.locator("xpath=..")
                inp = container.locator('input[data-testid="beast-core-input-htmlInput"], input').first
                if inp.is_visible(timeout=1500):
                    inp.scroll_into_view_if_needed(timeout=3000)
                    inp.click(timeout=3000)
                    inp.fill("", timeout=3000)
                    inp.fill(merchant_code, timeout=3000)
                    time.sleep(0.3)
                    current = str(inp.input_value(timeout=1000) or "").strip()
                    if merchant_code in current or current in merchant_code:
                        return {"filled": True, "method": "playwright_goods_search_wrap", "value": current}
    except Exception:
        pass

    try:
        ok = page.run_js(
            """
            const value = String(arguments[0] || '').trim();
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function fillInput(input, text) {
                input.scrollIntoView({ block: 'center', inline: 'nearest' });
                input.focus();
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                )?.set;
                if (setter) {
                    setter.call(input, text);
                } else {
                    input.value = text;
                }
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                return String(input.value || '').trim();
            }
            const wrap = document.querySelector('.goods-search-wrap');
            if (!wrap) return { filled: false };
            for (const node of wrap.querySelectorAll('label, span, div')) {
                const text = (node.innerText || node.textContent || '').trim();
                if (text !== '商品编码' || !isVisible(node)) continue;
                let cur = node;
                for (let depth = 0; depth < 7 && cur; depth++, cur = cur.parentElement) {
                    const inputs = Array.from(cur.querySelectorAll?.('input') || []).filter(isVisible);
                    if (!inputs.length) continue;
                    const labelRect = node.getBoundingClientRect();
                    const input = inputs
                        .map((i) => ({ input: i, rect: i.getBoundingClientRect() }))
                        .filter((x) => x.rect.left >= labelRect.left - 8)
                        .sort((a, b) => Math.abs(a.rect.top - labelRect.top) - Math.abs(b.rect.top - labelRect.top))[0]?.input
                        || inputs[0];
                    const current = fillInput(input, value);
                    return { filled: current.includes(value) || value.includes(current), value: current, method: 'js_goods_search_wrap' };
                }
            }
            return { filled: false };
            """,
            merchant_code,
        )
        if isinstance(ok, dict) and ok.get("filled"):
            return {
                "filled": True,
                "method": str(ok.get("method") or "js_goods_search_wrap"),
                "value": str(ok.get("value") or merchant_code),
            }
    except Exception:
        pass

    if _set_goods_filter(page, "商品编码", merchant_code):
        current = _read_goods_merchant_code_filter(page)
        if merchant_code in current or current in merchant_code:
            return {"filled": True, "method": "set_goods_filter_fallback", "value": current}

    return {"filled": False, "method": "", "value": _read_goods_merchant_code_filter(page)}


def _read_goods_spec_code_filter(page: DpPage) -> str:
    """读取商品列表筛选区「规格编码」输入框（仅限 .goods-search-wrap）。"""
    try:
        value = page.run_js(
            """
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none'
                    && s.visibility !== 'hidden';
            }
            const wrap = document.querySelector('.goods-search-wrap');
            if (!wrap) return '';
            for (const node of wrap.querySelectorAll('label, span, div')) {
                const text = (node.innerText || node.textContent || '').trim();
                if (text !== '规格编码' || !isVisible(node)) continue;
                let cur = node;
                for (let depth = 0; depth < 7 && cur; depth++, cur = cur.parentElement) {
                    const input = Array.from(cur.querySelectorAll?.('input') || []).find(isVisible);
                    if (input) return String(input.value || '').trim();
                }
            }
            return '';
            """
        )
        return str(value or "").strip()
    except Exception:
        return ""


def _fill_goods_spec_code_filter(page: DpPage, spec_code: str) -> dict[str, Any]:
    """填写商品列表筛选区「规格编码」，并校验值已写入。"""
    spec_code = str(spec_code or "").strip()
    if not spec_code:
        return {"filled": False, "method": "", "value": ""}

    raw = page._page
    try:
        wrap = raw.locator(".goods-search-wrap")
        if wrap.count() > 0:
            label = wrap.get_by_text("规格编码", exact=True).first
            if label.is_visible(timeout=1500):
                container = label.locator(
                    "xpath=ancestor::*[contains(@class,'form') or contains(@class,'Form') "
                    "or contains(@class,'item') or contains(@class,'Item')][1]"
                )
                if container.count() <= 0:
                    container = label.locator("xpath=..")
                inp = container.locator('input[data-testid="beast-core-input-htmlInput"], input').first
                if inp.is_visible(timeout=1500):
                    inp.scroll_into_view_if_needed(timeout=3000)
                    inp.click(timeout=3000)
                    inp.fill("", timeout=3000)
                    inp.fill(spec_code, timeout=3000)
                    time.sleep(0.3)
                    current = str(inp.input_value(timeout=1000) or "").strip()
                    if spec_code in current or current in spec_code:
                        return {"filled": True, "method": "playwright_goods_search_wrap_spec", "value": current}
    except Exception:
        pass

    if _set_goods_filter(page, "规格编码", spec_code):
        current = _read_goods_spec_code_filter(page)
        if spec_code in current or current in spec_code:
            return {"filled": True, "method": "set_goods_filter_spec_fallback", "value": current}

    return {"filled": False, "method": "", "value": _read_goods_spec_code_filter(page)}


def _click_goods_search(page: DpPage) -> dict[str, Any]:
    """点击商品列表筛选区的「查询」按钮。"""
    raw = page._page

    def _try_click(locator, method: str) -> dict[str, Any] | None:
        try:
            locator.wait_for(state="visible", timeout=2000)
            locator.scroll_into_view_if_needed(timeout=3000)
            locator.click(timeout=5000)
            time.sleep(1.5)
            return {"clicked": True, "method": method}
        except Exception:
            return None

    scoped = [
        (
            "pw_wrap_role_query",
            lambda: raw.locator(".goods-search-wrap").get_by_role("button", name="查询").first,
        ),
        (
            "pw_sku_inquire",
            lambda: raw.locator('button[data-tracking-viewid="sku_inquire"]').first,
        ),
        (
            "pw_wrap_beast_button",
            lambda: raw.locator(".goods-search-wrap button[data-testid='beast-core-button']")
            .filter(has_text="查询")
            .first,
        ),
        (
            "pw_wrap_suffix_query",
            lambda: raw.locator('.goods-search-wrap [data-testid="beast-core-input-suffix"]')
            .filter(has_text="查询")
            .first,
        ),
    ]
    for method, factory in scoped:
        result = _try_click(factory(), method)
        if result:
            return result

    for sel in (
        'button[data-tracking-viewid="sku_inquire"]',
        '.goods-search-wrap button[data-tracking-viewid="sku_inquire"]',
    ):
        try:
            loc = raw.locator(sel).first
            result = _try_click(loc, f"playwright_{sel}")
            if result:
                return result
        except Exception:
            continue

    for sel in (
        "css:button[data-tracking-viewid='sku_inquire']",
        "css:.goods-search-wrap button[data-testid='beast-core-button']",
    ):
        try:
            el = page.ele(sel, timeout=1)
            if el and el.states.is_displayed:
                el.click()
                time.sleep(1.5)
                return {"clicked": True, "method": sel}
        except Exception:
            continue

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
            function activate(btn) {
                btn.scrollIntoView({ block: 'center', inline: 'center' });
                btn.focus({ preventScroll: true });
                btn.click();
            }
            const scopes = [
                document.querySelector('.goods-search-wrap'),
                document.querySelector('[class*="goods-search"]'),
            ].filter(Boolean);
            for (const scope of scopes.length ? scopes : [document]) {
                for (const btn of scope.querySelectorAll('button[data-tracking-viewid="sku_inquire"], button[data-testid="beast-core-button"]')) {
                    const text = (btn.innerText || btn.textContent || '').trim();
                    if (text.includes('查询') && isVisible(btn)) {
                        activate(btn);
                        return { clicked: true, method: 'js_scope_button' };
                    }
                }
                for (const suffix of scope.querySelectorAll('[data-testid="beast-core-input-suffix"]')) {
                    const text = (suffix.innerText || suffix.textContent || '').trim();
                    if (text === '查询' && isVisible(suffix)) {
                        activate(suffix);
                        return { clicked: true, method: 'js_scope_suffix' };
                    }
                }
            }
            return { clicked: false, method: '' };
            """
        )
        if isinstance(clicked, dict) and clicked.get("clicked"):
            time.sleep(1.5)
            return clicked
        if clicked:
            time.sleep(1.5)
            return {"clicked": True, "method": "js_click"}
    except Exception:
        pass

    for selector in (
        '.goods-search-wrap input[placeholder*="商品编码"]',
        'input[placeholder*="商品编码"]',
        '.goods-search-wrap input[data-testid="beast-core-input-htmlInput"]',
        'input[placeholder*="商品ID"]',
    ):
        try:
            inp = raw.locator(selector).first
            if inp.is_visible(timeout=1500):
                inp.press("Enter")
                time.sleep(1.5)
                return {"clicked": True, "method": f"enter_{selector}"}
        except Exception:
            continue

    return {"clicked": False, "method": ""}


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


def _parse_goods_list_matches_by_merchant_code(
    page: DpPage,
    merchant_code: str,
) -> list[dict[str, Any]]:
    """在商品列表中仅按商品编码精确匹配（用于「全部」Tab 兜底核验）。"""
    query_code = str(merchant_code or "").strip()
    if not query_code:
        return []
    try:
        rows = page.eles("css:tbody tr", timeout=3)
    except Exception:
        rows = []
    matches: list[dict[str, Any]] = []
    for row in rows:
        text = row.text or ""
        if not merchant_code_matches_query(row, text, query_code):
            continue
        row_code = resolve_row_merchant_code(row, text)
        product_id = extract_product_id_from_text(text)
        if not product_id:
            continue
        row_meta = parse_goods_list_row_meta(text)
        inventory = extract_total_inventory_from_row_text(text)
        matches.append(
            {
                "pdd_product_id": product_id or "",
                "row_text": text.strip(),
                "merchant_code": row_code,
                "matched_created_at": row_meta.get("matched_created_at") or "",
                "list_status": row_meta.get("list_status") or "",
                "total_inventory": inventory,
            }
        )
    return matches


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
        if not merchant_code_matches_query(row, text, merchant_code):
            continue
        if not _row_matches_title(text, title):
            continue
        product_id = extract_product_id_from_text(text)
        if not product_id:
            continue
        row_meta = parse_goods_list_row_meta(text)
        matches.append(
            {
                "pdd_product_id": product_id or "",
                "row_text": text.strip(),
                "title_matched": True,
                "matched_created_at": row_meta.get("matched_created_at") or "",
                "list_status": row_meta.get("list_status") or "",
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
    list_status: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "tab": tab,
        "pdd_product_id": pdd_product_id,
        "matched_created_at": matched_created_at,
        "matched_row_text": matched_row_text,
        "list_status": list_status,
        "message": message,
    }


def _execute_goods_all_tab_query(
    page: DpPage,
    merchant_code: str,
) -> list[dict[str, Any]]:
    """「全部」Tab：重置筛选、按商品编码查询并解析匹配行。"""
    _reset_goods_list_filters(page)
    fill_result = _fill_goods_merchant_code_filter(page, merchant_code)
    if not fill_result.get("filled"):
        filter_ok = _set_goods_filter(page, "商品编码", merchant_code)
    else:
        filter_ok = True
    if filter_ok:
        _click_goods_search(page)
    return _parse_goods_list_matches_by_merchant_code(page, merchant_code)


def _evaluate_all_tab_row(
    selected: dict[str, Any],
    merchant_code: str,
) -> dict[str, Any]:
    """校验「全部」Tab 匹配行：编码一致 → 库存 → 销售状态。"""
    query_code = str(merchant_code or "").strip()
    row_code = str(selected.get("merchant_code") or "").strip()
    if not row_code:
        row_code = extract_merchant_code_from_row_text(str(selected.get("row_text") or ""))
    if row_code != query_code:
        return _capture_result(
            status="merchant_code_mismatch",
            tab="all",
            pdd_product_id=str(selected.get("pdd_product_id") or ""),
            matched_row_text=str(selected.get("row_text") or ""),
            message=f"商品编码不一致：期望 {query_code}，实际 {row_code or '(空)'}",
        )

    inventory = selected.get("total_inventory")
    if inventory is None:
        inventory = extract_total_inventory_from_row_text(str(selected.get("row_text") or ""))
    if inventory is None:
        return _capture_result(
            status="inventory_unparsed",
            tab="all",
            pdd_product_id=str(selected.get("pdd_product_id") or ""),
            matched_row_text=str(selected.get("row_text") or ""),
            message="未能解析总库存",
        )
    if int(inventory) == 0:
        return _capture_result(
            status="zero_inventory",
            tab="all",
            pdd_product_id=str(selected.get("pdd_product_id") or ""),
            matched_created_at=str(selected.get("matched_created_at") or ""),
            matched_row_text=str(selected.get("row_text") or ""),
            list_status=str(selected.get("list_status") or ""),
            message="当前库存为0",
        )

    list_status = str(selected.get("list_status") or "").strip()
    if list_status == "销售中":
        return _capture_result(
            status="captured",
            tab="all",
            pdd_product_id=str(selected.get("pdd_product_id") or ""),
            matched_created_at=str(selected.get("matched_created_at") or ""),
            matched_row_text=str(selected.get("row_text") or ""),
            list_status=list_status,
        )

    status_label = list_status or "未知"
    return _capture_result(
        status="invalid_list_status",
        tab="all",
        pdd_product_id=str(selected.get("pdd_product_id") or ""),
        matched_created_at=str(selected.get("matched_created_at") or ""),
        matched_row_text=str(selected.get("row_text") or ""),
        list_status=status_label,
        message=f"当前商品上架状态为{status_label}",
    )


def _search_goods_all_tab(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    merchant_code: str,
) -> dict[str, Any]:
    """在售中/已驳回均未命中时，改在「全部」Tab 按商品编码兜底核验。"""
    label = unit.listing_label
    if not _open_goods_list(page, account_id, "全部"):
        return _capture_result(status="open_goods_list_failed", tab="all")

    print(
        f"[{account_id}] [{label}] 在售中/已驳回未匹配，改在全部Tab按商品编码核验",
        flush=True,
    )
    matches = _execute_goods_all_tab_query(page, merchant_code)
    if not matches:
        return _capture_result(status="not_found", tab="all")

    selected = matches[0]
    result = _evaluate_all_tab_row(selected, merchant_code)
    status = str(result.get("status") or "")
    if status == "captured":
        print(
            f"[{account_id}] [{label}] 全部Tab核验通过："
            f"product_id={result.get('pdd_product_id')} "
            f"库存={selected.get('total_inventory')} 状态={result.get('list_status')}",
            flush=True,
        )
    elif status == "zero_inventory":
        print(
            f"[{account_id}] [{label}] 全部Tab找到商品但总库存为0",
            flush=True,
        )
    elif status == "invalid_list_status":
        print(
            f"[{account_id}] [{label}] 全部Tab找到商品但状态={result.get('list_status') or '未知'}",
            flush=True,
        )
    return result


def _execute_goods_tab_query(
    page: DpPage,
    merchant_code: str,
    title: str,
) -> list[dict[str, Any]]:
    """重置筛选、按商品编码查询并解析匹配行。"""
    _reset_goods_list_filters(page)
    fill_result = _fill_goods_merchant_code_filter(page, merchant_code)
    if not fill_result.get("filled"):
        filter_ok = _set_goods_filter(page, "商品编码", merchant_code)
    else:
        filter_ok = True
    if filter_ok:
        _click_goods_search(page)
    return _parse_goods_list_matches(page, merchant_code, title)


def _refresh_goods_list_tab(page: DpPage, tab_text: str) -> None:
    """刷新当前商品列表页并切回指定 Tab。"""
    try:
        page._page.reload(wait_until="domcontentloaded")
    except Exception:
        return
    time.sleep(2)
    try:
        tab = page.ele(f"text:{tab_text}", timeout=3)
        if tab:
            tab.click()
            time.sleep(1.5)
    except Exception:
        pass


def _search_goods_tab(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    *,
    tab_text: str,
    tab_key: str,
    merchant_code: str,
    title: str,
    max_attempts: int = 1,
    refresh_on_not_found: bool = False,
) -> dict[str, Any]:
    if not _open_goods_list(page, account_id, tab_text):
        return _capture_result(status="open_goods_list_failed", tab=tab_key)

    label = unit.listing_label
    attempts = max(1, int(max_attempts or 1))
    for attempt in range(1, attempts + 1):
        matches = _execute_goods_tab_query(page, merchant_code, title)
        if matches:
            selected = matches[0]
            if attempt > 1:
                print(
                    f"[{account_id}] [{label}] {tab_text} 第{attempt}次查询匹配成功",
                    flush=True,
                )
            return _capture_result(
                status="captured",
                tab=tab_key,
                pdd_product_id=str(selected.get("pdd_product_id") or ""),
                matched_created_at=str(selected.get("matched_created_at") or ""),
                matched_row_text=str(selected.get("row_text") or ""),
                list_status=str(selected.get("list_status") or ""),
            )

        if attempt >= attempts or not refresh_on_not_found:
            break

        print(
            f"[{account_id}] [{label}] {tab_text} 第{attempt}次未匹配到商品，刷新页面后重试",
            flush=True,
        )
        _refresh_goods_list_tab(page, tab_text)

    return _capture_result(status="not_found", tab=tab_key)


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
            max_attempts=2,
            refresh_on_not_found=True,
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
        all_tab = _search_goods_all_tab(page, account_id, unit, merchant_code)
        if all_tab.get("status") != "not_found":
            return all_tab
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
    result["pdd_product_list_status"] = capture.get("list_status") or ""
    result["pdd_product_link"] = capture.get("product_link") or ""
    if capture.get("message") and capture.get("status") != "captured":
        result["pdd_product_capture_message"] = capture["message"]
    return result


def _schedule_feishu_pdd_upload_log(
    *,
    account_id: str,
    unit: ListingUnit,
    title: str,
    merchant_code: str,
    capture: dict[str, Any],
    verified_at: datetime,
    submitted_at: datetime | None = None,
) -> None:
    try:
        from pdd_agent.integrations.feishu.config import load_feishu_config
        from pdd_agent.integrations.feishu.pdd_upload_sync import schedule_pdd_upload_log

        cfg = load_feishu_config()
        if not cfg.pdd_upload_log.enabled:
            return
        product_id = str(capture.get("pdd_product_id") or "").strip()
        if not product_id:
            return
        raw_link = str(capture.get("product_link") or "").strip()
        # 上架成功立即写入/更新飞书；限时限量购/活动/推广后续按商品ID检索并改列
        schedule_pdd_upload_log(
            account_id=account_id,
            listing_label=unit.listing_label,
            title=title,
            merchant_code=merchant_code,
            product_id=product_id,
            product_link=raw_link,
            product_link_method=str(capture.get("product_link_method") or ""),
            publish_start=submitted_at,
            publish_end=verified_at,
            verified_at=verified_at,
            sku_rows=[listing_unit_sku_metadata(sku) for sku in unit.skus],
        )
        from pdd_agent.integrations.feishu.pdd_activity_log_sync import schedule_pdd_activity_log_seed

        schedule_pdd_activity_log_seed(
            account_id=account_id,
            product_id=product_id,
            seeded_at=verified_at,
        )
    except Exception as exc:
        print(
            f"[{account_id}] [{unit.listing_label}] 飞书 PDD 上传日志调度失败：{_safe_exc(exc)}",
            flush=True,
        )


def _category_page_body_text(page: DpPage) -> str:
    try:
        text = page.run_js("return document.body?.innerText || '';")
        return str(text or "")
    except Exception:
        return ""


def _click_category_section_blank(page: DpPage) -> None:
    """点击商品分类/标题区域空白，促发推荐类目渲染（分支 C render_wait 用）。"""
    try:
        page.run_js(
            """
            for (const el of document.querySelectorAll('span, div, label, p')) {
                const t = (el.textContent || '').trim();
                if (t === '商品分类' || t === '商品标题') {
                    el.click();
                    return;
                }
            }
            const main = document.querySelector('.goods-basic, .goods-info, form');
            if (main) { main.click(); return; }
            document.body.click();
            """
        )
    except Exception:
        pass
    _blur_page_focus(page)
    time.sleep(0.35)


def _detect_category_ui_type(page: DpPage) -> str:
    """分类页 UI 分支：优先识别以图/搜索发品（C），避免 cate_tree_tab 误判为 B。"""
    body = _category_page_body_text(page)
    if "以图发品" in body and "搜索发品" in body:
        return "C"
    if page.ele("css:.goodsCarousel_btns__22KMn", timeout=1) or page.ele(
        'css:input[data-tracking-click-viewid="local_upload"]', timeout=1
    ):
        return "C"
    if page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]', timeout=1):
        return "B"
    return "A"


def _category_page_is_manual_picker(page: DpPage, ui_type: str = "") -> bool:
    """分类选择弹层/树已打开；分支 B 仅在尚未直通下一步时走手动选类。"""
    if ui_type == "C" and _branch_c_category_already_selected(page):
        return False
    if ui_type == "B" and _category_direct_next_ready(page):
        return False
    if ui_type == "B":
        return True
    body = _category_page_body_text(page)
    if "分类选择" in body and not _branch_c_category_already_selected(page):
        return True
    if page.ele('css:input[placeholder="请输入关键词搜索分类"]', timeout=0.4):
        return True
    return False


def _resolve_category_page_mode(
    page: DpPage,
    ui_type: str,
    *,
    manual_category: bool = False,
) -> CategoryPageMode:
    """已选类目直通；暂无推荐手动选类；其余走渲染 workaround。"""
    if manual_category:
        return "manual_picker"
    if _category_direct_next_ready(page):
        return "direct_next"
    if ui_type == "B" or _category_page_is_manual_picker(page, ui_type):
        return "manual_picker"
    return "render_wait"


def _category_direct_next_ready(page: DpPage) -> bool:
    """已选完整类目且下一步可点：以图/搜索发品或底部已选分类条。"""
    from pdd_agent.skills.listing.category_branch_c_recent import (
        branch_c_category_path_ready_strict,
    )

    if not branch_c_category_path_ready_strict(page):
        return False
    try:
        ready = page.run_js(
            """
            const body = document.body?.innerText || '';
            const compact = body.replace(/\\s+/g, '');
            const hasCategoryPath = compact.includes('已选分类')
                || /[^>\\n]{2,}\\s*>\\s*[^>\\n]{2,}\\s*>\\s*[^>\\n]{2,}/.test(body);
            if (!hasCategoryPath) return false;
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function norm(t) { return (t || '').replace(/\\s+/g, ''); }
            const byE2e = document.querySelector('[data-e2e-id="e2e-publish-button"]');
            if (byE2e && isVisible(byE2e) && !byE2e.disabled) return true;
            const byId = document.getElementById('bottomSubmitBtnId');
            if (byId && isVisible(byId) && !byId.disabled) return true;
            for (const el of document.querySelectorAll('button, a, div, span')) {
                const t = norm(el.innerText || el.textContent || '');
                if (!t.includes('下一步') || !t.includes('完善商品信息')) continue;
                if (isVisible(el) && !el.disabled) return true;
            }
            return false;
            """
        )
        return bool(ready)
    except Exception:
        return False


def _branch_c_direct_next_ready(page: DpPage) -> bool:
    """兼容旧名：同 _category_direct_next_ready。"""
    return _category_direct_next_ready(page)


_CONFIRM_CATEGORY_PICKER_JS = """
function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function clickEl(el) {
    if (!el || !isVisible(el)) return false;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    el.click();
    return true;
}
// 搜索命中后：点选三级列中最深层的 active/selected 项
let best = null;
let bestScore = -1;
for (const el of document.querySelectorAll(
    '[class*="active"], [class*="selected"], [class*="checked"], [class*="current"], [class*="highlight"]'
)) {
    if (!isVisible(el)) continue;
    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!t || t.length < 2 || t.includes('最近使用')) continue;
    const r = el.getBoundingClientRect();
    const score = r.left + r.top;
    if (score > bestScore) {
        bestScore = score;
        best = el;
    }
}
if (best && clickEl(best)) {
    return { ok: true, text: (best.innerText || '').slice(0, 50) };
}
// 点选带 > 的已选路径条
for (const el of document.querySelectorAll('div, span, li, button')) {
    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!t.includes('>')) continue;
    if (t.split('>').filter(p => p.trim()).length < 2) continue;
    if (clickEl(el)) return { ok: true, text: t.slice(0, 50) };
}
return { ok: false, text: '' };
"""


def _confirm_category_picker_selection(
    page: DpPage,
    account_id: str,
    label: str,
) -> bool:
    """手动选类：确认搜索/列选结果，消除「请选择完整的分类」。"""
    try:
        raw = page.run_js(_CONFIRM_CATEGORY_PICKER_JS)
        info = raw if isinstance(raw, dict) else {}
        if info.get("ok"):
            print(
                f"[{account_id}] [{label}] 已确认分类选择：{info.get('text', '')}",
                flush=True,
            )
            time.sleep(0.6)
            return True
    except Exception:
        pass
    return False


DEFAULT_BRANCH_A_CATEGORY_ADVANCE_WAIT = 45


def _read_branch_a_confirm_publish_state(page: DpPage) -> dict[str, Any]:
    """分支 A：检测「确认发布该类商品」是否可见且可点。"""
    try:
        state = page.run_js(
            """
            const body = document.body?.innerText || '';
            const compact = body.replace(/\\s+/g, '');
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function isDisabled(el) {
                return !!el.disabled
                    || el.getAttribute('aria-disabled') === 'true'
                    || (el.className || '').includes('disabled');
            }
            function norm(t) { return (t || '').replace(/\\s+/g, ''); }
            const blocking = body.includes('请选择完整的分类');
            let selectedPathReady = compact.includes('已选分类') && body.includes('>');
            if (!selectedPathReady) {
                for (const el of document.querySelectorAll(
                    '[class*="selected"], [class*="Selected"], [class*="active"], [class*="checked"], [class*="current"], div, span, li'
                )) {
                    if (!isVisible(el)) continue;
                    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!t.includes('>')) continue;
                    const parts = t.split('>').map((x) => x.trim()).filter(Boolean);
                    if (parts.length >= 3) {
                        selectedPathReady = true;
                        break;
                    }
                }
            }
            let btn = null;
            for (const el of document.querySelectorAll('button, a, div, span')) {
                const t = norm(el.innerText || el.textContent || '');
                if (t !== '确认发布该类商品') continue;
                if (!isVisible(el)) continue;
                btn = el;
                break;
            }
            if (!btn) {
                return {
                    ready: false,
                    visible: false,
                    disabled: true,
                    blocking,
                    selectedPathReady,
                    forceClick: false,
                };
            }
            const visible = isVisible(btn);
            const disabled = isDisabled(btn);
            const r = btn.getBoundingClientRect();
            const ready = visible && !disabled && selectedPathReady && !blocking;
            return {
                ready,
                visible,
                disabled,
                blocking,
                selectedPathReady,
                forceClick: ready || (visible && !disabled && selectedPathReady),
                x: r.left + r.width / 2,
                y: r.top + r.height / 2,
            };
            """
        )
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _click_branch_a_confirm_publish(
    page: DpPage,
    account_id: str,
    label: str,
) -> bool:
    """分支 A：点击「确认发布该类商品」。"""
    prefix = f"[{account_id}] [{label}] "
    _blur_page_focus(page)
    state = _read_branch_a_confirm_publish_state(page)
    if state.get("x") and state.get("y"):
        if _playwright_mouse_at(page, float(state["x"]), float(state["y"])):
            print(f"{prefix}分支 A：已点击「确认发布该类商品」(mouse)", flush=True)
            time.sleep(0.8)
            return True

    confirm = page.ele("text:确认发布该类商品", timeout=1)
    if confirm and _playwright_mouse_click_element(page, confirm):
        print(f"{prefix}分支 A：已点击「确认发布该类商品」", flush=True)
        time.sleep(0.8)
        return True

    try:
        clicked = page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            for (const el of document.querySelectorAll('button, a, div, span')) {
                const t = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
                if (t !== '确认发布该类商品' || !isVisible(el)) continue;
                try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
                el.click();
                return true;
            }
            return false;
            """
        )
        if clicked:
            print(f"{prefix}分支 A：已点击「确认发布该类商品」(JS)", flush=True)
            time.sleep(0.8)
            return True
    except Exception:
        pass

    print(f"{prefix}分支 A：未找到「确认发布该类商品」", flush=True)
    return False


def _wait_branch_a_confirm_publish_ready(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_wait: int = 15,
) -> bool:
    """分支 A：分类已选后等待「确认发布该类商品」可点。"""
    state = _read_branch_a_confirm_publish_state(page)
    if state.get("ready") or state.get("forceClick"):
        return True
    print(
        f"[{account_id}] [{label}] 分支 A：等待「确认发布该类商品」可点…",
        flush=True,
    )
    for sec in range(max_wait):
        _confirm_category_picker_selection(page, account_id, label)
        time.sleep(0.5)
        state = _read_branch_a_confirm_publish_state(page)
        if state.get("ready") or state.get("forceClick"):
            print(
                f"[{account_id}] [{label}] 分支 A：确认按钮已就绪 ({sec + 1}s)",
                flush=True,
            )
            return True
        if (sec + 1) % 5 == 0:
            reason = "按钮未就绪" if not state.get("visible") else "按钮禁用"
            if state.get("selectedPathReady"):
                reason = "已选完整分类，等待确认按钮"
            print(
                f"[{account_id}] [{label}] 分支 A：仍在等待确认按钮… "
                f"({sec + 1}/{max_wait}s, {reason})",
                flush=True,
            )
        time.sleep(1)
    state = _read_branch_a_confirm_publish_state(page)
    return bool(state.get("visible") and not state.get("disabled"))


def _branch_a_advanced_past_category_picker(page: DpPage) -> bool:
    """分支 A：已离开分类选择弹层，进入完善商品信息页。"""
    if page.ele("css:.uploadImgEnter.uploadImgEnterNew", timeout=0.3):
        return True
    if page.ele(
        'css:input[type="file"]:not([data-tracking-click-viewid="detail_img_localfile_upload"])',
        timeout=0.3,
    ):
        return True
    body = _category_page_body_text(page)
    if "确认发布该类商品" in body:
        return False
    if page.ele('css:input[placeholder="请输入关键词搜索分类"]', timeout=0.3):
        return False
    if "商品规格" in body or page.ele("#spec", timeout=0.3):
        return True
    return False


def _wait_for_branch_a_category_advance(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_wait: int = DEFAULT_BRANCH_A_CATEGORY_ADVANCE_WAIT,
) -> bool:
    if _branch_a_advanced_past_category_picker(page):
        return True
    print(
        f"[{account_id}] [{label}] 分支 A：等待离开分类选择页，最多 {max_wait}s…",
        flush=True,
    )
    for sec in range(max_wait):
        time.sleep(1)
        if _branch_a_advanced_past_category_picker(page):
            print(
                f"[{account_id}] [{label}] 分支 A：已进入完善商品信息页 ({sec + 1}s)",
                flush=True,
            )
            return True
        if (sec + 1) % 10 == 0:
            _click_branch_a_confirm_publish(page, account_id, label)
    advanced = _branch_a_advanced_past_category_picker(page)
    if not advanced:
        print(
            f"[{account_id}] [{label}] 分支 A：等待跳转超时 ({max_wait}s)，仍在分类选择页",
            flush=True,
        )
    return advanced


def click_category_branch_a_and_advance(
    page: DpPage,
    account_id: str,
    label: str,
) -> tuple[bool, Literal["", "not_found", "no_advance"]]:
    """分支 A 手动选类：确认类目后点击「确认发布该类商品」并等待跳转。"""
    print(
        f"[{account_id}] [{label}] 分支 A：确认选类后点击「确认发布该类商品」",
        flush=True,
    )
    _confirm_category_picker_selection(page, account_id, label)
    _dismiss_category_search_overlay(page, account_id, label)
    _wait_branch_a_confirm_publish_ready(page, account_id, label)
    if not _click_branch_a_confirm_publish(page, account_id, label):
        return False, "not_found"
    if not _wait_for_branch_a_category_advance(page, account_id, label):
        if _click_branch_a_confirm_publish(page, account_id, label):
            if _wait_for_branch_a_category_advance(page, account_id, label, max_wait=20):
                return True, ""
        return False, "no_advance"
    return True, ""


DEFAULT_CATEGORY_RENDER_WAIT = 45


def _category_section_is_ready(page: DpPage) -> bool:
    """商品分类区块已渲染：推荐类目卡片、或「暂无推荐/选择分类」手动入口。"""
    body = _category_page_body_text(page)
    if "商品分类" not in body:
        return False
    if "暂无推荐的分类" in body:
        return True
    if "暂无推荐" in body and "手动选择" in body:
        return True
    if "查看更多推荐" in body and body.count(">") >= 2:
        return True
    try:
        ready = page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 40 && r.height > 16
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            const bodyText = document.body?.innerText || '';
            if (bodyText.includes('暂无推荐的分类')) return true;
            if (bodyText.includes('暂无推荐') && bodyText.includes('手动选择')) return true;
            for (const el of document.querySelectorAll('div, span, li, button, a')) {
                const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (!t.includes('>')) continue;
                if (t.split('>').filter(p => p.trim()).length < 2) continue;
                if (!isVisible(el)) continue;
                return true;
            }
            for (const el of document.querySelectorAll('button, a, span, div')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t !== '选择分类') continue;
                if (isVisible(el)) return true;
            }
            return false;
            """
        )
        return bool(ready)
    except Exception:
        return body.count(">") >= 2


def _wait_for_category_section_ready(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_wait: int = DEFAULT_CATEGORY_RENDER_WAIT,
) -> bool:
    """主图/标题完成后等待「商品分类」区块渲染，再判定手动选类或点下一步。"""
    if _category_section_is_ready(page):
        return True
    print(
        f"[{account_id}] [{label}] 等待商品分类区块渲染…",
        flush=True,
    )
    for sec in range(max_wait):
        time.sleep(1)
        if _category_section_is_ready(page):
            print(
                f"[{account_id}] [{label}] 商品分类已渲染 ({sec + 1}s)",
                flush=True,
            )
            return True
        if (sec + 1) % 5 == 0:
            print(
                f"[{account_id}] [{label}] 仍在等待商品分类渲染… ({sec + 1}/{max_wait}s)",
                flush=True,
            )
    print(
        f"[{account_id}] [{label}] 商品分类渲染等待超时 ({max_wait}s)，继续尝试后续步骤",
        flush=True,
    )
    return False


DEFAULT_CATEGORY_ADVANCE_WAIT = 30
CATEGORY_NEXT_BURST_MIN = 3
CATEGORY_NEXT_BURST_MAX = 5
DEFAULT_CATEGORY_SUBMIT_READY_WAIT = 60


def _blur_page_focus(page: DpPage) -> None:
    try:
        page.run_js(
            """
            const ae = document.activeElement;
            if (ae && ae !== document.body && typeof ae.blur === 'function') ae.blur();
            """
        )
    except Exception:
        pass


def _playwright_mouse_at(page: DpPage, x: float, y: float) -> bool:
    """Playwright 底层鼠标坐标点击（isTrusted），与人工点击最接近。"""
    raw = getattr(page, "_page", None)
    if raw is None:
        return False
    try:
        raw.mouse.move(x, y)
        time.sleep(random.uniform(0.06, 0.14))
        raw.mouse.down()
        time.sleep(random.uniform(0.04, 0.10))
        raw.mouse.up()
        return True
    except Exception:
        return False


def _playwright_mouse_click_element(page: DpPage, el: Any) -> bool:
    try:
        el._loc.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    try:
        box = el._loc.bounding_box(timeout=3000)
    except Exception:
        box = None
    if box and box.get("width") and box.get("height"):
        x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
        y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
        if _playwright_mouse_at(page, x, y):
            return True
    try:
        el._loc.click(timeout=5000)
        return True
    except Exception:
        pass
    try:
        el._loc.click(timeout=5000, force=True)
        return True
    except Exception:
        return False


_HUMAN_CLICK_JS = """
function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 4 && r.height > 4
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function humanClick(el) {
    if (!el || !isVisible(el)) return false;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const base = { bubbles: true, cancelable: true, view: window, clientX: cx, clientY: cy };
    const ptrDown = Object.assign({}, base, { pointerId: 1, pointerType: 'mouse', isPrimary: true });
    const ptrUp = Object.assign({}, base, { pointerId: 1, pointerType: 'mouse', isPrimary: true });
    el.dispatchEvent(new PointerEvent('pointerdown', ptrDown));
    el.dispatchEvent(new MouseEvent('mousedown', base));
    el.dispatchEvent(new PointerEvent('pointerup', ptrUp));
    el.dispatchEvent(new MouseEvent('mouseup', base));
    el.dispatchEvent(new MouseEvent('click', base));
    if (typeof el.click === 'function') el.click();
    return true;
}
return humanClick(arguments[0]);
"""


def _is_still_on_category_publish_step(page: DpPage) -> bool:
    """仍在分类页「下一步，完善商品信息」步骤（未进入规格/详情页）。"""
    if page.ele("#spec", timeout=0.3):
        return False
    if page.ele('css:input[data-tracking-click-viewid="detail_img_localfile_upload"]', timeout=0.3):
        return False
    body = _category_page_body_text(page)
    if ("商品规格" in body or "规格类型" in body) and "完善商品信息" not in body.replace(" ", ""):
        return False
    if page.ele('css:button[data-e2e-id="e2e-publish-button"]', timeout=0.3):
        return True
    if page.ele("#bottomSubmitBtnId", timeout=0.3):
        return True
    compact = body.replace(" ", "")
    if "下一步" in compact and "完善商品信息" in compact:
        return True
    return "商品分类" in body and "商品主图" in body


def _wait_for_category_page_advance(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_wait: int = DEFAULT_CATEGORY_ADVANCE_WAIT,
    mode: CategoryPageMode = "render_wait",
    ui_type: str = "C",
) -> bool:
    """连续点击后等待跳转到完善商品信息页；已跳转则立即返回。"""
    if not _is_still_on_category_publish_step(page):
        return True

    print(
        f"[{account_id}] [{label}] 继续监听页面跳转，最多 {max_wait}s…",
        flush=True,
    )
    for sec in range(max_wait):
        time.sleep(1)
        if not _is_still_on_category_publish_step(page):
            print(
                f"[{account_id}] [{label}] 已跳转到完善商品信息页 ({sec + 1}s)",
                flush=True,
            )
            return True
        if (sec + 1) % 10 == 0:
            print(
                f"[{account_id}] [{label}] 仍在等待页面跳转… ({sec + 1}/{max_wait}s)",
                flush=True,
            )
            if mode == "manual_picker":
                _confirm_category_picker_selection(page, account_id, label)
            elif ui_type == "C":
                _click_branch_c_category_recommendation(page, account_id, label)
            _dismiss_category_search_overlay(page, account_id, label)
            if ui_type == "C":
                _click_branch_c_category_next(page, account_id, label)
            else:
                _mouse_click_category_next_button(page, account_id, label)

    advanced = not _is_still_on_category_publish_step(page)
    if not advanced:
        print(
            f"[{account_id}] [{label}] 等待跳转超时 ({max_wait}s)，仍在分类页",
            flush=True,
        )
    return advanced


def _category_page_needs_manual_selection(page: DpPage) -> bool:
    """分支 C 图二：暂无推荐分类，需点击「选择分类」后在搜索框选类目（图一弹层）。"""
    if _is_image_category_recommendation_modal_visible(page):
        return False
    if _branch_c_category_already_selected(page):
        return False
    body = _category_page_body_text(page)
    if "暂无推荐的分类" in body:
        return True
    if "暂无推荐" in body and "手动选择" in body:
        return True
    if "暂无推荐" in body:
        return True
    # 已有推荐类目路径（图一）→ 不必手动选类
    if "商品分类" in body and body.count(">") >= 2:
        if page.ele("#bottomSubmitBtnId", timeout=0.5) or page.ele("text:下一步", timeout=0.5):
            return False
    if page.ele("text:选择分类", timeout=0.5):
        if "确认发布该类商品" in body:
            return False
        return True
    return False


def _branch_c_category_already_selected(page: DpPage) -> bool:
    """分支 C：推荐分类已选中（带勾选/路径），可直接点下一步。"""
    from pdd_agent.skills.listing.category_branch_c_modal import (
        body_text_indicates_recommendation_modal,
        is_modal_blocking_category_advance,
    )
    from pdd_agent.skills.listing.category_branch_c_recent import (
        branch_c_category_path_ready_strict,
    )

    body = _category_page_body_text(page)
    if body_text_indicates_recommendation_modal(body) or is_modal_blocking_category_advance(page):
        return False
    if _is_image_category_recommendation_modal_visible(page):
        return False
    return branch_c_category_path_ready_strict(page)


def _open_category_selector_panel(page: DpPage) -> bool:
    for locator in (
        "text:选择分类",
        "text:手动选择商品分类",
        "text:手动选择分类",
    ):
        el = page.ele(locator, timeout=1)
        if el:
            try:
                page.run_js("arguments[0].click();", el)
            except Exception:
                el.click()
            time.sleep(2)
            return True
    try:
        clicked = page.run_js(
            """
            const labels = ['选择分类', '手动选择商品分类', '手动选择分类'];
            for (const el of document.querySelectorAll('button,a,span,div')) {
                const text = (el.innerText || el.textContent || '').trim();
                if (!labels.includes(text)) continue;
                const r = el.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) continue;
                el.click();
                return true;
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


def _dismiss_category_search_overlay(page: DpPage, account_id: str, label: str) -> bool:
    """收起「搜索类目/分类选择」浮层，避免遮挡底部「下一步」。"""
    try:
        result = page.run_js(
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
            const text = document.body?.innerText || '';
            let hasOverlay = false;
            if (text.includes('搜索类目') || text.includes('分类选择')) {
                hasOverlay = true;
            }
            let closed = false;
            const closeSelectors = [
                '[data-testid="beast-core-icon-close"]',
                '[class*="closeIcon"]',
                '[class*="close"]',
                'button[aria-label*="关闭"]',
            ];
            for (const sel of closeSelectors) {
                for (const el of document.querySelectorAll(sel)) {
                    if (!isVisible(el)) continue;
                    try { el.click(); closed = true; } catch (e) {}
                    if (closed) break;
                }
                if (closed) break;
            }
            if (!closed && hasOverlay) {
                const esc = new KeyboardEvent('keydown', {
                    key: 'Escape',
                    code: 'Escape',
                    bubbles: true,
                    cancelable: true,
                });
                document.dispatchEvent(esc);
                closed = true;
            }
            return { hasOverlay, closed };
            """
        )
        info = result if isinstance(result, dict) else {}
        if info.get("closed"):
            print(
                f"[{account_id}] [{label}] 已收起分类搜索浮层，避免遮挡下一步按钮",
                flush=True,
            )
            time.sleep(0.35)
            return True
    except Exception:
        pass
    return False


def _find_first_category_search_result(page: DpPage):
    for sel in (
        "css:li.SPP_searchItem_5-188-0",
        "css:li[class*='searchItem']",
        "css:li[class*='SearchItem']",
    ):
        el = page.ele(sel, timeout=1)
        if el:
            return el
    return None


def _select_category_by_keyword_search(
    page: DpPage,
    account_id: str,
    label: str,
    category_keyword: str,
) -> bool:
    keyword = str(category_keyword or "玩偶").strip() or "玩偶"
    search_input = page.ele('css:input[placeholder="请输入关键词搜索分类"]', timeout=3)
    if not search_input:
        print(f"[{account_id}] [{label}] 未找到分类搜索框", flush=True)
        return False
    search_input.click()
    time.sleep(0.5)
    search_input.input(keyword, clear=True)
    time.sleep(2)

    first_cat = _find_first_category_search_result(page)
    if first_cat:
        try:
            page.run_js("arguments[0].click();", first_cat)
        except Exception:
            first_cat.click()
        time.sleep(1)
        print(f"[{account_id}] [{label}] 已选择搜索分类：{keyword}", flush=True)
        return True

    try:
        clicked = page.run_js(
            """
            const items = Array.from(document.querySelectorAll(
                'li[class*="searchItem"], li[class*="SearchItem"], [class*="searchItem"] li'
            )).filter(el => {
                const t = (el.innerText || el.textContent || '').trim();
                return t && t.length > 2 && !t.includes('最近使用') && !t.includes('清空');
            });
            if (!items.length) return false;
            items[0].click();
            return true;
            """
        )
        if clicked:
            time.sleep(1)
            print(f"[{account_id}] [{label}] 已选择搜索分类（JS）：{keyword}", flush=True)
            return True
    except Exception:
        pass

    print(f"[{account_id}] [{label}] 分类搜索无结果：{keyword}", flush=True)
    return False


def _human_click_element(page: DpPage, el: Any) -> bool:
    if _playwright_mouse_click_element(page, el):
        return True
    try:
        return bool(page.run_js(_HUMAN_CLICK_JS, el))
    except Exception:
        return False


_CATEGORY_RECOMMENDATION_POINT_JS = """
function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 40 && r.height > 20
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function isCategoryPath(text) {
    const t = (text || '').replace(/\\s+/g, ' ').trim();
    if (!t.includes('>')) return false;
    const parts = t.split('>').map(p => p.trim()).filter(Boolean);
    return parts.length >= 2 && t.length >= 10 && t.length <= 150;
}
function pointOf(el, label) {
    if (!el || !isVisible(el)) return null;
    try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: label.slice(0, 60) };
}
for (const el of document.querySelectorAll(
    '[class*="selected"], [class*="Selected"], [class*="active"], [class*="checked"], [class*="current"]'
)) {
    const t = (el.innerText || el.textContent || '').trim();
    const pt = pointOf(el, t);
    if (pt && isCategoryPath(t)) return pt;
}
const cards = [];
for (const el of document.querySelectorAll('div, li, span, button, a')) {
    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!isCategoryPath(t)) continue;
    const r = el.getBoundingClientRect();
    if (!isVisible(el)) continue;
    cards.push({ el, score: r.width * r.height, t });
}
cards.sort((a, b) => a.score - b.score);
for (const item of cards) {
    const pt = pointOf(item.el, item.t);
    if (pt) return pt;
}
return null;
"""


_IMAGE_CATEGORY_RECOMMENDATION_MODAL_JS = """
function isVisible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 8 && r.height > 8
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}
function norm(t) {
    return (t || '').replace(/\\s+/g, '');
}
function isCategoryOptionText(t) {
    const s = (t || '').replace(/\\s+/g, ' ').trim();
    if (!s.includes('>')) return false;
    const parts = s.split('>').map((x) => x.trim()).filter(Boolean);
    return parts.length >= 2 && s.length >= 8 && s.length <= 180;
}
function findModalRoot() {
    for (const el of document.querySelectorAll(
        '[role="dialog"], [class*="modal"], [class*="Modal"], [class*="dialog"], [class*="Dialog"], [class*="popup"], [class*="Popup"], [class*="drawer"], [class*="Drawer"]'
    )) {
        if (!isVisible(el)) continue;
        const t = el.innerText || '';
        if (!t.includes('推荐分类')) continue;
        if (!t.includes('确认')) continue;
        if (!t.includes('请选择')) continue;
        if (!t.includes('为您推荐分类') && !t.includes('根据您上传的图片')) continue;
        return el;
    }
    return null;
}
function detectImageCategoryRecommendationModal() {
    return { visible: !!findModalRoot() };
}
function handleImageCategoryRecommendationModal() {
    const root = findModalRoot();
    if (!root) return { ok: false, reason: 'not_visible' };
    let selected = false;
    let selectedText = '';
    const radios = Array.from(root.querySelectorAll('input[type="radio"]')).filter(isVisible);
    radios.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
    for (const input of radios) {
        try {
            input.click();
            input.checked = true;
            selected = true;
            const label = input.closest('label') || input.parentElement;
            selectedText = ((label && label.innerText) || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
            break;
        } catch (e) {}
    }
    if (!selected) {
        const options = [];
        for (const el of root.querySelectorAll('label, li, div, span, button')) {
            const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!isCategoryOptionText(t)) continue;
            if (!isVisible(el)) continue;
            const r = el.getBoundingClientRect();
            options.push({ el, y: r.top, t });
        }
        options.sort((a, b) => a.y - b.y || a.t.length - b.t.length);
        if (options.length) {
            try {
                options[0].el.click();
                selected = true;
                selectedText = options[0].t.slice(0, 80);
            } catch (e) {}
        }
    }
    let confirmed = false;
    for (const el of root.querySelectorAll('button, a, div, span')) {
        const t = norm(el.innerText || el.textContent || '');
        if (t !== '确认') continue;
        if (!isVisible(el)) continue;
        try { el.click(); confirmed = true; break; } catch (e) {}
    }
    return {
        ok: selected && confirmed,
        selected,
        confirmed,
        selectedText,
    };
}
"""


def _is_image_category_recommendation_modal_visible(page: DpPage) -> bool:
    """分支 C：上传主图后「根据图片推荐分类」弹窗是否可见。"""
    from pdd_agent.skills.listing.category_branch_c_modal import (
        is_image_category_recommendation_modal_visible,
    )

    return is_image_category_recommendation_modal_visible(page)


def _handle_image_category_recommendation_modal(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    wait_seconds: int = 0,
) -> bool:
    """
    分支 C 以图推荐分类弹窗：选第一项 → 点「确认」。
    无弹窗返回 False，走原有分类链路。
    """
    from pdd_agent.skills.listing.category_branch_c_modal import (
        handle_image_category_recommendation_modal,
    )

    return handle_image_category_recommendation_modal(
        page,
        account_id,
        label,
        wait_seconds=wait_seconds,
    )


def _click_branch_c_category_recommendation(
    page: DpPage,
    account_id: str,
    label: str,
) -> bool:
    """Playwright 坐标点击推荐类目，完成平台分类校验。"""
    if _handle_image_category_recommendation_modal(page, account_id, label):
        return True
    if _branch_c_category_already_selected(page):
        return False
    try:
        point = page.run_js(_CATEGORY_RECOMMENDATION_POINT_JS)
    except Exception:
        point = None
    if not isinstance(point, dict) or not point.get("x") or not point.get("y"):
        return False
    if _playwright_mouse_at(page, float(point["x"]), float(point["y"])):
        print(
            f"[{account_id}] [{label}] 已点击推荐类目：{point.get('text', '')}",
            flush=True,
        )
        time.sleep(random.uniform(0.5, 1.0))
        return True
    return False


def _read_category_submit_state(page: DpPage) -> dict[str, Any]:
    try:
        state = page.run_js(
            """
            const body = document.body?.innerText || '';
            const compact = body.replace(/\\s+/g, '');
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 4 && r.height > 4
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function norm(t) { return (t || '').replace(/\\s+/g, ''); }
            function isDisabled(el) {
                return !!el.disabled
                    || el.getAttribute('aria-disabled') === 'true'
                    || (el.className || '').includes('disabled');
            }
            const blocking = body.includes('请选择完整的分类')
                || body.includes('请选择完整分类');
            const manualPickerOpen = !!Array.from(document.querySelectorAll(
                'input[placeholder="请输入关键词搜索分类"], div, span, li, button'
            )).find((el) => {
                const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (!isVisible(el)) return false;
                return t.includes('搜索类目') || t.includes('分类选择');
            });
            function isInRecentSection(el) {
                let node = el;
                for (let i = 0; i < 10 && node; i++) {
                    const t = (node.innerText || node.textContent || '').slice(0, 120);
                    if (t.includes('最近使用')) return true;
                    node = node.parentElement;
                }
                return false;
            }
            let selectedPathReady = false;
            if (compact.includes('已根据主轮播图选择分类')) {
                selectedPathReady = true;
            }
            if (!selectedPathReady && compact.includes('已选分类') && body.includes('>')) {
                selectedPathReady = true;
            }
            if (!selectedPathReady) {
                for (const el of document.querySelectorAll(
                    '[class*="selected"], [class*="Selected"], [class*="active"], [class*="checked"], [class*="current"], div, span, li'
                )) {
                    if (!isVisible(el) || isInRecentSection(el)) continue;
                    const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!t.includes('>')) continue;
                    const parts = t.split('>').map((x) => x.trim()).filter(Boolean);
                    if (parts.length >= 3) {
                        selectedPathReady = true;
                        break;
                    }
                }
            }
            if (blocking) selectedPathReady = false;
            let btn = document.querySelector('[data-e2e-id="e2e-publish-button"]')
                || document.getElementById('bottomSubmitBtnId');
            let visible = btn ? isVisible(btn) : false;
            let disabled = btn ? isDisabled(btn) : true;
            if (!visible) {
                for (const el of document.querySelectorAll('button, a, div, span')) {
                    const t = norm(el.innerText || el.textContent || '');
                    if (!t.includes('下一步') || !t.includes('完善商品信息')) continue;
                    if (!isVisible(el)) continue;
                    btn = el;
                    visible = true;
                    disabled = isDisabled(el);
                    break;
                }
            }
            if (!btn) return { ready: false, reason: 'no_button', blocking };
            const r = btn.getBoundingClientRect();
            const readyByPath = visible && !disabled && selectedPathReady && !blocking;
            return {
                ready: readyByPath,
                blocking,
                disabled,
                visible,
                manualPickerOpen,
                selectedPathReady,
                forceClick: readyByPath,
                x: r.left + r.width / 2,
                y: r.top + r.height / 2,
            };
            """
        )
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _wait_category_submit_ready(
    page: DpPage,
    account_id: str,
    label: str,
    *,
    max_wait: int = DEFAULT_CATEGORY_SUBMIT_READY_WAIT,
    click_recommendation: bool = True,
) -> bool:
    """等待「请选择完整的分类」消失且下一步按钮可点。"""
    state = _read_category_submit_state(page)
    if state.get("ready"):
        return True
    print(
        f"[{account_id}] [{label}] 等待分类校验通过、下一步可点…",
        flush=True,
    )
    for sec in range(max_wait):
        if click_recommendation:
            _click_branch_c_category_recommendation(page, account_id, label)
        else:
            _confirm_category_picker_selection(page, account_id, label)
            _dismiss_category_search_overlay(page, account_id, label)
        time.sleep(0.8)
        state = _read_category_submit_state(page)
        if state.get("ready"):
            print(
                f"[{account_id}] [{label}] 分类校验已通过 ({sec + 1}s)",
                flush=True,
            )
            return True
        if state.get("forceClick") and sec >= 2:
            print(
                f"[{account_id}] [{label}] 已选分类且按钮可见，结束等待并尝试点击 ({sec + 1}s)",
                flush=True,
            )
            return True
        if (sec + 1) % 10 == 0:
            reason = "请选择完整的分类" if state.get("blocking") else (
                "按钮未就绪" if not state.get("visible") else "按钮禁用"
            )
            if state.get("selectedPathReady") and state.get("manualPickerOpen"):
                reason = "已选完整分类，但弹层/校验未收起"
            print(
                f"[{account_id}] [{label}] 仍在等待分类校验… ({sec + 1}/{max_wait}s, {reason})",
                flush=True,
            )
        time.sleep(1)
    state = _read_category_submit_state(page)
    return bool(state.get("ready") or state.get("forceClick"))


def _resolve_category_next_click_point(page: DpPage) -> dict[str, Any]:
    try:
        point = page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 8 && r.height > 8
                    && s.display !== 'none' && s.visibility !== 'hidden'
                    && parseFloat(s.opacity || '1') > 0.05;
            }
            function norm(t) {
                return (t || '').replace(/\\s+/g, '');
            }
            function pick(el, method) {
                if (!el || !isVisible(el)) return null;
                try { el.scrollIntoView({ block: 'center', behavior: 'instant' }); } catch (e) {}
                const r = el.getBoundingClientRect();
                const cx = r.left + r.width / 2;
                const cy = r.top + r.height / 2;
                let target = document.elementFromPoint(cx, cy) || el;
                for (let i = 0; i < 8 && target; i++) {
                    const tag = (target.tagName || '').toLowerCase();
                    if (target.id === 'bottomSubmitBtnId' || tag === 'button') break;
                    const t = norm(target.innerText || target.textContent || '');
                    if (t.includes('下一步') && t.includes('完善商品信息')) break;
                    target = target.parentElement;
                }
                const tr = (target || el).getBoundingClientRect();
                return {
                    x: tr.left + tr.width / 2,
                    y: tr.top + tr.height / 2,
                    method,
                    id: (target || el).id || '',
                };
            }
            const byE2e = document.querySelector('[data-e2e-id="e2e-publish-button"]');
            const fromE2e = pick(byE2e, 'e2e-publish-button');
            if (fromE2e) return fromE2e;
            const byId = document.getElementById('bottomSubmitBtnId');
            const fromId = pick(byId, 'bottomSubmitBtnId');
            if (fromId) return fromId;
            const candidates = [];
            for (const el of document.querySelectorAll('button, a, div, span')) {
                const t = norm(el.innerText || el.textContent || '');
                if (!t.includes('下一步') || !t.includes('完善商品信息')) continue;
                if (!isVisible(el)) continue;
                const r = el.getBoundingClientRect();
                candidates.push({ el, score: r.width * r.height });
            }
            candidates.sort((a, b) => b.score - a.score);
            if (candidates.length) return pick(candidates[0].el, 'text_match');
            return null;
            """
        )
        return point if isinstance(point, dict) else {}
    except Exception:
        return {}


def _click_branch_c_category_next(
    page: DpPage,
    account_id: str,
    label: str,
) -> tuple[bool, str]:
    from pdd_agent.skills.listing.category_branch_c_next import (
        click_branch_c_category_next_button,
    )

    return click_branch_c_category_next_button(page, account_id, label)


def _mouse_click_category_next_button(
    page: DpPage,
    account_id: str,
    label: str,
) -> tuple[bool, str]:
    """用 Playwright 坐标鼠标点击「下一步」按钮。"""
    prefix = f"[{account_id}] [{label}] "
    _blur_page_focus(page)
    try:
        page.run_js("window.scrollTo(0, document.body.scrollHeight);")
    except Exception:
        pass
    time.sleep(0.35)

    raw = getattr(page, "_page", None)
    if raw is not None:
        try:
            loc = raw.locator("#bottomSubmitBtnId")
            loc.wait_for(state="visible", timeout=2000)
            box = loc.bounding_box(timeout=2000)
            if box:
                x = box["x"] + box["width"] / 2
                y = box["y"] + box["height"] / 2
                if _playwright_mouse_at(page, x, y):
                    print(f"{prefix}已坐标点击「下一步」(mouse/#bottomSubmitBtnId)", flush=True)
                    return True, "mouse/#bottomSubmitBtnId"
        except Exception:
            pass

    point = _resolve_category_next_click_point(page)
    if point.get("x") and point.get("y"):
        if _playwright_mouse_at(page, float(point["x"]), float(point["y"])):
            method = point.get("method") or "elementFromPoint"
            print(f"{prefix}已坐标点击「下一步」(mouse/{method})", flush=True)
            return True, f"mouse/{method}"

    for locator in ("#bottomSubmitBtnId", "text:下一步，完善商品信息"):
        btn = page.ele(locator, timeout=1)
        if btn and _playwright_mouse_click_element(page, btn):
            print(f"{prefix}已点击「下一步」({locator})", flush=True)
            return True, locator

    return False, ""


def _click_category_next_step(
    page: DpPage,
    *,
    ui_type: str = "C",
    account_id: str = "",
    label: str = "",
    quiet: bool = False,
) -> bool:
    """点击分类页「下一步，完善商品信息」；优先 Playwright 坐标鼠标。"""
    if ui_type == "C":
        _click_branch_c_category_recommendation(page, account_id, label)
    _dismiss_category_search_overlay(page, account_id, label)
    if not quiet:
        time.sleep(0.4)
    else:
        time.sleep(0.12)

    ok, _method = (
        _click_branch_c_category_next(page, account_id, label)
        if ui_type == "C"
        else _mouse_click_category_next_button(page, account_id, label)
    )
    if ok:
        time.sleep(0.25 if quiet else 0.8)
        return True

    if ui_type != "C":
        confirm = page.ele("text:确认发布该类商品", timeout=1)
        if confirm and _playwright_mouse_click_element(page, confirm):
            return True

    prefix = f"[{account_id}] [{label}] " if account_id and label else ""
    if not quiet:
        print(f"{prefix}未找到「下一步，完善商品信息」按钮", flush=True)
    return False


def _click_category_next_step_burst(
    page: DpPage,
    *,
    ui_type: str = "C",
    account_id: str = "",
    label: str = "",
    burst_min: int = CATEGORY_NEXT_BURST_MIN,
    burst_max: int = CATEGORY_NEXT_BURST_MAX,
) -> bool:
    """等待分类可提交 → 坐标点击下一步 → 未跳转则再随机连点。"""
    if ui_type == "C":
        _wait_category_submit_ready(page, account_id, label)
    _dismiss_category_search_overlay(page, account_id, label)

    if not _click_category_next_step(
        page, ui_type=ui_type, account_id=account_id, label=label
    ):
        return False
    if not _is_still_on_category_publish_step(page):
        return True

    extra = random.randint(burst_min, burst_max)
    print(
        f"[{account_id}] [{label}] 首次点击后未跳转，再随机坐标点击 {extra} 次…",
        flush=True,
    )
    for i in range(extra):
        if not _is_still_on_category_publish_step(page):
            print(
                f"[{account_id}] [{label}] 连续点击后已跳转（额外第 {i + 1}/{extra} 次后）",
                flush=True,
            )
            return True
        print(
            f"[{account_id}] [{label}] 再次坐标点击「下一步」({i + 1}/{extra})",
            flush=True,
        )
        if ui_type == "C":
            _click_branch_c_category_recommendation(page, account_id, label)
        _dismiss_category_search_overlay(page, account_id, label)
        if ui_type == "C":
            _click_branch_c_category_next(page, account_id, label)
        else:
            _mouse_click_category_next_button(page, account_id, label)
        time.sleep(random.uniform(0.45, 0.85))
    return True


def _click_branch_c_publish_tab(
    page: DpPage,
    tab_name: str,
    *,
    account_id: str = "",
    label: str = "",
) -> bool:
    """点击分支 C 顶部「以图发品 / 搜索发品」标签。"""
    target = str(tab_name or "").strip()
    if not target:
        return False
    prefix = f"[{account_id}] [{label}] " if account_id and label else (
        f"[{account_id}] " if account_id else ""
    )
    try:
        clicked = page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            const target = arguments[0];
            for (const el of document.querySelectorAll('div, span, a, button, li, p')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t !== target || !isVisible(el)) continue;
                el.click();
                return true;
            }
            return false;
            """,
            target,
        )
        if clicked:
            print(f"{prefix}分支 C：已切换到「{target}」", flush=True)
            time.sleep(1.5)
            return True
    except Exception:
        pass
    tab_el = page.ele(f"text:{target}", timeout=2)
    if tab_el:
        try:
            page.run_js("arguments[0].click();", tab_el)
        except Exception:
            tab_el.click()
        print(f"{prefix}分支 C：已切换到「{target}」", flush=True)
        time.sleep(1.5)
        return True
    print(f"{prefix}分支 C：未找到「{target}」标签", flush=True)
    return False


def _branch_c_carousel_upload_count(page: DpPage) -> tuple[int, int]:
    """解析轮播图上传进度，如「上传图片 (2/10)」。"""
    try:
        result = page.run_js(
            """
            const body = document.body?.innerText || '';
            const m = body.match(/上传图片\\s*[（(]\\s*(\\d+)\\s*\\/\\s*(\\d+)\\s*[）)]/);
            if (m) return [parseInt(m[1], 10), parseInt(m[2], 10)];
            let visible = 0;
            for (const img of document.querySelectorAll(
                '[class*="carousel"] img, [class*="Carousel"] img, [class*="uploadImg"] img'
            )) {
                const r = img.getBoundingClientRect();
                if (r.width > 30 && r.height > 30) visible++;
            }
            return [visible, 10];
            """
        )
        if isinstance(result, list) and len(result) >= 2:
            return int(result[0]), int(result[1])
    except Exception:
        pass
    return 0, 10


def _find_branch_c_cover_input(page: DpPage):
    for sel in (
        'css:input[data-tracking-click-viewid="local_upload"]',
        'css:input[type="file"][accept*="image"]',
        'css:input[type="file"]:not([data-tracking-click-viewid="detail_img_localfile_upload"])',
    ):
        el = page.ele(sel, timeout=1)
        if el:
            return el
    return None


def _read_branch_c_cover_upload_error(page: DpPage) -> str:
    return read_pdd_image_dimension_error(page)


def _raise_if_branch_c_cover_upload_rejected(
    page: DpPage,
    *,
    account_id: str = "",
    label: str = "",
) -> None:
    raise_if_pdd_image_dimension_rejected(
        page,
        account_id=account_id,
        label=label,
        image_kind="carousel",
    )


def _reveal_branch_c_carousel_section(page: DpPage) -> None:
    for sel in (
        "css:.goodsCarousel_btns__22KMn",
        "css:[class*='goodsCarousel']",
        "css:[class*='GoodsCarousel']",
    ):
        section_ele = page.ele(sel, timeout=0.5)
        if section_ele:
            try:
                page.run_js('arguments[0].style.display = "flex";', section_ele)
            except Exception:
                pass


def _click_branch_c_upload_placeholder(
    page: DpPage,
    *,
    account_id: str = "",
    label: str = "",
) -> bool:
    prefix = f"[{account_id}] [{label}] " if account_id and label else ""
    try:
        clicked = page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            for (const el of document.querySelectorAll('div, span, button, label, a')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (!t.includes('上传图片') || !isVisible(el)) continue;
                el.click();
                return true;
            }
            for (const el of document.querySelectorAll(
                '[class*="upload"], [class*="Upload"], [class*="carousel"], [class*="Carousel"]'
            )) {
                if (!isVisible(el)) continue;
                const t = (el.innerText || el.textContent || '').trim();
                if (t.includes('+') || t.includes('上传')) {
                    el.click();
                    return true;
                }
            }
            return false;
            """
        )
        if clicked:
            print(f"{prefix}分支 C：已点击上传占位区", flush=True)
            time.sleep(0.8)
            from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
                ensure_image_space_modal_cleared,
            )

            ensure_image_space_modal_cleared(
                page, account_id or "", label or "", max_attempts=2
            )
            return True
    except Exception:
        pass
    return False


def _upload_branch_c_cover_files(
    page: DpPage,
    cover_input,
    covers: list[str],
    *,
    account_id: str = "",
    label: str = "",
    wait_seconds: int = 18,
) -> bool:
    paths = [str(p) for p in covers if p]
    if not paths:
        print(f"[{account_id}] [{label}] 分支 C：无可用主图路径", flush=True)
        return False
    try:
        page.run_js(
            """
            arguments[0].style.display = 'block';
            arguments[0].style.visibility = 'visible';
            arguments[0].style.opacity = '1';
            arguments[0].style.width = '1px';
            arguments[0].style.height = '1px';
            """,
            cover_input,
        )
    except Exception:
        pass
    try:
        cover_input.input(paths if len(paths) > 1 else paths[0])
    except Exception as exc:
        print(
            f"[{account_id}] [{label}] 分支 C：主图 input 上传异常：{exc}",
            flush=True,
        )
        return False
    for sec in range(wait_seconds):
        time.sleep(1)
        from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
            ensure_image_space_modal_cleared,
        )

        ensure_image_space_modal_cleared(
            page, account_id or "", label or "", max_attempts=1
        )
        _raise_if_branch_c_cover_upload_rejected(
            page, account_id=account_id, label=label
        )
        current, total = _branch_c_carousel_upload_count(page)
        if current > 0:
            print(
                f"[{account_id}] [{label}] 分支 C：主图已上传 {current}/{total}",
                flush=True,
            )
            return True
        if sec in (4, 9, 14):
            print(
                f"[{account_id}] [{label}] 分支 C：等待主图上传完成… ({sec + 1}/{wait_seconds}s)",
                flush=True,
            )
    current, total = _branch_c_carousel_upload_count(page)
    _raise_if_branch_c_cover_upload_rejected(
        page, account_id=account_id, label=label
    )
    print(
        f"[{account_id}] [{label}] 分支 C：主图上传未完成（{current}/{total}）",
        flush=True,
    )
    return False


def _ensure_branch_c_covers_on_image_tab(
    page: DpPage,
    covers: list[str],
    *,
    account_id: str = "",
    label: str = "",
) -> bool:
    if not _click_branch_c_publish_tab(
        page, "以图发品", account_id=account_id, label=label
    ):
        print(
            f"[{account_id}] [{label}] 分支 C：未能激活「以图发品」，仍尝试上传",
            flush=True,
        )
    _reveal_branch_c_carousel_section(page)
    time.sleep(1)

    for attempt in range(1, 4):
        current, total = _branch_c_carousel_upload_count(page)
        if current > 0:
            print(
                f"[{account_id}] [{label}] 分支 C：主图已在页面上（{current}/{total}）",
                flush=True,
            )
            return True

        cover_input = _find_branch_c_cover_input(page)
        if not cover_input:
            _click_branch_c_upload_placeholder(
                page, account_id=account_id, label=label
            )
            cover_input = _find_branch_c_cover_input(page)
        if not cover_input:
            print(
                f"[{account_id}] [{label}] 分支 C：第 {attempt}/3 次未找到主图 input",
                flush=True,
            )
            time.sleep(1.5)
            continue

        try:
            if _upload_branch_c_cover_files(
                page,
                cover_input,
                covers,
                account_id=account_id,
                label=label,
            ):
                return True
        except BranchCCoverImageRejected:
            raise
        _click_branch_c_upload_placeholder(page, account_id=account_id, label=label)
        time.sleep(1)

    return _branch_c_carousel_upload_count(page)[0] > 0


def _branch_c_search_publish_and_select(
    page: DpPage,
    search_keyword: str,
    *,
    account_id: str = "",
    label: str = "",
) -> bool:
    """以图发品上传失败时，切到「搜索发品」搜索并点选首条结果。"""
    keyword = str(search_keyword or "笔袋").strip() or "笔袋"
    if not _click_branch_c_publish_tab(
        page, "搜索发品", account_id=account_id, label=label
    ):
        return False
    time.sleep(1.5)

    search_input = None
    for sel in (
        'css:input[placeholder*="搜索"]',
        'css:input[placeholder*="商品"]',
        'css:input[type="search"]',
    ):
        for inp in page.eles(sel) or []:
            placeholder = (inp.attr("placeholder") or "").strip()
            if "关键词搜索分类" in placeholder:
                continue
            search_input = inp
            break
        if search_input:
            break

    if not search_input:
        try:
            handle = page.run_js(
                """
                function isVisible(el) {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2
                        && s.display !== 'none' && s.visibility !== 'hidden';
                }
                for (const inp of document.querySelectorAll('input')) {
                    const ph = (inp.getAttribute('placeholder') || '').trim();
                    if (!ph || ph.includes('关键词搜索分类')) continue;
                    if (!ph.includes('搜索') && !ph.includes('商品')) continue;
                    if (!isVisible(inp)) continue;
                    inp.focus();
                    inp.click();
                    return inp;
                }
                return null;
                """
            )
            if handle:
                search_input = handle
        except Exception:
            search_input = None

    if not search_input:
        print(
            f"[{account_id}] [{label}] 分支 C：搜索发品页未找到搜索框",
            flush=True,
        )
        return False

    try:
        search_input.click()
    except Exception:
        pass
    time.sleep(0.4)
    try:
        search_input.input(keyword, clear=True)
    except Exception as exc:
        print(
            f"[{account_id}] [{label}] 分支 C：搜索发品输入失败：{exc}",
            flush=True,
        )
        return False
    time.sleep(2.5)

    first_cat = _find_first_category_search_result(page)
    if first_cat:
        try:
            page.run_js("arguments[0].click();", first_cat)
        except Exception:
            first_cat.click()
        print(
            f"[{account_id}] [{label}] 分支 C：搜索发品已选分类：{keyword}",
            flush=True,
        )
        time.sleep(1.5)
        return True

    try:
        clicked = page.run_js(
            """
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            const skip = ['以图发品', '搜索发品', '上传图片', '下一步'];
            const items = Array.from(document.querySelectorAll(
                'li, div[class*="item"], div[class*="Item"], [class*="search"] li, [class*="result"]'
            )).filter(el => {
                const t = (el.innerText || el.textContent || '').trim();
                if (t.length < 4 || !isVisible(el)) return false;
                return !skip.some(s => t.includes(s));
            });
            if (!items.length) return false;
            items[0].click();
            return true;
            """
        )
        if clicked:
            print(
                f"[{account_id}] [{label}] 分支 C：搜索发品已选首条结果：{keyword}",
                flush=True,
            )
            time.sleep(1.5)
            return True
    except Exception:
        pass

    print(
        f"[{account_id}] [{label}] 分支 C：搜索发品无可用结果：{keyword}",
        flush=True,
    )
    return False


_MATERIAL_UPLOAD_VIEWIDS = (
    "white_img_localfile_upload",
    "white_background_img_localfile_upload",
    "goods_material_white_img_localfile_upload",
    "material_white_img_localfile_upload",
    "bai_di_img_localfile_upload",
)


def _find_product_material_upload_input(page: DpPage):
    """定位「基本信息」-「商品素材」-「白底图」上传框。"""
    for vid in _MATERIAL_UPLOAD_VIEWIDS:
        ele = page.ele(f'css:input[data-tracking-click-viewid="{vid}"]', timeout=0.3)
        if ele:
            return ele
    for xpath in (
        'xpath://*[normalize-space(text())="白底图"]/following::input[@type="file"][1]',
        'xpath://*[contains(text(),"白底图") and string-length(normalize-space(text()))<=12]/following::input[@type="file"][1]',
        (
            'xpath://*[contains(text(),"商品素材")]'
            '/following::input[@type="file"][not(@data-tracking-click-viewid="detail_img_localfile_upload")][1]'
        ),
    ):
        ele = page.ele(xpath, timeout=0.5)
        if ele:
            return ele
    try:
        marked = page.run_js(
            """
            const exclude = new Set(['detail_img_localfile_upload', 'local_upload']);
            function clearMark() {
                document.querySelectorAll('input[data-pdd-agent-target="material-white-bg"]').forEach((el) => {
                    el.removeAttribute('data-pdd-agent-target');
                });
            }
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }
            clearMark();
            const allInputs = Array.from(document.querySelectorAll('input[type="file"]'));
            for (const input of allInputs) {
                const vid = (input.getAttribute('data-tracking-click-viewid') || '').toLowerCase();
                if (!vid || exclude.has(vid)) continue;
                if (vid.includes('white') || vid.includes('material') || vid.includes('bai_di') || vid.includes('baidi')) {
                    input.setAttribute('data-pdd-agent-target', 'material-white-bg');
                    return true;
                }
            }
            const labels = Array.from(document.querySelectorAll('*')).filter((el) => {
                if (!isVisible(el)) return false;
                const t = (el.innerText || '').trim();
                return t === '白底图' || (t.includes('白底图') && t.length <= 16);
            });
            for (const label of labels) {
                let node = label;
                for (let depth = 0; depth < 10 && node; depth++) {
                    const inputs = node.querySelectorAll('input[type="file"]');
                    for (const input of inputs) {
                        const vid = input.getAttribute('data-tracking-click-viewid') || '';
                        if (vid !== 'detail_img_localfile_upload') {
                            input.setAttribute('data-pdd-agent-target', 'material-white-bg');
                            return true;
                        }
                    }
                    node = node.parentElement;
                }
            }
            return false;
            """
        )
        if marked:
            return page.ele('css:input[data-pdd-agent-target="material-white-bg"]', timeout=0.5)
    except Exception:
        pass
    return None


def _upload_product_material_image(
    page: DpPage,
    account_id: str,
    label: str,
    image_path: str,
) -> bool:
    path = str(image_path or "").strip()
    if not path:
        return False
    print(f"[{account_id}] [{label}] 正在上传商品素材（白底图）...", flush=True)
    try:
        page.run_js("window.scrollTo(0, 0);")
        time.sleep(0.3)
    except Exception:
        pass
    material_input = _find_product_material_upload_input(page)
    if not material_input:
        print(f"[{account_id}] [{label}] 未找到商品素材上传框，跳过 9.png", flush=True)
        return False
    try:
        page.run_js("arguments[0].scrollIntoView({block:'center'});", material_input)
    except Exception:
        pass
    time.sleep(0.3)
    try:
        material_input.input(path)
    except Exception as exc:
        print(
            f"[{account_id}] [{label}] 商品素材上传失败：{_safe_exc(exc)}",
            flush=True,
        )
        return False
    time.sleep(1.5)
    try:
        raise_if_pdd_image_dimension_rejected(
            page,
            account_id=account_id,
            label=label,
            image_kind="material",
        )
    except PddImageDimensionRejected as exc:
        print(
            f"[{account_id}] [{label}] 商品素材尺寸不合规：{exc.platform_message or exc}",
            flush=True,
        )
        return False
    print(f"[{account_id}] [{label}] 商品素材已上传", flush=True)
    return True


def _upload_category_branch_c_covers(
    page: DpPage,
    account_id: str,
    product_info: dict[str, Any],
    listing_info: dict[str, Any],
    covers: list[str],
    *,
    label: str = "",
) -> str:
    uploaded = _ensure_branch_c_covers_on_image_tab(
        page,
        covers,
        account_id=account_id,
        label=label,
    )
    if not uploaded:
        search_keyword = str(
            listing_info.get("category_keyword")
            or product_info.get("category_keyword")
            or "笔袋"
        ).strip()
        print(
            f"[{account_id}] [{label}] 分支 C：以图发品主图未上传，尝试「搜索发品」",
            flush=True,
        )
        if not _branch_c_search_publish_and_select(
            page,
            search_keyword,
            account_id=account_id,
            label=label,
        ):
            raise RuntimeError(
                f"[{account_id}] [{label}] 分支 C 主图上传失败，且搜索发品未选到类目"
                if label
                else f"[{account_id}] 分支 C 主图上传失败，且搜索发品未选到类目"
            )

    time.sleep(random.uniform(1.0, 2.0))
    from pdd_agent.skills.listing.category_branch_c_page_ai_title import (
        META_KEY_CATEGORY_AI_APPLIED,
        prepare_branch_c_cover_upload_title,
    )

    title, ai_on_category = prepare_branch_c_cover_upload_title(
        page,
        account_id,
        product_info,
        listing_info.get("title", ""),
        label=label,
    )
    listing_info[META_KEY_CATEGORY_AI_APPLIED] = ai_on_category
    time.sleep(1)
    return title


def upload_one_listing(
    page: DpPage,
    account_id: str,
    unit: ListingUnit,
    product_info: dict[str, Any],
    defaults: dict[str, str],
    platform_listing_code: str = "",
    run_id: str = "",
    slot_alignment_test: bool = False,
    category_next_burst_demo: bool = True,
) -> dict[str, Any]:
    """对单个上架单元执行完整发布流程。"""
    label = unit.listing_label
    spec_errors = apply_unit_listing_specs(
        unit,
        account_id=account_id,
        allow_ai=True,
        slot_alignment_test=slot_alignment_test,
    )
    if spec_errors:
        return _finish_listing(
            run_id,
            account_id,
            unit,
            status="retryable",
            reason="slot_alignment_failed",
            error=spec_errors[0],
            retryable=True,
            legacy_status="skipped",
            phase="preflight",
            step="slot_alignment",
        )
    if run_id:
        from pdd_agent.api.services.listing_failure_log import (
            record_price_fill_summary,
            validate_unit_image_files,
        )

        validate_unit_image_files(unit, source_run_id=run_id, account_id=account_id)
    _log_unit_spec_snapshot(account_id, unit)
    covers = [str(p.resolve()) for p in unit.carousel_images]
    details = [str(p.resolve()) for p in unit.detail_images]
    material_path = str(unit.material_image.resolve()) if unit.material_image else ""
    style_names = ordered_style_names(unit)
    size_names = list(unit.model_codes)

    listing_info = dict(product_info)
    listing_info["title"] = resolve_listing_title(product_info, account_id)
    time.sleep(random.uniform(1.0, 2.0))

    print(f"[{account_id}] [{label}] 正在跳转商品分类界面...")
    page.get("https://mms.pinduoduo.com/goods/category")
    time.sleep(5)
    if _dismiss_address_required_page(page, account_id, label):
        time.sleep(2)
    from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
        ensure_image_space_modal_cleared,
    )

    ensure_image_space_modal_cleared(page, account_id, label, max_attempts=2)

    ui_type = _detect_category_ui_type(page)
    print(f"[{account_id}] [{label}] 路由判定：分支 {ui_type}")

    if ui_type == "C":
        try:
            listing_info["title"] = _upload_category_branch_c_covers(
                page,
                account_id,
                product_info,
                listing_info,
                covers,
                label=label,
            )
        except BranchCCoverImageRejected as exc:
            _clear_beforeunload(page)
            platform_msg = str(exc.platform_message or exc).strip()
            return _finish_listing(
                run_id,
                account_id,
                unit,
                status="failed",
                reason=ListingErrorCode.CAROUSEL_IMAGE_DIMENSION_REJECTED,
                error=platform_msg or "主图尺寸不符合要求",
                retryable=False,
                legacy_status="failed",
                phase="upload",
                step="branch_c_cover_upload",
            )
        next_ok, next_err, _category_mode = run_branch_c_category_after_covers(
            page,
            account_id,
            label,
            listing_info,
            category_next_burst_demo=category_next_burst_demo,
        )
        if not next_ok:
            _clear_beforeunload(page)
            if next_err == "modal_blocking":
                return _finish_listing(
                    run_id,
                    account_id,
                    unit,
                    status="retryable",
                    reason="category_recommendation_modal_blocking",
                    error="「根据图片推荐分类」弹窗未确认，无法点击下一步",
                    retryable=True,
                    legacy_status="skipped",
                    phase="upload",
                    step="category_recommendation_modal",
                )
            if next_err == "not_found":
                return _finish_listing(
                    run_id,
                    account_id,
                    unit,
                    status="retryable",
                    reason="category_next_step_not_found",
                    error="未找到「下一步，完善商品信息」按钮",
                    retryable=True,
                    legacy_status="skipped",
                    phase="upload",
                    step="category_next_step",
                )
            return _finish_listing(
                run_id,
                account_id,
                unit,
                status="retryable",
                reason="category_next_step_no_advance",
                error="点击「下一步，完善商品信息」后页面未跳转",
                retryable=True,
                legacy_status="skipped",
                phase="upload",
                step="category_next_step",
            )
        time.sleep(2)
        page.wait.load_start()
        if _dismiss_address_required_page(page, account_id, label):
            time.sleep(2)
        listing_info["title"] = apply_title_after_branch_c_category_advance(
            page,
            account_id,
            product_info,
            listing_info.get("title", ""),
            label=label,
        )
        time.sleep(1)
    else:
        if ui_type == "B":
            tab = page.ele('css:[data-tracking-click-viewid="cate_tree_tab"]')
            if tab:
                page.run_js("arguments[0].click();", tab)
                time.sleep(3)

        if not _select_category_by_keyword_search(
            page,
            account_id,
            label,
            str(listing_info.get("category_keyword") or "玩偶"),
        ):
            _clear_beforeunload(page)
            return _finish_listing(
                run_id,
                account_id,
                unit,
                status="retryable",
                reason="category_search_failed",
                error=f"分类搜索失败：{listing_info.get('category_keyword', '玩偶')}",
                retryable=True,
                legacy_status="skipped",
                phase="upload",
                step="search_category",
            )
        category_mode = _resolve_category_page_mode(page, ui_type)
        if category_mode == "direct_next":
            print(
                f"[{account_id}] [{label}] 分支 {ui_type}：已选分类可直通，直接点击下一步",
                flush=True,
            )
        prepare_category_before_next(
            page,
            account_id,
            label,
            mode=category_mode,
            burst_demo=False,
        )
        next_ok, next_err = click_category_next_and_advance(
            page,
            account_id,
            label,
            ui_type=ui_type,
            mode=category_mode,
            burst_demo=category_mode == "render_wait",
        )
        if not next_ok:
            _clear_beforeunload(page)
            if next_err == "not_found":
                return _finish_listing(
                    run_id,
                    account_id,
                    unit,
                    status="retryable",
                    reason="category_next_step_not_found",
                    error="未找到分类确认/下一步按钮",
                    retryable=True,
                    legacy_status="skipped",
                    phase="upload",
                    step="category_next_step",
                )
            return _finish_listing(
                run_id,
                account_id,
                unit,
                status="retryable",
                reason="category_next_step_no_advance",
                error="点击下一步后页面未跳转",
                retryable=True,
                legacy_status="skipped",
                phase="upload",
                step="category_next_step",
            )
        time.sleep(2)
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

    if material_path:
        _upload_product_material_image(page, account_id, label, material_path)
        time.sleep(1)

    print(f"[{account_id}] [{label}] 正在录入多规格（款式 + 型号）...")
    add_style_and_model_specs(page, account_id, style_names, size_names)
    time.sleep(1)
    sku_rows = wait_multi_sku_rows(
        page, account_id, unit.skus, style_names=style_names, size_names=size_names
    )

    print(f"[{account_id}] [{label}] 开始填写价格表...")
    try:
        fill_stats = fill_multi_spec_rows(
            page,
            account_id,
            unit.skus,
            defaults,
            rows=sku_rows,
            style_names=style_names,
            size_names=size_names,
        )
    except PddImageDimensionRejected as exc:
        _clear_beforeunload(page)
        sku_label = str(exc.sku_label or "").strip()
        platform_msg = str(exc.platform_message or exc).strip()
        error_text = (
            f"预览图尺寸不符合要求 [{sku_label}]：{platform_msg}"
            if sku_label
            else f"预览图尺寸不符合要求：{platform_msg}"
        )
        return _finish_listing(
            run_id,
            account_id,
            unit,
            status="failed",
            reason=ListingErrorCode.PREVIEW_IMAGE_DIMENSION_REJECTED,
            error=error_text,
            title=listing_info.get("title", ""),
            retryable=False,
            legacy_status="failed",
            extra={
                "preview_sku_label": sku_label,
                "platform_message": platform_msg,
            },
            phase="preview",
            step="upload_preview_image",
            page_url=str(page.url or ""),
        )
    previews_ok = bool(fill_stats.get("previews_ok"))
    price_filled = int(fill_stats.get("price_filled") or 0)
    price_total = int(fill_stats.get("price_total") or len(unit.skus))
    if price_filled < price_total:
        print(
            f"[{account_id}] [{label}] 价格表未填完整（{price_filled}/{price_total}），跳过提交",
            flush=True,
        )
        if run_id:
            from pdd_agent.api.services.listing_failure_log import record_listing_failure_detail

            record_listing_failure_detail(
                source_run_id=run_id,
                account_id=account_id,
                listing_label=unit.listing_label,
                product_code=unit.product_code,
                image_set=unit.image_set,
                family_code=unit.family_code,
                merchant_code=unit.merchant_code,
                phase="upload",
                step="verify_price_table",
                severity="error",
                reason_code="validation_incomplete",
                message=f"价格表填写 {price_filled}/{price_total} 行未完整",
                detail=dict(fill_stats),
            )
        _clear_beforeunload(page)
        return _finish_listing(
            run_id,
            account_id,
            unit,
            status="retryable",
            reason="validation_incomplete",
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="skipped",
            extra=dict(fill_stats),
            phase="upload",
            step="verify_price_table",
            page_url=str(page.url or ""),
        )
    if run_id:
        from pdd_agent.api.services.listing_failure_log import (
            record_listing_failure_detail,
            record_price_fill_summary,
        )

        record_price_fill_summary(
            source_run_id=run_id,
            account_id=account_id,
            unit=unit,
            filled=int(fill_stats.get("price_filled") or 0),
            total=int(fill_stats.get("price_total") or 0),
            failed_items=list(fill_stats.get("price_failed") or []),
            style_names=style_names,
            size_names=size_names,
        )
        if not previews_ok:
            record_listing_failure_detail(
                source_run_id=run_id,
                account_id=account_id,
                listing_label=unit.listing_label,
                product_code=unit.product_code,
                image_set=unit.image_set,
                family_code=unit.family_code,
                merchant_code=unit.merchant_code,
                phase="preview",
                step="verify_preview_images",
                severity="error",
                reason_code="preview_not_ready",
                message=(
                    f"预览图页面校验 {fill_stats.get('preview_verified')}/{fill_stats.get('preview_need')}，"
                    f"上传成功 {fill_stats.get('preview_uploaded')}/{fill_stats.get('preview_need')}"
                ),
                detail=dict(fill_stats),
            )

    try:
        page_url = str(page.url or "")
    except Exception:
        page_url = ""

    pcode = (platform_listing_code or "").strip() or unit.merchant_code
    if not _fill_global_product_code(page, account_id, label, pcode):
        _clear_beforeunload(page)
        return _finish_listing(
            run_id,
            account_id,
            unit,
            status="retryable",
            reason="platform_listing_code_not_filled",
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="skipped",
            extra={"platform_listing_code": pcode},
            phase="upload",
            step="fill_global_product_code",
            page_url=page_url,
        )

    time.sleep(random.uniform(1.0, 2.0))
    visible_global_code = _read_global_product_code(page)
    if visible_global_code != pcode:
        print(
            f"[{account_id}] [{label}] 提交前校验失败：底部商品编码={visible_global_code or '<空>'}，期望={pcode}",
            flush=True,
        )
        _clear_beforeunload(page)
        return _finish_listing(
            run_id,
            account_id,
            unit,
            status="retryable",
            reason="platform_listing_code_verify_failed",
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="skipped",
            extra={
                "platform_listing_code": pcode,
                "visible_global_code": visible_global_code or "",
            },
            phase="upload",
            step="verify_global_product_code",
            page_url=page_url,
        )

    if not previews_ok:
        print(f"[{account_id}] [{label}] 预览图未全部就绪，跳过提交", flush=True)
        _clear_beforeunload(page)
        return _finish_listing(
            run_id,
            account_id,
            unit,
            status="retryable",
            reason="preview_not_ready",
            retryable=True,
            legacy_status="skipped",
            extra=dict(fill_stats),
            phase="upload",
            step="skip_submit_preview",
            page_url=page_url,
        )

    publish_settings = apply_listing_publish_settings(page, account_id, label)
    if not publish_settings.get("ok"):
        shipping = publish_settings.get("shipping_template") or {}
        bulk = publish_settings.get("bulk_discount") or {}
        detail_parts = []
        if not bulk.get("ok"):
            detail_parts.append(f"满件折扣={bulk.get('reason') or bulk.get('after') or 'failed'}")
        if not shipping.get("ok"):
            detail_parts.append(
                f"运费模板={shipping.get('reason') or shipping.get('step') or 'failed'}"
            )
        detail = "；".join(detail_parts) or str(publish_settings)
        print(
            f"[{account_id}] [{label}] 提交前设置未完成，跳过提交：{detail}",
            flush=True,
        )
        _clear_beforeunload(page)
        return _finish_listing(
            run_id,
            account_id,
            unit,
            status="retryable",
            reason="publish_settings_incomplete",
            error=f"提交前设置未完成：{detail}",
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="skipped",
            extra={"publish_settings": publish_settings},
            phase="upload",
            step="publish_settings",
            page_url=page_url,
        )

    ok, submitted_at, blocked_reason = _click_submit(page, account_id, label)
    _clear_beforeunload(page)
    if blocked_reason in {"preview_missing", "validation_errors", "validation_incomplete", "validation_required"}:
        return _finish_listing(
            run_id,
            account_id,
            unit,
            status="retryable",
            reason=blocked_reason,
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="skipped",
            phase="submit",
            step="blocked_by_validation",
            page_url=page_url,
        )
    if submitted_at:
        wait_seconds = 20 if ok else 35
        print(f"[{account_id}] [{label}] 等待 {wait_seconds} 秒后核验在售/驳回状态", flush=True)
        time.sleep(wait_seconds)
        from pdd_agent.skills.listing.listing_pdd_overlay_dismiss import (
            ensure_post_publish_modals_cleared,
        )

        ensure_post_publish_modals_cleared(page, account_id, label, max_attempts=4)
        capture = _capture_publish_outcome(
            page,
            account_id,
            unit,
            pcode,
            listing_info.get("title", ""),
        )
        if capture["status"] == "captured" and capture.get("pdd_product_id"):
            capture = enrich_capture_from_goods_list(
                page,
                capture,
                merchant_code=pcode,
                title=listing_info.get("title", ""),
            )
            capture["list_status"] = capture.get("list_status") or "销售中"
            verified_at = datetime.now()
            link_method = str(capture.get("product_link_method") or "")
            product_link = str(capture.get("product_link") or "")
            link_ok = bool(capture.get("product_link_ok"))
            link_note = "弹窗完整链接" if link_ok else "未抓到完整链接"
            print(
                f"[{account_id}] [{label}] 飞书数据采集：product_id={capture.get('pdd_product_id')} "
                f"status={capture.get('list_status')} created_at={capture.get('matched_created_at') or '-'} "
                f"link_method={link_method or link_note} link={product_link or '(空)'}",
                flush=True,
            )
            result = _listing_result(
                unit=unit,
                status="success",
                reason="listed",
                title=listing_info.get("title", ""),
                legacy_status="listed",
            )
            result["platform_listing_code"] = pcode
            result["publish_submitted_at"] = format_datetime(submitted_at) if submitted_at else ""
            result = _attach_capture_fields(result, capture)
            if run_id:
                from pdd_agent.api.services.task_runner import persist_published_item

                persist_published_item(run_id, account_id, result)
            _schedule_feishu_pdd_upload_log(
                account_id=account_id,
                unit=unit,
                title=listing_info.get("title", ""),
                merchant_code=pcode,
                capture=capture,
                verified_at=verified_at,
                submitted_at=submitted_at,
            )
            return result
        if capture["status"] == "rejected":
            reject_error = "提交后在「已驳回」找到商品，平台已驳回"
            result = _finish_listing(
                run_id,
                account_id,
                unit,
                status="failed",
                reason="rejected_after_publish",
                error=reject_error,
                title=listing_info.get("title", ""),
                retryable=False,
                legacy_status="failed",
                extra={
                    "platform_listing_code": pcode,
                    "publish_submitted_at": format_datetime(submitted_at) if submitted_at else "",
                },
                phase="post_submit",
                step="capture_outcome",
                page_url=page_url,
            )
            result = _attach_capture_fields(result, capture)
            return result
        if capture["status"] == "zero_inventory":
            result = _finish_listing(
                run_id,
                account_id,
                unit,
                status="failed",
                reason="goods_list_zero_inventory",
                error="当前库存为0",
                title=listing_info.get("title", ""),
                retryable=False,
                legacy_status="failed",
                extra={
                    "platform_listing_code": pcode,
                    "publish_submitted_at": format_datetime(submitted_at) if submitted_at else "",
                },
                phase="post_submit",
                step="capture_outcome_all_tab",
                page_url=page_url,
            )
            result = _attach_capture_fields(result, capture)
            return result
        if capture["status"] == "invalid_list_status":
            status_label = str(capture.get("list_status") or "未知").strip() or "未知"
            result = _finish_listing(
                run_id,
                account_id,
                unit,
                status="failed",
                reason="goods_list_status_not_on_sale",
                error=f"当前商品上架状态为{status_label}",
                title=listing_info.get("title", ""),
                retryable=False,
                legacy_status="failed",
                extra={
                    "platform_listing_code": pcode,
                    "publish_submitted_at": format_datetime(submitted_at) if submitted_at else "",
                },
                phase="post_submit",
                step="capture_outcome_all_tab",
                page_url=page_url,
            )
            result = _attach_capture_fields(result, capture)
            return result
        if capture["status"] in {"merchant_code_mismatch", "inventory_unparsed"}:
            verify_error = str(capture.get("message") or "").strip() or "全部Tab商品核验失败"
            result = _finish_listing(
                run_id,
                account_id,
                unit,
                status="failed",
                reason="goods_list_all_tab_verify_failed",
                error=verify_error,
                title=listing_info.get("title", ""),
                retryable=False,
                legacy_status="failed",
                extra={
                    "platform_listing_code": pcode,
                    "publish_submitted_at": format_datetime(submitted_at) if submitted_at else "",
                },
                phase="post_submit",
                step="capture_outcome_all_tab",
                page_url=page_url,
            )
            result = _attach_capture_fields(result, capture)
            return result

        not_found_error = str(capture.get("message") or "").strip() or (
            "提交后在在售/驳回列表没找到刚上的商品，请人工核对"
        )
        result = _finish_listing(
            run_id,
            account_id,
            unit,
            status="retryable",
            reason="published_but_not_found_in_on_sale_or_rejected" if ok else "submit_uncertain",
            error=not_found_error,
            title=listing_info.get("title", ""),
            retryable=True,
            legacy_status="submit_uncertain",
            extra={
                "platform_listing_code": pcode,
                "publish_submitted_at": format_datetime(submitted_at) if submitted_at else "",
            },
            phase="post_submit",
            step="capture_outcome",
            page_url=page_url,
        )
        result = _attach_capture_fields(result, capture)
        return result
    return _finish_listing(
        run_id,
        account_id,
        unit,
        status="retryable",
        reason=blocked_reason or "submit_uncertain",
        title=listing_info.get("title", ""),
        retryable=True,
        legacy_status="submit_uncertain",
        phase="submit",
        step="submit_button",
        page_url=page_url,
    )


def _persist_unit_progress(run_id: str, item: dict[str, Any]) -> None:
    if not run_id:
        return
    from pdd_agent.api.services.task_runner import _compact_value_for_storage
    from pdd_agent.storage import TaskRunStore

    compacted = _compact_value_for_storage(item)
    if not isinstance(compacted, dict):
        compacted = item
    TaskRunStore().append_listing_result(run_id, compacted)
    try:
        from pdd_agent.api.services.pipeline_listing_batch_resume import (
            persist_batch_unit_outcome_for_run,
        )

        persist_batch_unit_outcome_for_run(
            run_id,
            compacted if isinstance(compacted, dict) else item,
        )
    except Exception:
        pass


def run_listing_uploads(
    page: DpPage,
    account_id: str,
    units: list[ListingUnit],
    *,
    category_keyword: str = "玩偶",
    title_mode: str = "page_ai",
    platform_listing_code: str = "",
    defaults: dict[str, str] | None = None,
    run_id: str = "",
    slot_alignment_test: bool = False,
    category_next_burst_demo: bool = True,
) -> list[dict[str, Any]]:
    """顺序上架多个单元；单套失败记日志并继续，手动取消时停止。"""
    from pdd_agent.api.services.run_cancel import is_cancelled

    product_info = {
        "category_keyword": category_keyword,
        "title_mode": title_mode,
        "title": "",
    }
    defaults = defaults or {}
    results: list[dict[str, Any]] = []

    for idx, unit in enumerate(units):
        if run_id and is_cancelled(run_id):
            print(f"[{account_id}] 任务已取消，停止上架剩余单元", flush=True)
            break
        if idx > 0:
            print(f"\n[{account_id}] 等待 5 秒后上架下一单元 [{unit.listing_label}]...\n")
            time.sleep(5)
        try:
            item_result = upload_one_listing(
                page,
                account_id,
                unit,
                product_info,
                defaults,
                platform_listing_code=platform_listing_code,
                run_id=run_id,
                slot_alignment_test=slot_alignment_test,
                category_next_burst_demo=category_next_burst_demo,
            )
            results.append(item_result)
            if run_id:
                _persist_unit_progress(run_id, item_result)
            if not _listing_unit_succeeded(item_result):
                from pdd_agent.skills.listing.listing_unit_feishu_log import (
                    schedule_listing_unit_failure_to_feishu,
                )

                schedule_listing_unit_failure_to_feishu(
                    account_id,
                    unit,
                    item_result,
                    run_id=run_id,
                )
                print(
                    f"[{account_id}] [{unit.listing_label}] 上架失败，继续下一单元",
                    flush=True,
                )
                continue
        except Exception as e:
            err = _safe_exc(e)
            reason, retryable = _classify_exception(e)
            print(f"[{account_id}] [{unit.listing_label}] 业务运行报错: {err}")
            shot = ""
            try:
                safe_set = (unit.image_set or "default").replace("/", "_")
                shot = _error_screenshot_path(
                    f"error_listing_{account_id}_{unit.product_code}_{safe_set}.png"
                )
                page.get_screenshot(path=shot)
                print(f"[{account_id}] 已保存报错截图：{shot}", flush=True)
            except Exception:
                pass
            exc_result = _finish_listing(
                run_id,
                account_id,
                unit,
                status="retryable" if retryable else "failed",
                reason=reason,
                error=err,
                retryable=retryable,
                legacy_status="failed",
                phase="upload",
                step="exception",
                screenshot_path=shot,
            )
            results.append(exc_result)
            if run_id:
                _persist_unit_progress(run_id, exc_result)
            from pdd_agent.skills.listing.listing_unit_feishu_log import (
                schedule_listing_unit_failure_to_feishu,
            )

            schedule_listing_unit_failure_to_feishu(
                account_id,
                unit,
                exc_result,
                run_id=run_id,
            )
            print(
                f"[{account_id}] [{unit.listing_label}] 上架异常，继续下一单元",
                flush=True,
            )
            continue
    return results
