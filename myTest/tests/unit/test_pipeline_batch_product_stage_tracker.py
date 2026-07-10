"""分批每商品阶段 tracker — 上架结果别名匹配。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_batch_product_stage_tracker import (
    record_listing_batch_from_result,
    resolve_finished_listing_batch_index,
)


def test_resolve_finished_listing_batch_index_prefers_last_batch_index():
    row = SimpleNamespace(
        meta={
            "listing_throttle": {"batch_index": 2},
            "listing_per_batch_limited_time": {"last_batch_index": 0},
        }
    )
    assert resolve_finished_listing_batch_index(row) == 0


@patch("pdd_agent.api.services.pipeline_batch_product_stage_tracker.session_scope")
@patch("pdd_agent.api.services.pipeline_batch_product_stage_tracker.ensure_batch_product_rows")
def test_record_listing_batch_matches_two_part_label_to_three_part_selector(
    mock_ensure,
    mock_session_scope,
):
    row = SimpleNamespace(
        pipeline_id="pipe_1",
        batch_index=0,
        product_selector="BD070/真一套图/BD070Z",
        listing_label="BD070/真一套图/BD070Z",
        listing_status="pending",
        listing_error="",
        pdd_product_id="",
        mapping_id="",
        updated_at=None,
    )
    session = MagicMock()
    mock_session_scope.return_value.__enter__.return_value = session
    session.query.return_value.filter_by.return_value.all.return_value = [row]

    record_listing_batch_from_result(
        pipeline_id="pipe_1",
        account_id="store_A",
        batch_index=0,
        batch_selectors=["BD070/真一套图/BD070Z"],
        listing_result={
            "results": [
                {
                    "listing_label": "BD070Z/真一套图",
                    "status": "success",
                    "pdd_product_id": "123456",
                    "mapping_id": "map_1",
                }
            ]
        },
    )

    assert row.listing_status == "success"
    assert row.pdd_product_id == "123456"
    assert row.listing_error == ""
