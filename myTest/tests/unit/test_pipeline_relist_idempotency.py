"""整合链路下架预备 — 幂等与重复回调防护。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_enqueue_pipeline_relist_prep_skips_when_already_queued():
    from pdd_agent.api.services.pipeline_relist_strategy import (
        RelistPrepTarget,
        enqueue_pipeline_relist_prep,
    )

    row = MagicMock()
    row.meta = {
        "relist_prep_run_id": "delist-existing",
        "pending_listing": {"product_codes": ["a/b/CODE1"]},
    }

    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.get_integrated_pipeline",
        return_value=row,
    ), patch(
        "pdd_agent.api.services.pipeline_relist_strategy.create_delist_run",
    ) as create_mock, patch(
        "pdd_agent.api.services.pipeline_relist_strategy.enqueue_task",
    ) as enqueue_mock:
        run_id = enqueue_pipeline_relist_prep(
            pipeline_id="pipe-1",
            account_id="shop-a",
            targets=[
                RelistPrepTarget(
                    selector="a/b/CODE1",
                    mapping_id="m1",
                    pdd_product_id="111",
                    merchant_code="CODE1",
                )
            ],
            pending_listing={"product_codes": ["a/b/CODE1"]},
        )

    assert run_id == "delist-existing"
    create_mock.assert_not_called()
    enqueue_mock.assert_not_called()


def test_enqueue_pending_listing_after_relist_prep_is_idempotent():
    from pdd_agent.api.services.pipeline_relist_strategy import (
        enqueue_pending_listing_after_relist_prep,
    )

    row = MagicMock()
    row.pipeline_id = "pipe-1"
    row.account_id = "shop-a"
    row.listing_run_id = "listing-1"
    row.product_codes = ["a/b/CODE1"]
    row.meta = {
        "pending_listing": {"product_codes": ["a/b/CODE1"]},
        "relist_prep_listing_enqueued_at": "2026-06-21T10:00:00",
    }

    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.update_integrated_pipeline",
    ) as update_mock, patch(
        "pdd_agent.api.services.pipeline_relist_strategy.enqueue_task",
    ) as enqueue_mock:
        enqueue_pending_listing_after_relist_prep(row)

    update_mock.assert_not_called()
    enqueue_mock.assert_not_called()


def test_handle_pipeline_delist_ignores_after_relist_prep_completed():
    from pdd_agent.api.services.pipeline_relist_strategy import handle_pipeline_delist_task_finished

    row = MagicMock()
    row.meta = {
        "relist_strategy": "delist_and_relist",
        "relist_prep_run_id": "delist-1",
        "relist_prep_completed_at": "2026-06-21T10:00:00",
        "relist_prep_pending_listing": {"product_codes": ["a/b/CODE1"]},
        "pending_listing": None,
    }
    row.pipeline_id = "pipe-1"

    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.get_integrated_pipeline",
        return_value=row,
    ), patch(
        "pdd_agent.api.services.pipeline_relist_strategy.enqueue_pending_listing_after_relist_prep",
    ) as enqueue_mock, patch(
        "pdd_agent.api.services.pipeline_relist_strategy.update_integrated_pipeline",
    ) as update_mock:
        handled = handle_pipeline_delist_task_finished(
            pipeline_id="pipe-1",
            run_id="delist-1",
            success=True,
            result={"results": [{"mapping_id": "m1", "status": "delisted"}]},
        )

    assert handled is True
    enqueue_mock.assert_not_called()
    update_mock.assert_not_called()


def test_handle_pipeline_delist_clears_pending_listing_on_success():
    from pdd_agent.api.services.pipeline_relist_strategy import handle_pipeline_delist_task_finished

    row = MagicMock()
    row.meta = {
        "relist_strategy": "delist_and_relist",
        "relist_prep_run_id": "delist-1",
        "pending_listing": {"product_codes": ["a/b/CODE1"], "category_keyword": "玩偶"},
    }
    row.pipeline_id = "pipe-1"
    row.account_id = "shop-a"
    row.listing_run_id = "listing-1"
    row.product_codes = ["a/b/CODE1"]

    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.get_integrated_pipeline",
        return_value=row,
    ), patch(
        "pdd_agent.api.services.pipeline_relist_strategy.finalize_relist_prep_after_delist",
        return_value=(["m1"], []),
    ), patch(
        "pdd_agent.api.services.pipeline_relist_strategy.update_integrated_pipeline",
    ), patch(
        "pdd_agent.api.services.pipeline_relist_strategy.enqueue_pending_listing_after_relist_prep",
    ) as enqueue_mock:
        handled = handle_pipeline_delist_task_finished(
            pipeline_id="pipe-1",
            run_id="delist-1",
            success=True,
            result={"results": [{"mapping_id": "m1", "status": "delisted"}]},
        )

    assert handled is True
    enqueue_mock.assert_called_once()
