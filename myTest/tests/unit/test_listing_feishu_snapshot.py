from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.integrations.feishu.config import FeishuConfig, PddProductCatalogConfig, PddPriceCompareConfig
from pdd_agent.integrations.feishu.listing_feishu_snapshot import (
    clear_listing_feishu_snapshot,
    get_listing_feishu_snapshot,
    init_listing_feishu_snapshot,
    warm_listing_feishu_snapshot,
)


def test_warm_listing_feishu_snapshot_fetches_each_code_once(monkeypatch):
    clear_listing_feishu_snapshot()
    init_listing_feishu_snapshot()

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(enabled=True, prefer_feishu=True),
        pdd_price_compare=PddPriceCompareConfig(enabled=True, prefer_feishu=True),
    )

    calls: list[list[str]] = []

    def fake_search(client, app_token, table_id, *, field_name, values, **kwargs):
        calls.append(list(values))
        return [
            {
                "fields": {
                    "商品编码": code,
                    "颜色规格": "灰色笔袋",
                    "商品类型": "笔袋",
                    "可用库存": 10,
                    "拼多多定价": 20.0,
                    "拼多多控价": 18.0,
                    "PDD控价下限价格": 15.0,
                    "PDD控价上限价格": 25.0,
                    "综合零售成本": 10.0,
                }
            }
            for code in values
        ]

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.search_records_by_field_values",
        fake_search,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.resolve_pdd_price_compare_table_id",
        lambda cfg, api, save_table_id=False: ("tbl_x", "test"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot._resolve_price_range_field_names",
        lambda api, app_token, table_id, names: ("商品编码", "PDD控价下限价格", "PDD控价上限价格", "综合零售成本"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.resolve_table_field_name",
        lambda client, app_token, table_id, name: name,
    )

    warm_listing_feishu_snapshot(["BD716A", "YKL001N"], config=cfg, client=MagicMock())
    warm_listing_feishu_snapshot(["BD716A", "BD716B"], config=cfg, client=MagicMock())

    assert len(calls) == 2
    assert calls[0] == ["BD716A", "YKL001N"]
    assert calls[1] == ["BD716B"]

    snapshot = get_listing_feishu_snapshot()
    assert snapshot is not None
    catalog = snapshot.product_catalog(cfg)
    assert "BD716A" in catalog
    assert "YKL001N" in catalog
    assert "BD716B" in catalog
    assert snapshot.pricing_catalog(cfg).prices.get("BD716A") == 20.0
    assert snapshot.control_catalog(cfg).prices.get("YKL001N") == 18.0
    assert snapshot.range_catalog(cfg).ranges.get("BD716A") is not None

    clear_listing_feishu_snapshot()


def test_feishu_snapshot_alias_allowed_blocks_short_row_for_long_pending():
    from pdd_agent.integrations.feishu.listing_feishu_catalog import feishu_snapshot_alias_allowed

    assert feishu_snapshot_alias_allowed("BD032A", "BD032A樱桃蛋糕笔袋")
    assert not feishu_snapshot_alias_allowed("BD025A面包小狗笔袋", "BD025A")
    assert feishu_snapshot_alias_allowed("BD025A面包小狗笔袋", "BD025A面包小狗笔袋")


def test_warm_listing_feishu_snapshot_fuzzy_matches_code_prefix(monkeypatch):
    clear_listing_feishu_snapshot()
    init_listing_feishu_snapshot()

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(enabled=True, prefer_feishu=True),
        pdd_price_compare=PddPriceCompareConfig(enabled=True, prefer_feishu=True),
    )

    def fake_exact(client, app_token, table_id, *, field_name, values, **kwargs):
        return []

    def fake_contains(client, app_token, table_id, *, field_name, values, **kwargs):
        return [
            {
                "fields": {
                    "商品编码": "BD032A樱桃蛋糕笔袋",
                    "颜色规格": "粉色",
                    "商品类型": "笔袋",
                    "可用库存": 10,
                    "拼多多定价": 10.0,
                    "拼多多控价": 9.0,
                    "PDD控价下限价格": 9.7,
                    "PDD控价上限价格": 11.0,
                    "综合零售成本": 2.0,
                }
            }
        ]

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.search_records_by_field_values",
        fake_exact,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.search_records_by_field_contains",
        fake_contains,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.resolve_pdd_price_compare_table_id",
        lambda cfg, api, save_table_id=False: ("tbl_x", "test"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot._resolve_price_range_field_names",
        lambda api, app_token, table_id, names: ("商品编码", "PDD控价下限价格", "PDD控价上限价格", "综合零售成本"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.resolve_table_field_name",
        lambda client, app_token, table_id, name: name,
    )

    warm_listing_feishu_snapshot(["BD032A"], config=cfg, client=MagicMock())

    snapshot = get_listing_feishu_snapshot()
    assert snapshot is not None
    assert "BD032A樱桃蛋糕笔袋" in snapshot.records_by_code
    assert snapshot.product_catalog(cfg)["BD032A樱桃蛋糕笔袋"].color_spec == "粉色"
    assert snapshot.range_catalog(cfg).ranges.get("BD032A樱桃蛋糕笔袋") is not None

    clear_listing_feishu_snapshot()


def test_warm_snapshot_short_incomplete_row_does_not_poison_long_code(monkeypatch):
    clear_listing_feishu_snapshot()
    init_listing_feishu_snapshot()

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(enabled=True, prefer_feishu=True),
        pdd_price_compare=PddPriceCompareConfig(enabled=True, prefer_feishu=True),
    )

    def fake_exact(client, app_token, table_id, *, field_name, values, **kwargs):
        return []

    def fake_contains(client, app_token, table_id, *, field_name, values, **kwargs):
        return [
            {
                "fields": {
                    "商品编码": "BD025A",
                    "PDD控价下限价格": 7.45,
                    "PDD控价上限价格": None,
                    "综合零售成本": None,
                }
            },
            {
                "fields": {
                    "商品编码": "BD025A面包小狗笔袋",
                    "颜色规格": "黄色",
                    "拼多多定价": 8.3,
                    "拼多多控价": 7.45,
                    "PDD控价下限价格": 7.45,
                    "PDD控价上限价格": 9.3,
                    "综合零售成本": 2.0,
                }
            },
        ]

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.search_records_by_field_values",
        fake_exact,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.search_records_by_field_contains",
        fake_contains,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.resolve_pdd_price_compare_table_id",
        lambda cfg, api, save_table_id=False: ("tbl_x", "test"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot._resolve_price_range_field_names",
        lambda api, app_token, table_id, names: ("商品编码", "PDD控价下限价格", "PDD控价上限价格", "综合零售成本"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.resolve_table_field_name",
        lambda client, app_token, table_id, name: name,
    )

    warm_listing_feishu_snapshot(["BD025A面包小狗笔袋"], config=cfg, client=MagicMock())

    snapshot = get_listing_feishu_snapshot()
    assert snapshot is not None
    row = snapshot.records_by_code.get("BD025A面包小狗笔袋")
    assert row is not None
    assert row["PDD控价上限价格"] == 9.3
    assert snapshot.range_catalog(cfg).ranges.get("BD025A面包小狗笔袋") is not None
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import resolve_feishu_range_aspect

    assert resolve_feishu_range_aspect(snapshot.range_catalog(cfg), ["BD025A面包小狗笔袋"]) is None

    clear_listing_feishu_snapshot()
