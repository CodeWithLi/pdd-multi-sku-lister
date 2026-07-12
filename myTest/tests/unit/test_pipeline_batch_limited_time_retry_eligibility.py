"""pipeline_batch_limited_time_retry_eligibility 单元测试。"""

from types import SimpleNamespace

from pdd_agent.api.services.pipeline_batch_limited_time_retry_eligibility import (
    is_batch_initial_limited_time_recorded,
    is_pipeline_initial_limited_time_phase_complete,
    is_pipeline_listing_batches_complete,
)


def test_listing_complete_when_throttle_reached_last_batch():
    row = SimpleNamespace(
        current_step="waiting_limited_time_per_batch",
        listing_run_id="lr1",
        meta={
            "listing_throttle": {
                "enabled": True,
                "batch_index": 18,
                "total_batches": 19,
                "completed": False,
            }
        },
    )
    assert is_pipeline_listing_batches_complete(row) is True


def test_listing_not_complete_when_waiting_next_batch():
    row = SimpleNamespace(
        current_step="waiting_listing_batch_5",
        listing_run_id="lr1",
        meta={"listing_throttle": {"enabled": True, "batch_index": 4, "total_batches": 19}},
    )
    assert is_pipeline_listing_batches_complete(row) is False


def test_initial_lt_not_complete_while_aggregate_in_progress():
    row = SimpleNamespace(
        current_step="waiting_limited_time_per_batch",
        status="running",
        meta={
            "listing_throttle": {"total_batches": 19},
            "std_per_batch_lt_agg_batch_log": [{"batch_index": i} for i in range(12)],
            "std_per_batch_lt_agg_in_progress": True,
        },
    )
    assert is_pipeline_initial_limited_time_phase_complete(row) is False


def test_initial_lt_complete_when_finalized():
    row = SimpleNamespace(
        current_step="waiting_activity",
        status="waiting_activity",
        meta={"std_per_batch_lt_agg_finalized": True},
    )
    assert is_pipeline_initial_limited_time_phase_complete(row) is True


def test_batch_initial_limited_time_recorded():
    products = [
        {"listing_status": "success", "limited_time_status": "failed"},
        {"listing_status": "success", "limited_time_status": "pending"},
    ]
    assert is_batch_initial_limited_time_recorded(products) is True
