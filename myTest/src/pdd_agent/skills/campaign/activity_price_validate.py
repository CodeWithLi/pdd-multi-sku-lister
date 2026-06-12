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
const links = Array.from(document.querySelectorAll(
    'a[data-testid="beast-core-button-link"], a[data-tracking-viewid*="fold"]'
))
    .filter(isVisible)
    .filter((el) => norm(el.innerText || el.textContent || '').includes('展开更多规格'));
const clicked = [];
for (const link of links) {
    try {
        link.scrollIntoView({ block: 'center', inline: 'nearest' });
        link.click();
        clicked.push(norm(link.innerText || link.textContent || ''));
    } catch (err) {
        clicked.push({ error: String(err) });
    }
}
return { clicked_count: clicked.length, clicked };
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
const specs = [];
const seen = new Set();
const inputs = Array.from(document.querySelectorAll(
    'input[data-testid="beast-core-input-htmlInput"], input[data-testid="beast-core-input-nativeInput"], input[class*="IPT"]'
))
    .filter(isVisible);
for (const input of inputs) {
    const row = input.closest('tr');
    if (!row || !isVisible(row)) continue;
    const rowText = norm(row.innerText || row.textContent || '');
    if (!rowText.includes('款式') && !rowText.includes('当前价')) continue;
    let specName = '';
    for (const cell of row.querySelectorAll('td, [class*="cell"], [role="cell"]')) {
        const text = norm(cell.innerText || cell.textContent || '');
        if (text.includes('款式')) {
            specName = text;
            break;
        }
    }
    if (!specName) {
        const lines = rowText.split('\\n').map(norm).filter(Boolean);
        specName = lines.find((line) => line.includes('款式')) || '';
    }
    if (!specName) continue;
    const activityPrice = readActivityPrice(input);
    const productId = findProductId(row);
    const key = [productId, specName, activityPrice].join('||');
    if (seen.has(key)) continue;
    seen.add(key);
    specs.push({
        product_id: productId,
        spec_name: specName,
        activity_price: activityPrice,
    });
}
return { specs, spec_count: specs.length };
"""


def _normalize_spec_name(text: str) -> str:
    return _parse_page_spec(text).get("style_text", "")


def _parse_page_spec(spec_name: str) -> dict[str, Any]:
    """解析价格确认页规格文本，支持「款式；尺寸」与「款式 + 型号」两种格式。"""
    text = str(spec_name or "").strip()
    text = re.split(r"当前价", text, maxsplit=1)[0].strip()

    style_text = ""
    size_text = ""
    size_parts = re.split(r"[；;]\s*尺寸[：:]\s*", text, maxsplit=1)
    if len(size_parts) == 2:
        style_part, size_text = size_parts[0].strip(), size_parts[1].strip()
    else:
        style_part = text

    style_text = re.sub(r"^款式[：:]\s*", "", style_part).strip()
    style_text = re.sub(r"\(主图款式\)", "", style_text).strip()

    is_combo = bool(size_text)
    if not is_combo and " + " in style_text:
        left, right = style_text.split(" + ", 1)
        style_text, size_text = left.strip(), right.strip()
        is_combo = bool(size_text)
    elif not is_combo:
        style_text = re.sub(r"\s*-\s*[^-]+$", "", style_text).strip()

    return {
        "style_text": re.sub(r"\s+", " ", style_text).strip(),
        "size_text": re.sub(r"\s+", " ", size_text).strip(),
        "is_combo": is_combo,
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
        sku = _match_spec_to_sku(spec_name, skus)
        floor_info: dict[str, Any] | None = None

        if sku and parsed.get("is_combo"):
            style_code = normalize_price_code(str(sku.get("style_code") or ""))
            model_code = normalize_price_code(str(sku.get("model_code") or ""))
            if style_code == model_code:
                sku = None

        if sku:
            floor_info = _resolve_price_floor(
                sku=sku,
                product_code=str(row.product_code or ""),
                pricing_map=pricing,
                control_map=control,
            )
            if parsed.get("is_combo") and not floor_info.get("is_combo"):
                sku = None
                floor_info = None

        if floor_info is None:
            floor_info = _resolve_floor_from_product_code(
                parsed=parsed,
                product_code=str(row.product_code or ""),
                pricing_map=pricing,
                control_map=control,
                control_entries=control_labels,
            )
            sku = None

        pricing_value = floor_info.get("pricing")
        control_value = floor_info.get("control_price")
        skip_reason = _skip_reason_for_floor(floor_info, parsed)
        if skip_reason:
            results.append(
                {
                    "spec_name": spec_name,
                    "activity_price": activity_price,
                    "valid": True,
                    "skipped": True,
                    "should_remove": True,
                    "reason": skip_reason,
                    "pdd_product_id": row.pdd_product_id,
                    "product_code": row.product_code,
                    "parsed_spec": parsed,
                    "sku_matched": sku is not None,
                    "sku_count": len(skus),
                    "pricing": pricing_value,
                    "control_price": control_value,
                    **floor_info,
                }
            )
            continue

        floor_price = float(floor_info.get("floor_price") or 0.0)
        valid = activity_price > floor_price
        if not valid:
            failed += 1
        results.append(
            {
                "spec_name": spec_name,
                "activity_price": activity_price,
                "floor_price": floor_price,
                "valid": valid,
                "skipped": False,
                "should_remove": not valid,
                "reason": "ok" if valid else "activity_price_not_above_floor",
                "pdd_product_id": row.pdd_product_id,
                "product_code": row.product_code,
                "parsed_spec": parsed,
                "sku_matched": sku is not None,
                "sku_count": len(skus),
                **floor_info,
            }
        )

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
        "pricing_rule_count": len(pricing),
        "control_rule_count": len(control),
        "results": results,
    }


def _should_remove_spec(result: dict[str, Any]) -> bool:
    return bool(result.get("should_remove"))


def _group_products_for_filter(
    results: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """按商品聚合：任一规格需删除则整商品删除。"""
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        pid = str(item.get("pdd_product_id") or item.get("page_product_id") or "").strip()
        by_product[pid].append(item)

    kept_ids: list[str] = []
    remove_ids: list[str] = []
    for pid, items in by_product.items():
        if not pid:
            if any(_should_remove_spec(item) for item in items):
                remove_ids.append("")
            else:
                kept_ids.append("")
            continue
        if all(not _should_remove_spec(item) for item in items):
            kept_ids.append(pid)
        else:
            remove_ids.append(pid)
    return kept_ids, remove_ids


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


def _delete_price_confirm_goods(
    page: DpPage,
    *,
    product_id: str = "",
    spec_name: str = "",
) -> dict[str, Any]:
    """价格确认页点击行内「删除」。"""
    raw_page = getattr(page, "_page", None)
    if raw_page is not None:
        for selector in (
            f'tr:has-text("{product_id}"):has([data-tracking-viewid="delete_goods_shared"]) '
            f'[data-tracking-viewid="delete_goods_shared"]'
            if product_id
            else "",
            '[data-tracking-viewid="delete_goods_shared"]',
        ):
            if not selector:
                continue
            try:
                buttons = raw_page.locator(selector)
                count = buttons.count()
                for index in range(count):
                    btn = buttons.nth(index)
                    if not btn.is_visible():
                        continue
                    if product_id:
                        row = btn.locator("xpath=ancestor::tr[1]")
                        if row.count():
                            row_text = str(row.inner_text(timeout=1_000) or "")
                            if product_id not in row_text:
                                continue
                    if spec_name:
                        row = btn.locator("xpath=ancestor::tr[1]")
                        if row.count():
                            row_text = str(row.inner_text(timeout=1_000) or "")
                            short_spec = spec_name.split("当前价")[0].strip()[:24]
                            if short_spec and short_spec not in row_text:
                                continue
                    btn.scroll_into_view_if_needed(timeout=3_000)
                    btn.click(timeout=5_000)
                    confirm = _confirm_delete_with_retry(page)
                    return {
                        "deleted": bool(confirm.get("clicked")),
                        "method": "playwright_delete_goods_shared",
                        "product_id": product_id,
                        "spec_name": spec_name,
                        "confirm": confirm,
                    }
            except Exception:
                continue

    needle = str(spec_name or "").split("当前价")[0].strip()
    result = page.run_js(
        """
        const productId = String(arguments[0] || '');
        const specName = String(arguments[1] || '');
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
        const rows = Array.from(document.querySelectorAll('tbody tr, tr'))
            .filter(isVisible)
            .filter((row) => {
                const text = norm(row.innerText || row.textContent || '');
                if (productId && text.includes(productId)) return true;
                if (specName && specName.length >= 6 && text.includes(specName.slice(0, 24))) return true;
                return false;
            });
        for (const row of rows) {
            const del = row.querySelector('[data-tracking-viewid="delete_goods_shared"]');
            if (!del || !isVisible(del)) continue;
            clickLikeUser(del);
            return {
                deleted: true,
                method: 'js_delete_goods_shared',
                product_id: productId,
                spec_name: specName,
            };
        }
        return { deleted: false, reason: 'delete_goods_not_found', product_id: productId, spec_name: specName };
        """,
        product_id,
        needle,
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
                document.querySelector('[data-tracking-viewid="delete_goods_shared"]')
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


def _delete_invalid_price_goods(
    page: DpPage,
    account_id: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    results = validation.get("results") if isinstance(validation.get("results"), list) else []
    kept_ids, remove_ids = _group_products_for_filter(results)
    deleted: list[dict[str, Any]] = []

    for pid in list(dict.fromkeys(remove_ids)):
        spec_names = [
            str(item.get("spec_name") or "")
            for item in results
            if _should_remove_spec(item)
            and str(item.get("pdd_product_id") or item.get("page_product_id") or "").strip() == pid
        ]
        spec_name = spec_names[0] if spec_names else ""
        delete_result = _delete_price_confirm_goods(page, product_id=pid, spec_name=spec_name)
        deleted.append({"product_id": pid, **delete_result})
        time.sleep(1.0)

    remaining = _scrape_price_confirm_specs(page)
    empty_state = _read_price_confirm_empty_state(page)
    remaining_count = int(remaining.get("spec_count") or 0)
    if empty_state.get("empty"):
        remaining_count = 0
    print(
        f"[{account_id}] 活动价筛选：保留商品 {len(kept_ids)} 个，删除 {len(remove_ids)} 个，剩余规格 {remaining_count} 条",
        flush=True,
    )
    return {
        "kept_product_ids": kept_ids,
        "removed_product_ids": remove_ids,
        "deleted": deleted,
        "remaining_count": remaining_count,
        "remaining_specs": remaining.get("specs") or [],
        "empty_state": empty_state,
    }


def _expand_all_specs_on_page(page: DpPage) -> dict[str, Any]:
    _scroll_price_page(page)
    result = page.run_js(_EXPAND_SPECS_JS) or {"clicked_count": 0, "clicked": []}
    if int(result.get("clicked_count") or 0) > 0:
        time.sleep(1.2)
    return result


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


def _scrape_price_confirm_specs(page: DpPage) -> dict[str, Any]:
    _scroll_price_page(page)
    return page.run_js(_SCRAPE_PRICE_SPECS_JS) or {"specs": [], "spec_count": 0}


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
        **validation,
    }


def filter_price_confirm_page(
    page: DpPage,
    account_id: str,
    pdd_product_ids: list[str],
) -> dict[str, Any]:
    """价格确认页：校验 → 删除不符合/无定价数据的商品 → 无剩余则取消提交。"""
    state = _prepare_price_validation_state(page, account_id, pdd_product_ids)
    if state.get("status") != "success":
        return {**state, "step": "filter_activity_prices"}

    validation = state.get("validation") if isinstance(state.get("validation"), dict) else state
    remove_count = int(validation.get("remove_count") or 0)
    if remove_count <= 0:
        return {
            "status": "success",
            "step": "filter_activity_prices",
            "action": "keep_all",
            "remaining_count": int(validation.get("spec_count") or 0),
            **state,
        }

    filter_result = _delete_invalid_price_goods(page, account_id, validation)
    empty_state = filter_result.get("empty_state") if isinstance(filter_result.get("empty_state"), dict) else {}
    remaining_count = int(filter_result.get("remaining_count") or 0)
    if remaining_count <= 0 or empty_state.get("empty"):
        close_result = _close_price_confirm_page(page, account_id)
        return {
            "status": "all_products_removed",
            "step": "filter_activity_prices",
            "action": "close_page",
            "error": "所有商品均不符合价格条件或缺少定价数据，已删除并关闭页面",
            "filter_result": filter_result,
            "close_result": close_result,
            **state,
        }

    return {
        "status": "success",
        "step": "filter_activity_prices",
        "action": "continue_submit",
        "remaining_count": remaining_count,
        "filter_result": filter_result,
        **state,
    }
