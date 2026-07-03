"""槽位对齐 + 逐格按「款式/尺寸」填写 + 填后校验 + 通过后再传预览图（试验）。

由 ``spec_fill_verify_test`` 开关启用，与单独 ``slot_alignment_test`` 互斥。
本模块为独立封装，上架主流程仅通过薄引用接入。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pdd_agent.domain.models import ListingUnit
from pdd_agent.skills.listing import _sku_table_debug as sku_dbg
from pdd_agent.skills.listing.listing_spec_code_preview_upload import (
    normalize_spec_code,
    upload_previews_by_spec_code,
)
from pdd_agent.skills.listing.pdd_product_catalog import catalog_codes_match
from pdd_agent.skills.listing.spec_labels import (
    enrich_listing_unit_specs,
    refresh_unit_spec_code_lists,
)


class _PageLike(Protocol):
    def run_js(self, script: str, *args) -> Any: ...


def _now() -> float:
    return time.perf_counter()


def _log(account_id: str, message: str) -> None:
    prefix = f"[{account_id}]" if account_id else ""
    print(f"{prefix} [规格校验填表] {message}", flush=True)


def _log_step(account_id: str, step: str, started: float) -> None:
    _log(account_id, f"[耗时 {time.perf_counter() - started:.2f}s] {step}")


@dataclass(frozen=True)
class VerifiedFillConfig:
    """大规格量时的滚动/重试/节流参数。"""

    large_spec_threshold: int = 30
    very_large_spec_threshold: int = 60
    max_retries_per_sku: int = 4
    retry_delay_sec: float = 0.35
    inter_sku_delay_sec: float = 0.08
    inter_sku_delay_large_sec: float = 0.14
    inter_sku_delay_very_large_sec: float = 0.22
    log_every_n: int = 10
    warmup_scroll_rounds: int = 3


@dataclass
class VerifiedFillResult:
    previews_ok: bool = False
    price_filled: int = 0
    price_total: int = 0
    verify_passed: bool = False
    verify_passed_count: int = 0
    verify_total: int = 0
    failed_items: list[dict[str, str]] = field(default_factory=list)
    verify_issues: list[dict[str, Any]] = field(default_factory=list)
    slot_catalog_mismatches: list[dict[str, str]] = field(default_factory=list)
    duplicate_spec_pairs: list[dict[str, str]] = field(default_factory=list)
    spec_fill_verify_mode: bool = True
    preview_uploaded: int = 0
    preview_need: int = 0
    preview_verified: int = 0
    matrix_need: int = 0
    unique_spec_pairs: int = 0

    def as_fill_stats(self) -> dict[str, Any]:
        return {
            "previews_ok": self.previews_ok,
            "price_filled": self.price_filled,
            "price_total": self.price_total,
            "price_failed": self.failed_items,
            "failed_items": self.failed_items,
            "verify_passed": self.verify_passed,
            "verify_passed_count": self.verify_passed_count,
            "verify_total": self.verify_total,
            "verify_issues": self.verify_issues,
            "slot_catalog_mismatches": self.slot_catalog_mismatches,
            "duplicate_spec_pairs": self.duplicate_spec_pairs,
            "spec_fill_verify_mode": True,
            "preview_uploaded": self.preview_uploaded,
            "preview_need": self.preview_need,
            "preview_verified": self.preview_verified,
            "matrix_need": self.matrix_need,
            "unique_spec_pairs": self.unique_spec_pairs,
        }


def apply_unit_specs_for_verified_fill(
    unit: ListingUnit,
    *,
    account_id: str = "",
    allow_ai: bool = True,
) -> tuple[list[str], dict[str, str]]:
    """
    enrich → 记录商品表尺寸名 → 槽位对齐 → 刷新 model_codes。
    返回 (error_messages, combo_folder → 槽位对齐前的 catalog 尺寸名)。
    """
    from pdd_agent.skills.listing.platform_skip_siblings import (
        filter_listing_unit_skus_by_platform_skip,
    )

    removed = filter_listing_unit_skus_by_platform_skip(unit)
    if removed:
        _log(account_id, f"[{unit.listing_label}] 平台跳过兄弟款：{', '.join(removed)}")

    enrich_listing_unit_specs(unit, account_id=account_id, allow_ai=allow_ai)
    catalog_by_combo: dict[str, str] = {}
    for sku in unit.skus:
        combo = str(getattr(sku, "combo_folder", "") or "").strip()
        if combo:
            catalog_by_combo[combo] = str(getattr(sku, "model_name", "") or "").strip()

    from pdd_agent.skills.listing.slot_alignment import apply_slot_alignment

    result = apply_slot_alignment(unit, account_id=account_id)
    if not result.ok:
        return list(result.errors), catalog_by_combo

    refresh_unit_spec_code_lists(unit)
    mismatches = find_slot_catalog_mismatches(unit, catalog_by_combo)
    if mismatches:
        for item in mismatches:
            _log(
                account_id,
                f"[{unit.listing_label}] 槽位/商品表尺寸不一致："
                f"{item.get('combo_folder')} 商品表={item.get('catalog_size')} "
                f"槽位={item.get('slot_size')}",
            )
    return [], catalog_by_combo


def find_slot_catalog_mismatches(
    unit: ListingUnit,
    catalog_by_combo: dict[str, str],
) -> list[dict[str, str]]:
    """组合款：槽位对齐后的尺寸名与商品表推断不一致时记录（如挂件被塞进套尺槽）。"""
    mismatches: list[dict[str, str]] = []
    for sku in unit.skus or []:
        combo = str(getattr(sku, "combo_folder", "") or "").strip()
        if not combo:
            continue
        if catalog_codes_match(
            str(getattr(sku, "model_code", "") or ""),
            str(getattr(sku, "style_code", "") or ""),
        ):
            continue
        catalog_size = str(catalog_by_combo.get(combo) or "").strip()
        slot_size = str(getattr(sku, "model_name", "") or "").strip()
        if catalog_size and slot_size and catalog_size != slot_size:
            mismatches.append(
                {
                    "combo_folder": combo,
                    "style_code": str(getattr(sku, "style_code", "") or ""),
                    "model_code": str(getattr(sku, "model_code", "") or ""),
                    "catalog_size": catalog_size,
                    "slot_size": slot_size,
                    "style_name": str(getattr(sku, "style_name", "") or ""),
                }
            )
    return mismatches


def find_duplicate_spec_pairs(skus: list[Any]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    dupes: list[dict[str, str]] = []
    for sku in skus or []:
        key = (
            str(getattr(sku, "style_name", "") or ""),
            str(getattr(sku, "model_name", "") or ""),
        )
        if key in seen:
            dupes.append(
                {
                    "style": key[0],
                    "size": key[1],
                    "combo_folder": str(getattr(sku, "combo_folder", "") or ""),
                    "reason": "duplicate_spec_pair",
                }
            )
        else:
            seen.add(key)
    return dupes


def _resolve_config(sku_count: int, matrix_need: int) -> VerifiedFillConfig:
    cfg = VerifiedFillConfig()
    scale = max(sku_count, matrix_need)
    if scale >= cfg.very_large_spec_threshold:
        return VerifiedFillConfig(
            max_retries_per_sku=5,
            retry_delay_sec=0.45,
            inter_sku_delay_sec=cfg.inter_sku_delay_very_large_sec,
            warmup_scroll_rounds=4,
            log_every_n=8,
        )
    if scale >= cfg.large_spec_threshold:
        return VerifiedFillConfig(
            max_retries_per_sku=4,
            retry_delay_sec=0.4,
            inter_sku_delay_sec=cfg.inter_sku_delay_large_sec,
            warmup_scroll_rounds=3,
            log_every_n=10,
        )
    return cfg


def _inter_sku_delay(cfg: VerifiedFillConfig, sku_count: int) -> float:
    if sku_count >= cfg.very_large_spec_threshold:
        return cfg.inter_sku_delay_very_large_sec
    if sku_count >= cfg.large_spec_threshold:
        return cfg.inter_sku_delay_large_sec
    return cfg.inter_sku_delay_sec


_READ_ROW_BY_SPEC_CODE_JS = """
function rowInputs(tr) {
    const inputs = [];
    for (const td of tr.querySelectorAll('td')) {
        if (td.querySelector('input[type="file"]')) continue;
        for (const inp of td.querySelectorAll('input')) {
            const t = (inp.type || '').toLowerCase();
            if (!['file','hidden','checkbox','radio','button','submit'].includes(t)) {
                inputs.push(inp);
                break;
            }
        }
    }
    return inputs;
}

