"""上架任务内按商品编码读取飞书「拼多多比价定价」表，同一次上架只拉需要的行。"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.feishu.bitable import (
    resolve_table_field_name,
    search_records_by_field_contains,
    search_records_by_field_values,
)
from pdd_agent.integrations.feishu.client import FeishuClient
from pdd_agent.integrations.feishu.config import FeishuConfig, load_feishu_config
from pdd_agent.integrations.feishu.pdd_product_catalog_sync import _entry_from_feishu_fields
from pdd_agent.integrations.feishu.listing_feishu_catalog import (
    feishu_snapshot_alias_allowed,
    normalize_listing_code,
)
from pdd_agent.integrations.feishu.pdd_price_compare_sync import (
    CodePriceCatalog,
    PriceRangeCatalog,
    _build_catalog_from_feishu_records,
    _build_code_price_catalog_from_feishu_records,
    _field_text,
    _resolve_price_range_field_names,
    _row_price_fields_score,
    resolve_pdd_price_compare_table_id,
)
from pdd_agent.skills.campaign.price_rules import price_rule_candidates
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, _norm_code

logger = get_logger(__name__)


@dataclass
class ListingFeishuSnapshot:
    """单次上架任务内缓存的飞书比价定价行（按商品编码）。"""

    source: str = "feishu"
    records_by_code: dict[str, dict[str, Any]] = field(default_factory=dict)
    queried_codes: set[str] = field(default_factory=set)
    _code_field: str = ""
    _pricing_field: str = ""
    _control_field: str = ""
    _min_field: str = ""
    _max_field: str = ""
    _retail_cost_field: str = ""
    _color_spec_field: str = ""
    _product_type_field: str = ""
    _inventory_field: str = ""

    def record_items(self) -> list[dict[str, Any]]:
        return [{"fields": fields} for fields in self.records_by_code.values()]

    def pending_codes(self, codes: list[str]) -> list[str]:
        pending: list[str] = []
        for raw in codes:
            code = normalize_listing_code(raw)
            if code and code not in self.queried_codes:
                pending.append(code)
        return list(dict.fromkeys(pending))

    def mark_queried(self, codes: list[str]) -> None:
        for raw in codes:
            code = normalize_listing_code(raw)
            if code:
                self.queried_codes.add(code)

    def product_catalog(self, cfg: FeishuConfig) -> dict[str, PddProductEntry]:
        names = cfg.pdd_product_catalog.field_names
        resolved_fields = {
            "product_code": self._code_field or names.product_code,
            "color_spec": self._color_spec_field or names.color_spec,
            "product_type": self._product_type_field or names.product_type,
            "available_inventory": self._inventory_field or names.available_inventory,
            "pricing": self._pricing_field or names.pricing,
        }
        catalog: dict[str, PddProductEntry] = {}
        for code, fields in self.records_by_code.items():
            row = dict(fields)
            code_field = resolved_fields["product_code"]
            row[names.product_code] = _field_text(row, code_field) or code
            entry = _entry_from_feishu_fields(row, names, resolved_fields=resolved_fields)
            if entry:
                catalog[entry.code] = entry
        return catalog

    def pricing_catalog(self, cfg: FeishuConfig) -> CodePriceCatalog:
        if not self._code_field:
            return CodePriceCatalog(source=self.source)
        return _build_code_price_catalog_from_feishu_records(
            self.record_items(),
            code_field=self._code_field,
            price_field=self._pricing_field or cfg.pdd_price_compare.field_names.pdd_pricing,
        )

    def control_catalog(self, cfg: FeishuConfig) -> CodePriceCatalog:
        if not self._code_field:
            return CodePriceCatalog(source=self.source)
        return _build_code_price_catalog_from_feishu_records(
            self.record_items(),
            code_field=self._code_field,
            price_field=self._control_field or cfg.pdd_price_compare.field_names.pdd_control_price,
        )

    def range_catalog(self, cfg: FeishuConfig) -> PriceRangeCatalog:
        if not self._code_field:
            return PriceRangeCatalog(source=self.source)
        names = cfg.pdd_price_compare.field_names
        return _build_catalog_from_feishu_records(
            self.record_items(),
            code_field=self._code_field,
            min_field=self._min_field or names.min_price,
            max_field=self._max_field or names.max_price,
            retail_cost_field=self._retail_cost_field or names.retail_cost,
        )


_listing_snapshot: ContextVar[ListingFeishuSnapshot | None] = ContextVar(
    "listing_feishu_snapshot",
    default=None,
)


def get_listing_feishu_snapshot() -> ListingFeishuSnapshot | None:
    return _listing_snapshot.get()


def init_listing_feishu_snapshot() -> None:
    _listing_snapshot.set(ListingFeishuSnapshot())


def clear_listing_feishu_snapshot() -> None:
    _listing_snapshot.set(None)


def warm_listing_feishu_snapshot(
    codes: list[str],
    *,
    config: FeishuConfig | None = None,
    client: FeishuClient | None = None,
) -> ListingFeishuSnapshot | None:
    """按商品编码增量拉取飞书行；同一次上架复用同一快照。"""
    cfg = config or load_feishu_config()
    cat_cfg = cfg.pdd_product_catalog
    price_cfg = cfg.pdd_price_compare
    if not (cat_cfg.enabled and cat_cfg.prefer_feishu) and not (
        price_cfg.enabled and price_cfg.prefer_feishu
    ):
        return get_listing_feishu_snapshot()

    pending = list(dict.fromkeys(normalize_listing_code(c) for c in codes if normalize_listing_code(c)))
    if not pending:
        return get_listing_feishu_snapshot()

    snapshot = get_listing_feishu_snapshot()
    if snapshot is None:
        snapshot = ListingFeishuSnapshot()
        _listing_snapshot.set(snapshot)

    to_fetch = snapshot.pending_codes(pending)
    if not to_fetch:
        return snapshot

    app_token = str(cfg.bitable_app_token or "").strip()
    if not app_token or not cfg.app_id or not cfg.app_secret:
        snapshot.source = "feishu_not_configured"
        snapshot.mark_queried(to_fetch)
        return snapshot

    api = client or FeishuClient(cfg)
    table_id, _ = resolve_pdd_price_compare_table_id(cfg, api, save_table_id=False)
    if not table_id:
        snapshot.source = "feishu_table_missing"
        snapshot.mark_queried(to_fetch)
        return snapshot

    names = cfg.pdd_product_catalog.field_names
    compare_names = cfg.pdd_price_compare.field_names
    code_field, min_field, max_field, retail_cost_field = _resolve_price_range_field_names(
        api, app_token, table_id, compare_names
    )
    snapshot._code_field = code_field
    snapshot._pricing_field = resolve_table_field_name(
        api, app_token, table_id, compare_names.pdd_pricing
    )
    snapshot._control_field = resolve_table_field_name(
        api, app_token, table_id, compare_names.pdd_control_price
    )
    snapshot._min_field = min_field
    snapshot._max_field = max_field
    snapshot._retail_cost_field = retail_cost_field
    snapshot._color_spec_field = resolve_table_field_name(
        api, app_token, table_id, names.color_spec
    )
    snapshot._product_type_field = resolve_table_field_name(
        api, app_token, table_id, names.product_type
    )
    snapshot._inventory_field = resolve_table_field_name(
        api, app_token, table_id, names.available_inventory
    )

    try:
        records = search_records_by_field_values(
            api,
            app_token,
            table_id,
            field_name=code_field,
            values=to_fetch,
        )
    except Exception:
        logger.exception("search feishu price compare rows failed codes=%s", to_fetch)
        snapshot.mark_queried(to_fetch)
        return snapshot

    def _store_record(item: dict[str, Any], *, aliases: list[str] | None = None) -> str | None:
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        raw_code = _field_text(fields, code_field)
        norm = normalize_listing_code(raw_code)
        if not norm:
            return None
        row = dict(fields)
        new_score = _row_price_fields_score(
            row,
            min_field=min_field,
            max_field=max_field,
            pricing_field=snapshot._pricing_field,
            control_field=snapshot._control_field,
        )
        keys_to_store: list[str] = [norm]
        keys_to_store.extend(normalize_listing_code(key) for key in price_rule_candidates(raw_code) if key)
        for alias in aliases or []:
            alias_key = normalize_listing_code(alias)
            if alias_key:
                keys_to_store.append(alias_key)
        keys_to_store = list(dict.fromkeys(key for key in keys_to_store if key))

        existing_scores = [
            _row_price_fields_score(
                snapshot.records_by_code[key],
                min_field=min_field,
                max_field=max_field,
                pricing_field=snapshot._pricing_field,
                control_field=snapshot._control_field,
            )
            for key in keys_to_store
            if key in snapshot.records_by_code
        ]
        if existing_scores and new_score <= max(existing_scores):
            return norm

        for key in keys_to_store:
            snapshot.records_by_code[key] = row
        return norm

    found: set[str] = set()
    for item in records:
        norm = _store_record(item)
        if norm:
            found.add(norm)

    still_missing = [code for code in to_fetch if code not in found]
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
            logger.exception("fuzzy search feishu price compare rows failed codes=%s", still_missing)
            fuzzy_records = []
        missing_set = set(still_missing)
        for item in fuzzy_records:
            fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
            raw_code = _field_text(fields, code_field)
            matched_keys = [key for key in price_rule_candidates(raw_code) if key in missing_set]
            if not matched_keys:
                for pending in still_missing:
                    if feishu_snapshot_alias_allowed(pending, raw_code):
                        matched_keys.append(pending)
            if not matched_keys:
                continue
            norm = _store_record(item, aliases=matched_keys)
            if norm:
                found.add(norm)
                found.update(matched_keys)

    snapshot.mark_queried(to_fetch)
    snapshot.source = "feishu" if snapshot.records_by_code else "feishu_empty"
    logger.info(
        "feishu listing snapshot warmed requested=%s fetched_rows=%s unique_codes=%s",
        len(to_fetch),
        len(records),
        len(found),
    )
    return snapshot
