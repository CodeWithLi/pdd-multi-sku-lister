"""拼多多比价定价表 — pdd.xls 控价区间迁移与运行时读取。

Excel 列「下限价格」「上限价格」→ 飞书「PDD控价下限价格」「PDD控价上限价格」。
运行时优先读飞书；字段缺失时返回「飞书缺少数据」供活动日志写入，不抛异常。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import xlrd

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import (
    FIELD_NUMBER,
    FIELD_TEXT,
    batch_update_records,
    ensure_fields,
    find_table_id_by_name,
    list_all_records,
    map_fields_to_table_names,
    resolve_table_field_name,
    resolve_table_field_name_from_candidates,
)
from pdd_agent.integrations.feishu.client import FeishuAPIError, FeishuClient
from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    excel_fallback_enabled,
    load_feishu_config,
    save_pdd_price_compare_table_id_to_config,
)
from pdd_agent.paths import PROJECT_ROOT
from pdd_agent.skills.campaign.price_rules import (
    CampaignPriceRange,
    CodePriceEntry,
    normalize_price_code,
    price_rule_candidates,
    _label_from_raw_code,
)

logger = get_logger(__name__)

FEISHU_DATA_MISSING_MESSAGE = "飞书缺少数据"
FEISHU_PRICE_NOT_FOUND_MESSAGE = "飞书没找到"

MIN_PRICE_FIELD_CANDIDATES = (
    "PDD控价下限价格",
    "PDD定价下限价格",
    "下限价格",
)
MAX_PRICE_FIELD_CANDIDATES = (
    "PDD控价上限价格",
    "PDD定价上限价格",
    "上限价格",
)

_CACHE: dict[str, Any] = {
    "loaded_at": 0.0,
    "range_catalog": None,
    "pricing_catalog": None,
    "control_catalog": None,
}


@dataclass(frozen=True)
class ExcelPriceRow:
    raw_code: str
    norm_code: str
    min_price: float
    max_price: float


@dataclass
class PriceRangeCatalog:
    ranges: dict[str, CampaignPriceRange] = field(default_factory=dict)
    source: str = "empty"
    incomplete_min_codes: frozenset[str] = field(default_factory=frozenset)
    incomplete_max_codes: frozenset[str] = field(default_factory=frozenset)
    incomplete_codes: frozenset[str] = field(default_factory=frozenset)
    feishu_record_codes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ExcelCodePriceRow:
    raw_code: str
    norm_code: str
    price: float


@dataclass
class CodePriceCatalog:
    prices: dict[str, float] = field(default_factory=dict)
    entries: list[CodePriceEntry] = field(default_factory=list)
    source: str = "empty"
    incomplete_codes: frozenset[str] = field(default_factory=frozenset)
    feishu_record_codes: frozenset[str] = field(default_factory=frozenset)


def _resolve_price_range_field_names(
    api: FeishuClient,
    app_token: str,
    table_id: str,
    names: Any,
) -> tuple[str, str, str]:
    code_field = resolve_table_field_name(api, app_token, table_id, names.merchant_code)
    min_field = resolve_table_field_name_from_candidates(
        api,
        app_token,
        table_id,
        MIN_PRICE_FIELD_CANDIDATES,
        names.min_price,
    )
    max_field = resolve_table_field_name_from_candidates(
        api,
        app_token,
        table_id,
        MAX_PRICE_FIELD_CANDIDATES,
        names.max_price,
    )
    return code_field, min_field, max_field


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _unwrap_feishu_field_value(value: Any) -> Any:
    """展开飞书公式/查找引用单元格：{\"type\": 2, \"value\": [9.3]} 或文本数组。"""
    if not isinstance(value, dict):
        return value
    if "type" not in value or "value" not in value:
        return value
    inner = value.get("value")
    if isinstance(inner, list):
        if not inner:
            return None
        first = inner[0]
        if isinstance(first, dict):
            return first.get("text") or first.get("value") or first.get("name") or first
        return first
    return inner


def _field_text(fields: dict[str, Any], field_name: str) -> str:
    if not field_name:
        return ""
    value = _unwrap_feishu_field_value(fields.get(field_name))
    if value is None:
        return ""
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("text") or first.get("name") or "").strip()
        return str(first).strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or "").strip()
    return str(value).strip()


