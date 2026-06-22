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
