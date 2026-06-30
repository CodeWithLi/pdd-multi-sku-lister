"""pipeline_activity_limited_time_success 单元测试。"""

from __future__ import annotations

from pdd_agent.api.services.pipeline_activity_limited_time_success import (
    extract_limited_time_success_products,
    is_activity_limited_time_success_only,
)


def test_extract_success_from_activity_created_with_kept_ids():
    result = {
        "results": [
            {
                "status": "success",
                "step": "activity_created",
                "price_filter": {"kept_product_ids": ["111", "222"]},
                "selected_pdd_product_ids": ["111", "222", "333"],
            }
        ]
    }
    extract = extract_limited_time_success_products(
        result,
        account_id="store_a",
        fallback_pdd_ids=["111", "222", "333"],
        fallback_mapping_ids=["m1", "m2", "m3"],
    )
    assert extract.pdd_product_ids == ["111", "222"]
    assert extract.source == "limited_time_success"


def test_extract_empty_when_limited_time_failed():
    result = {
        "results": [
            {
                "status": "failed",
                "step": "campaign_price_filter",
                "price_filter": {"kept_product_ids": ["111"]},
            }
        ],
        "errors": ["活动价格不符合价格区间"],
    }
    extract = extract_limited_time_success_products(
        result,
        account_id="store_a",
        fallback_pdd_ids=["111", "222"],
    )
    assert extract.pdd_product_ids == []
    assert extract.source == "none"


def test_meta_flag():
    assert is_activity_limited_time_success_only({"activity_limited_time_success_only": True})
    assert not is_activity_limited_time_success_only({"activity_limited_time_success_only": False})
    assert not is_activity_limited_time_success_only({})
