"""扫描拼多多发布页：收集未填项/校验提示，用于具体化 validation_incomplete 报错。"""

from __future__ import annotations

import json
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.domain.listing_errors import ListingErrors
from pdd_agent.skills.listing.multi_spec_page import collect_price_table_field_gaps

_SCAN_PAGE_VALIDATION_HINTS_JS = """
function collectPageValidationHints() {
    const hints = [];
    const seen = new Set();
    function add(text) {
        const t = String(text || '').replace(/\\s+/g, ' ').trim();
        if (!t || t.length < 2 || t.length > 120 || seen.has(t)) return;
        seen.add(t);
        hints.push(t);
    }
    const markers = [
        '错误项未处理', '个错误项', '请完善', '请填写', '不能为空',
        '请上传预览图', '未上传预览图', '预览图未上传', '必填',
    ];
    for (const node of document.querySelectorAll(
        'span, div, p, label, li, button, a, section, h1, h2, h3, h4'
    )) {
        const t = (node.innerText || node.textContent || '').trim();
        if (!t || t.length > 100) continue;
        for (const marker of markers) {
            if (t.includes(marker)) {
                add(t);
                break;
            }
        }
    }
    for (const el of document.querySelectorAll(
        '.form-item-explain-error, .error-tip, .has-error, [class*="error-text"], [class*="ErrorText"]'
    )) {
        const t = (el.innerText || el.textContent || '').trim();
        if (t) add(t);
    }
    return hints.slice(0, 12);
}
return collectPageValidationHints();
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


def scan_page_validation_hints(page: DpPage) -> list[str]:
    """读取页面上「请完善/请填写/错误项」等提示文案。"""
    try:
        raw = page.run_js(_SCAN_PAGE_VALIDATION_HINTS_JS) or "[]"
        hints = _safe_json_list(raw)
        out: list[str] = []
        seen: set[str] = set()
        for item in hints:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return out
    except Exception:
        return []


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
    """把缺项拼成一行具体说明，供飞书失败原因与系统原因使用。"""
    issues = collect_validation_incomplete_issues(
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
    return ListingErrors.format_validation_detail_brief(issues, merchant_code=merchant_code)


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
    """收集 validation_incomplete 的具体缺项列表。"""
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
        if missing:
            spec = f"{style}/{size}" if style or size else "未知规格"
            _add(f"规格「{spec}」缺{ '、'.join(missing)}")
            continue
        if reason == "matrix_value_mismatch":
            spec = f"{style}/{size}" if style or size else "未知规格"
            _add(f"规格「{spec}」库存/价格/编码与预期不一致")
            continue
        if reason in {"matrix_cell_empty", "value_verify_failed"}:
            spec = f"{style}/{size}" if style or size else "未知规格"
            _add(f"规格「{spec}」库存/价格/编码未填完整")

    if preview_need is not None and preview_verified is not None and preview_verified < preview_need:
        uploaded = preview_uploaded if preview_uploaded is not None else preview_verified
        _add(f"预览图仅 {uploaded}/{preview_need} 张已上传（校验通过 {preview_verified}/{preview_need}）")

    for hint in page_hints or []:
        text = str(hint or "").strip()
        if not text:
            continue
        if any(text in existing for existing in issues):
            continue
        _add(f"页面提示：{text}")

    return issues


def scan_listing_validation_issues(
    page: DpPage,
    *,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
    merchant_code: str = "",
    fill_stats: dict[str, Any] | None = None,
) -> str:
    """综合扫描发布页，返回一行具体缺项说明。"""
    stats = dict(fill_stats or {})
    styles = list(style_names or [])
    sizes = list(size_names or [])
    price_gaps = collect_price_table_field_gaps(page, styles, sizes) if styles and sizes else []
    page_hints = scan_page_validation_hints(page)
    return build_validation_incomplete_detail(
        merchant_code=merchant_code,
        style_names=styles,
        size_names=sizes,
        price_gaps=price_gaps,
        price_failed=list(stats.get("price_failed") or []),
        page_hints=page_hints,
        preview_verified=stats.get("preview_verified"),
        preview_need=stats.get("preview_need"),
        preview_uploaded=stats.get("preview_uploaded"),
    )