function isSkuDataRow(tr) {
    if (!tr || !tr.querySelector('.sku-preview-cell, td[class*="sku-preview"]')) return false;
    let n = 0;
    for (const inp of tr.querySelectorAll('input')) {
        const t = (inp.type || '').toLowerCase();
        if (!['file','hidden','checkbox','radio','button','submit'].includes(t)) n++;
    }
    return n >= 3;
}

function collectSkuDataRows() {
    const out = [];
    const sels = [
        '.sku-table tr[data-testid="beast-core-table-body-tr"]',
        '.sku-list tr[data-testid="beast-core-table-body-tr"]',
        'tr[data-pdd-sku-row]',
    ];
    const seen = new Set();
    for (const sel of sels) {
        for (const tr of document.querySelectorAll(sel)) {
            if (!isSkuDataRow(tr) || seen.has(tr)) continue;
            seen.add(tr);
            out.push(tr);
        }
    }
    return out;
}

function normFieldText(text) {
    return String(text || '').replace(/\\s+/g, ' ').trim();
}

function normSpecCode(code) {
    return normFieldText(code).replace(/\\s+/g, '').toUpperCase();
}

function readRowSpecCode(tr) {
    const inputs = rowInputs(tr);
    if (inputs.length >= 4) return normFieldText(inputs[3].value);
    return '';
}

