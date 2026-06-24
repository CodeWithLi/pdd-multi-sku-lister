"""拼多多所有商品飞书同步与定价浮动测试。"""

from __future__ import annotations

from pathlib import Path

from pdd_agent.domain.models import ListingUnit
from pdd_agent.integrations.feishu.config import FeishuConfig, PddProductCatalogConfig, PddUploadLogConfig, PddPriceCompareConfig, PipelineIntegrationConfig
from pdd_agent.integrations.feishu.pdd_product_catalog_sync import (
    FeishuCatalogIssueDetail,
    FeishuListingCatalogIssue,
    _entry_from_feishu_fields,
    feishu_product_catalog_missing_message,
    format_feishu_catalog_issue_detail_message,
    format_feishu_listing_catalog_issue_message,
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


def test_feishu_product_catalog_missing_message_includes_code():
    assert feishu_product_catalog_missing_message(product_code="BD716A") == "BD716A飞书无此行"


def test_format_feishu_catalog_issue_detail_message():
    reason, msg = format_feishu_catalog_issue_detail_message(
        listing_label="BD034B/第一套图",
        code="BD034B",
        merchant_code="BD034B",
        aspect="pricing_missing",
    )
    assert reason == "feishu_pricing_missing"
    assert msg == "BD034B定价为空"

    reason, msg = format_feishu_catalog_issue_detail_message(
        listing_label="BD034B/第一套图",
        code="YKL001N",
        merchant_code="BD034B",
        aspect="subcode_missing",
    )
    assert reason == "feishu_subcode_missing"
    assert msg == "BD034B缺YKL001N"

    reason, msg = format_feishu_catalog_issue_detail_message(
        listing_label="BD034B/第一套图",
        code="YKL001N",
        merchant_code="BD034B",
        aspect="control_missing",
    )
    assert reason == "feishu_subcode_control_missing"
    assert msg == "YKL001N控价为空"


def test_format_feishu_listing_catalog_issue_message():
    issue = FeishuListingCatalogIssue(
        listing_label="BD716A/第一套图",
        merchant_code="BD716A",
        code_details=(
            ("BD716A", ("商品表没数据",)),
            ("YKL001N", ("定价没数据", "控价没数据")),
        ),
        details=(
            FeishuCatalogIssueDetail(
                code="BD716A",
                reason_code="feishu_pricing_missing",
                message="失败: BD716A/第一套图: 定价数据缺失",
                aspect="pricing_missing",
            ),
        ),
    )
    assert format_feishu_listing_catalog_issue_message(issue) == "失败: BD716A/第一套图: 定价数据缺失"


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
        "diagnose_feishu_listing_catalog_issues",
        lambda **kwargs: [
            FeishuListingCatalogIssue(
                listing_label="BD716A/第一套图",
                merchant_code="BD716A",
                code_details=(("BD716A", ("定价没数据",)), ("YKL001N", ("控价没数据",))),
                details=(
                    FeishuCatalogIssueDetail(
                        code="BD716A",
                        reason_code="feishu_pricing_missing",
                        message="失败: BD716A/第一套图: 定价数据缺失",
                        aspect="pricing_missing",
                    ),
                    FeishuCatalogIssueDetail(
                        code="YKL001N",
                        reason_code="feishu_subcode_control_missing",
                        message="BD716A/第一套图：子编码 YKL001N 控价数据缺失",
                        aspect="control_missing",
                    ),
                ),
            )
        ],
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
    assert logged == 1
    assert captured[0]["message"] == "1、BD716A定价为空，2、YKL001N控价为空"
    assert captured[0]["reason_code"] == "feishu_subcode_control_missing"
    assert captured[0]["merchant_code"] == "BD716A"


def test_diagnose_feishu_listing_catalog_issues_marks_missing_fields(monkeypatch):
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
            enabled=True,
            prefer_feishu=True,
        ),
    )
    unit = ListingUnit(
        product_code="BD716A",
        family_code="BD716",
        image_set="第一套图",
        root=Path("."),
    )
    unit.style_codes = ["BD716A"]
    unit.model_codes = ["YKL001N"]

    class PricingCatalog:
        source = "feishu"
        prices = {}
        incomplete_codes = frozenset()
        feishu_record_codes = frozenset()

    class ControlCatalog:
        source = "feishu"
        prices = {}
        incomplete_codes = frozenset({"YKL001N"})
        feishu_record_codes = frozenset({"YKL001N"})

    class RangeCatalog:
        source = "feishu"
        ranges = {}
        incomplete_codes = frozenset()
        feishu_record_codes = frozenset()

    monkeypatch.setattr(
        pdd_product_catalog_sync,
        "load_pdd_product_catalog_from_feishu",
        lambda **kwargs: pdd_product_catalog_sync.ProductCatalogLoadResult(
            catalog={"BD716A": PddProductEntry("BD716A", "灰色笔袋", "笔袋", 10, 0.0)},
            source="feishu",
        ),
    )
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
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.is_feishu_price_data_missing",
        lambda catalog, candidates: False,
    )

    issues = pdd_product_catalog_sync.diagnose_feishu_listing_catalog_issues(units=[unit], config=cfg)
    assert len(issues) == 1
    assert issues[0].merchant_code == "BD716A"
    assert issues[0].listing_label == "BD716A/第一套图"
    details = dict(issues[0].code_details)
    assert "拼多多定价没数据" in details["BD716A"]
    assert "拼多多控价没数据" in details["YKL001N"]
    messages = [item.message for item in issues[0].details]
    assert "BD716A定价为空" in messages
    assert "YKL001N控价为空" in messages


def test_load_unified_pdd_product_catalog_falls_back_to_excel(monkeypatch, tmp_path):
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
            fallback_excel=True,
        ),
        pipeline=PipelineIntegrationConfig(excel_fallback_enabled=True),
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
