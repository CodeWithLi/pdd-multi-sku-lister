from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.integrations.feishu.config import FeishuConfig, PddPriceCompareConfig, PddProductCatalogConfig
from pdd_agent.integrations.feishu.listing_feishu_platform_guard import (
    check_product_folders_in_bag_view,
    extract_product_folder_name,
)


def _cfg() -> FeishuConfig:
    return FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_price_compare=PddPriceCompareConfig(
            enabled=True,
            prefer_feishu=True,
            listing_required_view_name="笔袋",
            listing_required_view_id="vew_bag",
        ),
        pdd_product_catalog=PddProductCatalogConfig(enabled=True, prefer_feishu=True),
    )


def test_extract_product_folder_name_from_selector():
    assert extract_product_folder_name("BD739/第一套图/BD739A") == "BD739A"
    assert extract_product_folder_name("BD739A") == "BD739A"


def test_check_product_folders_in_bag_view_hits(monkeypatch):
    cfg = _cfg()

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.resolve_pdd_price_compare_table_id",
        lambda cfg, api, save_table_id=False: ("tbl_x", "test"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.resolve_table_field_name",
        lambda api, app_token, table_id, configured_name: configured_name,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard._load_view_records",
        lambda *args, **kwargs: [{"fields": {"商品编码": "BD713A"}}],
    )

    data = check_product_folders_in_bag_view(["BD713A"], config=cfg, client=MagicMock())
    assert data["skipped"] is False
    assert data["missing_codes"] == []
    assert data["items"][0]["matched"] is True
    assert data["items"][0]["matched_code"] == "BD713A"


def test_check_product_folders_in_bag_view_marks_missing(monkeypatch):
    cfg = _cfg()

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.resolve_pdd_price_compare_table_id",
        lambda cfg, api, save_table_id=False: ("tbl_x", "test"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard.resolve_table_field_name",
        lambda api, app_token, table_id, configured_name: configured_name,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.listing_feishu_platform_guard._load_view_records",
        lambda *args, **kwargs: [{"fields": {"商品编码": "BD999A"}}],
    )

    data = check_product_folders_in_bag_view(["BD713A"], config=cfg, client=MagicMock())
    assert data["skipped"] is False
    assert data["missing_codes"] == ["BD713A"]
    assert data["items"][0]["matched"] is False
