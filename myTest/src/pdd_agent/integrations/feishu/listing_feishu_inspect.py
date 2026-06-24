"""上架前飞书「拼多多比价定价」读取结果诊断（供前端弹窗展示）。"""

from __future__ import annotations

from typing import Any

from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.integrations.feishu.listing_feishu_catalog import (
    codes_match,
    normalize_listing_code,
    snapshot_record_fields,
)
from pdd_agent.integrations.feishu.pdd_price_compare_sync import (
    _field_number,
    _field_text,
    _resolve_price_range_field_names,
    load_control_catalog,
    load_price_range_catalog,
    load_pricing_catalog,
    resolve_code_price_from_catalog,
    resolve_feishu_range_aspect,
    resolve_pdd_price_compare_table_id,
)
from pdd_agent.integrations.feishu.pdd_product_catalog_sync import (
    diagnose_feishu_listing_catalog_issues,
)
from pdd_agent.skills.campaign.price_rules import find_pdd_price_range, price_rule_candidates


def _merchant_code_from_selector(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if "/" in text:
        parts = [p for p in text.split("/") if p]
        if len(parts) >= 3:
            return normalize_listing_code(parts[-1])
        if len(parts) == 2:
            return normalize_listing_code(parts[0])
        return normalize_listing_code(parts[0])
    return normalize_listing_code(text)


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{float(value):g}"


def _row_field_summary(
    fields: dict[str, Any],
    *,
    code_field: str,
    pricing_field: str,
    control_field: str,
    min_field: str,
    max_field: str,
    retail_cost_field: str = "",
    retail_cost_label: str = "综合零售成本",
    color_field: str = "颜色规格",
) -> dict[str, Any]:
    summary = {
        "商品编码": _field_text(fields, code_field),
        "颜色规格": _field_text(fields, color_field),
        "拼多多定价": _format_price(_field_number(fields, pricing_field)),
        "拼多多控价": _format_price(_field_number(fields, control_field)),
        "PDD控价下限价格": _format_price(_field_number(fields, min_field)),
        "PDD控价上限价格": _format_price(_field_number(fields, max_field)),
    }
    if retail_cost_field:
        summary[retail_cost_label] = _format_price(_field_number(fields, retail_cost_field))
    return summary


def _matched_snapshot_key(snapshot: Any, query_code: str) -> str:
    if snapshot is None:
        return ""
    records: dict[str, dict[str, Any]] = getattr(snapshot, "records_by_code", None) or {}
    key = normalize_listing_code(query_code)
    if key in records:
        return key
    for candidate in price_rule_candidates(key):
        if candidate in records:
            return candidate
    for stored_key in records:
        if codes_match(key, stored_key):
            return stored_key
    return ""


def _search_feishu_rows_for_code(
    *,
    cfg: FeishuConfig,
    query_code: str,
    code_field: str,
    force_refresh: bool,
) -> list[dict[str, Any]]:
    from pdd_agent.integrations.feishu.bitable import (
        search_records_by_field_contains,
        search_records_by_field_values,
    )
    from pdd_agent.integrations.feishu.client import FeishuClient

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return []

    api = FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in price_rule_candidates(query_code):
        if not value:
            continue
        try:
            batch = search_records_by_field_values(
                api,
                app_token,
                table_id,
                field_name=code_field,
                values=[value],
            )
        except Exception:
            batch = []
        for item in batch:
            rid = str(item.get("record_id") or "")
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            items.append(item)

    try:
        fuzzy = search_records_by_field_contains(
            api,
            app_token,
            table_id,
            field_name=code_field,
            values=[query_code],
        )
    except Exception:
        fuzzy = []
    for item in fuzzy:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        if not codes_match(query_code, raw_code):
            continue
        rid = str(item.get("record_id") or "")
        if rid and rid in seen:
            continue
        if rid:
            seen.add(rid)
        items.append(item)
    return items


def inspect_listing_feishu_prices(
    codes: list[str],
    *,
    force_refresh: bool = True,
    config: FeishuConfig | None = None,
) -> dict[str, Any]:
    """按商品编码拉取并汇总飞书比价定价表实际读到的字段值。"""
    from pdd_agent.integrations.feishu.cache import clear_feishu_data_caches
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import (
        get_listing_feishu_snapshot,
        warm_listing_feishu_snapshot,
    )

    cfg = config or load_feishu_config()
    cat_names = cfg.pdd_product_catalog.field_names
    compare_names = cfg.pdd_price_compare.field_names

    merchant_codes = list(
        dict.fromkeys(
            code
            for raw in codes
            if (code := _merchant_code_from_selector(raw))
        )
    )

    if force_refresh:
        clear_feishu_data_caches()

    warm_listing_feishu_snapshot(merchant_codes, config=cfg)
    snapshot = get_listing_feishu_snapshot()

    from pdd_agent.integrations.feishu.client import FeishuClient

    api = FeishuClient(cfg)
    app_token = str(cfg.bitable_app_token or "").strip()
    table_id = ""
    code_field = compare_names.merchant_code
    min_field = compare_names.min_price
    max_field = compare_names.max_price
    pricing_field = compare_names.pdd_pricing
    control_field = compare_names.pdd_control_price
    retail_cost_field = compare_names.retail_cost
    retail_cost_label = compare_names.retail_cost
    if app_token and cfg.app_id and cfg.app_secret:
        table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
        if table_id:
            code_field, min_field, max_field, retail_cost_field = _resolve_price_range_field_names(
                api, app_token, table_id, compare_names
            )
            from pdd_agent.integrations.feishu.bitable import resolve_table_field_name

            pricing_field = resolve_table_field_name(
                api, app_token, table_id, compare_names.pdd_pricing
            )
            control_field = resolve_table_field_name(
                api, app_token, table_id, compare_names.pdd_control_price
            )
            retail_cost_field = resolve_table_field_name(
                api, app_token, table_id, compare_names.retail_cost
            )

    pricing_catalog = load_pricing_catalog(config=cfg, force_refresh=force_refresh)
    control_catalog = load_control_catalog(config=cfg, force_refresh=force_refresh)
    range_catalog = load_price_range_catalog(config=cfg, force_refresh=force_refresh)
    snapshot_range = snapshot.range_catalog(cfg) if snapshot is not None else None

    pseudo_units = [
        type(
            "_U",
            (),
            {
                "product_code": code,
                "style_codes": [],
                "model_codes": [],
                "listing_label": f"{code}/第一套图",
            },
        )()
        for code in merchant_codes
    ]
    issues = diagnose_feishu_listing_catalog_issues(units=pseudo_units, config=cfg)
    issue_by_code: dict[str, list[str]] = {}
    for issue in issues:
        merchant = str(issue.merchant_code or "").strip()
        for detail in issue.details:
            if merchant:
                issue_by_code.setdefault(merchant, []).append(detail.message)
            issue_by_code.setdefault(detail.code, []).append(detail.message)

    items: list[dict[str, Any]] = []
    for query_code in merchant_codes:
        snapshot_key = _matched_snapshot_key(snapshot, query_code)
        snapshot_fields = snapshot_record_fields(snapshot, query_code) if snapshot else None

        feishu_rows = _search_feishu_rows_for_code(
            cfg=cfg,
            query_code=query_code,
            code_field=code_field,
            force_refresh=force_refresh,
        )
        feishu_row_summaries = [
            _row_field_summary(
                item.get("fields") if isinstance(item.get("fields"), dict) else {},
                code_field=code_field,
                pricing_field=pricing_field,
                control_field=control_field,
                min_field=min_field,
                max_field=max_field,
                retail_cost_field=retail_cost_field,
                retail_cost_label=retail_cost_label,
                color_field=cat_names.color_spec,
            )
            for item in feishu_rows
        ]

        pricing_price, pricing_reason = resolve_code_price_from_catalog(pricing_catalog, query_code)
        control_price, control_reason = resolve_code_price_from_catalog(control_catalog, query_code)
        full_range = find_pdd_price_range(range_catalog.ranges, [query_code])
        snap_range = (
            find_pdd_price_range(snapshot_range.ranges, [query_code]) if snapshot_range else None
        )
        range_aspect = resolve_feishu_range_aspect(range_catalog, [query_code])
        snap_range_aspect = (
            resolve_feishu_range_aspect(snapshot_range, [query_code]) if snapshot_range else None
        )

        used_fields = snapshot_fields or (
            feishu_rows[0].get("fields")
            if feishu_rows and isinstance(feishu_rows[0].get("fields"), dict)
            else {}
        )
        parsed = _row_field_summary(
            used_fields or {},
            code_field=code_field,
            pricing_field=pricing_field,
            control_field=control_field,
            min_field=min_field,
            max_field=max_field,
            retail_cost_field=retail_cost_field,
            retail_cost_label=retail_cost_label,
            color_field=cat_names.color_spec,
        )

        items.append(
            {
                "query_code": query_code,
                "snapshot_matched_key": snapshot_key,
                "snapshot_has_row": bool(snapshot_fields),
                "feishu_row_count": len(feishu_rows),
                "feishu_rows": feishu_row_summaries,
                "parsed": parsed,
                "catalog_pricing": _format_price(pricing_price),
                "catalog_control": _format_price(control_price),
                "catalog_range_min": _format_price(full_range.min_price if full_range else None),
                "catalog_range_max": _format_price(full_range.max_price if full_range else None),
                "catalog_retail_cost": _format_price(
                    full_range.retail_cost if full_range and full_range.retail_cost is not None else None
                ),
                "snapshot_range_min": _format_price(snap_range.min_price if snap_range else None),
                "snapshot_range_max": _format_price(snap_range.max_price if snap_range else None),
                "snapshot_retail_cost": _format_price(
                    snap_range.retail_cost if snap_range and snap_range.retail_cost is not None else None
                ),
                "pricing_reason": pricing_reason,
                "control_reason": control_reason,
                "range_aspect": range_aspect or "",
                "snapshot_range_aspect": snap_range_aspect or "",
                "diagnose_messages": issue_by_code.get(query_code, []),
            }
        )

    snapshot_keys = sorted(getattr(snapshot, "records_by_code", {}) or {})

    return {
        "codes": merchant_codes,
        "items": items,
        "field_names": {
            "product_code": code_field,
            "pricing": pricing_field,
            "control": control_field,
            "min_price": min_field,
            "max_price": max_field,
            "retail_cost": retail_cost_field,
            "color_spec": cat_names.color_spec,
        },
        "table_name": cfg.pdd_price_compare.table_name,
        "table_id": table_id,
        "snapshot_source": getattr(snapshot, "source", "") if snapshot else "",
        "snapshot_keys": snapshot_keys,
        "pricing_catalog_source": pricing_catalog.source,
        "range_catalog_source": range_catalog.source,
    }
