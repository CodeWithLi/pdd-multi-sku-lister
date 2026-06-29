"""失败日志循环上架每日统计单元测试。"""

from unittest.mock import patch

from pdd_agent.api.services.daily_cycle_relist_service import record_cycle_relist_pipeline_started


def test_record_cycle_relist_skips_when_not_ok():
    with patch(
        "pdd_agent.api.services.daily_cycle_relist_service.create_daily_cycle_relist_record"
    ) as create_fn:
        record_cycle_relist_pipeline_started({"ok": False, "pipeline_id": "p1"})
        create_fn.assert_not_called()


def test_record_cycle_relist_creates_on_pipeline_started():
    outcome = {
        "ok": True,
        "skipped": False,
        "record_id": "recABC",
        "account_id": "store_A",
        "merchant_code": "BD046A",
        "pipeline_id": "pipe_123",
        "product_codes": ["BD046/第一套/BD046A"],
        "report_platform": "拼多多",
    }
    with patch(
        "pdd_agent.api.services.daily_cycle_relist_service.create_daily_cycle_relist_record"
    ) as create_fn:
        with patch(
            "pdd_agent.api.services.daily_cycle_relist_service.resolve_account_display_name",
            return_value="兔兔潮玩屋",
        ):
            record_cycle_relist_pipeline_started(outcome, trigger_source="auto_watch")
    create_fn.assert_called_once()
    kwargs = create_fn.call_args.kwargs
    assert kwargs["pipeline_id"] == "pipe_123"
    assert kwargs["feishu_record_id"] == "recABC"
    assert kwargs["shop_display_name"] == "兔兔潮玩屋"
    assert kwargs["trigger_source"] == "auto_watch"
