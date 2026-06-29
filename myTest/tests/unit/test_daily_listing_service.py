"""每日上架记录服务单元测试。"""

from unittest.mock import patch

from pdd_agent.api.services.daily_listing_service import record_daily_listing_from_item


def test_record_daily_listing_skips_non_success():
    with patch("pdd_agent.api.services.daily_listing_service.create_daily_listing_record") as create_fn:
        record_daily_listing_from_item(
            "run-1",
            "store_A",
            {"status": "failed", "pdd_product_id": "123", "product_code": "BD046A"},
        )
        create_fn.assert_not_called()


def test_record_daily_listing_creates_on_success():
    item = {
        "status": "success",
        "pdd_product_id": "99887766",
        "product_code": "BD046A",
        "family_code": "BD046",
        "image_set": "第一套",
        "listing_label": "BD046A/第一套",
        "merchant_code": "BD046A",
        "title": "测试商品",
        "spec_metadata": {"root": "/data/assets/BD046/第一套/BD046A"},
    }
    with patch("pdd_agent.api.services.daily_listing_service.create_daily_listing_record") as create_fn:
        with patch(
            "pdd_agent.api.services.daily_listing_service.resolve_listing_source_meta",
            return_value=("listing", ""),
        ):
            with patch(
                "pdd_agent.api.services.daily_listing_service.resolve_account_display_name",
                return_value="兔兔潮玩屋",
            ):
                record_daily_listing_from_item("run-1", "store_A", item)
    create_fn.assert_called_once()
    kwargs = create_fn.call_args.kwargs
    assert kwargs["account_id"] == "store_A"
    assert kwargs["shop_display_name"] == "兔兔潮玩屋"
    assert kwargs["pdd_product_id"] == "99887766"
    assert kwargs["product_code"] == "BD046A"
    assert kwargs["title"] == "测试商品"
    assert kwargs["source_run_id"] == "run-1"
