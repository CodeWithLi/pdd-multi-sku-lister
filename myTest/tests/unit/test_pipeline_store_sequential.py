"""店铺串行整合链路测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pdd_agent.api.services.pipeline_store_sequential import (
    build_coordinator_sequential_meta,
    maybe_advance_sequential_store,
)


def _row(
    *,
    pipeline_id: str,
    status: str,
    batch_id: str = "batch-1",
    meta: dict | None = None,
):
    return SimpleNamespace(
        pipeline_id=pipeline_id,
        status=status,
        meta={"batch_id": batch_id, **(meta or {})},
    )


def test_maybe_advance_starts_next_store_after_failure(monkeypatch):
    coordinator_id = "pipe-coord"
    finished = _row(
        pipeline_id=coordinator_id,
        status="failed",
        meta=build_coordinator_sequential_meta(
            pending_items=[{"account_id": "store_B", "product_codes": ["BD001/第一套图/BD001A"]}],
            common_params={"activity_ids": ["20981"], "category_keyword": "玩偶"},
            delay_min_seconds=0,
            delay_max_seconds=0,
            total_stores=2,
            active_pipeline_id=coordinator_id,
        ),
    )
    finished.meta["store_sequential"]["active_pipeline_id"] = coordinator_id
    finished.meta["store_sequential"]["started_pipeline_ids"] = [coordinator_id]

    coordinator = _row(
        pipeline_id=coordinator_id,
        status="failed",
        meta=dict(finished.meta),
    )

    get_calls = {"n": 0}

    def fake_get(pipeline_id):
        get_calls["n"] += 1
        if pipeline_id == coordinator_id:
            return coordinator
        return None

    updates: list[dict] = []

    def fake_update(pipeline_id, **kwargs):
        patch = kwargs.get("meta_patch") or {}
        if "store_sequential" in patch:
            coordinator.meta["store_sequential"] = {
                **coordinator.meta["store_sequential"],
                **patch["store_sequential"],
            }
        updates.append({"pipeline_id": pipeline_id, **kwargs})
        return coordinator

    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_store_sequential.get_integrated_pipeline",
        fake_get,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_store_sequential.update_integrated_pipeline",
        fake_update,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_store_sequential._call_start_integrated_pipeline",
        lambda **kwargs: {
            "pipeline_id": "pipe-store-b",
            "account_id": kwargs["account_id"],
            "listing_run_id": "run-b",
        },
    )

    result = maybe_advance_sequential_store(finished)
    assert result is not None
    assert result["pipeline_id"] == "pipe-store-b"
    seq = coordinator.meta["store_sequential"]
    assert seq["active_pipeline_id"] == "pipe-store-b"
    assert seq["pending_items"] == []
    assert seq["completed"] is True
    assert "pipe-store-b" in seq["started_pipeline_ids"]


def test_maybe_advance_ignores_non_active_pipeline(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_store_sequential.get_integrated_pipeline",
        lambda _pid: None,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_store_sequential.list_integrated_pipelines",
        lambda **_kwargs: [],
    )
    finished = _row(
        pipeline_id="pipe-old",
        status="completed",
        meta={
            "store_sequential": {
                "enabled": True,
                "coordinator_pipeline_id": "pipe-coord",
            }
        },
    )
    assert maybe_advance_sequential_store(finished) is None


def test_maybe_advance_ignores_running_pipeline(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_store_sequential.get_integrated_pipeline",
        lambda _pid: None,
    )
    finished = _row(
        pipeline_id="pipe-coord",
        status="running",
        meta=build_coordinator_sequential_meta(
            pending_items=[{"account_id": "store_B", "product_codes": ["X"]}],
            common_params={},
            delay_min_seconds=0,
            delay_max_seconds=0,
            total_stores=2,
            active_pipeline_id="pipe-coord",
        ),
    )
    assert maybe_advance_sequential_store(finished) is None
