"""扫描拼多多发布页：收集未填项/红色错误项，用于具体化 validation 类报错。"""

from __future__ import annotations

import json
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.skills.listing.multi_spec_page import (
    collect_preview_table_field_gaps,
    collect_price_table_field_gaps,
)
from pdd_agent.skills.listing.pdd_page_image_errors import (
    read_pdd_image_dimension_error,
    read_pdd_image_file_size_error,
)

_SCAN_PAGE_RED_ERRORS_JS = """
function norm(text) {
    return String(text || '').replace(/\\s+/g, ' ').trim();
}

function isVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 2 && r.height > 2
        && s.display !== 'none' && s.visibility !== 'hidden'
        && parseFloat(s.opacity || '1') > 0.05;
}

function isRedText(el) {
    if (!el) return false;
    const s = window.getComputedStyle(el);
    const c = String(s.color || '').toLowerCase();
    if (c.includes('red') || c.includes('#f') || c.includes('#e')) return true;
    const m = c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
    if (!m) return false;
    const r = parseInt(m[1], 10);
    const g = parseInt(m[2], 10);
    const b = parseInt(m[3], 10);
    return r > 170 && g < 130 && b < 130;
}

function findFieldLabel(errEl) {
    let cur = errEl;
    for (let depth = 0; depth < 10 && cur; depth++) {
        const labelEl = cur.querySelector?.(
            'label, .form-item-label, [class*="form-item-label"], [class*="FormItemLabel"]'
        );
        if (labelEl) {
            const text = norm(labelEl.innerText || labelEl.textContent);
            if (text && text.length <= 40) return text.replace(/[:：*\\s]+$/g, '');
        }
        const prev = cur.previousElementSibling;
        if (prev) {
            const text = norm(prev.innerText || prev.textContent);
            if (text && text.length <= 40 && !/错误项|个错误/.test(text)) {
                return text.replace(/[:：*\\s]+$/g, '');
            }
        }
        cur = cur.parentElement;
    }
    return '';
}

function findSectionTitle(errEl) {
    let cur = errEl;
    for (let depth = 0; depth < 12 && cur; depth++) {
        for (const marker of cur.querySelectorAll?.('h1,h2,h3,h4,legend,strong,.section-title,[class*="title"]') || []) {
            const text = norm(marker.innerText || marker.textContent);
            if (text && text.length <= 30 && !/错误项|个错误|提交/.test(text)) return text;
        }
        cur = cur.parentElement;
    }
    return '';
}

function addIssue(out, seen, item) {
    const key = JSON.stringify(item);
    if (seen.has(key)) return;
    seen.add(key);
    out.push(item);
}

function collectFieldErrors() {
    const out = [];
    const seen = new Set();
    const selectors = [
        '.form-item-explain-error',
        '.ant-form-item-explain-error',
        '[class*="form-item-feedback"]',
        '[class*="FormItemFeedback"]',
        '[class*="error-text"]',
        '[class*="ErrorText"]',
        '[class*="validate-error"]',
        '.has-error [class*="explain"]',
    ];
    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            if (!isVisible(el)) continue;
            const message = norm(el.innerText || el.textContent);
            if (!message || message.length < 2 || message.length > 120) continue;
            if (/^\\d+$/.test(message)) continue;
            const field = findFieldLabel(el) || findSectionTitle(el) || '';
            addIssue(out, seen, { type: 'field', field: field, message: message });
        }
    }
    return out;
}

function collectInlineRedErrors() {
    const out = [];
    const seen = new Set();
    const markers = [
        '不能为空', '请填写', '请完善', '请上传', '不符合', '无效', '错误', '必填', '缺失', '未填',
    ];
    for (const el of document.querySelectorAll('span, div, p, label, td, li')) {
        if (!isVisible(el) || !isRedText(el)) continue;
        const message = norm(el.innerText || el.textContent);
        if (!message || message.length < 2 || message.length > 100) continue;
        if (!markers.some((m) => message.includes(m)) && !/\\d+个错误项/.test(message)) continue;
        if (/错误项未处理/.test(message) && message.length < 12) continue;
        const field = findFieldLabel(el) || findSectionTitle(el) || '';
        addIssue(out, seen, { type: 'inline', field: field, message: message });
    }
    return out;
}

function collectSkuRowRedErrors() {
    const out = [];
    const seen = new Set();
    const rowSels = [
        '.sku-table tr[data-testid="beast-core-table-body-tr"]',
        '.sku-list tr[data-testid="beast-core-table-body-tr"]',
        'tr[data-pdd-sku-row]',
    ];
    for (const sel of rowSels) {
        for (const tr of document.querySelectorAll(sel)) {
            let style = '';
            let size = '';
            const labels = [];
            for (const td of tr.querySelectorAll('td')) {
                const hasInput = !!td.querySelector(
                    'input:not([type="file"]):not([type="hidden"]):not([type="checkbox"]):not([type="radio"])'
                );
                if (hasInput) break;
                const text = norm(td.innerText || td.textContent);
                if (text) labels.push(text);
            }
            style = labels[0] || '';
            size = labels[1] || '';
            for (const td of tr.querySelectorAll('td')) {
                for (const el of td.querySelectorAll('span, div, p')) {
                    if (!isVisible(el) || !isRedText(el)) continue;
                    const message = norm(el.innerText || el.textContent);
                    if (!message || message.length < 2 || message.length > 80) continue;
                    addIssue(out, seen, {
                        type: 'sku_row',
                        style: style,
                        size: size,
                        message: message,
                    });
                }
            }
        }
    }
    return out;
}

function collectErrorSummaryHints() {
    const out = [];
    const seen = new Set();
    const markers = [
        '错误项未处理', '个错误项', '请完善', '请填写', '不能为空',
        '请上传预览图', '未上传预览图', '预览图未上传', '必填',
        '上传图片', '商品主图', '轮播图',
    ];
    for (const node of document.querySelectorAll(
        'span, div, p, label, li, button, a, section, h1, h2, h3, h4'
    )) {
        if (!isVisible(node)) continue;
        const t = norm(node.innerText || node.textContent);
        if (!t || t.length > 100) continue;
        for (const marker of markers) {
            if (t.includes(marker)) {
                addIssue(out, seen, { type: 'hint', message: t });
                break;
            }
        }
    }
    return out;
}

function collectCarouselGap() {
    const body = document.body?.innerText || '';
    const m = body.match(/上传图片\\s*[（(]\\s*(\\d+)\\s*\\/\\s*(\\d+)\\s*[）)]/);
    if (m) {
        const current = parseInt(m[1], 10);
        const total = parseInt(m[2], 10);
        if (current < total) {
            return [{ type: 'carousel', current: current, total: total }];
        }
    }
    let visible = 0;
    for (const img of document.querySelectorAll(
        '[class*="carousel"] img, [class*="Carousel"] img, [class*="uploadImg"] img'
    )) {
        const r = img.getBoundingClientRect();
        if (r.width > 30 && r.height > 30) visible++;
    }
    if (visible > 0 && visible < 1) {
        return [{ type: 'carousel', current: visible, total: 5 }];
    }
    return [];
}

const issues = [];
const seen = new Set();
for (const batch of [
    collectFieldErrors(),
    collectInlineRedErrors(),
    collectSkuRowRedErrors(),
    collectErrorSummaryHints(),
    collectCarouselGap(),
]) {
    for (const item of batch) addIssue(issues, seen, item);
}
return JSON.stringify(issues);
"""


