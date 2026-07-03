"""飞书编码预热与商品表匹配回归测试。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.domain.models import ListingUnit
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


def test_product_catalog_reads_resolved_listing_pricing_field():
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
    snapshot._pricing_field = "拼多多定价"
    snapshot._listing_pricing_field = "拼多多定价+5元"
    snapshot._color_spec_field = "颜色规格"
    snapshot._product_type_field = "商品类型"
    snapshot._inventory_field = "可用库存"
    snapshot.records_by_code["BD029B"] = {
        "商品编码": "BD029B",
        "颜色规格": "笔袋",
        "商品类型": "笔袋",
        "可用库存": 10,
        "拼多多定价": 2.97,
        "拼多多定价+5元": 7.97,
    }
    catalog = snapshot.product_catalog(cfg)
    assert catalog["BD029B"].price == 7.97


def test_entry_from_feishu_fields_falls_back_color_spec():
    from pdd_agent.integrations.feishu.pdd_product_catalog_sync import _entry_from_feishu_fields
    from pdd_agent.integrations.feishu.config import PddProductCatalogFieldNames

    names = PddProductCatalogFieldNames()
    entry = _entry_from_feishu_fields(
        {
            "商品编码": "BD029B",
            "拼多多定价+5元": 7.97,
        },
        names,
        resolved_fields={
            "product_code": "商品编码",
            "pricing": "拼多多定价+5元",
            "color_spec": "颜色规格",
        },
    )
    assert entry is not None
    assert entry.code == "BD029B"
    assert entry.color_spec == "BD029B"
    assert entry.price == 7.97


def test_diagnose_reports_pricing_missing_when_only_raw_pdd_pricing_present(monkeypatch):
    """上架主价读「拼多多定价+5元」；仅有「拼多多定价」时仍应报定价缺失。"""
    from pdd_agent.integrations.feishu import pdd_product_catalog_sync
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import (
        ListingFeishuSnapshot,
        clear_listing_feishu_snapshot,
    )

    clear_listing_feishu_snapshot()

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(
            enabled=True,
            prefer_feishu=True,
        ),
        pdd_price_compare=PddPriceCompareConfig(
            enabled=True,
            prefer_feishu=True,
        ),
    )
    unit = ListingUnit(
        product_code="BD029B",
        family_code="BD029",
        image_set="第一套图",
        root=Path("."),
    )

    snapshot = ListingFeishuSnapshot(source="feishu")
    snapshot._code_field = "商品编码"
    snapshot._pricing_field = "拼多多定价"
    snapshot._listing_pricing_field = "拼多多定价+5元"
    snapshot._color_spec_field = "颜色规格"
    snapshot.records_by_code["BD029B"] = {
        "商品编码": "BD029B",
        "拼多多定价": 7.97,
    }
    from pdd_agent.integrations.feishu import listing_feishu_snapshot as snap_mod

    snap_mod._listing_snapshot.set(snapshot)

    class PricingCatalog:
        source = "feishu"
        prices = {"BD029B": 7.97}
        incomplete_codes = frozenset()
        feishu_record_codes = frozenset({"BD029B"})

    class ControlCatalog:
        source = "feishu"
        prices = {"BD029B": 7.97}
        incomplete_codes = frozenset()
        feishu_record_codes = frozenset({"BD029B"})

    class RangeCatalog:
        source = "feishu"
        ranges = {"BD029B": object()}
        incomplete_codes = frozenset()
        feishu_record_codes = frozenset({"BD029B"})

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.load_pricing_catalog",
        lambda **kwargs: PricingCatalog(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.load_control_catalog",
        lambda **kwargs: ControlCatalog(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.load_price_range_catalog",
        lambda **kwargs: RangeCatalog(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.resolve_feishu_range_aspect",
        lambda *_args, **_kwargs: None,
    )

    issues = pdd_product_catalog_sync.diagnose_feishu_listing_catalog_issues(units=[unit], config=cfg)
    assert len(issues) == 1
    assert issues[0].details[0].aspect == "pricing_missing"


def test_diagnose_fallback_uses_merchant_code_from_selector(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_product_catalog_sync
    from pdd_agent.integrations.feishu.listing_feishu_snapshot import clear_listing_feishu_snapshot

    clear_listing_feishu_snapshot()
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(
            enabled=True,
            prefer_feishu=True,
        ),
        pdd_price_compare=PddPriceCompareConfig(
            enabled=False,
            prefer_feishu=False,
        ),
    )

    captured: list[str] = []

    def _fake_load(**kwargs):
        captured.append("loaded")
        return pdd_product_catalog_sync.ProductCatalogLoadResult(
            catalog={"BD029B": PddProductEntry("BD029B", "笔袋", "笔袋", 10, 8.0)},
            source="feishu",
        )

    monkeypatch.setattr(pdd_product_catalog_sync, "load_pdd_product_catalog_from_feishu", _fake_load)

    issues = pdd_product_catalog_sync.diagnose_feishu_listing_catalog_issues(
        product_codes=["BD029/第一套图/BD029B"],
        config=cfg,
    )
    assert issues == []
    assert captured == ["loaded"]


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
