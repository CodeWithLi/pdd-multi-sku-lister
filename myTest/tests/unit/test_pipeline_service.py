"""整合链路服务单元测试。"""

from datetime import datetime, timedelta
from unittest.mock import patch

from pdd_agent.api.services.pipeline_service import (
    DEMO_ACTIVITY_DELAY_MINUTES,
    DEMO_ACTIVITY_JITTER_MAX_SECONDS,
    _activity_jitter_max_seconds,
    _extract_listing_products,
    _resolve_activity_delay,
    resolve_activity_scheduled_at,
    resolve_batch_delay,
    start_integrated_pipeline_batch,
)


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

