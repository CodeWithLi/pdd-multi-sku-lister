"""飞书编码预热与商品表匹配回归测试。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    PddProductCatalogConfig,
    PddProductCatalogFieldNames,
    PddPriceCompareConfig,
)
from pdd_agent.integrations.feishu.listing_feishu_catalog import (
    collect_merchant_codes_from_selectors,
    merchant_code_from_selector,
)
from pdd_agent.integrations.feishu.listing_feishu_snapshot import ListingFeishuSnapshot
from pdd_agent.skills.listing.catalog import collect_feishu_catalog_codes_for_targets
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry, resolve_combo_pricing


def test_merchant_code_from_two_part_selector():
    assert merchant_code_from_selector("BD029A卡皮巴拉笔袋/第一套图") == "BD029A卡皮巴拉笔袋"
    assert merchant_code_from_selector("BD029B/第一套图") == "BD029B"


def test_collect_merchant_codes_from_selectors():
    codes = collect_merchant_codes_from_selectors(
        ["BD029A卡皮巴拉笔袋/第一套图", "BD029B/第一套图", "BD029C/第一套图"]
    )
    assert codes == ["BD029A卡皮巴拉笔袋", "BD029B", "BD029C"]


def test_collect_feishu_catalog_codes_includes_family_without_assets(tmp_path: Path):
    codes = collect_feishu_catalog_codes_for_targets(
        ["BD029B/第一套图"],
        tmp_path,
    )
    assert "BD029B" in codes


def test_product_catalog_reads_resolved_pricing_field():
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(
            field_names=PddProductCatalogFieldNames(),
        ),
        pdd_price_compare=PddPriceCompareConfig(),
    )
    snapshot = ListingFeishuSnapshot()
    snapshot._code_field = "商品编码"
    snapshot._pricing_field = "定价列"
    snapshot._color_spec_field = "颜色规格"
    snapshot._product_type_field = "商品类型"
    snapshot._inventory_field = "可用库存"
    snapshot.records_by_code["BD029B"] = {
        "商品编码": "BD029B",
        "颜色规格": "笔袋",
        "商品类型": "笔袋",
        "可用库存": 10,
        "定价列": 7.97,
    }
    catalog = snapshot.product_catalog(cfg)
    assert catalog["BD029B"].price == 7.97


def test_resolve_combo_pricing_exact_catalog_key(monkeypatch):
    from pdd_agent.skills.listing import listing_price_float as float_mod

    monkeypatch.setattr(
        float_mod,
        "get_listing_price_float_registry",
        lambda: float_mod.ListingPriceFloatRegistry(enabled=False),
    )
    catalog = {
        "BD029A卡皮巴拉笔袋": PddProductEntry(
            code="BD029A卡皮巴拉笔袋",
            color_spec="卡皮巴拉",
            product_type="笔袋",
            inventory=10,
            price=8.5,
        )
    }
    inv, gp, sp = resolve_combo_pricing(
        "BD029A卡皮巴拉笔袋",
        "BD029A卡皮巴拉笔袋",
        catalog,
        {},
        listing_scope="BD029A卡皮巴拉笔袋/第一套图",
    )
    assert inv == "10"
    assert gp == "8.5"

    try:
        resolve_combo_pricing("BD029A", "BD029A", catalog, {})
    except Exception as exc:
        assert "BD029A" in str(exc)
    else:
        raise AssertionError("short code must not match full catalog key")
