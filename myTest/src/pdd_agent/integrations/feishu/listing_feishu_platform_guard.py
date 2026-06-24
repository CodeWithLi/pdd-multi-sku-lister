"""上架前平台适配校验：要求商品编码存在于指定飞书视图。"""

from __future__ import annotations

from typing import Any

from pdd_agent.integrations.feishu.bitable import (
    find_view_id_by_name,
    resolve_table_field_name,
    search_records_by_field_contains,
    search_records_by_field_values,
)
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.integrations.feishu.listing_feishu_catalog import codes_match, normalize_listing_code
from pdd_agent.integrations.feishu.pdd_price_compare_sync import _field_text, resolve_pdd_price_compare_table_id

PLATFORM_SKIP_REASON = "该商品不适用于此平台上架，自动跳过，无需处理"


def ensure_codes_in_required_view(
    codes: list[str],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """检查商品编码是否存在于飞书「拼多多比价定价」指定视图。"""
    cfg = config or load_feishu_config()
    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"ok": True, "skipped": True, "reason": "feishu_not_configured"}

    normalized = list(dict.fromkeys(str(code or "").strip() for code in codes if str(code or "").strip()))
    if not normalized:
        return {"ok": True, "items": []}

    api = client or FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        return {"ok": True, "skipped": True, "reason": "price_compare_table_missing"}

    view_name = str(cfg.pdd_price_compare.listing_required_view_name or "").strip()
    view_id = str(cfg.pdd_price_compare.listing_required_view_id or "").strip()
    if not view_id and not view_name:
        return {"ok": True, "items": [{"merchant_code": code, "matched": True} for code in normalized]}

    if not view_id:
        view_id = find_view_id_by_name(api, app_token, table_id, view_name)
    if not view_id:
        return {
            "ok": False,
            "reason": "required_view_missing",
            "error": f"飞书表「{cfg.pdd_price_compare.table_name}」未找到视图：{view_name}",
        }

    code_field = resolve_table_field_name(
        api,
        app_token,
        table_id,
        cfg.pdd_product_catalog.field_names.product_code,
    )
    exact = search_records_by_field_values(
        api,
        app_token,
        table_id,
        field_name=code_field,
        values=normalized,
        view_id=view_id,
    )
    fuzzy = search_records_by_field_contains(
        api,
        app_token,
        table_id,
        field_name=code_field,
        values=normalized,
        view_id=view_id,
    )

    found_rows = list(exact) + [row for row in fuzzy if row not in exact]
    found_codes: list[str] = []
    for row in found_rows:
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        raw = _field_text(fields, code_field)
        if raw:
            found_codes.append(raw)

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for code in normalized:
        matched_code = ""
        for raw in found_codes:
            if codes_match(code, raw) or normalize_listing_code(code) == normalize_listing_code(raw):
                matched_code = raw
                break
        item = {
            "merchant_code": code,
            "matched": bool(matched_code),
            "matched_code": matched_code,
            "view_name": view_name,
            "view_id": view_id,
        }
        items.append(item)
        if not matched_code:
            missing.append(code)

    return {
        "ok": True,
        "items": items,
        "missing_codes": missing,
        "view_name": view_name,
        "view_id": view_id,
        "table_id": table_id,
    }