def _safe_json_list(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def scan_page_red_errors(page: DpPage) -> list[dict]:
    """扫描页面红色错误项、表单校验文案、规格行内红字。"""
    try:
        raw = page.run_js(_SCAN_PAGE_RED_ERRORS_JS) or "[]"
        rows = _safe_json_list(raw)
        out: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = json.dumps(row, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out
    except Exception:
        return []


def scan_page_validation_hints(page: DpPage) -> list[str]:
    """读取页面上「请完善/请填写/错误项」等提示文案（兼容旧接口）。"""
    hints: list[str] = []
    for row in scan_page_red_errors(page):
        message = str(row.get("message") or "").strip()
        if message:
            hints.append(message)
    return hints


def _format_spec_label(style: str, size: str) -> str:
    style = str(style or "").strip()
    size = str(size or "").strip()
    if style and size and style != size:
        return f"{style}/{size}"
    return style or size or "未知规格"


def collect_listing_validation_issues(
    *,
    merchant_code: str = "",
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
    price_gaps: list[dict] | None = None,
    preview_gaps: list[dict] | None = None,
    price_failed: list[dict] | None = None,
    page_errors: list[dict] | None = None,
    page_hints: list[str] | None = None,
    preview_verified: int | None = None,
    preview_need: int | None = None,
    preview_uploaded: int | None = None,
    carousel_current: int | None = None,
    carousel_total: int | None = None,
    image_errors: list[str] | None = None,
) -> list[str]:
    """收集所有可定位的具体缺项/错误项。"""
    _ = merchant_code
    issues: list[str] = []
    seen: set[str] = set()

    def _add(line: str) -> None:
        text = str(line or "").strip()
        if text and text not in seen:
            seen.add(text)
            issues.append(text)

    gap_items = list(price_gaps or [])
    if not gap_items and price_failed:
        gap_items = list(price_failed)
    for gap in gap_items:
        if not isinstance(gap, dict):
            continue
        style = str(gap.get("style") or "").strip()
        size = str(gap.get("size") or "").strip()
        missing = [str(x).strip() for x in (gap.get("missing") or []) if str(x).strip()]
        reason = str(gap.get("reason") or "").strip()
        spec = _format_spec_label(style, size)
        if missing:
            _add(f"规格「{spec}」缺{'、'.join(missing)}")
            continue
        if reason == "matrix_value_mismatch":
            _add(f"规格「{spec}」库存/拼团价/单买价/规格编码与预期不一致")
            continue
        if reason in {"matrix_cell_empty", "value_verify_failed", "partial_empty"}:
            _add(f"规格「{spec}」库存/拼团价/单买价/规格编码未填完整")

    for gap in preview_gaps or []:
        if not isinstance(gap, dict):
            continue
        style = str(gap.get("style") or "").strip()
        size = str(gap.get("size") or "").strip()
        spec_code = str(gap.get("spec_code") or "").strip()
        spec = _format_spec_label(style, size)
        if spec_code:
            _add(f"规格「{spec}」缺规格预览图（编码 {spec_code}）")
        else:
            _add(f"规格「{spec}」缺规格预览图")

    if carousel_current is not None and carousel_total is not None and carousel_current < carousel_total:
        _add(f"轮播图仅 {carousel_current}/{carousel_total} 张")

    for err in image_errors or []:
        text = str(err or "").strip()
        if text:
            _add(f"图片错误：{text}")

    if preview_need is not None and preview_verified is not None and preview_verified < preview_need:
        uploaded = preview_uploaded if preview_uploaded is not None else preview_verified
        _add(f"预览图仅 {uploaded}/{preview_need} 张已上传（校验通过 {preview_verified}/{preview_need}）")

    for row in page_errors or []:
        if not isinstance(row, dict):
            continue
        err_type = str(row.get("type") or "").strip()
        message = str(row.get("message") or "").strip()
        field = str(row.get("field") or "").strip()
        style = str(row.get("style") or "").strip()
        size = str(row.get("size") or "").strip()
        if err_type == "carousel":
            current = int(row.get("current") or 0)
            total = int(row.get("total") or 0)
            if total and current < total:
                _add(f"轮播图仅 {current}/{total} 张")
            continue
        if err_type == "sku_row" and message:
            spec = _format_spec_label(style, size)
            _add(f"规格「{spec}」{message}")
            continue
        if err_type == "field" and field and message:
            if message in field or field in message:
                _add(f"{field}：{message}")
            else:
                _add(f"{field}未通过：{message}")
            continue
        if err_type == "inline" and message:
            if field:
                _add(f"{field}：{message}")
            else:
                _add(message)
            continue
        if err_type == "hint" and message:
            if not any(message in existing for existing in issues):
                _add(f"页面提示：{message}")
            continue
        if message:
            _add(message)

    for hint in page_hints or []:
        text = str(hint or "").strip()
        if not text:
            continue
        if any(text in existing or existing in text for existing in issues):
            continue
        _add(f"页面提示：{text}")

    return issues


def build_validation_detail(
    *,
    merchant_code: str = "",
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
    price_gaps: list[dict] | None = None,
    preview_gaps: list[dict] | None = None,
    price_failed: list[dict] | None = None,
    page_errors: list[dict] | None = None,
    page_hints: list[str] | None = None,
    preview_verified: int | None = None,
    preview_need: int | None = None,
    preview_uploaded: int | None = None,
    carousel_current: int | None = None,
    carousel_total: int | None = None,
    image_errors: list[str] | None = None,
) -> str:
    """把缺项/错误项拼成一行具体说明。"""
    issues = collect_listing_validation_issues(
        merchant_code=merchant_code,
        style_names=style_names,
        size_names=size_names,
        price_gaps=price_gaps,
        preview_gaps=preview_gaps,
        price_failed=price_failed,
        page_errors=page_errors,
        page_hints=page_hints,
        preview_verified=preview_verified,
        preview_need=preview_need,
        preview_uploaded=preview_uploaded,
        carousel_current=carousel_current,
        carousel_total=carousel_total,
        image_errors=image_errors,
    )
    return ListingErrors.format_validation_detail_brief(issues, merchant_code=merchant_code)


def build_validation_incomplete_detail(
    *,
    merchant_code: str = "",
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
    price_gaps: list[dict] | None = None,
    price_failed: list[dict] | None = None,
    page_hints: list[str] | None = None,
    preview_verified: int | None = None,
    preview_need: int | None = None,
    preview_uploaded: int | None = None,
) -> str:
    """兼容旧接口。"""
    return build_validation_detail(
        merchant_code=merchant_code,
        style_names=style_names,
        size_names=size_names,
        price_gaps=price_gaps,
        price_failed=price_failed,
        page_hints=page_hints,
        preview_verified=preview_verified,
        preview_need=preview_need,
        preview_uploaded=preview_uploaded,
    )


def collect_validation_incomplete_issues(
    *,
    merchant_code: str = "",
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
    price_gaps: list[dict] | None = None,
    price_failed: list[dict] | None = None,
    page_hints: list[str] | None = None,
    preview_verified: int | None = None,
    preview_need: int | None = None,
    preview_uploaded: int | None = None,
) -> list[str]:
    """兼容旧接口。"""
    return collect_listing_validation_issues(
        merchant_code=merchant_code,
        style_names=style_names,
        size_names=size_names,
        price_gaps=price_gaps,
        price_failed=price_failed,
        page_hints=page_hints,
        preview_verified=preview_verified,
        preview_need=preview_need,
        preview_uploaded=preview_uploaded,
    )


def _extract_carousel_from_page_errors(page_errors: list[dict]) -> tuple[int | None, int | None]:
    for row in page_errors:
        if str(row.get("type") or "") != "carousel":
            continue
        return int(row.get("current") or 0), int(row.get("total") or 0)
    return None, None


def scan_listing_validation_issues(
    page: DpPage,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
    merchant_code: str = "",
    fill_stats: dict[str, Any] | None = None,
    blocked_reason: str = "",
) -> str:
    """综合扫描发布页，返回一行具体缺项/错误说明。"""
    _ = blocked_reason
    stats = dict(fill_stats or {})
    styles = list(style_names or [])
    sizes = list(size_names or [])
    price_gaps = collect_price_table_field_gaps(page, styles, sizes) if styles and sizes else []
    preview_gaps = collect_preview_table_field_gaps(page, styles, sizes) if styles and sizes else []
    page_errors = scan_page_red_errors(page)
    carousel_current, carousel_total = _extract_carousel_from_page_errors(page_errors)

    image_errors: list[str] = []
    for reader in (read_pdd_image_file_size_error, read_pdd_image_dimension_error):
        msg = str(reader(page) or "").strip()
        if msg:
            image_errors.append(msg)

    return build_validation_detail(
        merchant_code=merchant_code,
        style_names=styles,
        size_names=sizes,
        price_gaps=price_gaps,
        preview_gaps=preview_gaps,
        price_failed=list(stats.get("price_failed") or []),
        page_errors=page_errors,
        preview_verified=stats.get("preview_verified"),
        preview_need=stats.get("preview_need"),
        preview_uploaded=stats.get("preview_uploaded"),
        carousel_current=carousel_current,
        carousel_total=carousel_total,
        image_errors=image_errors,
    )