function readRowStyleSizeLabels(tr) {
    const parts = [];
    for (const td of tr.querySelectorAll('td')) {
        let hasDataInput = false;
        for (const inp of td.querySelectorAll('input')) {
            const t = (inp.type || '').toLowerCase();
            if (!['file','hidden','checkbox','radio','button','submit'].includes(t)) {
                hasDataInput = true;
                break;
            }
        }
        if (hasDataInput) break;
        const t = normFieldText(td.innerText || td.textContent);
        if (t) parts.push(t);
    }
    let style = '';
    let size = '';
    if (parts.length >= 2) {
        style = parts[0];
        size = parts[1];
    } else if (parts.length === 1) {
        size = parts[0];
    }
    return { style, size, parts };
}

function getSkuScrollTargets() {
    const targets = [];
    const seen = new Set();
    function isScrollable(el) {
        if (!el) return false;
        const st = getComputedStyle(el);
        const oy = st.overflowY || st.overflow;
        return (oy === 'auto' || oy === 'scroll' || oy === 'overlay')
            && el.scrollHeight > el.clientHeight + 4;
    }
    function add(el) {
        if (!el || seen.has(el) || !isScrollable(el)) return;
        seen.add(el);
        targets.push(el);
    }
    const sample = document.querySelector(
        '.sku-table tr[data-testid="beast-core-table-body-tr"], '
        + '.sku-list tr[data-testid="beast-core-table-body-tr"]'
    );
    if (sample) {
        let el = sample.parentElement;
        while (el && el !== document.documentElement) {
            add(el);
            el = el.parentElement;
        }
    }
    for (const sel of ['.sku-table .ant-table-body', '.sku-list .ant-table-body', '.sku-table', '.sku-list']) {
        for (const el of document.querySelectorAll(sel)) add(el);
    }
    return targets;
}

function fireScroll(el) {
    if (!el) return;
    el.dispatchEvent(new Event('scroll', { bubbles: true }));
}

function scrollTableStep(stepPx) {
    const targets = getSkuScrollTargets();
    if (!targets.length) {
        window.scrollBy(0, stepPx);
        return true;
    }
    let moved = false;
    for (const t of targets) {
        const before = t.scrollTop;
        t.scrollTop = Math.min(t.scrollHeight, before + stepPx);
        fireScroll(t);
        if (t.scrollTop !== before) moved = true;
    }
    return moved;
}

function scrollTableToTop() {
    for (const t of getSkuScrollTargets()) {
        t.scrollTop = 0;
        fireScroll(t);
    }
}

function findRowBySpecCode(targetCode) {
    const target = normSpecCode(targetCode);
    if (!target) return null;
    function tryFind() {
        for (const tr of collectSkuDataRows()) {
            const code = readRowSpecCode(tr);
            if (!code || normSpecCode(code) !== target) continue;
            const labels = readRowStyleSizeLabels(tr);
            return {
                found: true,
                code: code,
                style: labels.style,
                size: labels.size,
                parts: labels.parts,
            };
        }
        return null;
    }
    scrollTableToTop();
    let hit = tryFind();
    if (hit) return hit;
    for (let step = 0; step < 200; step++) {
        const moved = scrollTableStep(72);
        hit = tryFind();
        if (hit) return hit;
        if (!moved) break;
    }
    for (const t of getSkuScrollTargets()) {
        t.scrollTop = t.scrollHeight;
        fireScroll(t);
    }
    hit = tryFind();
    return hit || { found: false };
}

