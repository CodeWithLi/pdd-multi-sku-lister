from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.integrations.feishu.config import FeishuConfig, PddPriceCompareConfig, PddProductCatalogConfig
from pdd_agent.integrations.feishu.listing_feishu_platform_guard import ensure_codes_in_required_view


def _cfg() -> FeishuConfig:
    return FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_price_compare=PddPriceCompareConfig(
            enabled=True,
            prefer_feishu=True,
            listing_required_view_name="笔袋视图",
        ),
        pdd_product_catalog=PddProductCatalogConfig(enabled=True, prefer_feishu=True),
    )


def test_ensure_codes_in_required_view_hits_named_view(monkeypatch):
    cfg = _cfg()

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.resolve_pdd_price_compare_table_id",
        lambda cfg, api, save_table_id=False: ("tbl_x", "test"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.find_view_id_by_name",
        lambda api, app_token, table_id, name: "vew_bag",
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.resolve_table_field_name",
        lambda api, app_token, table_id, configured_name: configured_name,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.search_records_by_field_values",
        lambda *args, **kwargs: [{"fields": {"商品编码": "BD713A"}}],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.search_records_by_field_contains",
        lambda *args, **kwargs: [],
    )

    data = ensure_codes_in_required_view(["BD713A"], config=cfg, client=MagicMock())
    assert data["ok"] is True
    assert data["missing_codes"] == []
    assert data["items"][0]["matched"] is True
    assert data["items"][0]["matched_code"] == "BD713A"


def test_ensure_codes_in_required_view_marks_missing(monkeypatch):
    cfg = _cfg()

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.resolve_pdd_price_compare_table_id",
        lambda cfg, api, save_table_id=False: ("tbl_x", "test"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.find_view_id_by_name",
        lambda api, app_token, table_id, name: "vew_bag",
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.resolve_table_field_name",
        lambda api, app_token, table_id, configured_name: configured_name,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.search_records_by_field_values",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.search_records_by_field_contains",
        lambda *args, **kwargs: [],
    )

    data = ensure_codes_in_required_view(["BD713A"], config=cfg, client=MagicMock())
    assert data["ok"] is True
    assert data["missing_codes"] == ["BD713A"]
    assert data["items"][0]["matched"] is False
