"""平台跳过场景：按飞书「拼多多比价定价」产品状态区分下架跳过原因与失败日志。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pdd_agent.integrations.feishu.bitable import (
    resolve_table_field_name,
    search_records_by_field_contains,
    search_records_by_field_values,
)
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.integrations.feishu.field_display import format_single_select
from pdd_agent.integrations.feishu.listing_feishu_catalog import (
    codes_match,
    feishu_snapshot_alias_allowed,
    normalize_listing_code,
)
from pdd_agent.integrations.feishu.listing_feishu_platform_guard import PLATFORM_SKIP_REASON
from pdd_agent.integrations.feishu.pdd_price_compare_sync import (
    _field_text,
    resolve_pdd_price_compare_table_id,
)
from pdd_agent.skills.campaign.price_rules import price_rule_candidates

logger = logging.getLogger(__name__)

PRODUCT_STATUS_DELISTED = "下架"
DELISTED_PRODUCT_SKIP_REASON = "该商品产品状态为下架，自动跳过，无需处理"


def is_delisted_product_status(status: str) -> bool:
    return format_single_select(status).strip() == PRODUCT_STATUS_DELISTED


def resolve_platform_skip_failure_reason(
    merchant_code: str,
    *,
    status_by_code: dict[str, str],
    default_reason: str = PLATFORM_SKIP_REASON,
) -> str:
    status = lookup_product_status_for_merchant_code(merchant_code, status_by_code)
    if is_delisted_product_status(status):
        return DELISTED_PRODUCT_SKIP_REASON
    return default_reason


def lookup_product_status_for_merchant_code(
    merchant_code: str,
    status_by_code: dict[str, str],
) -> str:
    code = normalize_listing_code(merchant_code)
    if not code:
        return ""
    direct = str(status_by_code.get(code) or "").strip()
    if direct:
        return direct
    for raw_code, status in status_by_code.items():
        if codes_match(code, raw_code):
            return str(status or "").strip()
    return ""


def lookup_product_status_by_merchant_codes(
    merchant_codes: list[str],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, str]:
    """批量查询飞书「拼多多比价定价」表中商品编码对应的「产品状态」。"""
    cfg = config or load_feishu_config()
    normalized = list(
        dict.fromkeys(normalize_listing_code(code) for code in merchant_codes if normalize_listing_code(code))
    )
    if not normalized:
        return {}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {}

    api = client or FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        return {}

    catalog_names = cfg.pdd_product_catalog.field_names
    code_field = resolve_table_field_name(api, app_token, table_id, catalog_names.product_code)
    status_field = resolve_table_field_name(api, app_token, table_id, catalog_names.product_status)
    if not code_field or not status_field:
        return {}

    rows: list[tuple[str, str]] = []
    try:
        records = search_records_by_field_values(
            api,
            app_token,
            table_id,
            field_name=code_field,
            values=normalized,
        )
    except Exception:
        logger.exception("lookup product status exact search failed codes=%s", normalized)
        records = []

    found: set[str] = set()
    for item in records:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        status = format_single_select(fields.get(status_field))
        if raw_code and status:
            rows.append((raw_code, status))
            norm = normalize_listing_code(raw_code)
            if norm:
                found.add(norm)
            for candidate in price_rule_candidates(raw_code):
                candidate_norm = normalize_listing_code(candidate)
                if candidate_norm:
                    found.add(candidate_norm)

    still_missing = [code for code in normalized if code not in found]
    if still_missing:
        try:
            fuzzy_records = search_records_by_field_contains(
                api,
                app_token,
                table_id,
                field_name=code_field,
                values=still_missing,
            )
        except Exception:
            logger.exception("lookup product status fuzzy search failed codes=%s", still_missing)
            fuzzy_records = []
        missing_set = set(still_missing)
        for item in fuzzy_records:
            fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
            raw_code = _field_text(fields, code_field)
            status = format_single_select(fields.get(status_field))
            if not raw_code or not status:
                continue
            matched = [key for key in price_rule_candidates(raw_code) if key in missing_set]
            if not matched:
                for pending in still_missing:
                    if feishu_snapshot_alias_allowed(pending, raw_code):
                        matched.append(pending)
            if matched:
                rows.append((raw_code, status))

    status_by_code: dict[str, str] = {}
    for merchant_code in normalized:
        for raw_code, status in rows:
            if codes_match(merchant_code, raw_code):
                status_by_code[merchant_code] = status
                break
    return status_by_code


def _merchant_code_from_skip_item(item: dict[str, Any]) -> str:
    return str(
        item.get("merchant_code")
        or item.get("platform_listing_code")
        or ""
    ).strip()


def enrich_platform_skip_items_with_delisted_status(
    items: list[dict[str, Any]],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, str]:
    """
    平台跳过结果项：若飞书产品状态为「下架」，将 error 改为下架专用文案。

    返回 {normalized_merchant_code: 产品状态} 供后续写失败日志复用。
    """
    codes = [_merchant_code_from_skip_item(item) for item in items if isinstance(item, dict)]
    status_by_code = lookup_product_status_by_merchant_codes(codes, config=config, client=client)
    for item in items:
        if not isinstance(item, dict):
            continue
        merchant_code = _merchant_code_from_skip_item(item)
        if not merchant_code:
            continue
        status = lookup_product_status_for_merchant_code(merchant_code, status_by_code)
        if is_delisted_product_status(status):
            item["error"] = DELISTED_PRODUCT_SKIP_REASON
            item["product_status"] = status
    return status_by_code


def schedule_platform_skip_feishu_failure_logs(
    *,
    account_id: str,
    account_name: str,
    entries: list[dict[str, Any]],
    status_by_code: dict[str, str] | None = None,
    write_mode: str,
    publish_start: datetime | None = None,
    publish_end: datetime | None = None,
    duration_seconds: float | None = None,
    report_platform: str = "拼多多",
) -> int:
    """
    平台跳过写飞书失败日志。

    write_mode:
    - dedupe: 仅产品状态为「下架」时写入（历史跳过去重命中后补记）
    - bag_view: 始终写入；下架时使用下架专用失败原因
    """
    from pdd_agent.integrations.feishu.pdd_upload_sync import schedule_pdd_upload_failure_log

    mode = str(write_mode or "").strip()
    status_map = dict(status_by_code or {})
    written = 0
    for raw in entries or []:
        if not isinstance(raw, dict):
            continue
        selector = str(raw.get("selector") or raw.get("listing_label") or "").strip()
        listing_label = str(raw.get("listing_label") or raw.get("selector") or "").strip()
        merchant_code = str(raw.get("merchant_code") or raw.get("platform_listing_code") or "").strip()
        if not selector and not merchant_code:
            continue

        failure_reason = str(raw.get("error") or "").strip() or resolve_platform_skip_failure_reason(
            merchant_code,
            status_by_code=status_map,
        )
        status = lookup_product_status_for_merchant_code(merchant_code, status_map)
        is_delisted = is_delisted_product_status(status)

        if mode == "dedupe":
            if not is_delisted:
                continue
            system_reason = f"产品状态为下架：{merchant_code}"
        elif mode == "bag_view":
            if is_delisted:
                system_reason = f"产品状态为下架：{merchant_code}"
            else:
                system_reason = str(raw.get("system_reason") or f"笔袋视图未找到：{merchant_code}").strip()
        else:
            logger.warning("unknown platform skip feishu log mode=%s merchant_code=%s", mode, merchant_code)
            continue

        schedule_pdd_upload_failure_log(
            account_id=account_id,
            account_name=account_name,
            listing_label=listing_label,
            merchant_code=merchant_code,
            record_type="跳过",
            failure_reason=failure_reason,
            system_reason=system_reason,
            report_platform=report_platform,
            publish_start=publish_start,
            publish_end=publish_end,
            duration_seconds=duration_seconds,
        )
        written += 1
    return written
