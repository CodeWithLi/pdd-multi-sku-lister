from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pdd_agent.api.services.listing_preflight_feishu_bridge import (
    sync_preflight_failures_to_feishu,
)
from pdd_agent.domain.listing_errors import ListingErrorCode
from pdd_agent.domain.models import ListingUnit, PreflightIssue, PreflightReport, SkuCombo


def _unit(product_code: str = "BD070A", image_set: str = "第一套图") -> ListingUnit:
    return ListingUnit(
        product_code=product_code,
        image_set=image_set,
        root=Path("D:/tmp"),
        skus=[
            SkuCombo(
                style_code=product_code,
                style_name="测试款式",
                model_code="YKL001A",
                model_name="测试型号",
                combo_folder=f"{product_code}+YKL001A",
                preview_image=Path("D:/tmp/preview.png"),
            )
        ],
    )


@patch("pdd_agent.api.services.listing_preflight_feishu_bridge.schedule_negative_inventory_skip_feishu_log")
@patch("pdd_agent.api.services.listing_preflight_feishu_bridge.evaluate_negative_inventory_guard")
@patch("pdd_agent.api.services.listing_preflight_feishu_bridge.resolve_account_display_name")
def test_sync_preflight_failures_to_feishu_for_negative_inventory(
    mock_display_name,
    mock_guard,
    mock_schedule,
):
    unit = _unit()
    report = PreflightReport(
        units=[unit],
        issues=[
            PreflightIssue(
                level="error",
                listing_label=unit.listing_label,
                reason_code=ListingErrorCode.NEGATIVE_INVENTORY_SKIP,
                message="BD070A可用库存小于0，跳过该商品上架",
            )
        ],
    )
    mock_display_name.return_value = "咕噜咕噜时尚店"
    mock_guard.return_value = SimpleNamespace(blocked=True, codes=["BD070A"], system_reason="BD070A聚水潭可用数=-1")

    synced = sync_preflight_failures_to_feishu(account_id="store_A", report=report)

    assert synced == 1
    mock_schedule.assert_called_once()
    kwargs = mock_schedule.call_args.kwargs
    assert kwargs["account_id"] == "store_A"
    assert kwargs["account_name"] == "咕噜咕噜时尚店"
    assert kwargs["unit"].listing_label == "BD070A/第一套图"


@patch("pdd_agent.api.services.listing_preflight_feishu_bridge.schedule_negative_inventory_skip_feishu_log")
def test_sync_preflight_failures_to_feishu_ignores_other_reasons(mock_schedule):
    unit = _unit()
    report = PreflightReport(
        units=[unit],
        issues=[
            PreflightIssue(
                level="error",
                listing_label=unit.listing_label,
                reason_code=ListingErrorCode.SPEC_FILL_VERIFY_FAILED,
                message="规格校验填表未通过",
            )
        ],
    )

    synced = sync_preflight_failures_to_feishu(account_id="store_A", report=report)

    assert synced == 0
    mock_schedule.assert_not_called()


@patch("pdd_agent.api.services.listing_preflight_feishu_bridge.schedule_zero_inventory_skip_feishu_log")
@patch("pdd_agent.api.services.listing_preflight_feishu_bridge.evaluate_zero_inventory_guard")
@patch("pdd_agent.api.services.listing_preflight_feishu_bridge.resolve_account_display_name")
def test_sync_preflight_failures_to_feishu_for_zero_inventory(
    mock_display_name,
    mock_guard,
    mock_schedule,
):
    unit = _unit()
    report = PreflightReport(
        units=[unit],
        issues=[
            PreflightIssue(
                level="error",
                listing_label=unit.listing_label,
                reason_code=ListingErrorCode.ZERO_INVENTORY_SKIP,
                message="库存为0，跳过该商品上架",
            )
        ],
    )
    mock_display_name.return_value = "咕噜咕噜时尚店"
    mock_guard.return_value = SimpleNamespace(
        blocked=True,
        failure_message="BD070A库存为0，跳过该商品上架",
        system_reason="BD070A聚水潭可用数=0",
    )

    synced = sync_preflight_failures_to_feishu(account_id="store_A", report=report)

    assert synced == 1
    mock_schedule.assert_called_once()
    kwargs = mock_schedule.call_args.kwargs
    assert kwargs["account_id"] == "store_A"
    assert kwargs["account_name"] == "咕噜咕噜时尚店"
    assert kwargs["unit"].listing_label == "BD070A/第一套图"
