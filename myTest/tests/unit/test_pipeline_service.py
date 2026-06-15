"""整合链路服务单元测试。"""

from datetime import timedelta

from pdd_agent.api.services.pipeline_service import (
    DEMO_ACTIVITY_DELAY_MINUTES,
    _extract_listing_products,
    _resolve_activity_delay,
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
