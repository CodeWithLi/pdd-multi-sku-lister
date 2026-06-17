"""整合链路服务单元测试。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_service import (
    CAMPAIGN_TIME_REQUIREMENT_STEP,
    DEMO_ACTIVITY_DELAY_MINUTES,
    DEMO_ACTIVITY_JITTER_MAX_SECONDS,
    _activity_jitter_max_seconds,
    _build_multi_activity_detail,
    _campaign_time_requirement_message,
    _extract_listing_products,
    _is_campaign_time_requirement_failure,
    _merge_skipped_listing_products,
    _normalize_pipeline_activity_ids,
    _on_listing_finished,
    _on_limited_time_finished,
    _on_campaign_finished,
    _resolve_activity_delay,
    cancel_integrated_pipeline,
    on_queue_task_finished,
    resolve_activity_scheduled_at,
    resolve_batch_delay,
    resolve_published_products_for_pipeline,
    start_integrated_pipeline,
    start_integrated_pipeline_batch,
)
from pdd_agent.domain.enums import AgentKind, RunStatus


def test_extract_listing_products_from_success_results():
    result = {
        "results": [
            {"status": "success", "pdd_product_id": "965182969751", "mapping_id": "m1"},
            {"status": "failed", "pdd_product_id": "111"},
            {"status": "listed", "pdd_product_id": "222", "mapping_id": "m2"},
        ]
    }
    pdd_ids, mapping_ids = _extract_listing_products(result)
    assert pdd_ids == ["965182969751", "222"]
    assert mapping_ids == ["m1", "m2"]


def test_resolve_activity_delay_demo_mode():
    delta = _resolve_activity_delay(demo_mode=True, activity_delay_hours=24)
    assert delta == timedelta(minutes=DEMO_ACTIVITY_DELAY_MINUTES)


def test_resolve_activity_delay_production_mode():
    delta = _resolve_activity_delay(demo_mode=False, activity_delay_hours=24)
    assert delta == timedelta(hours=24)


def test_activity_jitter_max_seconds_demo_mode_capped():
    with patch("pdd_agent.api.services.pipeline_service.load_yaml_settings") as load_settings:
        load_settings.return_value.batch.activity_schedule_jitter_max_seconds = 3600
        assert _activity_jitter_max_seconds(demo_mode=True) == DEMO_ACTIVITY_JITTER_MAX_SECONDS


def test_resolve_activity_scheduled_at_without_jitter():
    fixed_now = datetime(2026, 6, 15, 10, 0, 0)
    with patch("pdd_agent.api.services.pipeline_service.datetime") as dt:
        dt.now.return_value = fixed_now
        dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        scheduled = resolve_activity_scheduled_at(
            demo_mode=False,
            activity_delay_hours=24,
            jitter_max_seconds=0,
        )
    assert scheduled == fixed_now + timedelta(hours=24)


def test_resolve_activity_scheduled_at_with_jitter():
    fixed_now = datetime(2026, 6, 15, 10, 0, 0)
    with patch("pdd_agent.api.services.pipeline_service.datetime") as dt:
        dt.now.return_value = fixed_now
        dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        with patch("pdd_agent.api.services.pipeline_service.random.randint", return_value=600):
            scheduled = resolve_activity_scheduled_at(
                demo_mode=False,
                activity_delay_hours=24,
                jitter_max_seconds=1800,
            )
    assert scheduled == fixed_now + timedelta(hours=24, seconds=600)


def test_resolve_batch_delay_normalizes_range():
    with patch("pdd_agent.api.services.pipeline_service.load_yaml_settings") as load_settings:
        load_settings.return_value.batch.store_start_delay_min_seconds = 30
        load_settings.return_value.batch.store_start_delay_max_seconds = 180
        assert resolve_batch_delay(60, 30) == (60, 60)


def test_start_integrated_pipeline_batch_staggers_listing_schedule():
    captured: list[datetime | None] = []

    def _fake_start(**kwargs):
        captured.append(kwargs.get("listing_scheduled_at"))
        idx = len(captured)
        return {
            "account_id": kwargs["account_id"],
            "pipeline_id": f"pipe_{idx}",
            "listing_run_id": f"run_{idx}",
        }

    with patch(
        "pdd_agent.api.services.pipeline_service.start_integrated_pipeline",
        side_effect=_fake_start,
    ):
        with patch("pdd_agent.api.services.pipeline_service.resolve_batch_delay", return_value=(10, 10)):
            with patch("pdd_agent.api.services.pipeline_service.random.randint", return_value=10):
                with patch("pdd_agent.api.services.pipeline_service._batch_id", return_value="batch_test"):
                    result = start_integrated_pipeline_batch(
                        items=[
                            {"account_id": "store_A", "product_codes": ["BD720/第一套图/BD720A"]},
                            {"account_id": "store_B", "product_codes": ["BD720/第一套图/BD720A"]},
                        ],
                        activity_id="20981",
                    )

    assert result["batch_id"] == "batch_test"
    assert result["total"] == 2
    assert len(captured) == 2
    assert captured[0] is not None
    assert captured[1] is not None
    assert captured[1] == captured[0] + timedelta(seconds=10)


def test_cancel_integrated_pipeline_marks_canceled_and_stops_queue_tasks():
    row = SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        status="waiting_activity",
        current_step="waiting_activity",
        product_codes=[],
        activity_id="20981",
        auto_promotion=True,
        activity_delay_hours=24.0,
        demo_mode=False,
        meta={},
        listing_run_id="listing_run",
        campaign_run_id="campaign_run",
        traffic_run_id="",
        pdd_product_ids=[],
        mapping_ids=[],
        scheduled_activity_at=None,
        error="",
        created_at=None,
        updated_at=None,
    )
    updated_row = SimpleNamespace(**{**row.__dict__, "status": "canceled", "current_step": "canceled", "error": "用户取消"})
    worker = MagicMock()
    worker.cancel_run_ids.return_value = ["campaign_run"]

    with patch(
        "pdd_agent.api.services.pipeline_service.get_integrated_pipeline",
        side_effect=[row, updated_row],
    ):
        with patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline") as update:
            with patch("pdd_agent.api.app.worker", worker):
                with patch("pdd_agent.api.services.pipeline_service.TaskRunStore") as store_cls:
                    store = store_cls.return_value
                    store.load.side_effect = lambda run_id: SimpleNamespace(
                        status=RunStatus.SUCCESS if run_id == "listing_run" else RunStatus.PENDING
                    )
                    result = cancel_integrated_pipeline("pipe_1")

    worker.cancel_run_ids.assert_called_once_with(["listing_run", "campaign_run"])
    update.assert_called_once_with(
        "pipe_1",
        status="canceled",
        current_step="canceled",
        error="用户取消",
    )
    assert result["status"] == "canceled"


def test_on_queue_task_finished_ignores_canceled_pipeline():
    row = SimpleNamespace(
        pipeline_id="pipe_1",
        status="canceled",
        campaign_run_id="",
        traffic_run_id="",
        auto_promotion=True,
        demo_mode=False,
        activity_delay_hours=24,
        activity_id="20981",
        account_id="store_A",
        pdd_product_ids=[],
        mapping_ids=[],
    )
    with patch("pdd_agent.api.services.pipeline_service.get_integrated_pipeline", return_value=row):
        with patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline") as update:
            on_queue_task_finished(
                agent=AgentKind.LISTING.value,
                pipeline_id="pipe_1",
                run_id="listing_run",
                success=True,
                result={"results": [{"status": "success", "pdd_product_id": "123"}]},
            )
    update.assert_not_called()


def test_resolve_published_products_for_pipeline():
    row = SimpleNamespace(
        pdd_product_id="966914511094",
        mapping_id="map_1",
        status="on_sale",
    )
    with patch(
        "pdd_agent.api.services.pipeline_service.get_published_product",
        return_value=row,
    ):
        pdd_ids, mapping_ids, missing = resolve_published_products_for_pipeline(
            "store_A",
            ["BD713/第一套图/BD713A"],
        )
    assert pdd_ids == ["966914511094"]
    assert mapping_ids == ["map_1"]
    assert missing == []


def test_start_integrated_pipeline_skip_listing_schedules_activity():
    row = SimpleNamespace(
        pipeline_id="pipe_skip",
        account_id="store_A",
        product_codes=["BD713/第一套图/BD713A"],
        activity_id="20981",
        auto_promotion=True,
        demo_mode=True,
        activity_delay_hours=24,
        listing_run_id="listing_run",
        meta={},
    )
    listing_result = {
        "results": [{"status": "success", "pdd_product_id": "966914511094", "mapping_id": "map_1"}],
        "listing_skipped": True,
    }
    with patch("pdd_agent.api.services.pipeline_service.create_listing_run", return_value="listing_run"):
        with patch("pdd_agent.api.services.pipeline_service.create_integrated_pipeline", return_value=row):
            with patch("pdd_agent.api.services.pipeline_service._mark_listing_skipped_success", return_value=listing_result):
                with patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline"):
                    with patch("pdd_agent.api.services.pipeline_service._on_listing_finished") as on_listing:
                        with patch(
                            "pdd_agent.api.services.pipeline_service.get_integrated_pipeline",
                            return_value=row,
                        ):
                            with patch("pdd_agent.api.services.pipeline_service.pipeline_to_dict", return_value={"pipeline_id": "pipe_skip", "status": "waiting_activity"}):
                                result = start_integrated_pipeline(
                                    account_id="store_A",
                                    product_codes=["BD713/第一套图/BD713A"],
                                    activity_id="20981",
                                    skip_listing=True,
                                )
    on_listing.assert_called_once()
    assert result["status"] == "waiting_activity"


def test_start_integrated_pipeline_partial_listing_skip_enqueues_unlisted_only():
    row = SimpleNamespace(
        pipeline_id="pipe_partial",
        account_id="store_A",
        product_codes=["BD720/第一套图/BD720A", "BD720/第一套图/BD720B"],
        activity_id="20981",
        auto_promotion=True,
        demo_mode=True,
        activity_delay_hours=24,
        listing_run_id="listing_run",
        meta={},
    )
    with patch("pdd_agent.api.services.pipeline_service.create_listing_run", return_value="listing_run"):
        with patch("pdd_agent.api.services.pipeline_service.create_integrated_pipeline", return_value=row):
            with patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline"):
                with patch("pdd_agent.api.services.pipeline_service.enqueue_task") as enqueue:
                    with patch(
                        "pdd_agent.api.services.pipeline_service.get_integrated_pipeline",
                        return_value=row,
                    ):
                        with patch(
                            "pdd_agent.api.services.pipeline_service.pipeline_to_dict",
                            return_value={"pipeline_id": "pipe_partial", "status": "running"},
                        ):
                            start_integrated_pipeline(
                                account_id="store_A",
                                product_codes=["BD720/第一套图/BD720A", "BD720/第一套图/BD720B"],
                                activity_id="20981",
                                listing_skip_selectors=["BD720/第一套图/BD720A"],
                            )
    enqueue.assert_called_once()
    payload = enqueue.call_args.kwargs["payload"]
    assert payload["product_codes"] == ["BD720/第一套图/BD720B"]


def test_merge_skipped_listing_products():
    row = SimpleNamespace(
        account_id="store_A",
        meta={"listing_skip_selectors": ["BD720/第一套图/BD720A"]},
    )
    with patch(
        "pdd_agent.api.services.pipeline_service.resolve_published_products_for_pipeline",
        return_value=(["966914511094"], ["map_1"], []),
    ):
        pdd_ids, mapping_ids, missing = _merge_skipped_listing_products(
            row,
            pdd_ids=["111"],
            mapping_ids=["map_new"],
        )
    assert pdd_ids == ["111", "966914511094"]
    assert mapping_ids == ["map_new", "map_1"]
    assert missing == []


def test_normalize_pipeline_activity_ids_dedupes_and_preserves_order():
    assert _normalize_pipeline_activity_ids("20981", ["21365", "20981"]) == ["21365", "20981"]
    assert _normalize_pipeline_activity_ids("20981", []) == ["20981"]


def test_build_multi_activity_detail_lists_each_activity():
    row = SimpleNamespace(
        pipeline_id="pipe_multi",
        activity_id="20981",
        campaign_run_id="run_2",
        scheduled_activity_at=None,
        meta={
            "activity_ids": ["20981", "21365"],
            "campaign_activity_index": 1,
            "campaign_results": [
                {
                    "activity_id": "20981",
                    "run_id": "run_1",
                    "success": True,
                    "skipped": False,
                    "summary": "报名成功",
                }
            ],
        },
    )
    detail = _build_multi_activity_detail(row, campaign_status="running")
    assert "1/2 20981：成功" in detail
    assert "2/2 21365：进行中" in detail


def test_on_campaign_finished_schedules_second_activity_before_traffic():
    row = SimpleNamespace(
        pipeline_id="pipe_multi",
        account_id="store_A",
        status="running",
        auto_promotion=True,
        pdd_product_ids=["111"],
        mapping_ids=["m1"],
        activity_id="20981",
        campaign_run_id="run_1",
        meta={
            "activity_ids": ["20981", "21365"],
            "campaign_activity_index": 0,
            "campaign_results": [],
        },
    )
    with patch("pdd_agent.api.services.pipeline_service._summarize_run_message", return_value="ok"):
        with patch("pdd_agent.api.services.pipeline_service._schedule_pipeline_campaign") as schedule:
            with patch("pdd_agent.api.services.pipeline_service._enqueue_pipeline_traffic") as enqueue_traffic:
                _on_campaign_finished(
                    row,
                    run_id="run_1",
                    success=True,
                    result={"results": [{"status": "success"}]},
                    error="",
                )
    schedule.assert_called_once()
    assert schedule.call_args.kwargs["activity_index"] == 1
    enqueue_traffic.assert_not_called()


def test_on_campaign_finished_runs_traffic_after_last_activity():
    row = SimpleNamespace(
        pipeline_id="pipe_multi",
        account_id="store_A",
        status="running",
        auto_promotion=True,
        pdd_product_ids=["111"],
        mapping_ids=["m1"],
        activity_id="21365",
        campaign_run_id="run_2",
        meta={
            "activity_ids": ["20981", "21365"],
            "campaign_activity_index": 1,
            "campaign_results": [
                {
                    "activity_id": "20981",
                    "run_id": "run_1",
                    "success": True,
                    "skipped": False,
                    "summary": "ok",
                }
            ],
        },
    )
    with patch("pdd_agent.api.services.pipeline_service._summarize_run_message", return_value="ok"):
        with patch("pdd_agent.api.services.pipeline_service._schedule_pipeline_campaign") as schedule:
            with patch("pdd_agent.api.services.pipeline_service.get_integrated_pipeline", return_value=row):
                with patch("pdd_agent.api.services.pipeline_service._enqueue_pipeline_traffic") as enqueue_traffic:
                    _on_campaign_finished(
                        row,
                        run_id="run_2",
                        success=True,
                        result={"results": [{"status": "success"}]},
                        error="",
                    )
    schedule.assert_not_called()
    enqueue_traffic.assert_called_once()


def test_is_campaign_time_requirement_failure_detects_step():
    result = {
        "results": [
            {
                "status": "failed",
                "step": CAMPAIGN_TIME_REQUIREMENT_STEP,
                "error": "当前商品未满足时间要求，已取消报名：123（需等待1天）",
            }
        ]
    }
    assert _is_campaign_time_requirement_failure(result, "")
    assert "未满足时间要求" in _campaign_time_requirement_message(result, "")


def test_on_campaign_finished_skips_to_traffic_when_time_requirement_not_met():
    row = SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        status="waiting_activity",
        auto_promotion=True,
        pdd_product_ids=["965182969751"],
        mapping_ids=["m1"],
        activity_id="20981",
        meta={"activity_ids": ["20981"], "campaign_activity_index": 0, "campaign_results": []},
    )
    result = {
        "results": [
            {
                "status": "failed",
                "step": CAMPAIGN_TIME_REQUIREMENT_STEP,
                "error": "当前商品未满足时间要求，已取消报名",
            }
        ]
    }

    with patch("pdd_agent.api.services.pipeline_service._summarize_run_message", return_value="time blocked"):
        with patch("pdd_agent.api.services.pipeline_service._enqueue_pipeline_traffic") as enqueue_traffic:
            with patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline") as update:
                _on_campaign_finished(
                    row,
                    run_id="campaign_run",
                    success=False,
                    result=result,
                    error="",
                )

    enqueue_traffic.assert_called_once()
    update.assert_not_called()


def test_on_campaign_finished_skips_to_traffic_when_product_not_eligible():
    row = SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        status="waiting_activity",
        auto_promotion=True,
        pdd_product_ids=["966914511094"],
        mapping_ids=["m1"],
        activity_id="20981",
        meta={"activity_ids": ["20981"], "campaign_activity_index": 0, "campaign_results": []},
    )
    result = {
        "results": [
            {
                "status": "failed",
                "step": "product_not_eligible_for_activity",
                "error": "部分商品不可报名活动，已取消操作：966914511094",
            }
        ],
        "errors": ["部分商品不可报名活动，已取消操作：966914511094"],
    }

    with patch("pdd_agent.api.services.pipeline_service._summarize_run_message", return_value="not eligible"):
        with patch("pdd_agent.api.services.pipeline_service._enqueue_pipeline_traffic") as enqueue_traffic:
            with patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline") as update:
                _on_campaign_finished(
                    row,
                    run_id="campaign_run",
                    success=False,
                    result=result,
                    error="部分商品不可报名活动，已取消操作：966914511094",
                )

    enqueue_traffic.assert_called_once()
    update.assert_not_called()


def test_on_campaign_finished_still_fails_on_other_campaign_errors():
    row = SimpleNamespace(
        pipeline_id="pipe_1",
        account_id="store_A",
        status="waiting_activity",
        auto_promotion=True,
        pdd_product_ids=["965182969751"],
        mapping_ids=["m1"],
        activity_id="20981",
        meta={"activity_ids": ["20981"], "campaign_activity_index": 0, "campaign_results": []},
    )

    with patch("pdd_agent.api.services.pipeline_service._enqueue_pipeline_traffic") as enqueue_traffic:
        with patch("pdd_agent.api.services.pipeline_service.update_integrated_pipeline") as update:
            _on_campaign_finished(
                row,
                run_id="campaign_run",
                success=False,
                result={"results": [{"status": "failed", "step": "filter_activity_prices"}]},
                error="价格确认页筛选失败",
            )

    enqueue_traffic.assert_not_called()
    update.assert_called_once()
    assert update.call_args.args[0] == "pipe_1"
    assert update.call_args.kwargs["status"] == "failed"
    assert update.call_args.kwargs["current_step"] == "activity_failed"
    assert update.call_args.kwargs["error"] == "价格确认页筛选失败"


def test_on_listing_finished_queues_limited_time_before_activity():
    row = SimpleNamespace(
        pipeline_id="pipe_lt",
        account_id="store_A",
        demo_mode=True,
        activity_delay_hours=24,
        activity_id="20981",
        meta={"activity_ids": ["20981"]},
    )
    with patch("pdd_agent.api.services.pipeline_service._summarize_run_message", return_value="listed"):
        with patch("pdd_agent.api.services.pipeline_service._enqueue_pipeline_limited_time") as enqueue_lt:
            with patch("pdd_agent.api.services.pipeline_service._schedule_pipeline_campaign") as schedule:
                with patch("pdd_agent.api.services.pipeline_service.datetime") as dt:
                    fixed_now = datetime(2026, 6, 17, 10, 0, 0)
                    dt.now.return_value = fixed_now
                    dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
                    _on_listing_finished(
                        row,
                        run_id="listing_run",
                        success=True,
                        result={
                            "results": [
                                {"status": "success", "pdd_product_id": "111", "mapping_id": "m1"},
                            ]
                        },
                        error="",
                    )
    enqueue_lt.assert_called_once()
    assert enqueue_lt.call_args.kwargs["pdd_ids"] == ["111"]
    assert enqueue_lt.call_args.kwargs["scheduled_at"] == fixed_now + timedelta(seconds=5)
    schedule.assert_not_called()


def test_on_limited_time_finished_schedules_activity():
    row = SimpleNamespace(
        pipeline_id="pipe_lt",
        account_id="store_A",
        demo_mode=True,
        activity_delay_hours=24,
        activity_id="20981",
        pdd_product_ids=["111"],
        mapping_ids=["m1"],
        meta={"activity_ids": ["20981"], "limited_time_run_id": "lt_run"},
    )
    with patch("pdd_agent.api.services.pipeline_service._summarize_run_message", return_value="ok"):
        with patch("pdd_agent.api.services.pipeline_service.get_integrated_pipeline", return_value=row):
            with patch(
                "pdd_agent.api.services.pipeline_service._schedule_pipeline_activity_after_limited_time"
            ) as schedule_activity:
                _on_limited_time_finished(
                    row,
                    run_id="lt_run",
                    success=True,
                    result={"results": [{"status": "success"}]},
                    error="",
                )
    schedule_activity.assert_called_once()

