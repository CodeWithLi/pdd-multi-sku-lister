"""整合链路 — 已上架商品处理策略单元测试。"""

from unittest.mock import MagicMock, patch

import pytest

from pdd_agent.api.services.pipeline_relist_strategy import (
    build_pipeline_listing_plan,
    finalize_relist_prep_after_delist,
    normalize_relist_strategy,
    resolve_listing_flags_for_strategy,
    validate_relist_strategy_for_start,
)


def test_normalize_relist_strategy_defaults_to_ignore():
    assert normalize_relist_strategy(None) == "ignore"
    assert normalize_relist_strategy("unknown") == "ignore"
    assert normalize_relist_strategy("delist_and_relist") == "delist_and_relist"


def test_validate_append_to_existing_raises():
    with pytest.raises(ValueError, match="尚未实现"):
        validate_relist_strategy_for_start("append_to_existing")


def test_resolve_listing_flags_for_delist_and_relist():
    skip, selectors = resolve_listing_flags_for_strategy(
        "delist_and_relist",
        skip_listing=True,
        listing_skip_selectors=["BD713/第一套/BD713A"],
    )
    assert skip is False
    assert selectors == []


def test_build_pipeline_listing_plan_relist_prep_when_on_sale():
    fake_row = MagicMock()
    fake_row.status = "on_sale"
    fake_row.mapping_id = "map-1"
    fake_row.pdd_product_id = "123456"

    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.get_published_product",
        return_value=fake_row,
    ):
        plan = build_pipeline_listing_plan(
            relist_strategy="delist_and_relist",
            account_id="shop-a",
            selectors=["BD713/第一套/BD713A"],
            skip_listing=False,
            skip_selectors=[],
            listing_payload_base={"category_keyword": "玩偶"},
        )

    assert plan.action == "relist_prep"
    assert len(plan.relist_targets) == 1
    assert plan.relist_targets[0].mapping_id == "map-1"
    assert plan.relist_targets[0].merchant_code == "BD713A"
    assert plan.pending_listing["product_codes"] == ["BD713/第一套/BD713A"]


def test_build_pipeline_listing_plan_relist_prep_even_without_db_record():
    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.get_published_product",
        return_value=None,
    ):
        plan = build_pipeline_listing_plan(
            relist_strategy="delist_and_relist",
            account_id="shop-a",
            selectors=["BD037/第一套图/BD037B奶油色长条笔袋"],
            skip_listing=False,
            skip_selectors=[],
            listing_payload_base={},
        )

    assert plan.action == "relist_prep"
    assert plan.relist_targets[0].merchant_code == "BD037B奶油色长条笔袋"
    assert plan.relist_targets[0].mapping_id == ""


def test_build_pipeline_listing_plan_ignore_goes_listing_without_db():
    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.get_published_product",
        return_value=None,
    ):
        plan = build_pipeline_listing_plan(
            relist_strategy="ignore",
            account_id="shop-a",
            selectors=["BD713/第一套/BD713A"],
            skip_listing=False,
            skip_selectors=[],
            listing_payload_base={},
        )

    assert plan.action == "listing"
    assert plan.listing_codes == ["BD713/第一套/BD713A"]


def test_finalize_relist_prep_deletes_mapping_once_for_duplicate_ids():
    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.delete_published_product",
        return_value=True,
    ) as delete_mock:
        deleted, errors = finalize_relist_prep_after_delist(
            {
                "results": [
                    {"mapping_id": "m1", "status": "delisted", "target_product_id": "970099768599"},
                    {"mapping_id": "m1", "status": "delisted", "target_product_id": "970100031973"},
                ]
            }
        )

    assert deleted == ["m1"]
    assert errors == []
    delete_mock.assert_called_once_with("m1")


def test_finalize_relist_prep_deletes_delisted_and_not_found():
    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.delete_published_product",
        return_value=True,
    ) as delete_mock:
        deleted, errors = finalize_relist_prep_after_delist(
            {
                "results": [
                    {"mapping_id": "m1", "status": "delisted"},
                    {"mapping_id": "m2", "error": "product_id_not_found_on_sale"},
                    {"mapping_id": "m3", "error": "confirm_delist_failed", "selector": "BD713A"},
                ]
            }
        )

    assert deleted == ["m1", "m2"]
    assert errors == ["BD713A: confirm_delist_failed"]
    assert delete_mock.call_count == 2
