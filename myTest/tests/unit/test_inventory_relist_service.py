"""库存恢复上架 — 触发任务拆分逻辑。"""

from pdd_agent.inventory_delist.relist_analysis import RelistTarget
from pdd_agent.inventory_delist.service import _build_relist_per_account_tasks


def test_build_relist_per_account_tasks_splits_by_shop_and_record_ids():
    targets = [
        RelistTarget(
            product_code="AXB001",
            account_ids=["acc1", "acc2"],
            record_ids=["r1", "r2"],
            per_account=[
                {"account_id": "acc1", "record_id": "r1"},
                {"account_id": "acc2", "record_id": "r2"},
            ],
        ),
        RelistTarget(
            product_code="AXB002",
            account_ids=["acc1"],
            record_ids=["r3"],
            per_account=[{"account_id": "acc1", "record_id": "r3"}],
        ),
    ]

    rows = _build_relist_per_account_tasks(["acc1", "acc2"], targets)

    assert len(rows) == 2
    acc1 = next(row for row in rows if row["account_id"] == "acc1")
    acc2 = next(row for row in rows if row["account_id"] == "acc2")
    assert acc1["candidate_codes"] == ["AXB001", "AXB002"]
    assert acc1["code_record_ids"]["AXB001"] == ["r1"]
    assert acc1["code_record_ids"]["AXB002"] == ["r3"]
    assert acc2["candidate_codes"] == ["AXB001"]
    assert acc2["code_record_ids"]["AXB001"] == ["r2"]


def test_trigger_inventory_relist_run_filters_product_codes(monkeypatch):
    from pdd_agent.inventory_delist.relist_analysis import InventoryRelistAnalysis, RelistTarget
    from pdd_agent.inventory_delist import service as relist_service

    target_a = RelistTarget(product_code="AXB001", account_ids=["acc1"], available_qty=10)
    target_b = RelistTarget(product_code="AXB002", account_ids=["acc1"], available_qty=5)

    def fake_analyze(*args, **kwargs):
        return InventoryRelistAnalysis(
            account_ids=["acc1"],
            relist_candidates=[target_a, target_b],
        )

    created_snapshot: dict = {}

    def fake_create_relist_job(**kwargs):
        created_snapshot.update(kwargs.get("analysis_snapshot") or {})
        from pdd_agent.inventory_delist.relist_job_store import InventoryRelistJob

        return InventoryRelistJob(job_id="inv_relist_test", account_ids=["acc1"])

    def fake_start(job, **kwargs):
        return job

    from types import SimpleNamespace

    cfg = SimpleNamespace(account_ids=["acc1"], execution_mode="parallel")

    monkeypatch.setattr(relist_service, "is_database_available", lambda: True)
    monkeypatch.setattr(relist_service, "_resolve_account_ids", lambda ids: (["acc1"], []))
    monkeypatch.setattr(relist_service, "load_inventory_delist_config", lambda: cfg)
    monkeypatch.setattr(relist_service, "analyze_inventory_relist_targets", fake_analyze)
    monkeypatch.setattr(relist_service, "create_relist_job", fake_create_relist_job)
    monkeypatch.setattr(relist_service, "start_inventory_relist_job", fake_start)

    relist_service.trigger_inventory_relist_run(
        account_ids=["acc1"],
        product_codes=["AXB002"],
    )

    assert created_snapshot["relist_candidates_count"] == 1
    assert created_snapshot["relist_candidates"][0]["product_code"] == "AXB002"
    assert created_snapshot["per_account_tasks"][0]["candidate_codes"] == ["AXB002"]


def test_trigger_inventory_relist_run_rejects_negative_inventory(monkeypatch):
    from pdd_agent.inventory_delist.relist_analysis import InventoryRelistAnalysis, RelistTarget
    from pdd_agent.inventory_delist import service as relist_service
    import pytest

    def fake_analyze(*args, **kwargs):
        return InventoryRelistAnalysis(
            account_ids=["acc1"],
            still_negative_codes=[RelistTarget(product_code="BD070B", available_qty=-1, account_ids=["acc1"])],
        )

    from types import SimpleNamespace

    cfg = SimpleNamespace(account_ids=["acc1"], execution_mode="parallel")

    monkeypatch.setattr(relist_service, "is_database_available", lambda: True)
    monkeypatch.setattr(relist_service, "_resolve_account_ids", lambda ids: (["acc1"], []))
    monkeypatch.setattr(relist_service, "load_inventory_delist_config", lambda: cfg)
    monkeypatch.setattr(relist_service, "analyze_inventory_relist_targets", fake_analyze)

    with pytest.raises(ValueError, match="仍为负库存"):
        relist_service.trigger_inventory_relist_run(
            account_ids=["acc1"],
            product_codes=["BD070B"],
        )
