"""
整合链路 — 限时限量购按「第一个规格立减后价」校验成本。

与 limited_time.py 解耦：本模块负责读价/比价；limited_time 仅在价格筛选入口委托调用。
默认开启（feishu.yaml pipeline.limited_time_first_spec_price_enabled）。
"""

from __future__ import annotations

import re
import time
from typing import Any

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.integrations.feishu.config import load_feishu_config
from pdd_agent.integrations.feishu.pdd_price_compare_sync import (
    is_feishu_price_data_missing,
    load_price_range_catalog,
)
from pdd_agent.skills.campaign.price_rules import (
    evaluate_campaign_activity_price,
    find_pdd_price_range,
    price_rule_candidates,
)

_FIRST_SPEC_AFTER_DISCOUNT_RE = re.compile(
    r"立减后价格[^\d¥]*¥\s*([0-9]+(?:\.[0-9]+)?)"
)
_YUAN_PRICE_RE = re.compile(r"¥\s*([0-9]+(?:\.[0-9]+)?)")


def is_limited_time_first_spec_price_enabled() -> bool:
    try:
        cfg = load_feishu_config()
        return bool(cfg.pipeline.limited_time_first_spec_price_enabled)
    except Exception:
        return True


def parse_first_spec_after_discount_price(block_text: str) -> float | None:
    """从商品块文本解析第一个规格的立减后价格。"""
    text = str(block_text or "").strip()
    if not text:
        return None
    match = _FIRST_SPEC_AFTER_DISCOUNT_RE.search(text)
    if match:
        return float(match.group(1))
    parts = re.split(r"(?=拼单价)", text)
    if len(parts) > 1:
        first_spec = parts[1]
        prices = [float(item) for item in _YUAN_PRICE_RE.findall(first_spec)]
        if prices:
            return prices[-1]
    prices = [float(item) for item in _YUAN_PRICE_RE.findall(text)]
    if len(prices) >= 2:
        return prices[1]
    if len(prices) == 1:
        return prices[0]
    return None


def resolve_retail_cost_by_product_code(
    target: dict[str, Any],
    *,
    price_ranges: list[Any],
    catalog: Any,
) -> tuple[dict[str, Any] | None, str]:
    """按商品 ID 对应 published 行的 product_code 匹配飞书零售综合成本。"""
    product_code = str(target.get("product_code") or "").strip()
    if not product_code:
        return None, "missing_product_code"
    candidates = list(dict.fromkeys(price_rule_candidates(product_code)))
    rule = find_pdd_price_range(price_ranges, candidates)
    if rule:
        return {
            "code": rule.code,
            "min_price": rule.min_price,
            "max_price": rule.max_price,
            "retail_cost": rule.retail_cost,
            "matched_by": "product_code",
            "product_code": product_code,
        }, ""
    if is_feishu_price_data_missing(catalog, candidates):
        return None, "feishu_data_missing"
    return None, "price_rule_not_found"


