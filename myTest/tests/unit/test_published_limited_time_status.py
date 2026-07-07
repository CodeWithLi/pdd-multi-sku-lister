"""已发布商品限时限量购状态 — 单元测试。"""

from datetime import datetime
from types import SimpleNamespace

from pdd_agent.api.services.published_limited_time_status_resolver import (
    LIMITED_TIME_STATUS_FAILED,
    LIMITED_TIME_STATUS_SUCCESS,
    resolve_published_limited_time_statuses,
)
from pdd_agent.api.services.published_limited_time_status_store import (
    persist_published_limited_time_status_items,
)
from pdd_agent.domain.enums import RunStatus


def test_resolve_partial_success_marks_kept_and_missing(monkeypatch):
    rows = [
        SimpleNamespace(mapping_id="m1", pdd_product_id="111"),
        SimpleNamespace(mapping_id="m2", pdd_product_id="222"),
        SimpleNamespace(mapping_id="m3", pdd_product_id="333"),
    ]
    monkeypatch.setattr(
        "pdd_agent.db.repositories.get_published_products_by_pdd_product_ids",
        lambda **kwargs: rows,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_activity_limited_time_success.extract_limited_time_success_products",
        lambda *args, **kwargs: SimpleNamespace(pdd_product_ids=["111", "222"]),
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner._extract_limited_time_price_filter_errors",
        lambda result: {},
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner._extract_per_product_activity_errors",
        lambda result, fallback_error="", product_ids=None: {"333": "弹窗内未找到"},
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner._campaign_failure_message",
        lambda result, status: "",
    )

    result = {
        "results": [
            {
                "status": "success",
                "step": "activity_created",
                "selected_pdd_product_ids": ["111", "222"],
                "product_selection": {
                    "missing_ids": ["333"],
                    "partial_skip_reason": "弹窗内 1 个商品未找到",
                },
                "price_filter": {
                    "kept_product_ids": ["111", "222"],
                    "deleted_product_ids": [],
                },
            }
        ]
    }
    items = resolve_published_limited_time_statuses(
        account_id="store_A",
        selected_product_ids=["111", "222", "333"],
        result=result,
        run_status=RunStatus.SUCCESS,
        run_id="run_lt_1",
    )
    by_pdd = {item.pdd_product_id: item for item in items}
    assert by_pdd["111"].status == LIMITED_TIME_STATUS_SUCCESS
    assert by_pdd["111"].error == ""
    assert by_pdd["222"].status == LIMITED_TIME_STATUS_SUCCESS
    assert by_pdd["333"].status == LIMITED_TIME_STATUS_FAILED
    assert "未找到" in by_pdd["333"].error


def test_resolve_run_failed_marks_all_failed(monkeypatch):
    rows = [SimpleNamespace(mapping_id="m9", pdd_product_id="999")]
    monkeypatch.setattr(
        "pdd_agent.db.repositories.get_published_products_by_pdd_product_ids",
        lambda **kwargs: rows,
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.pipeline_activity_limited_time_success.extract_limited_time_success_products",
        lambda *args, **kwargs: SimpleNamespace(pdd_product_ids=[]),
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner._extract_limited_time_price_filter_errors",
        lambda result: {},
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner._extract_per_product_activity_errors",
        lambda result, fallback_error="", product_ids=None: {},
    )
    monkeypatch.setattr(
        "pdd_agent.api.services.task_runner._campaign_failure_message",
        lambda result, status: "限时限量购整单失败",
    )

    items = resolve_published_limited_time_statuses(
        account_id="store_A",
        selected_product_ids=["999"],
        result={"error": "browser failed"},
        run_status=RunStatus.FAILED,
        run_id="run_lt_2",
    )
    assert len(items) == 1
    assert items[0].status == LIMITED_TIME_STATUS_FAILED
    assert items[0].error == "限时限量购整单失败"


def test_persist_published_limited_time_status_items(monkeypatch):
    updated: list[str] = []

    def fake_update(mapping_id, **kwargs):
        updated.append(mapping_id)
        return SimpleNamespace(mapping_id=mapping_id)

    monkeypatch.setattr(
        "pdd_agent.api.services.published_limited_time_status_store.update_published_product_limited_time_status",
        fake_update,
    )
    items = [
        SimpleNamespace(
            mapping_id="m1",
            status=LIMITED_TIME_STATUS_SUCCESS,
            error="",
            run_id="run1",
            completed_at=datetime.now(),
        )
    ]
    summary = persist_published_limited_time_status_items(items)
    assert summary["updated"] == 1
    assert updated == ["m1"]
