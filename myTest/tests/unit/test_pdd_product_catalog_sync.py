"""拼多多所有商品飞书同步与定价浮动测试。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.domain.models import ListingUnit
from pdd_agent.integrations.feishu.config import FeishuConfig, PddProductCatalogConfig, PddUploadLogConfig
from pdd_agent.integrations.feishu.pdd_product_catalog_sync import (
    _entry_from_feishu_fields,
    feishu_product_catalog_missing_message,
    load_unified_pdd_product_catalog,
    schedule_feishu_product_catalog_missing_logs,
)
from pdd_agent.integrations.feishu.config import PddProductCatalogFieldNames
from pdd_agent.skills.listing.listing_price_float import reset_listing_price_float_registry
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, resolve_combo_pricing


def test_entry_from_feishu_fields_maps_inventory_and_pricing():
    names = PddProductCatalogFieldNames()
    entry = _entry_from_feishu_fields(
        {
            names.product_code: "BD716A",
            names.color_spec: "灰色笔袋",
            names.product_type: "笔袋",
            names.available_inventory: 120,
            names.pricing: 20.5,
        },
        names,
    )
    assert entry == PddProductEntry("BD716A", "灰色笔袋", "笔袋", 120, 20.5)


def test_resolve_combo_pricing_shares_float_for_same_base_price():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "白色笔袋", "笔袋", 100, 1.0),
        "BD716B": PddProductEntry("BD716B", "黑色笔袋", "笔袋", 100, 1.0),
        "YKL001N": PddProductEntry("YKL001N", "A挂架", "亚克力", 50, 1.0),
    }
    reset_listing_price_float_registry(float_min=1.0, float_max=1.0, enabled=True)
    scope = "BD716/第一套图"

    _, white_gp, _ = resolve_combo_pricing("BD716A", "YKL001N", catalog, {}, listing_scope=scope)
    _, black_gp, _ = resolve_combo_pricing("BD716B", "YKL001N", catalog, {}, listing_scope=scope)

    assert white_gp == black_gp == "4"


def test_resolve_combo_pricing_uses_different_float_when_base_price_differs():
    catalog = {
        "BD716A": PddProductEntry("BD716A", "白色笔袋", "笔袋", 100, 1.0),
        "YKL001N": PddProductEntry("YKL001N", "A挂架", "亚克力", 50, 2.0),
    }
    reset_listing_price_float_registry(float_min=1.0, float_max=1.0, enabled=True)
    scope = "BD716/第一套图"

    _, gp, _ = resolve_combo_pricing("BD716A", "YKL001N", catalog, {}, listing_scope=scope)
    assert gp == "5"


def test_feishu_product_catalog_missing_message_includes_table_and_code():
    assert feishu_product_catalog_missing_message(table_name="拼多多所有商品", product_code="BD716A") == (
        "飞书拼多多所有商品没数据(BD716A)"
    )
    assert feishu_product_catalog_missing_message(table_name="拼多多所有商品") == "飞书拼多多所有商品没数据"


def test_schedule_feishu_product_catalog_missing_logs_writes_failure_rows(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_product_catalog_sync

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(enabled=True, failure_table_id="tbl_fail"),
        pdd_product_catalog=PddProductCatalogConfig(
            enabled=True,
            prefer_feishu=True,
            table_name="拼多多所有商品",
        ),
    )
    unit = ListingUnit(
        product_code="BD716A",
        family_code="BD716",
        image_set="第一套图",
        root=Path("."),
    )
    unit.style_codes = ["BD716A", "BD716B"]
    unit.model_codes = ["YKL001N"]

    monkeypatch.setattr(
        pdd_product_catalog_sync,
        "find_missing_feishu_product_codes",
        lambda codes, **kwargs: (["BD716A", "YKL001N"], "feishu_empty"),
    )
    captured: list[dict] = []

    def _fake_schedule(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_upload_sync.schedule_pdd_upload_failure_log",
        _fake_schedule,
    )

    logged = schedule_feishu_product_catalog_missing_logs(
        account_id="store_A",
        units=[unit],
        config=cfg,
    )
    assert logged == 2
    assert captured[0]["failure_reason"] == "飞书拼多多所有商品没数据(BD716A)"
    assert captured[0]["reason_code"] == "feishu_product_catalog_missing"
    assert captured[1]["failure_reason"] == "飞书拼多多所有商品没数据(YKL001N)"


def test_load_unified_pdd_product_catalog_falls_back_to_excel(monkeypatch, tmp_path):
    from pdd_agent.integrations.feishu import pdd_product_catalog_sync

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(
            enabled=True,
            prefer_feishu=True,
            fallback_excel=True,
        ),
    )
    monkeypatch.setattr(
        pdd_product_catalog_sync,
        "load_pdd_product_catalog_from_feishu",
        lambda **kwargs: pdd_product_catalog_sync.ProductCatalogLoadResult(catalog={}, source="feishu_empty"),
    )
    monkeypatch.setattr(
        pdd_product_catalog_sync,
        "load_pdd_product_catalog",
        lambda path: {"BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 10, 20.0)},
    )

    catalog = load_unified_pdd_product_catalog(
        excel_path=tmp_path / "mock.xls",
        config=cfg,
        force_refresh=True,
    )
    assert catalog["BD716A"].inventory == 10
    assert catalog["BD716A"].price == 20.0