def _field_number(fields: dict[str, Any], field_name: str) -> float | None:
    if not field_name:
        return None
    value = _unwrap_feishu_field_value(fields.get(field_name))
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, (int, float)) and not isinstance(first, bool):
            return float(first)
        if isinstance(first, dict):
            nested = first.get("value", first.get("text"))
            if nested is not None and nested != "":
                try:
                    return float(nested)
                except (TypeError, ValueError):
                    pass
        try:
            return float(str(first).strip())
        except (TypeError, ValueError):
            return None
    if isinstance(value, dict):
        nested = value.get("value", value.get("text"))
        if nested is not None and nested != "":
            try:
                return float(nested)
            except (TypeError, ValueError):
                return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _row_price_fields_score(
    fields: dict[str, Any],
    *,
    min_field: str,
    max_field: str,
    pricing_field: str = "",
    control_field: str = "",
) -> int:
    score = 0
    if _field_number(fields, min_field) is not None:
        score += 1
    max_val = _field_number(fields, max_field)
    if max_val is not None and max_val > 0:
        score += 4
    if pricing_field and (_field_number(fields, pricing_field) or 0) > 0:
        score += 1
    if control_field and (_field_number(fields, control_field) or 0) > 0:
        score += 1
    return score


def _project_relative_path(config: FeishuConfig, rel: str, override: Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    path = Path(str(rel or "").strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _excel_path(config: FeishuConfig, override: Path | None = None) -> Path:
    return _project_relative_path(config, config.pdd_price_compare.excel_relpath, override)


def _pricing_excel_path(config: FeishuConfig, override: Path | None = None) -> Path:
    return _project_relative_path(config, config.pdd_price_compare.pricing_excel_relpath, override)


def _control_excel_path(config: FeishuConfig, override: Path | None = None) -> Path:
    return _project_relative_path(config, config.pdd_price_compare.control_excel_relpath, override)


def load_pdd_xls_rows(path: Path | None = None, config: FeishuConfig | None = None) -> list[ExcelPriceRow]:
    """读取 pdd.xls 控价区间行（商品编码 / 下限价格 / 上限价格）。"""
    cfg = config or load_feishu_config()
    excel_path = _excel_path(cfg, path)
    if not excel_path.is_file():
        logger.warning("pdd.xls not found: %s", excel_path)
        return []

    book = xlrd.open_workbook(str(excel_path))
    if book.nsheets <= 0:
        return []
    sheet = book.sheet_by_index(0)
    if sheet.nrows <= 1:
        return []

    headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    code_col = headers.index("商品编码") if "商品编码" in headers else 0
    min_col = headers.index("下限价格") if "下限价格" in headers else 1
    max_col = headers.index("上限价格") if "上限价格" in headers else 2

    rows: list[ExcelPriceRow] = []
    for row_idx in range(1, sheet.nrows):
        raw_code = str(sheet.cell_value(row_idx, code_col)).strip()
        norm_code = normalize_price_code(raw_code)
        if not norm_code:
            continue
        min_price = _to_float(sheet.cell_value(row_idx, min_col), 0.0)
        max_price = _to_float(sheet.cell_value(row_idx, max_col), 0.0)
        rows.append(
            ExcelPriceRow(
                raw_code=raw_code,
                norm_code=norm_code,
                min_price=min_price,
                max_price=max_price,
            )
        )
    return rows


def load_code_price_xls_rows(
    *,
    excel_path: Path,
    price_header: str,
) -> list[ExcelCodePriceRow]:
    if not excel_path.is_file():
        logger.warning("code price xls not found: %s", excel_path)
        return []
    book = xlrd.open_workbook(str(excel_path))
    if book.nsheets <= 0:
        return []
    sheet = book.sheet_by_index(0)
    if sheet.nrows <= 1:
        return []

    headers = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    code_col = headers.index("商品编码") if "商品编码" in headers else 0
    price_col = headers.index(price_header) if price_header in headers else 1

    rows: list[ExcelCodePriceRow] = []
    for row_idx in range(1, sheet.nrows):
        raw_code = str(sheet.cell_value(row_idx, code_col)).strip()
        norm_code = normalize_price_code(raw_code)
        if not norm_code:
            continue
        price = _to_float(sheet.cell_value(row_idx, price_col), 0.0)
        rows.append(ExcelCodePriceRow(raw_code=raw_code, norm_code=norm_code, price=price))
    return rows


def load_pricing_xls_rows(path: Path | None = None, config: FeishuConfig | None = None) -> list[ExcelCodePriceRow]:
    cfg = config or load_feishu_config()
    return load_code_price_xls_rows(excel_path=_pricing_excel_path(cfg, path), price_header="拼多多定价")


def load_control_xls_rows(path: Path | None = None, config: FeishuConfig | None = None) -> list[ExcelCodePriceRow]:
    cfg = config or load_feishu_config()
    return load_code_price_xls_rows(excel_path=_control_excel_path(cfg, path), price_header="PDD控价")


def _prices_from_excel_rows(rows: list[ExcelCodePriceRow]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for row in rows:
        if row.price <= 0:
            continue
        for key in price_rule_candidates(row.raw_code):
            prices[key] = row.price
    return prices


def _entries_from_excel_rows(rows: list[ExcelCodePriceRow]) -> list[CodePriceEntry]:
    entries: list[CodePriceEntry] = []
    for row in rows:
        entries.append(
            CodePriceEntry(
                raw_code=row.raw_code,
                norm_code=row.norm_code,
                label=_label_from_raw_code(row.raw_code),
                price=row.price,
            )
        )
    return entries


def _ranges_from_excel_rows(rows: list[ExcelPriceRow]) -> dict[str, CampaignPriceRange]:
    ranges: dict[str, CampaignPriceRange] = {}
    for row in rows:
        if row.max_price <= 0:
            continue
        rule = CampaignPriceRange(
            code=row.norm_code,
            min_price=row.min_price,
            max_price=row.max_price,
        )
        for key in price_rule_candidates(row.raw_code):
            ranges[key] = rule
    return ranges


def _field_defs_for_price_compare(config: FeishuConfig) -> list[dict[str, Any]]:
    names = config.pdd_price_compare.field_names
    return [
        {"field_name": names.merchant_code, "type": FIELD_TEXT},
        {"field_name": names.min_price, "type": FIELD_NUMBER},
        {"field_name": names.max_price, "type": FIELD_NUMBER},
        {"field_name": names.pdd_pricing, "type": FIELD_NUMBER},
        {"field_name": names.pdd_control_price, "type": FIELD_NUMBER},
    ]


def resolve_pdd_price_compare_table_id(
    cfg: FeishuConfig,
    client: FeishuClient,
    *,
    save_table_id: bool = True,
) -> tuple[str, str]:
    compare_cfg = cfg.pdd_price_compare
    app_token = str(cfg.bitable_app_token or "").strip()
    configured = str(compare_cfg.table_id or "").strip()
    table_name = str(compare_cfg.table_name or "").strip()

    if table_name:
        found = find_table_id_by_name(client, app_token, table_name)
        if found:
            if configured and configured != found:
                logger.warning(
                    "pdd price compare table_id corrected by name: config=%s actual=%s name=%s",
                    configured,
                    found,
                    table_name,
                )
            if save_table_id and found != configured:
                try:
                    save_pdd_price_compare_table_id_to_config(found)
                except Exception as exc:
                    logger.warning("save pdd price compare table_id failed: %s", exc)
            return found, "table_name"

    if configured:
        return configured, "config_table_id"
    return "", "missing"


def ensure_pdd_price_compare_table_ready(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """启动时校验「拼多多比价定价」表存在；不自动创建业务列（表由运营维护）。"""
    cfg = config or load_feishu_config()
    compare_cfg = cfg.pdd_price_compare
    if not compare_cfg.enabled:
        return {"skipped": True, "reason": "pdd_price_compare_disabled"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"skipped": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_price_compare_table_id(cfg, api)
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到飞书表「{compare_cfg.table_name}」",
        }

    try:
        ensure_fields(api, app_token, table_id, _field_defs_for_price_compare(cfg))
    except FeishuAPIError as exc:
        logger.warning("ensure pdd price compare fields failed: %s", exc)
        return {"failed": True, "reason": "ensure_fields_failed", "message": str(exc)}

    return {
        "ready": True,
        "table_id": table_id,
        "table_name": compare_cfg.table_name,
        "resolve_method": resolve_method,
    }


def _build_catalog_from_feishu_records(
    records: list[dict[str, Any]],
    *,
    code_field: str,
    min_field: str,
    max_field: str,
) -> PriceRangeCatalog:
    ranges: dict[str, CampaignPriceRange] = {}
    incomplete_min: set[str] = set()
    incomplete_max: set[str] = set()
    record_codes: set[str] = set()

    for item in records:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        keys = [key for key in price_rule_candidates(raw_code) if key]
        if not keys:
            continue
        for key in keys:
            record_codes.add(key)
        norm_code = normalize_price_code(raw_code) or keys[0]
        min_price = _field_number(fields, min_field)
        max_price = _field_number(fields, max_field)
        min_bad = min_price is None
        max_bad = max_price is None or max_price <= 0

        if min_bad:
            for key in price_rule_candidates(raw_code):
                if key not in ranges:
                    incomplete_min.add(key)
        if max_bad:
            for key in price_rule_candidates(raw_code):
                if key not in ranges:
                    incomplete_max.add(key)
        if min_bad or max_bad:
            continue

        rule = CampaignPriceRange(
            code=norm_code,
            min_price=float(min_price),
            max_price=float(max_price),
        )
        for key in price_rule_candidates(raw_code):
            ranges[key] = rule
            incomplete_min.discard(key)
            incomplete_max.discard(key)

    incomplete = incomplete_min | incomplete_max
    return PriceRangeCatalog(
        ranges=ranges,
        source="feishu",
        incomplete_min_codes=frozenset(incomplete_min),
        incomplete_max_codes=frozenset(incomplete_max),
        incomplete_codes=frozenset(incomplete),
        feishu_record_codes=frozenset(record_codes),
    )


def _build_code_price_catalog_from_feishu_records(
    records: list[dict[str, Any]],
    *,
    code_field: str,
    price_field: str,
) -> CodePriceCatalog:
    prices: dict[str, float] = {}
    entries: list[CodePriceEntry] = []
    incomplete: set[str] = set()
    record_codes: set[str] = set()

    for item in records:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        keys = [key for key in price_rule_candidates(raw_code) if key]
        if not keys:
            continue
        for key in keys:
            record_codes.add(key)
        norm_code = normalize_price_code(raw_code) or keys[0]
        price_val = _field_number(fields, price_field)
        entry = CodePriceEntry(
            raw_code=raw_code,
            norm_code=norm_code,
            label=_label_from_raw_code(raw_code),
            price=float(price_val or 0.0),
        )
        entries.append(entry)
        if price_val is None or price_val <= 0:
            for key in price_rule_candidates(raw_code):
                incomplete.add(key)
            continue
        for key in price_rule_candidates(raw_code):
            prices[key] = float(price_val)

    return CodePriceCatalog(
        prices=prices,
        entries=entries,
        source="feishu",
        incomplete_codes=frozenset(incomplete),
        feishu_record_codes=frozenset(record_codes),
    )


def _load_code_price_catalog_from_feishu(
    *,
    price_field_name: str,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> CodePriceCatalog:
    cfg = config or load_feishu_config()
    compare_cfg = cfg.pdd_price_compare
    if not compare_cfg.enabled:
        return CodePriceCatalog(source="empty")

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return CodePriceCatalog(source="empty")

    api = client or FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        return CodePriceCatalog(source="empty")

    names = compare_cfg.field_names
    code_field = resolve_table_field_name(api, app_token, table_id, names.merchant_code)
    price_field = resolve_table_field_name(api, app_token, table_id, price_field_name)
    records = list_all_records(api, app_token, table_id)
    return _build_code_price_catalog_from_feishu_records(
        records,
        code_field=code_field,
        price_field=price_field,
    )


def load_pricing_catalog_from_feishu(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> CodePriceCatalog:
    cfg = config or load_feishu_config()
    return _load_code_price_catalog_from_feishu(
        price_field_name=cfg.pdd_price_compare.field_names.pdd_pricing,
        config=cfg,
        client=client,
    )


def load_control_catalog_from_feishu(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> CodePriceCatalog:
    cfg = config or load_feishu_config()
    return _load_code_price_catalog_from_feishu(
        price_field_name=cfg.pdd_price_compare.field_names.pdd_control_price,
        config=cfg,
        client=client,
    )


def _catalog_keys_match(catalog_keys: frozenset[str] | set[str], candidates: list[str]) -> bool:
    from pdd_agent.integrations.feishu.listing_feishu_catalog import codes_match

    wanted = [key for key in candidates if key]
    for key in wanted:
        if key in catalog_keys:
            return True
    for stored_key in catalog_keys:
        for key in wanted:
            if codes_match(key, stored_key):
                return True
    return False


def resolve_code_price_from_catalog(catalog: CodePriceCatalog, code: str) -> tuple[float | None, str]:
    """返回 (价格, 缺失说明)。飞书有行但无价格→缺少数据；飞书无行→没找到。"""
    normalized_candidates: list[str] = []
    for key in price_rule_candidates(code):
        if key:
            normalized_candidates.append(key)
    if not normalized_candidates:
        return None, ""

    for key in normalized_candidates:
        if key in catalog.prices:
            return catalog.prices[key], ""

    for stored_key, price in catalog.prices.items():
        for key in normalized_candidates:
            if key == stored_key:
                return price, ""
            from pdd_agent.integrations.feishu.listing_feishu_catalog import codes_match

            if codes_match(key, stored_key):
                return price, ""

    if catalog.source != "feishu":
        return None, ""

    if _catalog_keys_match(catalog.incomplete_codes, normalized_candidates):
        return None, FEISHU_DATA_MISSING_MESSAGE

    if _catalog_keys_match(catalog.feishu_record_codes, normalized_candidates):
        return None, FEISHU_DATA_MISSING_MESSAGE

    return None, FEISHU_PRICE_NOT_FOUND_MESSAGE


def is_feishu_code_price_missing(catalog: CodePriceCatalog, code: str) -> bool:
    _, reason = resolve_code_price_from_catalog(catalog, code)
    return bool(reason)


def load_price_ranges_from_feishu(
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> PriceRangeCatalog:
    cfg = config or load_feishu_config()
    compare_cfg = cfg.pdd_price_compare
    if not compare_cfg.enabled:
        return PriceRangeCatalog(source="empty")

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return PriceRangeCatalog(source="empty")

    api = client or FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        return PriceRangeCatalog(source="empty")

    names = compare_cfg.field_names
    code_field, min_field, max_field = _resolve_price_range_field_names(api, app_token, table_id, names)

    records = list_all_records(api, app_token, table_id)
    return _build_catalog_from_feishu_records(
        records,
        code_field=code_field,
        min_field=min_field,
        max_field=max_field,
    )


def clear_price_compare_caches() -> None:
    _CACHE["loaded_at"] = 0.0
    _CACHE["range_catalog"] = None
    _CACHE["pricing_catalog"] = None
    _CACHE["control_catalog"] = None


def clear_price_range_cache() -> None:
    """兼容旧调用。"""
    clear_price_compare_caches()


def _cache_get(name: str, cache_seconds: int, force_refresh: bool) -> Any | None:
    if force_refresh or cache_seconds <= 0:
        return None
    loaded_at = float(_CACHE.get("loaded_at") or 0.0)
    if time.time() - loaded_at >= cache_seconds:
        return None
    return _CACHE.get(name)


def _cache_set(name: str, catalog: Any) -> Any:
    _CACHE["loaded_at"] = time.time()
    _CACHE[name] = catalog
    return catalog


def load_price_range_catalog(
    *,
    force_refresh: bool = False,
    excel_path: Path | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> PriceRangeCatalog:
    """优先飞书；无数据且允许回退时读本地 pdd.xls。"""
    cfg = config or load_feishu_config()
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot

    snapshot = get_listing_feishu_snapshot()
    if snapshot is not None:
        return snapshot.range_catalog(cfg)

    compare_cfg = cfg.pdd_price_compare
    cache_seconds = int(compare_cfg.cache_seconds or 0)

    cached = _cache_get("range_catalog", cache_seconds, force_refresh)
    if cached is not None:
        return cached

    catalog = PriceRangeCatalog(source="empty")
    if compare_cfg.enabled and compare_cfg.prefer_feishu:
        try:
            catalog = load_price_ranges_from_feishu(config=cfg, client=client)
        except Exception:
            logger.exception("load price ranges from feishu failed")
            catalog = PriceRangeCatalog(source="empty")

    if catalog.ranges:
        return _cache_set("range_catalog", catalog)

    if excel_fallback_enabled(cfg):
        rows = load_pdd_xls_rows(path=excel_path, config=cfg)
        excel_ranges = _ranges_from_excel_rows(rows)
        catalog = PriceRangeCatalog(ranges=excel_ranges, source="excel" if excel_ranges else "empty")
        return _cache_set("range_catalog", catalog)

    return _cache_set("range_catalog", catalog)


def load_pricing_catalog(
    *,
    force_refresh: bool = False,
    excel_path: Path | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> CodePriceCatalog:
    cfg = config or load_feishu_config()
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot

    snapshot = get_listing_feishu_snapshot()
    if snapshot is not None:
        return snapshot.pricing_catalog(cfg)

    compare_cfg = cfg.pdd_price_compare
    cache_seconds = int(compare_cfg.cache_seconds or 0)

    cached = _cache_get("pricing_catalog", cache_seconds, force_refresh)
    if cached is not None:
        return cached

    catalog = CodePriceCatalog(source="empty")
    if compare_cfg.enabled and compare_cfg.prefer_feishu:
        try:
            catalog = load_pricing_catalog_from_feishu(config=cfg, client=client)
        except Exception:
            logger.exception("load pricing from feishu failed")
            catalog = CodePriceCatalog(source="empty")

    if catalog.prices:
        return _cache_set("pricing_catalog", catalog)

    if excel_fallback_enabled(cfg):
        rows = load_pricing_xls_rows(path=excel_path, config=cfg)
        prices = _prices_from_excel_rows(rows)
        entries = _entries_from_excel_rows(rows)
        catalog = CodePriceCatalog(
            prices=prices,
            entries=entries,
            source="excel" if prices else "empty",
        )
        return _cache_set("pricing_catalog", catalog)

    return _cache_set("pricing_catalog", catalog)


def load_control_catalog(
    *,
    force_refresh: bool = False,
    excel_path: Path | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> CodePriceCatalog:
    cfg = config or load_feishu_config()
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import get_listing_feishu_snapshot

    snapshot = get_listing_feishu_snapshot()
    if snapshot is not None:
        return snapshot.control_catalog(cfg)

    compare_cfg = cfg.pdd_price_compare
    cache_seconds = int(compare_cfg.cache_seconds or 0)

    cached = _cache_get("control_catalog", cache_seconds, force_refresh)
    if cached is not None:
        return cached

    catalog = CodePriceCatalog(source="empty")
    if compare_cfg.enabled and compare_cfg.prefer_feishu:
        try:
            catalog = load_control_catalog_from_feishu(config=cfg, client=client)
        except Exception:
            logger.exception("load control prices from feishu failed")
            catalog = CodePriceCatalog(source="empty")

    if catalog.prices:
        return _cache_set("control_catalog", catalog)

    if excel_fallback_enabled(cfg):
        rows = load_control_xls_rows(path=excel_path, config=cfg)
        prices = _prices_from_excel_rows(rows)
        entries = _entries_from_excel_rows(rows)
        catalog = CodePriceCatalog(
            prices=prices,
            entries=entries,
            source="excel" if prices else "empty",
        )
        return _cache_set("control_catalog", catalog)

    return _cache_set("control_catalog", catalog)


def is_feishu_price_data_missing(catalog: PriceRangeCatalog, candidates: list[str]) -> bool:
    """候选编码在飞书有行但 PDD 控价上下限不完整；飞书无行则不算缺失。"""
    return resolve_feishu_range_aspect(catalog, candidates) is not None


def resolve_feishu_range_aspect(
    catalog: PriceRangeCatalog,
    candidates: list[str],
) -> str | None:
    """返回 range_min_missing / range_max_missing；数据齐全或飞书无行则 None。"""
    from pdd_agent.skills.campaign.price_rules import find_pdd_price_range

    if catalog.source != "feishu":
        return None
    normalized_candidates: list[str] = []
    for value in candidates:
        for key in price_rule_candidates(value):
            if key:
                normalized_candidates.append(key)
    normalized_candidates = list(dict.fromkeys(normalized_candidates))
    if not normalized_candidates:
        return None

    if find_pdd_price_range(catalog.ranges, normalized_candidates):
        return None

    if not _catalog_keys_match(catalog.feishu_record_codes, normalized_candidates):
        return None

    if _catalog_keys_match(catalog.incomplete_min_codes, normalized_candidates):
        return "range_min_missing"
    if _catalog_keys_match(catalog.incomplete_max_codes, normalized_candidates):
        return "range_max_missing"
    return None


def _record_matches_excel_candidates(raw_feishu_code: str, excel_candidates: set[str]) -> bool:
    for key in price_rule_candidates(raw_feishu_code):
        if key in excel_candidates:
            return True
    return False


def migrate_pdd_xls_to_feishu(
    *,
    dry_run: bool = False,
    excel_path: Path | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """将 pdd.xls 下限/上限价格写入飞书「拼多多比价定价」表（按商品编码匹配行）。"""
    cfg = config or load_feishu_config()
    compare_cfg = cfg.pdd_price_compare
    if not compare_cfg.enabled:
        return {"skipped": True, "reason": "pdd_price_compare_disabled"}

    excel_rows = load_pdd_xls_rows(path=excel_path, config=cfg)
    if not excel_rows:
        return {"failed": True, "reason": "excel_empty", "message": "pdd.xls 无有效行"}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"failed": True, "reason": "feishu_not_configured"}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_price_compare_table_id(cfg, api)
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到飞书表「{compare_cfg.table_name}」",
        }

    names = compare_cfg.field_names
    code_field, min_field, max_field = _resolve_price_range_field_names(api, app_token, table_id, names)

    excel_candidate_keys: set[str] = set()
    excel_by_norm: dict[str, ExcelPriceRow] = {}
    for row in excel_rows:
        excel_by_norm[row.norm_code] = row
        for key in price_rule_candidates(row.raw_code):
            excel_candidate_keys.add(key)

    feishu_records = list_all_records(api, app_token, table_id)
    updates: list[dict[str, Any]] = []
    updated_codes: list[str] = []
    feishu_missing_field_codes: list[str] = []
    excel_unmatched: list[str] = []

    for item in feishu_records:
        record_id = str(item.get("record_id") or "").strip()
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        if not raw_code or not record_id:
            continue
        if not _record_matches_excel_candidates(raw_code, excel_candidate_keys):
            continue

        norm = normalize_price_code(raw_code)
        excel_row = excel_by_norm.get(norm)
        if excel_row is None:
            for key in price_rule_candidates(raw_code):
                if key in excel_by_norm:
                    excel_row = excel_by_norm[key]
                    break
        if excel_row is None:
            continue

        if excel_row.max_price <= 0:
            feishu_missing_field_codes.append(raw_code)
            continue

        patch = {
            names.min_price: excel_row.min_price,
            names.max_price: excel_row.max_price,
        }
        mapped = map_fields_to_table_names(api, app_token, table_id, patch)
        updates.append({"record_id": record_id, "fields": mapped})
        updated_codes.append(raw_code)

    matched_excel_norms: set[str] = set()
    for row in excel_rows:
        for rec in feishu_records:
            fields = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
            raw_code = _field_text(fields, code_field)
            if _record_matches_excel_candidates(raw_code, set(price_rule_candidates(row.raw_code))):
                matched_excel_norms.add(row.norm_code)
                break

    excel_unmatched = [row.raw_code for row in excel_rows if row.norm_code not in matched_excel_norms]

    updated_record_ids: list[str] = []
    if updates and not dry_run:
        chunk_size = 100
        for start in range(0, len(updates), chunk_size):
            chunk = updates[start:start + chunk_size]
            updated_record_ids.extend(batch_update_records(api, app_token, table_id, chunk))

    if not dry_run:
        clear_price_compare_caches()

    logger.info(
        "pdd.xls migrate to feishu: excel=%d feishu=%d updated=%d unmatched=%d dry_run=%s",
        len(excel_rows),
        len(feishu_records),
        len(updated_codes),
        len(excel_unmatched),
        dry_run,
    )

    return {
        "success": True,
        "dry_run": dry_run,
        "table_id": table_id,
        "resolve_method": resolve_method,
        "excel_rows": len(excel_rows),
        "feishu_rows": len(feishu_records),
        "updated_count": len(updated_codes),
        "updated_codes": updated_codes[:50],
        "updated_record_ids": updated_record_ids,
        "excel_unmatched_codes": excel_unmatched[:50],
        "excel_unmatched_count": len(excel_unmatched),
        "feishu_missing_field_codes": feishu_missing_field_codes[:50],
    }


def _migrate_code_price_xls_to_feishu(
    *,
    excel_rows: list[ExcelCodePriceRow],
    feishu_price_field: str,
    dry_run: bool = False,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
    label: str = "code_price",
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    compare_cfg = cfg.pdd_price_compare
    if not compare_cfg.enabled:
        return {"skipped": True, "reason": "pdd_price_compare_disabled", "label": label}

    if not excel_rows:
        return {"failed": True, "reason": "excel_empty", "message": f"{label} Excel 无有效行", "label": label}

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        return {"failed": True, "reason": "feishu_not_configured", "label": label}

    api = client or FeishuClient(cfg)
    table_id, resolve_method = resolve_pdd_price_compare_table_id(cfg, api)
    if not table_id:
        return {
            "failed": True,
            "reason": "table_not_found",
            "message": f"未找到飞书表「{compare_cfg.table_name}」",
            "label": label,
        }

    names = compare_cfg.field_names
    code_field = resolve_table_field_name(api, app_token, table_id, names.merchant_code)

    excel_candidate_keys: set[str] = set()
    excel_by_norm: dict[str, ExcelCodePriceRow] = {}
    for row in excel_rows:
        excel_by_norm[row.norm_code] = row
        for key in price_rule_candidates(row.raw_code):
            excel_candidate_keys.add(key)

    feishu_records = list_all_records(api, app_token, table_id)
    updates: list[dict[str, Any]] = []
    updated_codes: list[str] = []

    for item in feishu_records:
        record_id = str(item.get("record_id") or "").strip()
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        if not raw_code or not record_id:
            continue
        if not _record_matches_excel_candidates(raw_code, excel_candidate_keys):
            continue

        norm = normalize_price_code(raw_code)
        excel_row = excel_by_norm.get(norm)
        if excel_row is None:
            for key in price_rule_candidates(raw_code):
                if key in excel_by_norm:
                    excel_row = excel_by_norm[key]
                    break
        if excel_row is None or excel_row.price <= 0:
            continue

        patch = {feishu_price_field: excel_row.price}
        mapped = map_fields_to_table_names(api, app_token, table_id, patch)
        updates.append({"record_id": record_id, "fields": mapped})
        updated_codes.append(raw_code)

    matched_excel_norms: set[str] = set()
    for row in excel_rows:
        for rec in feishu_records:
            fields = rec.get("fields") if isinstance(rec.get("fields"), dict) else {}
            raw_code = _field_text(fields, code_field)
            if _record_matches_excel_candidates(raw_code, set(price_rule_candidates(row.raw_code))):
                matched_excel_norms.add(row.norm_code)
                break

    excel_unmatched = [row.raw_code for row in excel_rows if row.norm_code not in matched_excel_norms]

    updated_record_ids: list[str] = []
    if updates and not dry_run:
        chunk_size = 100
        for start in range(0, len(updates), chunk_size):
            chunk = updates[start:start + chunk_size]
            updated_record_ids.extend(batch_update_records(api, app_token, table_id, chunk))

    logger.info(
        "%s migrate to feishu: excel=%d feishu=%d updated=%d unmatched=%d dry_run=%s",
        label,
        len(excel_rows),
        len(feishu_records),
        len(updated_codes),
        len(excel_unmatched),
        dry_run,
    )

    return {
        "success": True,
        "label": label,
        "dry_run": dry_run,
        "table_id": table_id,
        "resolve_method": resolve_method,
        "excel_rows": len(excel_rows),
        "feishu_rows": len(feishu_records),
        "updated_count": len(updated_codes),
        "updated_codes": updated_codes[:50],
        "updated_record_ids": updated_record_ids,
        "excel_unmatched_codes": excel_unmatched[:50],
        "excel_unmatched_count": len(excel_unmatched),
    }


def migrate_pricing_xls_to_feishu(
    *,
    dry_run: bool = False,
    excel_path: Path | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    rows = load_pricing_xls_rows(path=excel_path, config=cfg)
    return _migrate_code_price_xls_to_feishu(
        excel_rows=rows,
        feishu_price_field=cfg.pdd_price_compare.field_names.pdd_pricing,
        dry_run=dry_run,
        config=cfg,
        client=client,
        label="pricing",
    )


def migrate_control_xls_to_feishu(
    *,
    dry_run: bool = False,
    excel_path: Path | None = None,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    cfg = config or load_feishu_config()
    rows = load_control_xls_rows(path=excel_path, config=cfg)
    return _migrate_code_price_xls_to_feishu(
        excel_rows=rows,
        feishu_price_field=cfg.pdd_price_compare.field_names.pdd_control_price,
        dry_run=dry_run,
        config=cfg,
        client=client,
        label="control",
    )


def migrate_all_price_compare_excels(
    *,
    dry_run: bool = False,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> dict[str, Any]:
    """迁移 pdd.xls 控价区间 + 拼多多定价 + 拼多多控价 到飞书「拼多多比价定价」表。"""
    cfg = config or load_feishu_config()
    api = client or FeishuClient(cfg)
    range_result = migrate_pdd_xls_to_feishu(dry_run=dry_run, config=cfg, client=api)
    pricing_result = migrate_pricing_xls_to_feishu(dry_run=dry_run, config=cfg, client=api)
    control_result = migrate_control_xls_to_feishu(dry_run=dry_run, config=cfg, client=api)

    if not dry_run:
        clear_price_compare_caches()

    failed = [
        item
        for item in (range_result, pricing_result, control_result)
        if item.get("failed")
    ]
    return {
        "success": not failed,
        "dry_run": dry_run,
        "range": range_result,
        "pricing": pricing_result,
        "control": control_result,
        "failed_count": len(failed),
    }
