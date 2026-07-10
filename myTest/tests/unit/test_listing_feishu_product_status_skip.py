"""产品状态下架跳过：飞书查询与失败日志封装测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.config import FeishuConfig, PddProductCatalogConfig, PddProductCatalogFieldNames
from pdd_agent.integrations.feishu.listing_feishu_platform_guard import PLATFORM_SKIP_REASON
from pdd_agent.integrations.feishu import listing_feishu_product_status_skip as mod


def test_is_delisted_product_status():
    assert mod.is_delisted_product_status("下架")
    assert mod.is_delisted_product_status({"name": "下架"})
    assert not mod.is_delisted_product_status("现货")


def test_resolve_platform_skip_failure_reason():
    status_map = {"BD051D": "下架", "BD751A": "现货"}
    assert (
        mod.resolve_platform_skip_failure_reason("BD051D", status_by_code=status_map)
        == mod.DELISTED_PRODUCT_SKIP_REASON
    )
    assert (
        mod.resolve_platform_skip_failure_reason("BD751A", status_by_code=status_map)
        == PLATFORM_SKIP_REASON
    )


def test_enrich_platform_skip_items_with_delisted_status(monkeypatch):
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(
            field_names=PddProductCatalogFieldNames(product_status="产品状态"),
        ),
    )
    monkeypatch.setattr(
        mod,
        "lookup_product_status_by_merchant_codes",
        lambda codes, **kwargs: {"BD051D": "下架", "BD751A": "现货"},
    )

    items = [
        {
            "selector": "BD051/第一套图/BD051D",
            "merchant_code": "BD051D",
            "platform_listing_code": "BD051D",
            "error": PLATFORM_SKIP_REASON,
        },
        {
            "selector": "BD751/第一套图/BD751A",
            "merchant_code": "BD751A",
            "platform_listing_code": "BD751A",
            "error": PLATFORM_SKIP_REASON,
        },
    ]
    status_map = mod.enrich_platform_skip_items_with_delisted_status(items, config=cfg)
    assert status_map["BD051D"] == "下架"
    assert items[0]["error"] == mod.DELISTED_PRODUCT_SKIP_REASON
    assert items[1]["error"] == PLATFORM_SKIP_REASON


def test_schedule_platform_skip_feishu_failure_logs_dedupe_only_delisted(monkeypatch):
    scheduled: list[dict] = []

    def fake_schedule(**kwargs):
        scheduled.append(kwargs)

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_upload_sync.schedule_pdd_upload_failure_log",
        fake_schedule,
    )

    written = mod.schedule_platform_skip_feishu_failure_logs(
        account_id="store_A",
        account_name="店铺A",
        entries=[
            {
                "selector": "BD051/第一套图/BD051D",
                "merchant_code": "BD051D",
                "error": mod.DELISTED_PRODUCT_SKIP_REASON,
            },
            {
                "selector": "BD751/第一套图/BD751A",
                "merchant_code": "BD751A",
                "error": PLATFORM_SKIP_REASON,
            },
        ],
        status_by_code={"BD051D": "下架", "BD751A": "现货"},
        write_mode="dedupe",
    )
    assert written == 1
    assert scheduled[0]["failure_reason"] == mod.DELISTED_PRODUCT_SKIP_REASON
    assert scheduled[0]["record_type"] == "跳过"


def test_schedule_platform_skip_feishu_failure_logs_bag_view_always(monkeypatch):
    scheduled: list[dict] = []

    def fake_schedule(**kwargs):
        scheduled.append(kwargs)

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_upload_sync.schedule_pdd_upload_failure_log",
        fake_schedule,
    )

    written = mod.schedule_platform_skip_feishu_failure_logs(
        account_id="store_A",
        account_name="店铺A",
        entries=[
            {
                "selector": "BD051/第一套图/BD051D",
                "listing_label": "BD051D/第一套图",
                "merchant_code": "BD051D",
                "error": mod.DELISTED_PRODUCT_SKIP_REASON,
            },
            {
                "selector": "BD751/第一套图/BD751A",
                "listing_label": "BD751A/第一套图",
                "merchant_code": "BD751A",
                "error": PLATFORM_SKIP_REASON,
            },
        ],
        status_by_code={"BD051D": "下架", "BD751A": "现货"},
        write_mode="bag_view",
    )
    assert written == 2
    assert scheduled[0]["failure_reason"] == mod.DELISTED_PRODUCT_SKIP_REASON
    assert scheduled[0]["system_reason"] == "产品状态为下架：BD051D"
    assert scheduled[1]["failure_reason"] == PLATFORM_SKIP_REASON
    assert scheduled[1]["system_reason"] == "笔袋视图未找到：BD751A"


def test_lookup_product_status_by_merchant_codes(monkeypatch):
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_product_catalog=PddProductCatalogConfig(
            field_names=PddProductCatalogFieldNames(product_status="产品状态"),
        ),
    )

    class FakeClient:
        pass

    monkeypatch.setattr(
        mod,
        "resolve_pdd_price_compare_table_id",
        lambda *_args, **_kwargs: ("tbl_price", False),
    )
    monkeypatch.setattr(
        mod,
        "resolve_table_field_name",
        lambda api, app_token, table_id, field_name: field_name,
    )
    monkeypatch.setattr(
        mod,
        "search_records_by_field_values",
        lambda *_args, **_kwargs: [
            {
                "fields": {
                    "商品编码": "BD051D",
                    "产品状态": "下架",
                }
            }
        ],
    )
    monkeypatch.setattr(
        mod,
        "search_records_by_field_contains",
        lambda *_args, **_kwargs: [],
    )

    status_map = mod.lookup_product_status_by_merchant_codes(["BD051D"], config=cfg, client=FakeClient())
    assert status_map["BD051D"] == "下架"
