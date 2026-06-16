"""整合链路服务单元测试。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_service import (
    DEMO_ACTIVITY_DELAY_MINUTES,
    DEMO_ACTIVITY_JITTER_MAX_SECONDS,
    _activity_jitter_max_seconds,
    _extract_listing_products,
    _resolve_activity_delay,
    cancel_integrated_pipeline,
    on_queue_task_finished,
    resolve_activity_scheduled_at,
    resolve_batch_delay,
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

