"""拼多多所有商品表 — Excel 迁移与运行时读取（库存/定价来自飞书）。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import (
    FIELD_NUMBER,
    FIELD_TEXT,
    batch_create_records,
    batch_update_records,
    ensure_fields,
    find_table_id_by_name,
    list_all_records,
    map_fields_to_table_names,
    resolve_table_field_name,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    excel_fallback_enabled,
    load_feishu_config,
    save_pdd_product_catalog_table_id_to_config,
)
from pdd_agent.integrations.feishu.pdd_price_compare_sync import _field_number, _field_text
from pdd_agent.integrations.feishu.pdd_upload_sync import _resolve_or_create_pdd_table_id
from pdd_agent.paths import PROJECT_ROOT
from pdd_agent.skills.listing.pdd_product_catalog import (
    PddProductEntry,
    _norm_code,
    _parse_cell_float,
    _parse_cell_int,
    load_pdd_product_catalog,
)

logger = get_logger(__name__)

FEISHU_PRODUCT_CATALOG_MISSING_REASON = "feishu_product_catalog_missing"


@dataclass(frozen=True)
class FeishuCatalogIssueDetail:
    """单条飞书商品/定价校验失败，便于分派处理。"""

    code: str
    reason_code: str
    message: str
    aspect: str = ""


@dataclass(frozen=True)
class FeishuListingCatalogIssue:
    """单个上架单元在飞书商品/定价表中的缺失项。"""

    listing_label: str
    merchant_code: str
    code_details: tuple[tuple[str, tuple[str, ...]], ...]
    details: tuple[FeishuCatalogIssueDetail, ...] = ()


def _is_sub_catalog_code(code: str, merchant_code: str) -> bool:
    norm_code = _norm_code(code)
    norm_merchant = _norm_code(merchant_code)
    return bool(norm_code and norm_merchant and norm_code != norm_merchant)


def format_feishu_catalog_issue_detail_message(
    *,
    listing_label: str,
    code: str,
    merchant_code: str,
    aspect: str,
) -> tuple[str, str]:
    """生成 (reason_code, message)。主商品码带「失败:」前缀，子编码用「子编码 XXX …」格式。"""
    label = str(listing_label or "").strip()
    norm_code = _norm_code(code)
    is_sub = _is_sub_catalog_code(code, merchant_code)

    aspect_config: dict[str, tuple[str, str]] = {
        "pricing_missing": ("feishu_pricing_missing", "定价数据缺失"),
        "control_missing": ("feishu_control_missing", "控价数据缺失"),
        "range_missing": ("feishu_price_range_missing", "控价区间数据缺失"),
        "color_spec_missing": ("feishu_color_spec_missing", "颜色规格没数据"),
        "product_row_missing": ("feishu_product_row_missing", "商品表没数据"),
        "subcode_missing": ("feishu_subcode_missing", "没数据"),
    }
    reason_code, aspect_text = aspect_config.get(
        aspect, ("feishu_product_catalog_missing", "飞书数据缺失")
    )

    if is_sub:
        sub_reason_map = {
            "pricing_missing": "feishu_subcode_pricing_missing",
            "control_missing": "feishu_subcode_control_missing",
            "range_missing": "feishu_subcode_range_missing",
            "color_spec_missing": "feishu_subcode_color_spec_missing",
            "product_row_missing": "feishu_subcode_missing",
            "subcode_missing": "feishu_subcode_missing",
        }
        reason_code = sub_reason_map.get(aspect, reason_code)
        if aspect in {"product_row_missing", "subcode_missing"}:
            message = f"{label}：子编码 {norm_code} 没数据"
        else:
            message = f"{label}：子编码 {norm_code} {aspect_text}"
    else:
        message = f"失败: {label}: {aspect_text}" if label else f"失败: {aspect_text}"

    return reason_code, message


def _aspect_label(aspect: str) -> str:
    labels = {
        "pricing_missing": "定价没数据",
        "control_missing": "控价没数据",
        "range_missing": "控价区间没数据",
        "color_spec_missing": "颜色规格没数据",
        "product_row_missing": "商品表没数据",
        "subcode_missing": "商品表没数据",
    }
    return labels.get(aspect, "飞书数据缺失")


def _append_catalog_detail(
    details: list[FeishuCatalogIssueDetail],
    *,
    listing_label: str,
    merchant_code: str,
    code: str,
    aspect: str,
) -> None:
    norm_code = _norm_code(code)
    for existing in details:
        if existing.code == norm_code and existing.aspect == aspect:
            return
    reason_code, message = format_feishu_catalog_issue_detail_message(
        listing_label=listing_label,
        code=code,
        merchant_code=merchant_code,
        aspect=aspect,
    )
    details.append(
        FeishuCatalogIssueDetail(
            code=_norm_code(code),
            reason_code=reason_code,
            message=message,
            aspect=aspect,
        )
    )


_CACHE: dict[str, Any] = {"loaded_at": 0.0, "catalog": None, "source": ""}


@dataclass(frozen=True)
class ProductCatalogLoadResult:
    catalog: dict[str, PddProductEntry]
    source: str = "empty"


def _catalog_excel_path(config: FeishuConfig, override: Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    rel = str(config.pdd_product_catalog.excel_relpath or "").strip()
    path = Path(rel)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _field_defs_for_product_catalog(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_product_catalog.field_names
    return [
        {"field_name": names.product_code, "type": FIELD_TEXT},
        {"field_name": names.color_spec, "type": FIELD_TEXT},
        {"field_name": names.product_type, "type": FIELD_TEXT},
        {"field_name": names.available_inventory, "type": FIELD_NUMBER},
        {"field_name": names.pricing, "type": FIELD_NUMBER},
    ]


def resolve_pdd_product_catalog_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
    create_if_missing: bool = False,
) -> tuple[str, str]:
    catalog_cfg = cfg.pdd_product_catalog
    return _resolve_or_create_pdd_table_id(
        cfg,
        client,
        configured_id=catalog_cfg.table_id,
        table_name=catalog_cfg.table_name,
        save_table_id=save_table_id,
        save_fn=save_pdd_product_catalog_table_id_to_config,
        create_if_missing=create_if_missing,
    )


def ensure_pdd_product_catalog_table_ready(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    catalog_cfg = cfg.pdd_product_catalog
    if not catalog_cfg.enabled:
        return {"skipped": True, "reason": "pdd_product_catalog_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_product_catalog_table_id(
        cfg, api, save_table_id=True, create_if_missing=True
    )
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到或无法创建飞书表「{catalog_cfg.table_name}」",
        }

    ensure_fields(api, app_token, table_id, _field_defs_for_product_catalog(cfg))
    return {
        "ready": True,
        "table_id": table_id,
        "table_name": catalog_cfg.table_name,
        "resolve_method": resolve_method,
    }


def _entry_from_feishu_fields(fields: dict[str, Any], names) -> PddProductEntry | None:
    code = _norm_code(_field_text(fields, names.product_code))
    color_spec = _field_text(fields, names.color_spec)
    if not code or not color_spec:
        return None
    inventory = _field_number(fields, names.available_inventory)
    pricing = _field_number(fields, names.pricing)
    return PddProductEntry(
        code=code,
        color_spec=color_spec,
        product_type=_field_text(fields, names.product_type),
        inventory=int(inventory or 0),
        price=float(pricing or 0.0),
    )


def load_pdd_product_catalog_from_feishu(
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> ProductCatalogLoadResult:
    """从飞书「拼多多比价定价」读取商品编码/规格/库存/定价。"""
    cfg = config or load_feishu_config()
    catalog_cfg = cfg.pdd_product_catalog
    if not catalog_cfg.enabled:
        return ProductCatalogLoadResult(catalog={}, source="disabled")

    from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot

    snapshot = get_listing_feishu_snapshot()
    if snapshot is not None:
        catalog = snapshot.product_catalog(cfg)
        return ProductCatalogLoadResult(
            catalog=catalog,
            source=snapshot.source if catalog else "feishu_empty",
        )

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return ProductCatalogLoadResult(catalog={}, source="feishu_not_configured")

    from pdd_agent.integrations.feishu.pdd_price_compare_sync import resolve_pdd_price_compare_table_id

    api = client or FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        return ProductCatalogLoadResult(catalog={}, source="feishu_table_missing")

    names = catalog_cfg.field_names
    code_field = resolve_table_field_name(api, app_token, table_id, names.product_code)
    catalog: dict[str, PddProductEntry] = {}
    for item in list_all_records(api, app_token, table_id):
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        if raw_code:
            fields = dict(fields)
            fields[names.product_code] = raw_code
        entry = _entry_from_feishu_fields(fields, names)
        if entry:
            catalog[entry.code] = entry

    return ProductCatalogLoadResult(
        catalog=catalog,
        source="feishu" if catalog else "feishu_empty",
    )


def feishu_product_catalog_missing_message(*, table_name: str = "", product_code: str = "") -> str:
    """兼容旧调用；新逻辑请用 format_feishu_listing_catalog_issue_message。"""
    code = _norm_code(product_code)
    if code:
        return f"{code}商品表没数据"
    label = str(table_name or "拼多多所有商品").strip() or "拼多多所有商品"
    return f"飞书{label}没数据"


def format_feishu_listing_catalog_issue_message(issue: FeishuListingCatalogIssue) -> str:
    """对外展示：优先返回首条分项说明。"""
    if issue.details:
        return issue.details[0].message
    return str(issue.listing_label or "").strip()


def _collect_product_catalog_issue_details(
    *,
    code: str,
    catalog: dict[str, PddProductEntry],
    source: str,
    raw_fields: dict[str, Any] | None,
    names,
    listing_label: str,
    merchant_code: str,
    details: list[FeishuCatalogIssueDetail],
) -> list[str]:
    """返回 legacy aspect 标签列表，并追加结构化 details。"""
    aspects: list[str] = []
    if source in {"feishu_empty", "feishu_table_missing", "feishu_not_configured"}:
        aspect = "subcode_missing" if _is_sub_catalog_code(code, merchant_code) else "product_row_missing"
        aspects.append(_aspect_label(aspect))
        _append_catalog_detail(
            details,
            listing_label=listing_label,
            merchant_code=merchant_code,
            code=code,
            aspect=aspect,
        )
        return aspects

    if raw_fields:
        color_spec = _field_text(raw_fields, names.color_spec)
        if not color_spec:
            aspect = "color_spec_missing"
            aspects.append(_aspect_label(aspect))
            _append_catalog_detail(
                details,
                listing_label=listing_label,
                merchant_code=merchant_code,
                code=code,
                aspect=aspect,
            )
            return aspects

    entry = catalog.get(code)
    if not entry:
        aspect = "subcode_missing" if _is_sub_catalog_code(code, merchant_code) else "product_row_missing"
        aspects.append(_aspect_label(aspect))
        _append_catalog_detail(
            details,
            listing_label=listing_label,
            merchant_code=merchant_code,
            code=code,
            aspect=aspect,
        )
        return aspects

    if float(entry.price or 0.0) <= 0:
        aspect = "pricing_missing"
        aspects.append(_aspect_label(aspect))
        _append_catalog_detail(
            details,
            listing_label=listing_label,
            merchant_code=merchant_code,
            code=code,
            aspect=aspect,
        )
    return aspects


def _collect_price_catalog_issue_detail(
    *,
    code: str,
    catalog: Any,
    aspect: str,
    listing_label: str,
    merchant_code: str,
    details: list[FeishuCatalogIssueDetail],
) -> str | None:
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import (
        FEISHU_DATA_MISSING_MESSAGE,
        FEISHU_PRICE_NOT_FOUND_MESSAGE,
        resolve_code_price_from_catalog,
    )

    if getattr(catalog, "source", "") != "feishu":
        return None
    _price, reason = resolve_code_price_from_catalog(catalog, code)
    if not reason:
        return None
    if reason == FEISHU_PRICE_NOT_FOUND_MESSAGE:
        resolved_aspect = (
            "subcode_missing" if _is_sub_catalog_code(code, merchant_code) else "product_row_missing"
        )
    elif reason == FEISHU_DATA_MISSING_MESSAGE:
        resolved_aspect = aspect
    else:
        resolved_aspect = aspect
    _append_catalog_detail(
        details,
        listing_label=listing_label,
        merchant_code=merchant_code,
        code=code,
        aspect=resolved_aspect,
    )
    return _aspect_label(resolved_aspect)


def _unit_catalog_codes(unit: Any) -> list[str]:
    codes: list[str] = []
    for raw in [
        getattr(unit, "product_code", ""),
        *(getattr(unit, "style_codes", None) or []),
        *(getattr(unit, "model_codes", None) or []),
    ]:
        text = _norm_code(raw)
        if text:
            codes.append(text)
    return list(dict.fromkeys(codes))


def diagnose_feishu_listing_catalog_issues(
    *,
    units: list[Any] | None = None,
    product_codes: list[str] | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> list[FeishuListingCatalogIssue]:
    """检查飞书商品表/定价比价表，返回按套图聚合的缺失明细。"""
    cfg = config or load_feishu_config()
    cat_cfg = cfg.pdd_product_catalog
    price_cfg = cfg.pdd_price_compare
    if not (
        (cat_cfg.enabled and cat_cfg.prefer_feishu)
        or (price_cfg.enabled and price_cfg.prefer_feishu)
    ):
        return []

    unit_list = list(units or [])
    if not unit_list and product_codes:
        unit_list = [
            type("_U", (), {"product_code": code, "style_codes": [], "model_codes": [], "listing_label": code})()
            for code in product_codes
            if _norm_code(code)
        ]

    product_catalog: dict[str, PddProductEntry] = {}
    product_source = ""
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot

    snapshot = get_listing_feishu_snapshot()
    if snapshot is not None:
        product_catalog = snapshot.product_catalog(cfg)
        product_source = snapshot.source
    elif cat_cfg.enabled and cat_cfg.prefer_feishu:
        loaded = load_pdd_product_catalog_from_feishu(config=cfg, client=client)
        product_catalog = loaded.catalog
        product_source = loaded.source

    pricing_catalog = control_catalog = range_catalog = None
    if price_cfg.enabled and price_cfg.prefer_feishu:
        from pdd_agent.integrations.feishu.pdd_price_compare_sync import (
            is_feishu_price_data_missing,
            load_control_catalog,
            load_price_range_catalog,
            load_pricing_catalog,
        )

        if snapshot is not None:
            pricing_catalog = snapshot.pricing_catalog(cfg)
            control_catalog = snapshot.control_catalog(cfg)
            range_catalog = snapshot.range_catalog(cfg)
        else:
            pricing_catalog = load_pricing_catalog(config=cfg, client=client)
            control_catalog = load_control_catalog(config=cfg, client=client)
            range_catalog = load_price_range_catalog(config=cfg, client=client)

    issues: list[FeishuListingCatalogIssue] = []
    names = cat_cfg.field_names
    for unit in unit_list:
        listing_label = str(
            getattr(unit, "listing_label", "") or getattr(unit, "product_code", "") or ""
        ).strip()
        merchant_code = _norm_code(getattr(unit, "product_code", ""))
        code_details: list[tuple[str, tuple[str, ...]]] = []
        details: list[FeishuCatalogIssueDetail] = []
        for code in _unit_catalog_codes(unit):
            aspects: list[str] = []
            raw_fields = None
            if snapshot is not None:
                raw_fields = snapshot.records_by_code.get(code)
            if cat_cfg.enabled and cat_cfg.prefer_feishu:
                aspects.extend(
                    _collect_product_catalog_issue_details(
                        code=code,
                        catalog=product_catalog,
                        source=product_source,
                        raw_fields=raw_fields,
                        names=names,
                        listing_label=listing_label,
                        merchant_code=merchant_code,
                        details=details,
                    )
                )
            if price_cfg.enabled and price_cfg.prefer_feishu:
                pricing_aspect = _collect_price_catalog_issue_detail(
                    code=code,
                    catalog=pricing_catalog,
                    aspect="pricing_missing",
                    listing_label=listing_label,
                    merchant_code=merchant_code,
                    details=details,
                )
                if pricing_aspect:
                    aspects.append(pricing_aspect)
                control_aspect = _collect_price_catalog_issue_detail(
                    code=code,
                    catalog=control_catalog,
                    aspect="control_missing",
                    listing_label=listing_label,
                    merchant_code=merchant_code,
                    details=details,
                )
                if control_aspect:
                    aspects.append(control_aspect)
                if range_catalog and is_feishu_price_data_missing(range_catalog, [code]):
                    aspects.append(_aspect_label("range_missing"))
                    _append_catalog_detail(
                        details,
                        listing_label=listing_label,
                        merchant_code=merchant_code,
                        code=code,
                        aspect="range_missing",
                    )
            deduped = tuple(dict.fromkeys(x for x in aspects if x))
            if deduped:
                code_details.append((code, deduped))
        if not code_details:
            continue
        if not merchant_code:
            merchant_code = code_details[0][0]
        issues.append(
            FeishuListingCatalogIssue(
                listing_label=listing_label,
                merchant_code=merchant_code,
                code_details=tuple(code_details),
                details=tuple(details),
            )
        )
    return issues


def _collect_catalog_codes(*, units: list[Any], extra_codes: list[str] | None = None) -> list[str]:
    codes: list[str] = []
    for unit in units or []:
        for raw in [getattr(unit, "product_code", ""), *(getattr(unit, "style_codes", None) or []), *(getattr(unit, "model_codes", None) or [])]:
            text = _norm_code(raw)
            if text:
                codes.append(text)
    for raw in extra_codes or []:
        text = _norm_code(raw)
        if text:
            codes.append(text)
    return list(dict.fromkeys(codes))


def _listing_label_for_code(units: list[Any], product_code: str) -> str:
    target = _norm_code(product_code)
    for unit in units or []:
        candidates = {_norm_code(getattr(unit, "product_code", ""))}
        candidates.update(_norm_code(x) for x in (getattr(unit, "style_codes", None) or []))
        candidates.update(_norm_code(x) for x in (getattr(unit, "model_codes", None) or []))
        candidates.discard("")
        if target in candidates:
            return str(getattr(unit, "listing_label", "") or product_code).strip() or product_code
    return product_code


def find_missing_feishu_product_codes(
    codes: list[str],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> tuple[list[str], str]:
    """返回飞书商品表中缺失的商品编码（prefer_feishu 开启时）。"""
    cfg = config or load_feishu_config()
    catalog_cfg = cfg.pdd_product_catalog
    if not catalog_cfg.enabled or not catalog_cfg.prefer_feishu:
        return [], ""

    normalized = list(dict.fromkeys(_norm_code(code) for code in codes if _norm_code(code)))
    if not normalized:
        return [], ""

    loaded = load_pdd_product_catalog_from_feishu(config=cfg, client=client)
    if loaded.source in {"feishu_empty", "feishu_table_missing", "feishu_not_configured"}:
        return normalized, loaded.source

    missing = [code for code in normalized if code not in loaded.catalog]
    return missing, loaded.source


def schedule_feishu_product_catalog_missing_logs(
    *,
    account_id: str,
    units: list[Any] | None = None,
    product_codes: list[str] | None = None,
    config: FeishuConfig | None = None,
) -> int:
    """飞书商品表缺数据时写入 PDD发布日志表(失败)（每店铺每次仅一条）。"""
    cfg = config or load_feishu_config()
    if not cfg.pdd_upload_log.enabled:
        return 0
    if not cfg.pdd_product_catalog.enabled or not cfg.pdd_product_catalog.prefer_feishu:
        return 0

    account_id = str(account_id or "").strip()
    if not account_id:
        return 0

    units = list(units or [])
    issues = diagnose_feishu_listing_catalog_issues(
        units=units,
        product_codes=product_codes,
        config=cfg,
    )
    if not issues:
        return 0

    from pdd_agent.integrations.feishu.pdd_upload_sync import schedule_pdd_upload_failure_log

    written = 0
    for issue in issues:
        detail_rows = list(issue.details)
        if not detail_rows:
            label = str(issue.listing_label or "").strip()
            if not label:
                continue
            detail_rows = [
                FeishuCatalogIssueDetail(
                    code=issue.merchant_code,
                    reason_code=FEISHU_PRODUCT_CATALOG_MISSING_REASON,
                    message=label,
                    aspect="",
                )
            ]
        for detail in detail_rows:
            schedule_pdd_upload_failure_log(
                account_id=account_id,
                listing_label=issue.listing_label,
                merchant_code=issue.merchant_code,
                reason_code=detail.reason_code,
                message=detail.message,
            )
            written += 1
    return written


def clear_pdd_product_catalog_cache() -> None:
    _CACHE["loaded_at"] = 0.0
    _CACHE["catalog"] = None
    _CACHE["source"] = ""


def load_unified_pdd_product_catalog(
    *,
    excel_path: Path | None = None,
    settings=None,
    force_refresh: bool = False,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, PddProductEntry]:
    """优先飞书「拼多多所有商品」；无数据且允许回退时读本地 Excel。"""
    cfg = config or load_feishu_config()
    catalog_cfg = cfg.pdd_product_catalog
    cache_seconds = int(catalog_cfg.cache_seconds or 0)

    if (
        not force_refresh
        and cache_seconds > 0
        and _CACHE.get("catalog") is not None
        and time.time() - float(_CACHE.get("loaded_at") or 0) < cache_seconds
    ):
        return dict(_CACHE["catalog"])

    from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot

    snapshot = get_listing_feishu_snapshot()
    if snapshot is not None and catalog_cfg.enabled and catalog_cfg.prefer_feishu:
        catalog = snapshot.product_catalog(cfg)
        if catalog:
            _CACHE["loaded_at"] = time.time()
            _CACHE["catalog"] = catalog
            _CACHE["source"] = snapshot.source
            return dict(catalog)

    if catalog_cfg.enabled and catalog_cfg.prefer_feishu:
        try:
            loaded = load_pdd_product_catalog_from_feishu(config=cfg, client=client)
            if loaded.catalog:
                _CACHE["loaded_at"] = time.time()
                _CACHE["catalog"] = loaded.catalog
                _CACHE["source"] = loaded.source
                return dict(loaded.catalog)
        except Exception:
            logger.exception("load pdd product catalog from feishu failed")

    if excel_fallback_enabled(cfg):
        path = excel_path
        if path is None and settings is not None:
            path = settings.multi_spec.excel_path
        if path is None:
            path = _catalog_excel_path(cfg)
        catalog = load_pdd_product_catalog(path)
        if catalog:
            _CACHE["loaded_at"] = time.time()
            _CACHE["catalog"] = catalog
            _CACHE["source"] = "excel"
            return catalog

    _CACHE["loaded_at"] = time.time()
    _CACHE["catalog"] = {}
    _CACHE["source"] = "empty"
    return {}


def migrate_pdd_product_catalog_xls_to_feishu(
    *,
    dry_run: bool = False,
    excel_path: Path | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """将 拼多多所有商品.xls 迁移到飞书表（按商品编码 upsert）。"""
    cfg = config or load_feishu_config()
    catalog_cfg = cfg.pdd_product_catalog
    if not catalog_cfg.enabled:
        return {"skipped": True, "reason": "pdd_product_catalog_disabled"}

    path = excel_path or _catalog_excel_path(cfg)
    excel_catalog = load_pdd_product_catalog(path)
    if not excel_catalog:
        return {"failed": True, "reason": "excel_empty", "message": f"Excel 无有效行: {path}"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"failed": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    ready = ensure_pdd_product_catalog_table_ready(cfg, api)
    if ready.get("failed") or ready.get("skipped"):
        return ready
    table_id = str(ready.get("table_id") or "")

    names = catalog_cfg.field_names
    code_field = resolve_table_field_name(api, app_token, table_id, names.product_code)
    feishu_records = list_all_records(api, app_token, table_id)
    record_by_code: dict[str, str] = {}
    for item in feishu_records:
        record_id = str(item.get("record_id") or "").strip()
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        code = _norm_code(_field_text(fields, code_field))
        if code and record_id:
            record_by_code[code] = record_id

    creates: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    for code, entry in sorted(excel_catalog.items()):
        row = {
            names.product_code: entry.code,
            names.color_spec: entry.color_spec,
            names.product_type: entry.product_type,
            names.available_inventory: int(entry.inventory or 0),
            names.pricing: float(entry.price or 0.0),
        }
        mapped = map_fields_to_table_names(api, app_token, table_id, row)
        record_id = record_by_code.get(code)
        if record_id:
            updates.append({"record_id": record_id, "fields": mapped})
        else:
            creates.append(mapped)

    created_ids: list[str] = []
    updated_ids: list[str] = []
    if not dry_run:
        if creates:
            chunk_size = 100
            for start in range(0, len(creates), chunk_size):
                created_ids.extend(
                    batch_create_records(api, app_token, table_id, creates[start : start + chunk_size])
                )
        if updates:
            chunk_size = 100
            for start in range(0, len(updates), chunk_size):
                updated_ids.extend(
                    batch_update_records(api, app_token, table_id, updates[start : start + chunk_size])
                )
        clear_pdd_product_catalog_cache()
        try:
            from pdd_agent.skills.listing.pdd_product_catalog import get_pdd_product_catalog

            get_pdd_product_catalog.cache_clear()
        except Exception:
            pass

    return {
        "success": True,
        "dry_run": dry_run,
        "table_id": table_id,
        "excel_rows": len(excel_catalog),
        "feishu_rows_before": len(feishu_records),
        "created_count": len(created_ids) if not dry_run else len(creates),
        "updated_count": len(updated_ids) if not dry_run else len(updates),
        "created_codes": [entry.code for entry in list(excel_catalog.values())[:20] if entry.code not in record_by_code],
    }


__all__ = [
    "FEISHU_PRODUCT_CATALOG_MISSING_REASON",
    "FeishuListingCatalogIssue",
    "clear_pdd_product_catalog_cache",
    "diagnose_feishu_listing_catalog_issues",
    "ensure_pdd_product_catalog_table_ready",
    "feishu_product_catalog_missing_message",
    "find_missing_feishu_product_codes",
    "format_feishu_listing_catalog_issue_message",
    "load_pdd_product_catalog_from_feishu",
    "load_unified_pdd_product_catalog",
    "migrate_pdd_product_catalog_xls_to_feishu",
    "schedule_feishu_product_catalog_missing_logs",
]
