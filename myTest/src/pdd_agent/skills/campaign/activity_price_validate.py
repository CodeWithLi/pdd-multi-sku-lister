"""营销活动价格确认页：展开规格、抓取活动价并与定价/控价表校验。"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.db.repositories import get_published_products_by_pdd_product_ids
from pdd_agent.skills.campaign.price_rules import (
    CodePriceEntry,
    find_code_by_label,
    find_code_price,
    load_pdd_control_entries,
    load_pdd_control_prices,
    load_pdd_pricing,
    normalize_price_code,
)
from pdd_agent.skills.published.pdd_sku_normalize import normalize_pdd_lookup_skus
from pdd_agent.skills.published.pdd_spec_format import (
    clean_spec_fragment,
    parse_spec_text,
)

_DELETE_GOODS_SELECTOR = (
    '[data-tracking-subid="delete_goods_shared"], '
    '[data-tracking-viewid="delete_goods_shared"]'
)

_EXPAND_SPECS_JS = """
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
function isExpandLink(el) {
    const text = norm(el.innerText || el.textContent || '');
    if (!text.includes('展开更多规格')) return false;
    if (text.length > 48) return false;
    return isVisible(el);
}
function countExpandLinks() {
    let count = 0;
    for (const el of document.querySelectorAll('a, button, span')) {
        if (isExpandLink(el)) count += 1;
    }
    return count;
}
function clickOneExpandLink() {
    const priority = [
        'a[data-testid="beast-core-button-link"]',
        'a[data-tracking-viewid*="fold"]',
        'button[data-testid="beast-core-button-link"]',
        'span[class*="fold"]',
    ];
    for (const sel of priority) {
        for (const el of document.querySelectorAll(sel)) {
            if (!isExpandLink(el)) continue;
            el.scrollIntoView({ block: 'center', inline: 'nearest' });
            el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
            el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
            el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
            return {
                clicked: true,
                text: norm(el.innerText || el.textContent || ''),
                method: sel,
                remaining: countExpandLinks(),
            };
        }
    }
    for (const el of document.querySelectorAll('a, button, span')) {
        if (!isExpandLink(el)) continue;
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
        el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
        el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
        return {
            clicked: true,
            text: norm(el.innerText || el.textContent || ''),
            method: 'broad',
            remaining: countExpandLinks(),
        };
    }
    return { clicked: false, remaining: countExpandLinks() };
}
return clickOneExpandLink();
"""

_SCRAPE_PRICE_SPECS_JS = """
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
function findProductId(el) {
    let node = el;
    while (node) {
        const text = norm(node.innerText || node.textContent || '');
        const match = text.match(/ID[：:]\\s*(\\d{5,})/);
        if (match) return match[1];
        node = node.parentElement;
    }
    return '';
}
function readActivityPrice(input) {
    if (!input) return '';
    const value = input.value ?? input.getAttribute('value') ?? '';
    return String(value).trim();
}
function findColumnIndex(label) {
    const ths = Array.from(document.querySelectorAll('th[data-testid="beast-core-table-th"], th'));
    for (let i = 0; i < ths.length; i++) {
        const t = norm(ths[i].innerText || ths[i].textContent || '');
        if (t.includes(label)) return i;
    }
    return -1;
}
function readRowSpecName(row, specColIdx) {
    const cells = Array.from(row.querySelectorAll('td'));
    let cell = specColIdx >= 0 ? cells[specColIdx] : null;
    if (!cell) {
        for (const c of cells) {
            const text = norm(c.innerText || c.textContent || '');
            if (text.includes('款式') || text.includes('尺寸') || text.includes('规格')) {
                cell = c;
                break;
            }
        }
    }
    if (cell) {
        const titled = cell.querySelector('[title]');
        const title = (cell.getAttribute('title') || titled?.getAttribute('title') || '').trim();
        if (title && (title.includes('款式') || title.includes('套餐') || title.includes('尺寸') || title.includes('规格'))) {
            return norm(title.split('当前价')[0]);
        }
        const text = norm(cell.innerText || cell.textContent || '');
        if (text.includes('款式') || text.includes('规格') || text.includes('尺寸')) {
            return norm(text.split('当前价')[0]);
        }
    }
    for (const cell of row.querySelectorAll('td, [class*="cell"], [role="cell"]')) {
        const text = norm(cell.innerText || cell.textContent || '');
        if (text.includes('款式')) return norm(text.split('当前价')[0]);
    }
    const rowText = norm(row.innerText || row.textContent || '');
    const lines = rowText.split('\\n').map(norm).filter(Boolean);
    const hit = lines.find((line) => line.includes('款式') || line.includes('规格：') || line.includes('尺寸'));
    return hit ? norm(hit.split('当前价')[0]) : '';
}
function readRowActivityInput(row) {
    const inputs = Array.from(row.querySelectorAll(
        'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"], input[class*="IPT"]'
    )).filter(isVisible);
    return inputs.length ? inputs[0] : null;
}
function pushSpec(specs, seen, productId, specName, activityPrice) {
    const key = [productId, specName, activityPrice].join('||');
    if (!specName || seen.has(key)) return;
    seen.add(key);
    specs.push({
        product_id: productId,
        spec_name: specName,
        activity_price: activityPrice,
    });
}
const specs = [];
const seen = new Set();
const specColIdx = findColumnIndex('规格名称');
const tbodyRows = Array.from(document.querySelectorAll('tbody tr')).filter(isVisible);
for (const row of tbodyRows) {
    const rowText = norm(row.innerText || row.textContent || '');
    if (!rowText.includes('款式') && !rowText.includes('当前价') && specColIdx < 0) continue;
    const specName = readRowSpecName(row, specColIdx);
    if (!specName) continue;
    const input = readRowActivityInput(row);
    if (!input) continue;
    pushSpec(specs, seen, findProductId(row), specName, readActivityPrice(input));
}
if (!specs.length) {
    const inputs = Array.from(document.querySelectorAll(
        'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"], input[class*="IPT"]'
    )).filter(isVisible);
    for (const input of inputs) {
        const row = input.closest('tr');
        if (!row || !isVisible(row)) continue;
        const rowText = norm(row.innerText || row.textContent || '');
        if (!rowText.includes('款式') && !rowText.includes('当前价')) continue;
        const specName = readRowSpecName(row, specColIdx);
        if (!specName) continue;
        pushSpec(specs, seen, findProductId(row), specName, readActivityPrice(input));
    }
}
return { specs, spec_count: specs.length, spec_column_index: specColIdx };
"""


def _normalize_spec_name(text: str) -> str:
    parsed = parse_spec_text(text)
    return str(parsed.get("dim1_value") or parsed.get("style_text") or "")


def _parse_page_spec(spec_name: str) -> dict[str, Any]:
    """解析价格确认页规格文本（款式/尺寸 + 套餐/规格，或单规格）。"""
    return parse_spec_text(spec_name)


def _clean_spec_fragment(text: str) -> str:
    return clean_spec_fragment(text)


def _sku_product_code(sku: dict[str, Any]) -> str:
    spec_code = str(sku.get("spec_code") or "").strip().upper()
    if spec_code:
        return spec_code
    combo = str(sku.get("combo_folder") or "").strip().upper()
    if combo:
        return combo
    style_code = normalize_price_code(str(sku.get("style_code") or ""))
    model_code = normalize_price_code(str(sku.get("model_code") or ""))
    if model_code and model_code != style_code:
        return f"{style_code}+{model_code}" if style_code else model_code
    return style_code


def _effective_product_code(row: Any) -> str:
    """手动录入时 product_code 可能是拼多多 ID，回退到货号或 SKU 母码。"""
    code = str(getattr(row, "product_code", "") or "").strip()
    if code and not re.fullmatch(r"\d{8,}", code):
        return normalize_price_code(code)
    merchant = str(getattr(row, "merchant_code", "") or "").strip()
    if merchant and not re.fullmatch(r"\d{8,}", merchant):
        return normalize_price_code(merchant)
    for sku in _skus_for_published_row(row):
        spec_code = _sku_product_code(sku)
        if not spec_code:
            continue
        parent, _ = _split_combo_folder(spec_code)
        if parent:
            return parent
    return normalize_price_code(code)


def _match_spec_to_pdd_sku(
    spec_name: str,
    skus: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int, str]:
    """用活动页「规格名称」反查 pdd_goods_lookup 里的 spec_code。"""
    parsed = parse_spec_text(spec_name)
    dim1_part = _clean_spec_fragment(parsed.get("dim1_value") or parsed.get("style_text") or "")
    dim2_part = _clean_spec_fragment(parsed.get("dim2_value") or parsed.get("size_text") or "")
    activity_combined = _clean_spec_fragment(parsed.get("spec_combined") or "")
    compact_spec = _clean_spec_fragment(re.split(r"当前价", spec_name, maxsplit=1)[0])

    if dim2_part and "单件装" in dim2_part:
        for sku in skus:
            if not isinstance(sku, dict):
                continue
            spec_code = _sku_product_code(sku)
            if "+" in spec_code:
                continue
            for field in (
                sku.get("spec_dim2_value"),
                sku.get("package_name"),
                sku.get("spec_dim1_value"),
                sku.get("style_name"),
            ):
                part = _clean_spec_fragment(str(field or ""))
                if part and (dim2_part in part or part in dim2_part):
                    return sku, 95, "pdd_single_package"

    best: dict[str, Any] | None = None
    best_score = 0
    best_method = "no_match"

    for sku in skus:
        if not isinstance(sku, dict):
            continue
        sku_dim1 = _clean_spec_fragment(
            str(sku.get("spec_dim1_value") or sku.get("style_name") or "")
        )
        sku_dim2 = _clean_spec_fragment(
            str(sku.get("spec_dim2_value") or sku.get("package_name") or sku.get("model_name") or "")
        )
        sku_combined = _clean_spec_fragment(str(sku.get("spec_combined") or ""))
        sku_combined_listing = _clean_spec_fragment(str(sku.get("spec_combined_listing") or ""))
        spec_code = _sku_product_code(sku).replace(" ", "")

        score = 0
        if spec_code and spec_code in compact_spec.upper():
            score += 90
        for stored_combined in (sku_combined, sku_combined_listing):
            if activity_combined and stored_combined:
                if activity_combined == stored_combined:
                    score += 85
                elif activity_combined in stored_combined or stored_combined in activity_combined:
                    score += 70
        if dim2_part:
            if sku_dim2 and len(dim2_part) >= 4 and (dim2_part in sku_dim2 or sku_dim2 in dim2_part):
                score += 55
            if sku_dim1 and len(dim2_part) >= 4 and (dim2_part in sku_dim1 or sku_dim1 in dim2_part):
                score += 50
        if dim1_part and not dim2_part:
            if sku_dim1 and len(dim1_part) >= 3 and (dim1_part in sku_dim1 or sku_dim1 in dim1_part):
                score += 70
        if dim1_part and dim2_part:
            if sku_dim1 and len(dim1_part) >= 3 and (dim1_part in sku_dim1 or sku_dim1 in dim1_part):
                score += 35
            if sku_dim2 and len(dim1_part) >= 3 and (dim1_part in sku_dim2 or sku_dim2 in dim1_part):
                score += 25
        combined_sku = sku_dim1 + sku_dim2
        if dim2_part and dim1_part and combined_sku:
            target = dim1_part + dim2_part
            if target in combined_sku or combined_sku in target:
                score += 40

        if score > best_score:
            best_score = score
            best = sku
            best_method = "pdd_lookup_text"

    if best_score >= 50:
        return best, best_score, best_method
    return None, 0, "no_match"


def _resolve_matched_sku(
    spec_name: str,
    skus: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    """统一规格名称 → SKU 匹配：先 catalog 款式名，再 pdd 反查文本。"""
    sku = _match_spec_to_sku(spec_name, skus)
    if sku is not None:
        return sku, "catalog_style_match"
    sku, _, method = _match_spec_to_pdd_sku(spec_name, skus)
    if sku is not None:
        return sku, method
    return None, "no_match"


def lookup_spec_codes_from_specs(
    *,
    specs: list[dict[str, Any]],
    published_rows: list[Any],
) -> dict[str, Any]:
    """根据活动页抓到的规格名称 + 活动价，反查 SKU 商品编码。"""
    if not specs:
        return {
            "status": "failed",
            "reason": "no_specs_found",
            "spec_count": 0,
            "matched_count": 0,
            "rows": [],
        }

    row_by_pdd_id = {str(row.pdd_product_id).strip(): row for row in published_rows}
    default_row = published_rows[0] if len(published_rows) == 1 else None
    rows: list[dict[str, Any]] = []
    matched_count = 0

    for item in specs:
        spec_name = str(item.get("spec_name") or "").strip()
        activity_price = str(item.get("activity_price") or "").strip()
        page_product_id = str(item.get("product_id") or "").strip()
        row = row_by_pdd_id.get(page_product_id) if page_product_id else None
        if row is None:
            row = default_row

        sku: dict[str, Any] | None = None
        match_score = 0
        match_method = "no_match"
        skus: list[dict[str, Any]] = []

        if row is not None:
            skus = _skus_for_published_row(row)
            sku, match_method = _resolve_matched_sku(spec_name, skus)
            match_score = 100 if sku is not None else 0

        spec_code = _sku_product_code(sku) if sku else ""
        if spec_code:
            matched_count += 1

        rows.append(
            {
                "spec_name": spec_name,
                "activity_price": activity_price,
                "pdd_product_id": page_product_id or (str(row.pdd_product_id) if row else ""),
                "product_code": str(row.product_code or "") if row else "",
                "spec_code": spec_code,
                "match_score": match_score,
                "match_method": match_method,
                "sku_count": len(skus),
                "parsed_spec": _parse_page_spec(spec_name),
            }
        )

    return {
        "status": "success",
        "spec_count": len(specs),
        "matched_count": matched_count,
        "rows": rows,
    }


def lookup_spec_codes_on_price_page(
    page: DpPage,
    account_id: str,
    pdd_product_ids: list[str],
) -> dict[str, Any]:
    """价格确认页：展开全部规格 → 抓取规格名称/活动价 → 反查 SKU 商品编码。"""
    prepared = scrape_activity_specs_on_price_page(page, account_id=account_id)
    expand_result = prepared.get("expand_result") if isinstance(prepared.get("expand_result"), dict) else {}
    scrape_result = prepared.get("scrape_result") if isinstance(prepared.get("scrape_result"), dict) else {}
    specs = scrape_result.get("specs") if isinstance(scrape_result.get("specs"), list) else []
    published_rows = get_published_products_by_pdd_product_ids(
        account_id=account_id,
        pdd_product_ids=pdd_product_ids,
    )
    lookup = lookup_spec_codes_from_specs(specs=specs, published_rows=published_rows)
    return {
        **lookup,
        "expand_result": expand_result,
        "scrape_result": scrape_result,
        "published_product_count": len(published_rows),
    }


def _catalog_skus_for_row(row: Any) -> list[dict[str, Any]]:
    try:
        from pdd_agent.core.config import load_yaml_settings
        from pdd_agent.skills.listing.catalog import parse_all_listings

        product_code = str(getattr(row, "product_code", "") or "").strip()
        if not product_code:
            return []
        image_set = str(getattr(row, "image_set", "") or "").strip()
        units = parse_all_listings(product_code, load_yaml_settings())
        selected = None
        if image_set:
            for unit in units:
                if unit.image_set == image_set:
                    selected = unit
                    break
        if selected is None and units:
            selected = units[0]
        if selected is None:
            return []
        return [
            {
                "style_code": sku.style_code,
                "style_name": sku.style_name,
                "model_code": sku.model_code,
                "model_name": sku.model_name,
                "combo_folder": sku.combo_folder,
            }
            for sku in selected.skus
        ]
    except Exception:
        return []


def _skus_for_published_row(row: Any) -> list[dict[str, Any]]:
    meta = row.spec_metadata or {}
    if isinstance(meta, dict):
        lookup = meta.get("pdd_goods_lookup")
        if isinstance(lookup, dict):
            pdd_skus = lookup.get("pdd_skus")
            if isinstance(pdd_skus, list) and pdd_skus:
                return normalize_pdd_lookup_skus(pdd_skus)
    skus = meta.get("skus") if isinstance(meta, dict) else []
    if isinstance(skus, list) and skus:
        return [item for item in skus if isinstance(item, dict)]
    return _catalog_skus_for_row(row)


def _split_combo_folder(combo_folder: str) -> tuple[str, str]:
    text = str(combo_folder or "").strip().upper()
    if "+" not in text:
        code = normalize_price_code(text)
        return code, ""
    left, right = text.split("+", 1)
    return normalize_price_code(left), normalize_price_code(right)


def _spec_match_score(spec_name: str, sku: dict[str, Any]) -> int:
    parsed = _parse_page_spec(spec_name)
    style_text = parsed.get("style_text") or ""
    size_text = parsed.get("size_text") or ""
    if not style_text and not size_text:
        return 0

    style_name = str(sku.get("style_name") or "").strip()
    model_name = str(sku.get("model_name") or "").strip()
    style_code = normalize_price_code(str(sku.get("style_code") or ""))
    model_code = normalize_price_code(str(sku.get("model_code") or ""))
    combo_folder = str(sku.get("combo_folder") or "")
    is_combo_sku = bool(model_code and model_code != style_code) or "+" in combo_folder

    if size_text:
        style_ok = bool(style_name and style_name in style_text)
        model_ok = bool(
            model_name and (model_name in size_text or size_text in model_name)
        )
        if not is_combo_sku:
            return 0
        if style_ok and model_ok:
            return 100
        return 0

    if parsed.get("is_combo") or " + " in style_text:
        core = style_text
        if style_name and model_name and style_name in core and model_name in core:
            return 100
        if style_name in core and model_name in core:
            return 90
        return 0

    if not is_combo_sku:
        if style_name and style_name in style_text:
            return 100
        if style_code and style_code in style_text.upper():
            return 80
    return 0


def _match_spec_to_sku(spec_name: str, skus: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_score = 0
    for sku in skus:
        if not isinstance(sku, dict):
            continue
        score = _spec_match_score(spec_name, sku)
        if score > best_score:
            best_score = score
            best = sku
    return best if best_score >= 80 else None


def _skip_reason_for_floor(floor_info: dict[str, Any], parsed: dict[str, Any]) -> str:
    """定价/控价表无数据时跳过校验，不阻断测试流程。"""
    pricing_value = floor_info.get("pricing")
    control_value = floor_info.get("control_price")
    if floor_info.get("is_combo"):
        if parsed.get("is_combo") and not floor_info.get("child_code"):
            return "skipped_child_code_not_found"
        if pricing_value is None or control_value is None:
            return "skipped_price_rules_missing"
        return ""
    if pricing_value is None:
        return "skipped_pricing_missing"
    return ""


def _resolve_floor_from_product_code(
    *,
    parsed: dict[str, Any],
    product_code: str,
    pricing_map: dict[str, float],
    control_map: dict[str, float],
    control_entries: list[CodePriceEntry],
) -> dict[str, Any]:
    """DB/catalog 无 SKU 时：用商品编码 + 规格名称反查定价/控价。"""
    parent_code = normalize_price_code(product_code)
    child_code = ""
    if parsed.get("is_combo"):
        size_text = str(parsed.get("size_text") or "").strip()
        if size_text:
            child_code = find_code_by_label(control_entries, size_text)
        if not child_code and " + " in str(parsed.get("style_text") or ""):
            _, right = str(parsed["style_text"]).split(" + ", 1)
            child_code = find_code_by_label(control_entries, right.strip())

    is_combo = bool(parsed.get("is_combo"))
    pricing = find_code_price(pricing_map, parent_code)
    control = find_code_price(control_map, child_code) if is_combo and child_code else None
    floor = (pricing or 0.0) + (control or 0.0 if is_combo else 0.0)

    return {
        "is_combo": is_combo,
        "parent_code": parent_code,
        "child_code": child_code if is_combo else "",
        "pricing": pricing,
        "control_price": control if is_combo else None,
        "floor_price": floor,
        "combo_folder": f"{parent_code}+{child_code}" if is_combo and child_code else parent_code,
        "style_text": parsed.get("style_text") or "",
        "size_text": parsed.get("size_text") or "",
        "resolve_method": "product_code_and_spec_label",
    }


def _resolve_price_floor(
    *,
    sku: dict[str, Any],
    product_code: str,
    pricing_map: dict[str, float],
    control_map: dict[str, float],
) -> dict[str, Any]:
    combo_folder = str(sku.get("combo_folder") or "")
    style_code = normalize_price_code(str(sku.get("style_code") or ""))
    model_code = normalize_price_code(str(sku.get("model_code") or ""))
    parent_code, child_code = _split_combo_folder(combo_folder)
    if not parent_code:
        parent_code = style_code or normalize_price_code(product_code)
    if not child_code and model_code and model_code != style_code:
        child_code = model_code

    is_combo = bool(child_code and child_code != parent_code)
    pricing = find_code_price(pricing_map, parent_code)
    control = find_code_price(control_map, child_code) if is_combo else None
    floor = (pricing or 0.0) + (control or 0.0 if is_combo else 0.0)

    return {
        "is_combo": is_combo,
        "parent_code": parent_code,
        "child_code": child_code if is_combo else "",
        "pricing": pricing,
        "control_price": control if is_combo else None,
        "floor_price": floor,
        "combo_folder": combo_folder,
        "style_code": style_code,
        "model_code": model_code,
        "resolve_method": "sku_metadata",
    }


def validate_spec_prices(
    *,
    specs: list[dict[str, Any]],
    published_rows: list[Any],
    pricing_map: dict[str, float] | None = None,
    control_map: dict[str, float] | None = None,
    control_entries: list[CodePriceEntry] | None = None,
) -> dict[str, Any]:
    pricing = pricing_map if pricing_map is not None else load_pdd_pricing()
    control = control_map if control_map is not None else load_pdd_control_prices()
    control_labels = control_entries if control_entries is not None else load_pdd_control_entries()
    if not specs:
        return {"status": "failed", "reason": "no_specs_found", "results": []}

    row_by_pdd_id = {str(row.pdd_product_id).strip(): row for row in published_rows}
    default_row = published_rows[0] if len(published_rows) == 1 else None

    results: list[dict[str, Any]] = []
    failed = 0
    for item in specs:
        spec_name = str(item.get("spec_name") or "").strip()
        activity_raw = str(item.get("activity_price") or "").strip()
        page_product_id = str(item.get("product_id") or "").strip()
        try:
            activity_price = float(activity_raw)
        except (TypeError, ValueError):
            activity_price = 0.0

        row = row_by_pdd_id.get(page_product_id) if page_product_id else None
        if row is None:
            row = default_row
        if row is None and published_rows:
            row = published_rows[0]

        if row is None:
            results.append(
                {
                    "spec_name": spec_name,
                    "activity_price": activity_raw,
                    "valid": False,
                    "should_remove": True,
                    "reason": "published_product_not_found",
                    "page_product_id": page_product_id,
                }
            )
            failed += 1
            continue

        parsed = _parse_page_spec(spec_name)
        skus = _skus_for_published_row(row)
        sku, match_method = _resolve_matched_sku(spec_name, skus)
        floor_info: dict[str, Any] | None = None

        if sku and parsed.get("is_combo"):
            style_code = normalize_price_code(str(sku.get("style_code") or ""))
            model_code = normalize_price_code(str(sku.get("model_code") or ""))
            if style_code == model_code:
                sku = None

        if sku:
            floor_info = _resolve_price_floor(
                sku=sku,
                product_code=_effective_product_code(row),
                pricing_map=pricing,
                control_map=control,
            )
            if parsed.get("is_combo") and not floor_info.get("is_combo"):
                sku = None
                floor_info = None

        if floor_info is None:
            floor_info = _resolve_floor_from_product_code(
                parsed=parsed,
                product_code=_effective_product_code(row),
                pricing_map=pricing,
                control_map=control,
                control_entries=control_labels,
            )
            sku = None

        pricing_value = floor_info.get("pricing")
        control_value = floor_info.get("control_price")
        skip_reason = _skip_reason_for_floor(floor_info, parsed)
        if skip_reason:
            skip_item = {
                "spec_name": spec_name,
                "activity_price": activity_price,
                "valid": True,
                "skipped": True,
                "should_remove": True,
                "reason": skip_reason,
                "pdd_product_id": row.pdd_product_id,
                "product_code": row.product_code,
                "spec_code": _sku_product_code(sku) if sku else "",
                "match_method": match_method,
                "parsed_spec": parsed,
                "sku_matched": sku is not None,
                "sku_count": len(skus),
                "pricing": pricing_value,
                "control_price": control_value,
                **floor_info,
            }
            skip_item["reason_text"] = _format_removal_reason_text(skip_reason, skip_item)
            results.append(skip_item)
            continue

        floor_price = float(floor_info.get("floor_price") or 0.0)
        valid = activity_price > floor_price
        if not valid:
            failed += 1
        reason_code = "ok" if valid else "activity_price_not_above_floor"
        result_item = {
            "spec_name": spec_name,
            "activity_price": activity_price,
            "floor_price": floor_price,
            "valid": valid,
            "skipped": False,
            "should_remove": not valid,
            "reason": reason_code,
            "pdd_product_id": row.pdd_product_id,
            "product_code": row.product_code,
            "spec_code": _sku_product_code(sku) if sku else floor_info.get("combo_folder") or "",
            "match_method": match_method,
            "parsed_spec": parsed,
            "sku_matched": sku is not None,
            "sku_count": len(skus),
            **floor_info,
        }
        result_item["reason_text"] = _format_removal_reason_text(reason_code, result_item)
        results.append(result_item)

    skipped_count = sum(1 for item in results if item.get("skipped"))
    checked_count = len(specs) - skipped_count
    passed_count = sum(1 for item in results if not item.get("skipped") and item.get("valid"))
    remove_count = sum(1 for item in results if item.get("should_remove"))
    return {
        "status": "success" if failed == 0 else "failed",
        "spec_count": len(specs),
        "failed_count": failed,
        "passed_count": passed_count,
        "skipped_count": skipped_count,
        "checked_count": checked_count,
        "remove_count": remove_count,
        "removed_specs": [item for item in results if item.get("should_remove")],
        "pricing_rule_count": len(pricing),
        "control_rule_count": len(control),
        "results": results,
    }


def _should_remove_spec(result: dict[str, Any]) -> bool:
    return bool(result.get("should_remove"))


_REMOVAL_REASON_LABELS: dict[str, str] = {
    "activity_price_not_above_floor": "活动价未高于底价",
    "skipped_pricing_missing": "定价表缺少母商品编码",
    "skipped_price_rules_missing": "定价/控价表数据不完整",
    "skipped_child_code_not_found": "未能识别子商品编码",
    "published_product_not_found": "未找到已发布商品映射",
    "delete_goods_not_found": "活动页未找到删除按钮",
    "delete_js_failed": "点击删除失败",
    "left_price_confirm_before_delete": "删除前已离开价格确认页",
    "left_price_confirm_after_delete": "删除后已离开价格确认页",
    "pdd_product_level_delete_skipped": "拼多多仅支持整商品删除，存在合格规格时无法自动剔除",
}


def _format_partial_invalid_error(
    validation: dict[str, Any],
    removed_specs: list[dict[str, Any]],
) -> str:
    spec_count = int(validation.get("spec_count") or 0)
    passed_count = int(validation.get("passed_count") or 0)
    remove_count = int(validation.get("remove_count") or 0)
    lines = [
        f"共 {spec_count} 条规格：{passed_count} 条价格合格，{remove_count} 条不合格。",
        "拼多多「删除」会移除整商品，无法只删部分规格，已停止自动删除与提交。",
        "请先在活动页把下列规格的活动价调高（须高于底价），或补全控价表后重新报名：",
    ]
    for item in removed_specs[:8]:
        code = str(item.get("spec_code") or "").strip()
        reason = str(item.get("reason_text") or item.get("reason") or "").strip()
        lines.append(f"· {code or '未知编码'}：{reason}")
    if len(removed_specs) > 8:
        lines.append(f"… 另有 {len(removed_specs) - 8} 条，见下方明细表")
    return "\n".join(lines)


def _format_removal_reason_text(reason: str, item: dict[str, Any]) -> str:
    code = str(reason or "").strip()
    if code == "activity_price_not_above_floor":
        activity = item.get("activity_price")
        floor = item.get("floor_price")
        parent = str(item.get("parent_code") or "").strip()
        child = str(item.get("child_code") or "").strip()
        pricing = item.get("pricing")
        control = item.get("control_price")
        parts = [f"活动价 {activity} ≤ 底价 {floor}"]
        if parent:
            pricing_text = pricing if pricing is not None else "无"
            parts.append(f"母码 {parent} 定价 {pricing_text}")
        if child:
            control_text = control if control is not None else "无"
            parts.append(f"子码 {child} 控价 {control_text}")
        return "；".join(parts)
    if code in _REMOVAL_REASON_LABELS:
        return _REMOVAL_REASON_LABELS[code]
    return code or "不符合条件"


def _build_removed_spec_record(
    item: dict[str, Any],
    *,
    deleted: bool | None = None,
    delete_error: str = "",
) -> dict[str, Any]:
    reason = str(item.get("reason") or "").strip()
    record: dict[str, Any] = {
        "spec_name": str(item.get("spec_name") or ""),
        "spec_code": str(item.get("spec_code") or item.get("combo_folder") or ""),
        "activity_price": item.get("activity_price"),
        "floor_price": item.get("floor_price"),
        "pricing": item.get("pricing"),
        "control_price": item.get("control_price"),
        "parent_code": str(item.get("parent_code") or ""),
        "child_code": str(item.get("child_code") or ""),
        "pdd_product_id": str(item.get("pdd_product_id") or item.get("page_product_id") or ""),
        "product_code": str(item.get("product_code") or ""),
        "reason": reason,
        "reason_text": _format_removal_reason_text(reason, item),
        "sku_matched": bool(item.get("sku_matched")),
        "match_method": str(item.get("match_method") or ""),
        "skipped": bool(item.get("skipped")),
    }
    if deleted is not None:
        record["deleted"] = deleted
    if delete_error:
        record["delete_error"] = delete_error
        record["delete_error_text"] = _REMOVAL_REASON_LABELS.get(delete_error, delete_error)
    return record


def _removed_specs_from_validation(validation: dict[str, Any]) -> list[dict[str, Any]]:
    results = validation.get("results") if isinstance(validation.get("results"), list) else []
    return [
        _build_removed_spec_record(item)
        for item in results
        if isinstance(item, dict) and _should_remove_spec(item)
    ]


def _group_products_for_filter(
    results: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """按商品聚合：仅当全部规格都需删除时，才整商品删除（拼多多删除按钮是商品级）。"""
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        pid = str(item.get("pdd_product_id") or item.get("page_product_id") or "").strip()
        by_product[pid].append(item)

    kept_ids: list[str] = []
    remove_ids: list[str] = []
    partial_ids: list[str] = []
    for pid, items in by_product.items():
        if not pid:
            if any(_should_remove_spec(item) for item in items):
                remove_ids.append("")
            else:
                kept_ids.append("")
            continue
        flags = [_should_remove_spec(item) for item in items]
        if all(flags):
            remove_ids.append(pid)
        elif any(flags):
            partial_ids.append(pid)
            kept_ids.append(pid)
        else:
            kept_ids.append(pid)
    return kept_ids, remove_ids, partial_ids


def _confirm_delete_modal(page: DpPage) -> dict[str, Any]:
    """删除商品后确认弹层：「确认要删除该商品吗？」→ 点击「确认」。"""
    time.sleep(0.8)
    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        playwright_selectors = (
            'div[data-testid="beast-core-portal-main"] button[data-testid="beast-core-button"]:has-text("确认")',
            '[class*="withConfirmPopoverMain"] button[data-testid="beast-core-button"]:has-text("确认")',
            '[class*="PP_withConfirmPopoverMain"] button[data-testid="beast-core-button"]:has-text("确认")',
            'button[data-testid="beast-core-button"]:has-text("确认")',
        )
        for selector in playwright_selectors:
            try:
                buttons = raw_page.locator(selector)
                count = buttons.count()
                for index in range(count):
                    btn = buttons.nth(index)
                    if not btn.is_visible():
                        continue
                    text = str(btn.inner_text(timeout=1_000) or "").strip()
                    if text != "确认":
                        continue
                    btn.scroll_into_view_if_needed(timeout=2_000)
                    btn.click(timeout=5_000)
                    time.sleep(0.5)
                    return {"clicked": True, "method": f"playwright_{selector}", "text": "确认"}
            except Exception:
                continue

    try:
        return (
            page.run_js(
                """
                function norm(text) {
                    return (text || '').replace(/\\s+/g, '').trim();
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
                function isDeleteConfirmRoot(el) {
                    const text = norm(textOf(el));
                    return text.includes('确认要删除')
                        || text.includes('从当前列表')
                        || text.includes('操作成功后');
                }
                function findDeleteConfirmRoot() {
                    const candidates = Array.from(document.querySelectorAll(
                        '[data-testid="beast-core-portal-main"], [class*="withConfirmPopoverMain"], [class*="PP_popoverMain"], [data-testid="beast-core-modal"], [class*="MDL_modal"]'
                    )).filter(isVisible);
                    const matched = candidates.filter(isDeleteConfirmRoot);
                    if (matched.length) return matched[matched.length - 1];
                    if (candidates.length) return candidates[candidates.length - 1];
                    return null;
                }
                const root = findDeleteConfirmRoot();
                if (!root) return { clicked: false, reason: 'delete_confirm_popover_not_found' };
                const buttons = Array.from(root.querySelectorAll('button[data-testid="beast-core-button"], button'))
                    .filter(isVisible)
                    .map((el) => ({
                        el,
                        text: textOf(el),
                        primary: /primary|BTN_primary/i.test(el.className || ''),
                    }))
                    .filter((item) => item.text === '确认' || item.text === '确定');
                buttons.sort((a, b) => Number(b.primary) - Number(a.primary));
                if (!buttons.length) {
                    return { clicked: false, reason: 'delete_confirm_button_not_found', root_text: textOf(root).slice(0, 120) };
                }
                clickLikeUser(buttons[0].el);
                return { clicked: true, text: buttons[0].text, method: 'js_delete_confirm_popover' };
                """
            )
            or {"clicked": False, "reason": "confirm_js_failed"}
        )
    except Exception as exc:
        return {"clicked": False, "reason": str(exc)}


def _confirm_delete_with_retry(page: DpPage) -> dict[str, Any]:
    confirm = _confirm_delete_modal(page)
    if confirm.get("clicked"):
        time.sleep(0.8)
        return confirm
    time.sleep(0.5)
    retry = _confirm_delete_modal(page)
    if retry.get("clicked"):
        time.sleep(0.8)
    return retry if retry.get("clicked") else confirm


def _spec_row_match_keys(spec_name: str) -> list[str]:
    """从完整规格名提取用于表格行匹配的关键片段。"""
    name = str(spec_name or "").split("当前价")[0].strip()
    keys: list[str] = []
    if name:
        keys.append(name)
    for pattern in (r"套餐[：:]\s*([^；;\n]+)", r"规格[：:]\s*([^；;\n]+)"):
        match = re.search(pattern, name)
        if match:
            fragment = match.group(1).strip()
            if len(fragment) >= 4:
                keys.append(fragment)
    for pattern in (r"款式[：:]\s*([^；;\n+]+)",):
        match = re.search(pattern, name)
        if match:
            fragment = match.group(1).strip()
            if len(fragment) >= 4:
                keys.append(fragment)
    deduped: list[str] = []
    for key in keys:
        if key not in deduped:
            deduped.append(key)
    return deduped


def _row_matches_spec_target(
    row_text: str,
    *,
    product_id: str,
    spec_name: str,
    activity_price: str,
) -> bool:
    text = re.sub(r"\s+", " ", str(row_text or "")).strip()
    if product_id and product_id not in text:
        return False
    if activity_price:
        try:
            target = float(str(activity_price).strip())
        except (TypeError, ValueError):
            target = None
        if target is not None:
            prices = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", text) if item]
            if prices and not any(abs(value - target) < 0.011 for value in prices):
                return False
    keys = _spec_row_match_keys(spec_name)
    if not keys:
        return bool(product_id)
    for key in keys:
        probe = key[: min(len(key), 28)]
        if probe and probe in text:
            return True
        if len(key) >= 8 and key[:16] in text:
            return True
    return False


def _delete_price_confirm_goods(
    page: DpPage,
    *,
    product_id: str = "",
    spec_name: str = "",
    activity_price: str = "",
) -> dict[str, Any]:
    """价格确认页点击行内「删除」（图三/图四）。"""
    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        try:
            buttons = raw_page.locator(_DELETE_GOODS_SELECTOR)
            count = buttons.count()
            for index in range(count):
                btn = buttons.nth(index)
                if not btn.is_visible():
                    continue
                row = btn.locator("xpath=ancestor::tr[1]")
                if not row.count():
                    continue
                row_text = str(row.inner_text(timeout=1_000) or "")
                if not _row_matches_spec_target(
                    row_text,
                    product_id=product_id,
                    spec_name=spec_name,
                    activity_price=activity_price,
                ):
                    continue
                btn.scroll_into_view_if_needed(timeout=3_000)
                btn.click(timeout=5_000)
                confirm = _confirm_delete_with_retry(page)
                return {
                    "deleted": bool(confirm.get("clicked")),
                    "method": "playwright_delete_goods_shared",
                    "product_id": product_id,
                    "spec_name": spec_name,
                    "activity_price": activity_price,
                    "confirm": confirm,
                }
        except Exception:
            pass

    needle = str(spec_name or "").split("当前价")[0].strip()
    result = page.run_js(
        """
        const productId = String(arguments[0] || '');
        const specName = String(arguments[1] || '');
        const activityPrice = String(arguments[2] || '');
        const matchKeys = Array.isArray(arguments[3]) ? arguments[3] : [];
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
        function rowMatches(row) {
            const text = norm(row.innerText || row.textContent || '');
            if (productId && !text.includes(productId)) return false;
            if (activityPrice) {
                const target = parseFloat(activityPrice);
                if (!Number.isNaN(target)) {
                    const input = row.querySelector(
                        'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"]'
                    );
                    const inputVal = input ? parseFloat(norm(input.value)) : NaN;
                    if (!Number.isNaN(inputVal) && Math.abs(inputVal - target) > 0.011) return false;
                }
            }
            if (!matchKeys.length) return Boolean(productId);
            return matchKeys.some((key) => {
                const probe = String(key || '').slice(0, 28);
                return probe.length >= 4 && text.includes(probe);
            });
        }
        const rows = Array.from(document.querySelectorAll('tbody tr, tr'))
            .filter(isVisible)
            .filter(rowMatches);
        for (const row of rows) {
            const del = row.querySelector(
                '[data-tracking-subid="delete_goods_shared"], [data-tracking-viewid="delete_goods_shared"]'
            );
            if (!del || !isVisible(del)) continue;
            clickLikeUser(del);
            return {
                deleted: true,
                method: 'js_delete_goods_shared',
                product_id: productId,
                spec_name: specName,
                activity_price: activityPrice,
            };
        }
        return { deleted: false, reason: 'delete_goods_not_found', product_id: productId, spec_name: specName };
        """,
        product_id,
        needle,
        activity_price,
        _spec_row_match_keys(spec_name),
    ) or {"deleted": False, "reason": "delete_js_failed", "product_id": product_id}
    if result.get("deleted"):
        confirm = _confirm_delete_with_retry(page)
        result["confirm"] = confirm
        result["deleted"] = bool(confirm.get("clicked"))
    return result


def _read_price_confirm_empty_state(page: DpPage) -> dict[str, Any]:
    return (
        page.run_js(
            """
            function norm(text) {
                return (text || '').replace(/\\s+/g, ' ').trim();
            }
            const text = norm(document.body?.innerText || document.body?.textContent || '');
            const selectedMatch = text.match(/已选商品\\s*(\\d+)\\s*个/);
            const selectedCount = selectedMatch ? parseInt(selectedMatch[1], 10) : -1;
            const noData = text.includes('暂无数据');
            const hasDeleteLink = Boolean(
                document.querySelector(
                    '[data-tracking-subid="delete_goods_shared"], [data-tracking-viewid="delete_goods_shared"]'
                )
            );
            const activityInputs = Array.from(document.querySelectorAll(
                'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"]'
            )).filter((el) => {
                const row = el.closest('tr');
                return row && norm(row.innerText || '').includes('款式');
            });
            const empty = noData || selectedCount === 0 || (!hasDeleteLink && activityInputs.length === 0);
            return {
                empty,
                no_data: noData,
                selected_count: selectedCount,
                activity_input_count: activityInputs.length,
                has_delete_link: hasDeleteLink,
            };
            """
        )
        or {
            "empty": False,
            "no_data": False,
            "selected_count": -1,
            "activity_input_count": 0,
            "has_delete_link": False,
        }
    )


def _close_price_confirm_page(page: DpPage, account_id: str) -> dict[str, Any]:
    """删除后无商品：关闭价格确认页标签或后退，不再继续提交流程。"""
    from pdd_agent.skills.campaign.limited_time import _bind_page, _live_context_pages

    raw_page = getattr(page, "_page", None)
    if raw_page is None:
        return {"closed": False, "reason": "page_unavailable"}

    try:
        current_url = str(raw_page.url or "")
    except Exception:
        current_url = ""

    pages = _live_context_pages(page)
    if len(pages) > 1:
        try:
            if not raw_page.is_closed():
                raw_page.close()
                print(f"[{account_id}] 已关闭价格确认页: {current_url}", flush=True)
            remaining = [item for item in _live_context_pages(page) if not item.is_closed()]
            if remaining:
                target = remaining[-1]
                _bind_page(page, target)
                try:
                    target.bring_to_front()
                except Exception:
                    pass
                time.sleep(0.8)
                return {
                    "closed": True,
                    "method": "close_tab",
                    "closed_url": current_url,
                    "current_url": str(getattr(target, "url", "") or ""),
                }
        except Exception as exc:
            return {"closed": False, "reason": str(exc), "method": "close_tab"}

    try:
        raw_page.go_back(wait_until="domcontentloaded", timeout=15_000)
        time.sleep(1)
        print(f"[{account_id}] 价格确认页无商品，已后退离开", flush=True)
        return {
            "closed": True,
            "method": "go_back",
            "closed_url": current_url,
            "current_url": str(raw_page.url or ""),
        }
    except Exception as exc:
        return {"closed": False, "reason": str(exc), "method": "go_back", "closed_url": current_url}


def _on_price_confirm_page(page: DpPage) -> bool:
    url = str(page.url or "")
    if "goods_price/confirm" in url or "goods/price" in url:
        return True
    try:
        body = page.run_js("return (document.body && document.body.innerText) || ''") or ""
    except Exception:
        body = ""
    return "确认商品价格信息" in body or "填写报名信息" in body


def _delete_invalid_price_goods(
    page: DpPage,
    account_id: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    results = validation.get("results") if isinstance(validation.get("results"), list) else []
    all_to_remove = [item for item in results if _should_remove_spec(item)]
    kept_ids, remove_product_ids, partial_ids = _group_products_for_filter(results)
    passed_count = int(validation.get("passed_count") or 0)
    deleted: list[dict[str, Any]] = []
    failed_deletes: list[dict[str, Any]] = []
    removed_specs: list[dict[str, Any]] = []
    partial_id_set = {str(pid).strip() for pid in partial_ids if str(pid).strip()}
    partial_items = [
        item
        for item in all_to_remove
        if str(item.get("pdd_product_id") or item.get("page_product_id") or "").strip() in partial_id_set
    ]
    for item in partial_items:
        removed_specs.append(
            _build_removed_spec_record(
                item,
                deleted=False,
                delete_error="pdd_product_level_delete_skipped",
            )
        )

    if partial_items and not remove_product_ids:
        remaining = _scrape_price_confirm_specs(page)
        empty_state = _read_price_confirm_empty_state(page)
        remaining_count = int(remaining.get("spec_count") or 0)
        if empty_state.get("empty"):
            remaining_count = 0
        print(
            f"[{account_id}] 活动价筛选：{len(partial_id_set)} 个商品存在部分不合格规格，"
            f"跳过删除（拼多多为整商品删除），合格 {passed_count} 条，不合格 {len(all_to_remove)} 条",
            flush=True,
        )
        return {
            "kept_product_ids": kept_ids,
            "removed_product_ids": remove_product_ids,
            "partial_product_ids": partial_ids,
            "removed_spec_count": len(all_to_remove),
            "deleted_spec_count": 0,
            "failed_deletes": [],
            "removed_specs": removed_specs,
            "deleted": [],
            "remaining_count": remaining_count,
            "remaining_specs": remaining.get("specs") or [],
            "empty_state": empty_state,
            "on_price_confirm_after": _on_price_confirm_page(page),
            "url_after": str(page.url or ""),
            "skipped_delete": True,
            "skip_reason": "partial_invalid_specs",
            "passed_spec_count": passed_count,
        }

    for pid in remove_product_ids:
        if not pid:
            continue
        if not _on_price_confirm_page(page):
            print(f"[{account_id}] 删除中止：已离开价格确认页 url={page.url}", flush=True)
            break

        delete_result = _delete_price_confirm_goods(page, product_id=pid, spec_name="")
        for item in all_to_remove:
            if str(item.get("pdd_product_id") or item.get("page_product_id") or "").strip() != pid:
                continue
            deleted_ok = bool(delete_result.get("deleted"))
            record = _build_removed_spec_record(
                item,
                deleted=deleted_ok,
                delete_error=str(delete_result.get("reason") or "") if not deleted_ok else "",
            )
            removed_specs.append(record)
            entry = {
                "pdd_product_id": pid,
                "spec_code": item.get("spec_code"),
                "spec_name": item.get("spec_name"),
                "activity_price": item.get("activity_price"),
                "reason": item.get("reason"),
                "reason_text": record.get("reason_text"),
                "delete_scope": "whole_product",
                **delete_result,
            }
            deleted.append(entry)
            if not deleted_ok:
                failed_deletes.append(entry)
        time.sleep(1.2)

        if not _on_price_confirm_page(page):
            print(
                f"[{account_id}] 删除后离开价格确认页: product={pid} url={page.url}",
                flush=True,
            )
            break

    time.sleep(1.0)
    remaining = _scrape_price_confirm_specs(page)
    empty_state = _read_price_confirm_empty_state(page)
    remaining_count = int(remaining.get("spec_count") or 0)
    if empty_state.get("empty"):
        remaining_count = 0
    deleted_ok = [item for item in deleted if item.get("deleted")]
    print(
        f"[{account_id}] 活动价筛选：整商品删除 {len(deleted_ok)} 次，保留商品 {len(kept_ids)} 个，"
        f"剩余规格 {remaining_count} 条，on_price_confirm={_on_price_confirm_page(page)}",
        flush=True,
    )
    return {
        "kept_product_ids": kept_ids,
        "removed_product_ids": remove_product_ids,
        "partial_product_ids": partial_ids,
        "removed_spec_count": len(all_to_remove),
        "deleted_spec_count": len(deleted_ok),
        "failed_deletes": failed_deletes,
        "removed_specs": removed_specs,
        "deleted": deleted,
        "remaining_count": remaining_count,
        "remaining_specs": remaining.get("specs") or [],
        "empty_state": empty_state,
        "on_price_confirm_after": _on_price_confirm_page(page),
        "url_after": str(page.url or ""),
        "skipped_delete": False,
        "passed_spec_count": passed_count,
    }


def _count_remaining_expand_links(page: DpPage) -> int:
    try:
        val = page.run_js(
            """
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
            let count = 0;
            for (const el of document.querySelectorAll('a, button, span')) {
                const text = norm(el.innerText || el.textContent || '');
                if (!text.includes('展开更多规格')) continue;
                if (text.length > 48) continue;
                if (isVisible(el)) count += 1;
            }
            return count;
            """
        )
        return int(val or 0)
    except Exception:
        return 0


def _click_one_expand_spec_link_playwright(page: DpPage) -> str | None:
    raw = getattr(page, "_page", None)
    if raw is None:
        return None
    try:
        loc = raw.get_by_text(re.compile(r"展开更多规格(\(\d+个\))?"))
        count = loc.count()
        for index in range(count):
            el = loc.nth(index)
            try:
                if not el.is_visible(timeout=800):
                    continue
                text = str(el.inner_text(timeout=800) or "").strip()
                if "展开更多规格" not in text or len(text) > 48:
                    continue
                el.scroll_into_view_if_needed(timeout=3000)
                el.click(timeout=5000)
                return text
            except Exception:
                continue
    except Exception:
        return None
    return None


def _click_one_expand_spec_link(page: DpPage) -> dict[str, Any]:
    hit = _click_one_expand_spec_link_playwright(page)
    if hit:
        return {"clicked": True, "text": hit, "method": "playwright_text"}

    try:
        result = page.run_js(_EXPAND_SPECS_JS) or {}
        if isinstance(result, dict) and result.get("clicked"):
            return result
    except Exception:
        pass
    return {"clicked": False, "remaining": _count_remaining_expand_links(page)}


def _expand_all_specs_on_page(page: DpPage, max_clicks: int = 50) -> dict[str, Any]:
    """逐一点击「展开更多规格」，支持单商品多个链接、多商品各自展开。"""
    clicked: list[str] = []
    methods: list[str] = []
    stagnant = 0
    for _ in range(max_clicks):
        _scroll_price_page(page)
        remaining_before = _count_remaining_expand_links(page)
        if remaining_before <= 0:
            break

        one = _click_one_expand_spec_link(page)
        if not one.get("clicked"):
            stagnant += 1
            if stagnant >= 2:
                break
            time.sleep(0.6)
            continue

        stagnant = 0
        clicked.append(str(one.get("text") or "展开更多规格"))
        methods.append(str(one.get("method") or ""))
        time.sleep(1.0)

        remaining_after = _count_remaining_expand_links(page)
        if remaining_after >= remaining_before and remaining_after > 0:
            time.sleep(0.8)
            retry = _click_one_expand_spec_link(page)
            if retry.get("clicked"):
                clicked.append(str(retry.get("text") or "展开更多规格"))
                methods.append(str(retry.get("method") or "retry"))
                time.sleep(1.0)

    remaining = _count_remaining_expand_links(page)
    return {
        "clicked_count": len(clicked),
        "clicked": clicked,
        "methods": methods,
        "remaining_links": remaining,
    }


def _scroll_price_page(page: DpPage) -> None:
    try:
        page.run_js(
            """
            window.scrollTo(0, document.body.scrollHeight);
            const nodes = Array.from(document.querySelectorAll('div, main, section'))
                .filter((el) => el.scrollHeight > el.clientHeight + 40);
            nodes.forEach((el) => { el.scrollTop = el.scrollHeight; });
            """
        )
    except Exception:
        pass
    time.sleep(0.5)


_TOOLTIP_SELECTORS = (
    '[data-testid="beast-core-tooltip"]',
    '[class*="Tooltip"]',
    '[class*="tooltip"]',
    '[role="tooltip"]',
)


def _is_truncated_spec_text(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return True
    if value.endswith("...") or value.endswith("…"):
        return True
    head = re.split(r"当前价", value, maxsplit=1)[0].strip()
    match = re.search(r"套餐[：:]\s*(.+)$", head)
    if match:
        tail = match.group(1).strip()
        if tail.endswith("...") or tail.endswith("…") or len(tail) <= 2:
            return True
    return False


def _extract_spec_name_from_tooltip_text(text: str) -> str:
    raw = str(text or "").replace("\r", "\n")
    parts: list[str] = []
    for line in raw.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if line.startswith("当前价") or line.startswith("线上库存"):
            break
        if re.search(r"(款式|尺寸|规格|套餐)[：:]", line):
            parts.append(line)
    if parts:
        return re.split(r"当前价", parts[0], maxsplit=1)[0].strip()
    return re.sub(r"\s+", " ", raw.split("当前价")[0]).strip()


def _normalize_visible_spec_text(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return re.split(r"当前价", value, maxsplit=1)[0].strip()


def _read_full_spec_name_playwright(raw_page: Any, spec_cell: Any) -> tuple[str, str]:
    """规格名称可能被省略号截断：优先 title，再 hover 读 tooltip。"""
    try:
        title = spec_cell.get_attribute("title")
        if title and re.search(r"(款式|尺寸|套餐|规格)", title):
            return _normalize_visible_spec_text(title), "title_attr"
    except Exception:
        pass

    try:
        child = spec_cell.locator("[title]").first
        if child.count():
            title = child.get_attribute("title")
            if title and re.search(r"(款式|尺寸|套餐|规格)", title):
                return _normalize_visible_spec_text(title), "child_title"
    except Exception:
        pass

    visible = ""
    try:
        visible = _normalize_visible_spec_text(spec_cell.inner_text(timeout=1000) or "")
    except Exception:
        pass

    if visible and not _is_truncated_spec_text(visible):
        return visible, "visible_text"

    try:
        spec_cell.scroll_into_view_if_needed(timeout=3000)
        box = spec_cell.bounding_box()
        if box:
            raw_page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            time.sleep(0.5)

        for selector in _TOOLTIP_SELECTORS:
            tips = raw_page.locator(selector)
            for index in range(tips.count() - 1, -1, -1):
                tip = tips.nth(index)
                try:
                    if not tip.is_visible(timeout=400):
                        continue
                    tip_text = tip.inner_text(timeout=800) or ""
                    if not re.search(r"(款式|尺寸|套餐|规格)", tip_text):
                        continue
                    full = _extract_spec_name_from_tooltip_text(tip_text)
                    if full and not _is_truncated_spec_text(full):
                        return full, f"hover_{selector}"
                except Exception:
                    continue

        portal = raw_page.locator('[data-testid="beast-core-portal-main"]').filter(has_text="当前价")
        if portal.count():
            tip_text = portal.last.inner_text(timeout=800) or ""
            full = _extract_spec_name_from_tooltip_text(tip_text)
            if full:
                return full, "hover_portal"
    except Exception:
        pass

    if visible:
        return visible, "visible_truncated"
    return "", "empty"


def _scrape_price_confirm_specs_playwright(page: DpPage) -> dict[str, Any]:
    """Playwright 逐行读取活动价；规格名截断时 hover 获取完整文本。"""
    raw = getattr(page, "_page", None)
    if raw is None:
        return {"specs": [], "spec_count": 0, "scrape_method": "playwright_unavailable"}

    spec_col_idx = -1
    try:
        spec_col_idx = int(
            page.run_js(
                """
                function norm(t){return (t||'').replace(/\\s+/g,' ').trim();}
                const ths = Array.from(document.querySelectorAll('th'));
                for (let i = 0; i < ths.length; i++) {
                    if (norm(ths[i].innerText).includes('规格名称')) return i;
                }
                return -1;
                """
            )
            or -1
        )
    except Exception:
        pass

    specs: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        rows = raw.locator("tbody tr").all()
    except Exception:
        return {"specs": [], "spec_count": 0, "scrape_method": "playwright_rows_failed"}

    for row in rows:
        try:
            if not row.is_visible(timeout=500):
                continue
            row_text = row.inner_text(timeout=1500) or ""
            if "展开更多规格" in row_text:
                continue
            if "款式" not in row_text and "当前价" not in row_text and "规格" not in row_text:
                continue

            price_input = row.locator(
                'input[data-testid="beast-core-input-htmlInput"], '
                'input[data-testid="beast-core-input-nativeInput"]'
            ).first
            if not price_input.count() or not price_input.is_visible(timeout=400):
                continue
            activity_price = str(price_input.input_value(timeout=800) or "").strip()

            spec_cell = row.locator("td").filter(has_text=re.compile(r"款式|尺寸|规格")).first
            if not spec_cell.count():
                cells = row.locator("td")
                if spec_col_idx >= 0 and cells.count() > spec_col_idx:
                    spec_cell = cells.nth(spec_col_idx)
                else:
                    spec_cell = cells.first

            spec_name, source = _read_full_spec_name_playwright(raw, spec_cell)
            spec_name = _normalize_visible_spec_text(spec_name)
            if not spec_name:
                continue

            pid_match = re.search(r"ID[：:]?\s*(\d{5,})", row_text)
            product_id = pid_match.group(1) if pid_match else ""
            dedupe_key = f"{product_id}||{spec_name}||{activity_price}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            parsed = parse_spec_text(spec_name)
            specs.append(
                {
                    "product_id": product_id,
                    "spec_name": spec_name,
                    "activity_price": activity_price,
                    "spec_name_source": source,
                    "spec_combined": parsed.get("spec_combined") or "",
                    "spec_dim1_key": parsed.get("dim1_key") or "",
                    "spec_dim1_value": parsed.get("dim1_value") or "",
                    "spec_dim2_key": parsed.get("dim2_key") or "",
                    "spec_dim2_value": parsed.get("dim2_value") or "",
                    "spec_count": parsed.get("spec_count") or 0,
                }
            )
        except Exception:
            continue

    hover_count = sum(1 for item in specs if str(item.get("spec_name_source", "")).startswith("hover"))
    return {
        "specs": specs,
        "spec_count": len(specs),
        "spec_column_index": spec_col_idx,
        "scrape_method": "playwright_hover",
        "hover_resolved_count": hover_count,
    }


def scrape_activity_specs_on_price_page(page: DpPage, account_id: str = "") -> dict[str, Any]:
    """20981 等：展开全部规格 → 读取完整规格名 + 活动价。"""
    expand_result = _expand_all_specs_on_page(page)
    if account_id and int(expand_result.get("remaining_links") or 0) > 0:
        print(
            f"[{account_id}] 警告：仍有 {expand_result.get('remaining_links')} 个「展开更多规格」未点击",
            flush=True,
        )
    scrape_result = _scrape_price_confirm_specs(page)
    return {
        "status": "success" if scrape_result.get("spec_count") else "failed",
        "expand_result": expand_result,
        "scrape_result": scrape_result,
        "specs": scrape_result.get("specs") or [],
        "spec_count": scrape_result.get("spec_count") or 0,
    }


def _scrape_price_confirm_specs(page: DpPage) -> dict[str, Any]:
    _scroll_price_page(page)
    pw_result = _scrape_price_confirm_specs_playwright(page)
    if int(pw_result.get("spec_count") or 0) > 0:
        return pw_result
    js_result = page.run_js(_SCRAPE_PRICE_SPECS_JS) or {"specs": [], "spec_count": 0}
    if isinstance(js_result, dict):
        js_result["scrape_method"] = js_result.get("scrape_method") or "js_fallback"
    return js_result


def validate_price_confirm_page(
    page: DpPage,
    account_id: str,
    pdd_product_ids: list[str],
) -> dict[str, Any]:
    """价格确认页：展开规格 → 抓取活动价 → 对比定价/控价。"""
    state = _prepare_price_validation_state(page, account_id, pdd_product_ids)
    if state.get("status") != "success":
        return state
    return {
        "step": "validate_activity_prices",
        **state,
    }


def _prepare_price_validation_state(
    page: DpPage,
    account_id: str,
    pdd_product_ids: list[str],
) -> dict[str, Any]:
    expand_result = _expand_all_specs_on_page(page)
    scrape_result = _scrape_price_confirm_specs(page)
    specs = scrape_result.get("specs") if isinstance(scrape_result.get("specs"), list) else []

    published_rows = get_published_products_by_pdd_product_ids(
        account_id=account_id,
        pdd_product_ids=pdd_product_ids,
    )
    if not published_rows:
        return {
            "status": "failed",
            "step": "load_published_products",
            "reason": "published_products_not_found",
            "pdd_product_ids": pdd_product_ids,
            "expand_result": expand_result,
            "scrape_result": scrape_result,
        }

    validation = validate_spec_prices(specs=specs, published_rows=published_rows)
    return {
        "status": "success",
        "step": "price_validation_ready",
        "expand_result": expand_result,
        "scrape_result": scrape_result,
        "published_products": [
            {
                "mapping_id": row.mapping_id,
                "pdd_product_id": row.pdd_product_id,
                "product_code": row.product_code,
                "sku_count": len(_skus_for_published_row(row)),
                "db_sku_count": len((row.spec_metadata or {}).get("skus") or []),
            }
            for row in published_rows
        ],
        "validation": validation,
        "validation_status": validation.get("status"),
        "spec_count": validation.get("spec_count"),
        "remove_count": validation.get("remove_count"),
        "failed_count": validation.get("failed_count"),
        "passed_count": validation.get("passed_count"),
        "skipped_count": validation.get("skipped_count"),
        "results": validation.get("results"),
    }


def filter_price_confirm_page(
    page: DpPage,
    account_id: str,
    pdd_product_ids: list[str],
) -> dict[str, Any]:
    """价格确认页：校验 → 删除不符合/无定价数据的规格 → 无剩余则取消提交。"""
    state = _prepare_price_validation_state(page, account_id, pdd_product_ids)
    if state.get("status") != "success":
        return {
            **state,
            "step": "filter_activity_prices",
            "error": state.get("reason") or state.get("error") or "价格确认页数据准备失败",
        }

    validation = state.get("validation") if isinstance(state.get("validation"), dict) else state
    remove_count = int(validation.get("remove_count") or 0)
    if remove_count <= 0:
        return {
            **state,
            "status": "success",
            "step": "filter_activity_prices",
            "action": "keep_all",
            "remaining_count": int(validation.get("spec_count") or 0),
            "removed_specs": [],
        }

    filter_result = _delete_invalid_price_goods(page, account_id, validation)
    if filter_result.get("skipped_delete"):
        return {
            **state,
            "status": "failed",
            "step": "filter_activity_prices",
            "action": "partial_invalid_needs_manual",
            "error": _format_partial_invalid_error(
                validation,
                filter_result.get("removed_specs") if isinstance(filter_result.get("removed_specs"), list) else [],
            ),
            "removed_specs": filter_result.get("removed_specs") or [],
            "filter_result": filter_result,
        }

    empty_state = filter_result.get("empty_state") if isinstance(filter_result.get("empty_state"), dict) else {}
    remaining_count = int(filter_result.get("remaining_count") or 0)
    on_price_confirm = bool(filter_result.get("on_price_confirm_after"))
    passed_count = int(validation.get("passed_count") or 0)
    if remaining_count <= 0 or empty_state.get("empty"):
        if passed_count > 0 and int(filter_result.get("deleted_spec_count") or 0) > 0:
            error = (
                f"删除不合格规格时拼多多移除了整商品（原 {validation.get('spec_count')} 条中 "
                f"{passed_count} 条合格）。请改为在活动页手动调高不合格规格的活动价后重新报名。"
            )
        else:
            error = "所有商品均不符合价格条件或缺少定价数据，已删除并关闭页面"
        close_result = _close_price_confirm_page(page, account_id)
        return {
            **state,
            "status": "all_products_removed",
            "step": "filter_activity_prices",
            "action": "close_page",
            "error": error,
            "removed_specs": filter_result.get("removed_specs") or _removed_specs_from_validation(validation),
            "filter_result": filter_result,
            "close_result": close_result,
        }

    if not on_price_confirm:
        return {
            **state,
            "status": "failed",
            "step": "filter_activity_prices",
            "action": "left_price_confirm_after_delete",
            "error": "价格筛选删除后已离开价格确认页，无法继续提交",
            "filter_result": filter_result,
            "url_after": filter_result.get("url_after"),
        }

    result: dict[str, Any] = {
        **state,
        "status": "success",
        "step": "filter_activity_prices",
        "action": "continue_submit",
        "remaining_count": remaining_count,
        "removed_specs": filter_result.get("removed_specs") or [],
        "filter_result": filter_result,
    }
    failed_deletes = filter_result.get("failed_deletes") if isinstance(filter_result.get("failed_deletes"), list) else []
    if failed_deletes:
        result["warning"] = f"{len(failed_deletes)} 条不合格规格未能点击删除，请人工核对"
    return result