def _read_first_spec_price_rows(page: DpPage) -> dict[str, Any]:
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
            function firstSpecPriceFromText(text) {
                const afterDiscount = text.match(/立减后价格[^\\d¥]*¥\\s*([0-9]+(?:\\.[0-9]+)?)/);
                if (afterDiscount) {
                    return {
                        check_price: Number(afterDiscount[1]),
                        method: 'first_spec_after_discount_label',
                    };
                }
                const parts = text.split(/(?=拼单价)/).filter(Boolean);
                if (parts.length > 1) {
                    const prices = Array.from(parts[1].matchAll(/¥\\s*([0-9]+(?:\\.[0-9]+)?)/g))
                        .map((m) => Number(m[1]))
                        .filter((n) => Number.isFinite(n) && n > 0);
                    if (prices.length) {
                        return {
                            check_price: prices[prices.length - 1],
                            method: 'first_spec_last_yuan',
                        };
                    }
                }
                const prices = Array.from(text.matchAll(/¥\\s*([0-9]+(?:\\.[0-9]+)?)/g))
                    .map((m) => Number(m[1]))
                    .filter((n) => Number.isFinite(n) && n > 0);
                if (prices.length >= 2) {
                    return { check_price: prices[1], method: 'fallback_second_yuan' };
                }
                if (prices.length === 1) {
                    return { check_price: prices[0], method: 'fallback_only_yuan' };
                }
                return { check_price: null, method: 'not_found' };
            }
            const roots = Array.from(document.querySelectorAll(
                '[data-testid="beast-core-table"], table, [class*="TB_outerWrapper"], [class*="TB_table"]'
            ))
                .filter((el) => isVisible(el))
                .filter((el) => {
                    const text = textOf(el);
                    return text.includes('活动库存')
                        && text.includes('促销维度')
                        && (
                            text.includes('折后价')
                            || text.includes('立减后价格')
                            || text.includes('拼单价')
                            || text.includes('立减')
                        );
                });
            const rows = [];
            for (const root of roots) {
                const tableRows = Array.from(root.querySelectorAll(
                    'tbody tr,[data-testid="beast-core-table-body"] tr'
                )).filter(isVisible);
                for (let index = 0; index < tableRows.length; index += 1) {
                    const row = tableRows[index];
                    const text = textOf(row);
                    const ids = Array.from(text.matchAll(/ID[:：]?\\s*(\\d{6,})/g)).map((m) => m[1]);
                    if (!ids.length) continue;
                    const productId = ids[0];
                    let blockText = text;
                    for (let next = index + 1; next < tableRows.length; next += 1) {
                        const nextText = textOf(tableRows[next]);
                        if (/ID[:：]?\\s*\\d{6,}/.test(nextText) && !nextText.includes(productId)) {
                            break;
                        }
                        if (nextText.includes('拼单价') || nextText.includes('立减后价格')) {
                            blockText += '\\n' + nextText;
                        }
                    }
                    const parsed = firstSpecPriceFromText(blockText);
                    rows.push({
                        ids,
                        product_id: productId,
                        check_price: parsed.check_price,
                        price_method: parsed.method,
                        text: blockText.slice(0, 800),
                    });
                }
            }
            return { rows, row_count: rows.length };
            """
        )
    except Exception as exc:
        return {"rows": [], "row_count": 0, "error": str(exc)}
    if isinstance(result, dict):
        return result
    return {"rows": [], "row_count": 0, "raw": result}


def _price_filter_failure_message(price_filter: dict[str, Any]) -> str:
    from pdd_agent.skills.campaign.limited_time import _price_filter_failure_message as _legacy

    return _legacy(price_filter)


def filter_activity_products_by_first_spec_price(
    page: DpPage,
    account_id: str,
    mapping_ids: list[str],
    *,
    pdd_product_ids: list[str] | None = None,
    phase: str = "",
) -> dict[str, Any]:
    """限时限量购：仅第一个规格立减后价 vs 商品编码对应零售综合成本。"""
    from pdd_agent.skills.campaign.limited_time import (
        _delete_activity_product_by_id,
        _load_campaign_price_targets,
    )

    target_state = _load_campaign_price_targets(
        mapping_ids,
        account_id=account_id,
        pdd_product_ids=pdd_product_ids,
    )
    if target_state.get("status") == "skipped":
        return target_state

    catalog = load_price_range_catalog()
    price_ranges = catalog.ranges
    require_retail_cost = catalog.source == "feishu"

    enriched_targets: list[dict[str, Any]] = []
    feishu_missing_targets: list[str] = []
    for target in target_state.get("targets") or []:
        item = dict(target)
        rule, missing_reason = resolve_retail_cost_by_product_code(
            item,
            price_ranges=price_ranges,
            catalog=catalog,
        )
        if rule:
            item["price_rule"] = rule
            item.pop("price_rule_missing_reason", None)
        else:
            item["price_rule"] = None
            if missing_reason == "feishu_data_missing":
                item["price_rule_missing_reason"] = missing_reason
                pid = str(item.get("pdd_product_id") or "").strip()
                if pid:
                    feishu_missing_targets.append(pid)
        enriched_targets.append(item)

    if feishu_missing_targets:
        return {
            "status": "skipped",
            "reason": "feishu_data_missing",
            "targets": enriched_targets,
            "feishu_missing_product_ids": feishu_missing_targets,
            "price_check_mode": "first_spec_product_code_cost",
        }

    time.sleep(2)
    row_state = _read_first_spec_price_rows(page)
    rows = row_state.get("rows") or []
    rows_by_product = {
        str(item.get("product_id") or "").strip(): item
        for item in rows
        if str(item.get("product_id") or "").strip()
    }

    decisions: list[dict[str, Any]] = []
    kept: list[str] = []
    deleted: list[str] = []

    for target in enriched_targets:
        product_id = str(target.get("pdd_product_id") or "").strip()
        row = rows_by_product.get(product_id) or {}
        check_price = row.get("check_price")
        if check_price is None and isinstance(row.get("text"), str):
            parsed = parse_first_spec_after_discount_price(row.get("text") or "")
            if parsed is not None:
                check_price = parsed

        rule = target.get("price_rule")
        missing_reason = str(target.get("price_rule_missing_reason") or "").strip()
        if missing_reason == "feishu_data_missing":
            ok = False
            fail_reason = "feishu_data_missing"
        elif not isinstance(check_price, (int, float)):
            ok = False
            fail_reason = "first_spec_price_not_found"
        elif isinstance(rule, dict):
            ok, fail_reason = evaluate_campaign_activity_price(
                check_price=check_price,
                retail_cost=rule.get("retail_cost"),
                require_retail_cost=require_retail_cost,
            )
        else:
            ok = False
            fail_reason = "price_rule_not_found"

        decision: dict[str, Any] = {
            "product_id": product_id,
            "mapping_id": target.get("mapping_id"),
            "product_code": target.get("product_code"),
            "family_code": target.get("family_code"),
            "first_sku": target.get("first_sku"),
            "price_rule": rule,
            "check_price": check_price,
            "price_check_mode": "first_spec_product_code_cost",
            "price_method": row.get("price_method"),
            "row_found": bool(row),
            "keep": ok,
            "reason": fail_reason,
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

    phase_label = str(phase or "").strip()
    filter_label = "创建前首规格价复核" if phase_label == "pre_submit" else "首规格立减后价筛选"
    print(
        f"[{account_id}] {filter_label}（商品编码成本）：保留 {len(kept)} 个，删除 {len(deleted)} 个",
        flush=True,
    )

    all_feishu_missing = bool(decisions) and all(
        str(item.get("reason") or "") == "feishu_data_missing" for item in decisions
    )
    status = "success"
    if not kept:
        status = "feishu_data_missing" if all_feishu_missing else "no_eligible_products"
    return {
        "status": status,
        "reason": "feishu_data_missing" if all_feishu_missing else "",
        "step": "campaign_price_filter_pre_submit" if phase_label == "pre_submit" else "campaign_price_filter",
        "phase": phase_label or "after_reduction",
        "kept_product_ids": kept,
        "deleted_product_ids": deleted,
        "decisions": decisions,
        "targets": {**target_state, "targets": enriched_targets},
        "activity_rows": row_state,
        "price_check_mode": "first_spec_product_code_cost",
    }


def try_pipeline_first_spec_price_filter(
    page: DpPage,
    account_id: str,
    mapping_ids: list[str],
    *,
    pdd_product_ids: list[str] | None = None,
    phase: str = "",
) -> dict[str, Any] | None:
    """整合链路首规格比价策略；未开启时返回 None，由 limited_time 走原逻辑。"""
    if not is_limited_time_first_spec_price_enabled():
        return None
    return filter_activity_products_by_first_spec_price(
        page,
        account_id,
        mapping_ids,
        pdd_product_ids=pdd_product_ids,
        phase=phase,
    )