const targetCode = arguments[0] || '';
return JSON.stringify(findRowBySpecCode(targetCode));
"""


def _read_row_by_spec_code(page: _PageLike, spec_code: str) -> dict[str, Any]:
    try:
        raw = page.run_js(_READ_ROW_BY_SPEC_CODE_JS, spec_code) or "{}"
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _prepare_price_table(
    page: _PageLike,
    account_id: str,
    skus: list[Any],
    style_names: list[str],
    size_names: list[str],
    *,
    cfg: VerifiedFillConfig,
) -> int:
    from pdd_agent.skills.listing.multi_spec_page import (
        _activate_spec_price_table,
        _click_blank_area,
        _count_loaded_spec_rows,
        _log_price_table_spec_map,
        _remark_sku_rows,
        _scroll_sku_table_to_load,
        _sku_table_debug_snapshot,
        _stamp_global_row_indices,
        _unique_sku_spec_pairs,
    )

    unique_rows = _unique_sku_spec_pairs(skus)
    matrix_need = len(style_names) * len(size_names) if style_names and size_names else unique_rows
    _log(
        account_id,
        f"预热虚拟表格：SKU={len(skus)} 唯一格={unique_rows} 矩阵={matrix_need} "
        f"（款式 {len(style_names)} × 尺寸 {len(size_names)}）",
    )
    _scroll_sku_table_to_load(
        page,
        matrix_need,
        style_names=style_names,
        size_names=size_names,
    )
    for warm in range(cfg.warmup_scroll_rounds):
        loaded = _count_loaded_spec_rows(
            page,
            matrix_need,
            style_names=style_names,
            size_names=size_names,
        )
        if loaded >= matrix_need:
            break
        _click_blank_area(page)
        if style_names and size_names:
            _activate_spec_price_table(page, style_names, size_names, account_id=account_id)
        time.sleep(0.75)
    if style_names and size_names:
        _remark_sku_rows(page)
        stamped = _stamp_global_row_indices(page, style_names, size_names)
        _log(account_id, f"虚拟表格标记 {stamped}/{matrix_need} 行")
        _sku_table_debug_snapshot(page, account_id, "verified_after_stamp", style_names, size_names)
    _log_price_table_spec_map(page, account_id, style_names, size_names)
    return matrix_need


def _fill_one_sku(
    page: _PageLike,
    sku: Any,
    defaults: dict[str, str],
    style_names: list[str],
    size_names: list[str],
    *,
    cfg: VerifiedFillConfig,
) -> tuple[bool, str]:
    from pdd_agent.skills.listing.multi_spec_page import (
        _fill_row_by_style_size,
        _row_data_from_sku,
        _scroll_spec_row_into_view,
    )

    style = str(getattr(sku, "style_name", "") or "")
    size = str(getattr(sku, "model_name", "") or "")
    row_data = _row_data_from_sku(sku, defaults)
    last_reason = "fill_failed"
    for attempt in range(cfg.max_retries_per_sku):
        _scroll_spec_row_into_view(
            page,
            style,
            size,
            style_names=style_names,
            size_names=size_names,
        )
        if _fill_row_by_style_size(
            page,
            style,
            size,
            row_data,
            style_names=style_names,
            size_names=size_names,
        ):
            return True, ""
        last_reason = f"fill_retry_{attempt + 1}"
        time.sleep(cfg.retry_delay_sec)
    return False, last_reason


def _verify_one_sku(
    page: _PageLike,
    sku: Any,
    defaults: dict[str, str],
    style_names: list[str],
    size_names: list[str],
) -> list[dict[str, Any]]:
    from pdd_agent.skills.listing.multi_spec_page import (
        _row_data_from_sku,
        _verify_row_values_by_spec,
    )

    issues: list[dict[str, Any]] = []
    style = str(getattr(sku, "style_name", "") or "")
    size = str(getattr(sku, "model_name", "") or "")
    combo = str(getattr(sku, "combo_folder", "") or "").strip()
    row_data = _row_data_from_sku(sku, defaults)

    if not _verify_row_values_by_spec(
        page,
        style,
        size,
        row_data,
        style_names=style_names,
        size_names=size_names,
    ):
        issues.append(
            {
                "combo_folder": combo,
                "style": style,
                "size": size,
                "reason": "forward_verify_failed",
                "detail": "款式/尺寸定位行上编码或价格未匹配",
            }
        )

    if combo:
        row_info = _read_row_by_spec_code(page, combo)
        if not row_info.get("found"):
            issues.append(
                {
                    "combo_folder": combo,
                    "style": style,
                    "size": size,
                    "reason": "spec_code_not_on_page",
                    "detail": "页面未找到该规格编码（可能虚拟滚动未加载）",
                }
            )
        else:
            page_style = str(row_info.get("style") or "").strip()
            page_size = str(row_info.get("size") or "").strip()
            if page_style and page_style != style:
                issues.append(
                    {
                        "combo_folder": combo,
                        "style": style,
                        "size": size,
                        "reason": "reverse_style_mismatch",
                        "detail": f"编码所在行款式={page_style}，期望={style}",
                    }
                )
            if page_size and page_size != size:
                issues.append(
                    {
                        "combo_folder": combo,
                        "style": style,
                        "size": size,
                        "reason": "reverse_size_mismatch",
                        "detail": f"编码所在行尺寸={page_size}，期望={size}",
                    }
                )
    return issues


def fill_multi_spec_rows_verified(
    page: _PageLike,
    account_id: str,
    skus: list[Any],
    defaults: dict[str, str],
    *,
    rows: list | None = None,
    style_names: list[str] | None = None,
    size_names: list[str] | None = None,
    catalog_by_combo: dict[str, str] | None = None,
    unit: ListingUnit | None = None,
) -> dict[str, Any]:
    """
    槽位对齐模式下：逐 SKU 按「款式+尺寸」填写 → 全量校验 → 通过后再上传预览图。
  """
    from pdd_agent.skills.listing.multi_spec_page import (
        _audit_sku_spec_coverage,
        _diagnose_fill_state,
        _sku_table_debug_snapshot,
        _unique_sku_spec_pairs,
    )

    _ = rows  # 与 fill_multi_spec_rows 签名兼容；本流程自行预热表格
    style_names = list(style_names or [])
    size_names = list(size_names or [])
    result = VerifiedFillResult(price_total=len(skus or []))
    catalog_map = dict(catalog_by_combo or {})

    if unit is not None and not catalog_map:
        catalog_map = {
            str(s.combo_folder or ""): str(s.model_name or "")
            for s in unit.skus
            if str(s.combo_folder or "").strip()
        }

    dupes = find_duplicate_spec_pairs(skus)
    if dupes:
        result.duplicate_spec_pairs = dupes
        result.failed_items = dupes
        _log(account_id, f"存在重复「款式+尺寸」映射 {len(dupes)} 处，停止填表")
        sku_dbg.log_fill_failures(account_id, "verified_duplicate_pairs", dupes)
        return result.as_fill_stats()

    unique_rows = _unique_sku_spec_pairs(skus)
    result.unique_spec_pairs = unique_rows
    matrix_need = len(style_names) * len(size_names) if style_names and size_names else unique_rows
    result.matrix_need = matrix_need
    cfg = _resolve_config(len(skus or []), matrix_need)

    total_start = _now()
    t = _now()
    _prepare_price_table(page, account_id, skus, style_names, size_names, cfg=cfg)
    _log_step(account_id, "表格预热完成", t)

    slot_mismatches: list[dict[str, str]] = []
    if unit is not None:
        slot_mismatches = find_slot_catalog_mismatches(unit, catalog_map)
    result.slot_catalog_mismatches = slot_mismatches
    if slot_mismatches:
        for item in slot_mismatches:
            result.verify_issues.append({**item, "reason": "slot_catalog_mismatch"})
        _log(account_id, f"发现 {len(slot_mismatches)} 处槽位名与商品表不一致（校验时将判失败）")

    _audit_sku_spec_coverage(account_id, skus, style_names, size_names)

    t = _now()
    fill_failed: list[dict[str, str]] = []
    filled_ok = 0
    delay = _inter_sku_delay(cfg, len(skus or []))
    for index, sku in enumerate(skus or [], start=1):
        style = str(getattr(sku, "style_name", "") or "")
        size = str(getattr(sku, "model_name", "") or "")
        combo = str(getattr(sku, "combo_folder", "") or "")
        ok, reason = _fill_one_sku(
            page,
            sku,
            defaults,
            style_names,
            size_names,
            cfg=cfg,
        )
        if ok:
            filled_ok += 1
            if index <= 5 or index % cfg.log_every_n == 0 or index == len(skus):
                _log(
                    account_id,
                    f"填写 {index}/{len(skus)} ✓ {style} / {size} | 编码={combo}",
                )
        else:
            fill_failed.append(
                {
                    "style": style,
                    "size": size,
                    "combo_folder": combo,
                    "reason": reason or "fill_failed",
                }
            )
            _log(
                account_id,
                f"填写 {index}/{len(skus)} ✗ {style} / {size} | 编码={combo} ({reason})",
            )
        if index < len(skus):
            time.sleep(delay)

    result.price_filled = filled_ok
    result.failed_items = fill_failed
    _log_step(account_id, f"逐格填写 {filled_ok}/{len(skus)}", t)
    sku_dbg.log_fill_progress(
        account_id,
        "verified_after_fill",
        filled=filled_ok,
        total=len(skus or []),
        failed_count=len(fill_failed),
    )

    t = _now()
    verify_issues: list[dict[str, Any]] = list(result.verify_issues)
    verify_passed_count = 0
    for index, sku in enumerate(skus or [], start=1):
        combo = str(getattr(sku, "combo_folder", "") or "")
        issues = _verify_one_sku(page, sku, defaults, style_names, size_names)
        if issues:
            verify_issues.extend(issues)
            for issue in issues:
                _log(
                    account_id,
                    f"校验 {index}/{len(skus)} ✗ {combo} | {issue.get('reason')}: {issue.get('detail', '')}",
                )
        else:
            verify_passed_count += 1
            if index <= 5 or index % cfg.log_every_n == 0 or index == len(skus):
                _log(account_id, f"校验 {index}/{len(skus)} ✓ {combo}")

    result.verify_total = len(skus or [])
    result.verify_passed_count = verify_passed_count
    result.verify_passed = (
        verify_passed_count == len(skus or [])
        and not slot_mismatches
        and not fill_failed
    )
    result.verify_issues = verify_issues

    if not result.verify_passed:
        _diagnose_fill_state(page, account_id, style_names=style_names, size_names=size_names)
        _sku_table_debug_snapshot(
            page, account_id, "verified_verify_fail", style_names, size_names
        )
        merged_failed = { (f.get("style"), f.get("size")) for f in fill_failed }
        for issue in verify_issues:
            key = (str(issue.get("style") or ""), str(issue.get("size") or ""))
            if key in merged_failed:
                continue
            result.failed_items.append(
                {
                    "style": str(issue.get("style") or ""),
                    "size": str(issue.get("size") or ""),
                    "combo_folder": str(issue.get("combo_folder") or ""),
                    "reason": str(issue.get("reason") or "verify_failed"),
                }
            )
        _log_step(
            account_id,
            f"校验未通过：填写失败 {len(fill_failed)}，校验问题 {len(verify_issues)}，"
            f"槽位/商品表不一致 {len(slot_mismatches)}；跳过预览图",
            t,
        )
        sku_dbg.log_fill_failures(account_id, "verified_verify", verify_issues)
        return result.as_fill_stats()

    _log_step(account_id, f"校验全部通过 {verify_passed_count}/{len(skus)}，开始上传预览图", t)

    t = _now()
    preview_result = upload_previews_by_spec_code(
        page,
        account_id,
        skus,
        prepare_table=True,
    )
    result.preview_uploaded = preview_result.uploaded
    result.preview_need = preview_result.need_upload
    result.preview_verified = preview_result.verified
    result.previews_ok = preview_result.verified >= preview_result.need_upload
    if not result.previews_ok:
        for code in preview_result.missing_codes:
            result.failed_items.append(
                {"combo_folder": code, "reason": "preview_missing_after_verify"}
            )
        for item in preview_result.failed_items:
            result.failed_items.append(dict(item))
        _log(
            account_id,
            f"预览图上传未完成 {preview_result.verified}/{preview_result.need_upload}",
        )
    else:
        _log(
            account_id,
            f"预览图上传完成 {preview_result.verified}/{preview_result.need_upload}",
        )
    _log_step(account_id, f"全部流程合计（SKU {len(skus)}）", total_start)
    return result.as_fill_stats()
