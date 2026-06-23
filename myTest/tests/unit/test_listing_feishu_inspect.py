"""飞书定价读取诊断测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.integrations.feishu.config import FeishuConfig, PddPriceCompareConfig, PddProductCatalogConfig
from pdd_agent.integrations.feishu.listing_feishu_inspect import (
    _merchant_code_from_selector,
    inspect_listing_feishu_prices,
)


def test_merchant_code_from_selector():
    assert _merchant_code_from_selector("BD025A面包小狗笔袋") == "BD025A面包小狗笔袋"
    assert _merchant_code_from_selector("BD021/第一套图/BD021A") == "BD021A"
    assert _merchant_code_from_selector("BD021A/第一套图") == "BD021A"


def test_inspect_listing_feishu_prices(monkeypatch):
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(enabled=True, prefer_feishu=True),
        pdd_price_compare=PddPriceCompareConfig(enabled=True, prefer_feishu=True),
    )

    def fake_warm(codes, **kwargs):
        from pdd_agent.integrations.feishu.listing_feishu_snapshot import (
            ListingFeishuSnapshot,
            get_listing_feishu_snapshot,
        )

        snapshot = get_listing_feishu_snapshot() or ListingFeishuSnapshot()
        for code in codes:
            snapshot.records_by_code[code] = {
                "商品编码": code,
                "拼多多定价": 8.3,
                "拼多多控价": 7.45,
                "PDD控价下限价格": 7.45,
                "PDD控价上限价格": 9.3,
            }
        from pdd_agent.integrations.feishu import listing_feishu_snapshot as mod

        mod._listing_snapshot.set(snapshot)
        return snapshot

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_snapshot.warm_listing_feishu_snapshot",
        fake_warm,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.cache.clear_feishu_data_caches",
        lambda **kwargs: {"cleared": []},
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_inspect._search_feishu_rows_for_code",
        lambda **kwargs: [
            {
                "record_id": "rec1",
                "fields": {
                    "商品编码": kwargs["query_code"],
                    "拼多多定价": 8.3,
                    "拼多多控价": 7.45,
                    "PDD控价下限价格": 7.45,
                    "PDD控价上限价格": 9.3,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_inspect.resolve_pdd_price_compare_table_id",
        lambda *args, **kwargs: ("tbl_x", "test"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_inspect._resolve_price_range_field_names",
        lambda *args, **kwargs: ("商品编码", "PDD控价下限价格", "PDD控价上限价格"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.bitable.resolve_table_field_name",
        lambda *args, **kwargs: args[3] if len(args) > 3 else "",
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.client.FeishuClient",
        lambda cfg: MagicMock(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_inspect.load_pricing_catalog",
        lambda **kwargs: type("C", (), {"source": "feishu", "prices": {"BD025A面包小狗笔袋": 8.3}, "incomplete_codes": frozenset(), "feishu_record_codes": frozenset({"BD025A面包小狗笔袋"})})(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_inspect.load_control_catalog",
        lambda **kwargs: type("C", (), {"source": "feishu", "prices": {"BD025A面包小狗笔袋": 7.45}, "incomplete_codes": frozenset(), "feishu_record_codes": frozenset({"BD025A面包小狗笔袋"})})(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_inspect.load_price_range_catalog",
        lambda **kwargs: type(
            "R",
            (),
            {
                "source": "feishu",
                "ranges": {
                    "BD025A面包小狗笔袋": type(
                        "Rule",
                        (),
                        {"min_price": 7.45, "max_price": 9.3},
                    )()
                },
                "incomplete_min_codes": frozenset(),
                "incomplete_max_codes": frozenset(),
                "feishu_record_codes": frozenset({"BD025A面包小狗笔袋"}),
            },
        )(),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_inspect.diagnose_feishu_listing_catalog_issues",
        lambda **kwargs: [],
    )

    result = inspect_listing_feishu_prices(["BD025A面包小狗笔袋"], force_refresh=False, config=cfg)
    assert result["codes"] == ["BD025A面包小狗笔袋"]
    assert result["items"][0]["parsed"]["PDD控价上限价格"] == "9.3"
    assert result["items"][0]["feishu_row_count"] == 1
