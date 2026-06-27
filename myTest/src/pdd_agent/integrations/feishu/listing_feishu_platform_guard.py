"""上架前平台适配校验：套图文件夹名须在飞书「笔袋」视图中存在。"""

from __future__ import annotations

import logging
from typing import Any

from pdd_agent.integrations.feishu.bitable import find_view_id_by_name, resolve_table_field_name
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.integrations.feishu.listing_feishu_catalog import codes_match, normalize_listing_code
from pdd_agent.integrations.feishu.pdd_price_compare_sync import _field_text, resolve_pdd_price_compare_table_id

logger = logging.getLogger(__name__)

PLATFORM_SKIP_REASON = "该商品不适用于此平台上架，自动跳过，无需处理"


def extract_product_folder_name(selector: str) -> str:
    """从套图选择器取最后一级文件夹名，如 BD739/第一套图/BD739A -> BD739A。"""
    text = str(selector or "").strip()
    if not text:
        return ""
    if "/" in text:
        return text.rsplit("/", 1)[-1].strip()
    return text


def _load_view_records(
    api: FeishuClient,
    app_token: str,
    table_id: str,
    view_id: str,
    *,
    page_size: int = 500,
) -> list[dict[str, Any]]:
    """与系统设置「笔袋视图」调试接口一致：GET records + view_id 分页拉全量。"""
    items: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {
            "view_id": view_id,
            "page_size": max(1, min(int(page_size), 500)),
        }
        if page_token:
            params["page_token"] = page_token
        resp = api.request(
            "GET",
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            params=params,
            prefer_user_token=True,
        )
        data = resp.get("data") or {}
        items.extend(list(data.get("items") or []))
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "").strip()
        if not page_token:
            break
    return items


def _match_code_in_view(product_folder: str, found_codes: list[str]) -> str:
    for raw in found_codes:
        if codes_match(product_folder, raw) or normalize_listing_code(product_folder) == normalize_listing_code(raw):
            return raw
    return ""


def check_product_folders_in_bag_view(
    folder_names: list[str],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """检查套图文件夹名是否存在于飞书「拼多多比价定价」笔袋视图。"""
    cfg = config or load_feishu_config()
    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    normalized = list(dict.fromkeys(str(name or "").strip() for name in folder_names if str(name or "").strip()))
    if not normalized:
        return {"skipped": True, "reason": "empty_input", "items": []}

    view_name = str(cfg.pdd_price_compare.listing_required_view_name or "").strip() or "笔袋"
    view_id = str(cfg.pdd_price_compare.listing_required_view_id or "").strip()
    if not view_name and not view_id:
        return {"skipped": True, "reason": "guard_not_configured"}

    api = client or FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        return {"skipped": True, "reason": "price_compare_table_missing"}

    if not view_id:
        view_id = find_view_id_by_name(api, app_token, table_id, view_name)
    if not view_id:
        logger.warning(
            "bag view guard skipped: table=%s view_name=%s view not found",
            cfg.pdd_price_compare.table_name,
            view_name,
        )
        return {
            "skipped": True,
            "reason": "required_view_missing",
            "error": f"飞书表「{cfg.pdd_price_compare.table_name}」未找到视图：{view_name}",
        }

    code_field = resolve_table_field_name(
        api,
        app_token,
        table_id,
        cfg.pdd_product_catalog.field_names.product_code,
    )
    try:
        rows = _load_view_records(api, app_token, table_id, view_id)
    except FeishuAPIError as exc:
        if exc.code == 1254005 and view_name:
            logger.warning(
                "bag view guard stale view_id=%s, re-resolving view_name=%s",
                view_id,
                view_name,
            )
            view_id = find_view_id_by_name(api, app_token, table_id, view_name) or ""
            if not view_id:
                return {
                    "skipped": True,
                    "reason": "required_view_missing",
                    "error": f"飞书表「{cfg.pdd_price_compare.table_name}」未找到视图：{view_name}",
                }
            rows = _load_view_records(api, app_token, table_id, view_id)
        else:
            raise
    found_codes: list[str] = []
    for row in rows:
        fields = row.get("fields") if isinstance(row.get("fields"), dict) else {}
        raw = _field_text(fields, code_field)
        if raw:
            found_codes.append(raw)

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for folder in normalized:
        matched_code = _match_code_in_view(folder, found_codes)
        items.append(
            {
                "merchant_code": folder,
                "matched": bool(matched_code),
                "matched_code": matched_code,
                "view_name": view_name,
                "view_id": view_id,
            }
        )
        if not matched_code:
            missing.append(folder)

    return {
        "skipped": False,
        "items": items,
        "missing_codes": missing,
        "matched_codes": [folder for folder in normalized if folder not in missing],
        "view_name": view_name,
        "view_id": view_id,
        "table_id": table_id,
        "view_record_count": len(rows),
    }


# 兼容旧调用名
def ensure_codes_in_required_view(
    codes: list[str],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    data = check_product_folders_in_bag_view(codes, config=config, client=client)
    if data.get("skipped"):
        reason = str(data.get("reason") or "")
        if reason == "required_view_missing":
            return {
                "ok": False,
                "reason": reason,
                "error": str(data.get("error") or ""),
            }
        return {"ok": True, "skipped": True, "reason": reason, "items": data.get("items") or []}
    return {
        "ok": True,
        "items": data.get("items") or [],
        "missing_codes": list(data.get("missing_codes") or []),
        "view_name": data.get("view_name"),
        "view_id": data.get("view_id"),
        "table_id": data.get("table_id"),
    }
