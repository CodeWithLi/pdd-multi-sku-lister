"""标准分批限时 — 子趟拆分单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.api.services.pipeline_per_batch_lt_chunks.orchestrator import (
    build_product_chunks,
    format_chunk_display,
    is_standard_per_batch_lt_chunk_pipeline,
    maybe_handle_limited_time_chunk_finished,
    maybe_start_chunked_limited_time_after_listing,
    resolve_chunk_size,
)


def _row(**kwargs):
    defaults = {
        "pipeline_id": "pipe_1",
        "account_id": "acc_1",
        "meta": {},
        "pdd_product_ids": [],
        "mapping_ids": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_is_standard_per_batch_lt_chunk_pipeline():
    row = _row(
        meta={
            "listing_per_batch_limited_time_enabled": True,
            "auto_limited_time_setup": True,
            "listing_throttle": {"enabled": True, "total_batches": 3},
        }
    )
    assert is_standard_per_batch_lt_chunk_pipeline(row) is True

    row.meta["listing_per_batch_lt_traffic_activity_enabled"] = True
    assert is_standard_per_batch_lt_chunk_pipeline(row) is False


def test_build_product_chunks_splits_by_size():
    row = _row()
    pdd_ids = [f"p{i}" for i in range(25)]
    mapping_ids = [f"m{i}" for i in range(25)]
    chunks = build_product_chunks(row, pdd_ids=pdd_ids, mapping_ids=mapping_ids, batch_size=10)
    assert len(chunks) == 3
    assert len(chunks[0]["pdd_product_ids"]) == 10
    assert len(chunks[2]["pdd_product_ids"]) == 5


def test_format_chunk_display():
    text = format_chunk_display(
        listing_batch_index=2,
        chunk_index=1,
        total_chunks=3,
        batch_size=10,
    )
    assert text == "上架第 3 批 · 限时 2/3 趟（每趟最多 10 个）"


def test_resolve_chunk_size_default():
    row = _row(meta={})
    assert resolve_chunk_size(row) == 10
    row.meta["per_batch_limited_time_chunk_size"] = 15
    assert resolve_chunk_size(row) == 15


@patch("pdd_agent.api.services.pipeline_per_batch_lt_chunks.orchestrator._enqueue_limited_time_chunk")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_chunks.orchestrator.update_integrated_pipeline")
def test_maybe_start_chunked_skips_single_chunk(mock_update, mock_enqueue):
    mock_enqueue.return_value = "lt_run_1"
    row = _row(
        meta={
            "listing_per_batch_limited_time_enabled": True,
            "auto_limited_time_setup": True,
            "listing_throttle": {
                "enabled": True,
                "total_batches": 2,
                "batch_index": 0,
                "interval_minutes": 30,
                "batches": [["a"], ["b"]],
            },
        }
    )
    handled = maybe_start_chunked_limited_time_after_listing(
        row,
        pdd_ids=["p1"],
        mapping_ids=["m1"],
        listing_meta={},
    )
    assert handled is False
    mock_enqueue.assert_not_called()


@patch("pdd_agent.api.services.pipeline_per_batch_lt_chunks.orchestrator._enqueue_limited_time_chunk")
def test_maybe_start_chunked_enqueues_first_trip(mock_enqueue):
    mock_enqueue.return_value = "lt_run_1"
    row = _row(
        meta={
            "listing_per_batch_limited_time_enabled": True,
            "auto_limited_time_setup": True,
            "listing_throttle": {
                "enabled": True,
                "total_batches": 2,
                "batch_index": 0,
                "interval_minutes": 30,
                "batches": [["a"], ["b"]],
            },
        }
    )
    pdd_ids = [f"p{i}" for i in range(12)]
    handled = maybe_start_chunked_limited_time_after_listing(
        row,
        pdd_ids=pdd_ids,
        mapping_ids=[f"m{i}" for i in range(12)],
        listing_meta={},
    )
    assert handled is True
    mock_enqueue.assert_called_once()
    call_chunk = mock_enqueue.call_args.kwargs["chunk"]
    assert len(call_chunk["pdd_product_ids"]) == 10


@patch("pdd_agent.api.services.pipeline_per_batch_lt_chunks.orchestrator._enqueue_limited_time_chunk")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_chunks.orchestrator._record_chunk_product_tracker")
@patch("pdd_agent.api.services.pipeline_per_batch_lt_chunks.orchestrator.get_integrated_pipeline")
def test_maybe_handle_queues_next_chunk(mock_get, mock_record, mock_enqueue):
    mock_record.return_value = (["p1"], ["m1"])
    mock_enqueue.return_value = "lt_run_2"
    mock_get.return_value = _row(
        pipeline_id="pipe_1",
        meta={
            "limited_time_run_id": "lt_run_1",
            "listing_per_batch_lt_chunks": {
                "enabled": True,
                "mode": "listing_batch",
                "listing_batch_index": 0,
                "chunk_index": 0,
                "total_chunks": 2,
                "batch_size": 10,
                "chunks": [
                    {"pdd_product_ids": ["p1"], "mapping_ids": ["m1"]},
                    {"pdd_product_ids": ["p2"], "mapping_ids": ["m2"]},
                ],
                "chunk_success_pdd_ids": [],
                "chunk_success_mapping_ids": [],
            },
        },
    )
    row = mock_get.return_value
    handled = maybe_handle_limited_time_chunk_finished(
        row,
        run_id="lt_run_1",
        success=True,
        result={},
        error="",
    )
    assert handled is True
    mock_enqueue.assert_called_once()
