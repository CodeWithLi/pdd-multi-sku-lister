"""套图上架结果索引与笔袋视图跳过合并。"""

from __future__ import annotations

from pdd_agent.api.services.pipeline_listing_unit_results import (
    build_bag_view_skip_result_item,
    build_bag_view_skip_result_items,
    canonical_listing_unit_label,
    classify_listing_unit_pipeline_status,
    compose_all_skipped_listing_run_result,
    index_listing_result_items,
    merge_skip_results_into_listing_payload,
    resolve_listing_result_item,
)


def test_canonical_listing_unit_label_from_three_part_selector():
    assert canonical_listing_unit_label("BD757/第一套图/BD757A") == "BD757A/第一套图"


def test_index_and_resolve_three_part_result_with_two_part_selector():
    items = [
        {
            "listing_label": "BD757/第一套图/BD757A",
            "status": "skipped",
            "reason": "platform_not_applicable",
        }
    ]
    index = index_listing_result_items(items)
    item = resolve_listing_result_item(index, "BD757/第一套图/BD757A")
    assert item is not None
    assert item["status"] == "skipped"
    assert resolve_listing_result_item(index, "BD757A/第一套图") is item


def test_classify_skipped_platform_not_applicable_as_platform_skip_dedupe():
    status, reason = classify_listing_unit_pipeline_status(
        {"status": "skipped", "reason": "platform_not_applicable"}
    )
    assert status == "platform_skip_dedupe"
    assert reason == "platform_not_applicable"


def test_build_bag_view_skip_result_item_uses_canonical_label():
    item = build_bag_view_skip_result_item(
        selector="BD695/第一套图/BD695D",
        folder="BD695D",
    )
    assert item["listing_label"] == "BD695D/第一套图"
    assert item["reason"] == "platform_not_applicable"


def test_compose_all_skipped_merges_dedupe_and_bag_view():
    result = compose_all_skipped_listing_run_result(
        dedupe_skipped_results=[
            {
                "status": "skipped",
                "reason": "platform_skip_dedupe",
                "listing_label": "BD999A/第一套图",
            }
        ],
        bag_view_skipped_results=build_bag_view_skip_result_items(
            missing_selectors=["BD757/第一套图/BD757A"],
            folder_by_selector={"BD757/第一套图/BD757A": "BD757A"},
        ),
    )
    labels = {item["listing_label"] for item in result["results"]}
    assert labels == {"BD999A/第一套图", "BD757A/第一套图"}


def test_merge_skip_results_prefers_graph_result_over_skip():
    payload = merge_skip_results_into_listing_payload(
        {
            "results": [
                {
                    "listing_label": "BD987A/第一套图",
                    "status": "success",
                    "pdd_product_id": "123",
                }
            ]
        },
        bag_view_skipped_results=build_bag_view_skip_result_items(
            missing_selectors=["BD987/第一套图/BD987A"],
            folder_by_selector={"BD987/第一套图/BD987A": "BD987A"},
        ),
    )
    assert len(payload["results"]) == 1
    assert payload["results"][0]["pdd_product_id"] == "123"


def test_merge_skip_results_appends_missing_bag_view_skips():
    payload = merge_skip_results_into_listing_payload(
        {
            "results": [
                {
                    "listing_label": "BD987A/第一套图",
                    "status": "success",
                    "pdd_product_id": "123",
                }
            ]
        },
        bag_view_skipped_results=build_bag_view_skip_result_items(
            missing_selectors=["BD997/第一套图/BD997S"],
            folder_by_selector={"BD997/第一套图/BD997S": "BD997S"},
        ),
    )
    labels = {item["listing_label"] for item in payload["results"]}
    assert labels == {"BD987A/第一套图", "BD997S/第一套图"}


def test_index_pipeline_listing_skip_records():
    from pdd_agent.api.services.pipeline_listing_unit_results import (
        index_pipeline_listing_skip_records,
        resolve_listing_result_item,
    )

    index = index_pipeline_listing_skip_records(
        [
            {
                "skip_kind": "bag_view_missing",
                "product_selector": "BD997/第一套图/BD997S",
                "merchant_code": "BD997S",
                "listing_label": "BD997/第一套图/BD997S",
                "message": "笔袋视图未找到",
            }
        ]
    )
    item = resolve_listing_result_item(index, "BD997S/第一套图")
    assert item is not None
    assert item["reason"] == "platform_not_applicable"
