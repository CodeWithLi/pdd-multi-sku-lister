"""整合链路下架预备单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_verify_scanned_rows_rejects_unmatched_merchant_code():
    from pdd_agent.skills.delist.pipeline_relist_prep import (
        SKIP_REASON_FILTER_UNVERIFIED,
        _verify_scanned_rows_for_merchant_codes,
    )

    rows = [
        {"product_id": "111", "merchant_code": "BD001"},
        {"product_id": "999", "merchant_code": ""},
    ]
    verified, err = _verify_scanned_rows_for_merchant_codes(rows, ["BD001"])
    assert verified == []
    assert err == SKIP_REASON_FILTER_UNVERIFIED


def test_verify_known_product_ids_requires_overlap():
    from pdd_agent.skills.delist.pipeline_relist_prep import (
        SKIP_REASON_ID_MISMATCH,
        _verify_known_product_ids,
    )

    groups = {
        "BD001": {"known_ids": ["111"]},
    }
    discovered = {"BD001": ["999"]}
    assert _verify_known_product_ids(groups, discovered) == SKIP_REASON_ID_MISMATCH


def test_skip_delist_when_filter_verification_fails(monkeypatch):
    from pdd_agent.skills.delist import pipeline_relist_prep as mod

    monkeypatch.setattr(mod, "open_goods_list_on_sale", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mod,
        "verify_shop_for_account",
        lambda *_a, **_k: MagicMock(ok=True, expected="兔兔潮玩屋", actual="兔兔潮玩屋", error=""),
    )
    monkeypatch.setattr(mod, "filter_goods_by_merchant_codes", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mod,
        "scan_filtered_product_rows_all_pages",
        lambda *_a, **_k: [{"product_id": "999", "merchant_code": ""}],
    )
    delist = MagicMock()
    monkeypatch.setattr(mod, "_delist_verified_product_ids", delist)

    stats = mod.process_pipeline_relist_prep_delist(
        MagicMock(),
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        [{"selector": "a/b/BD001", "merchant_code": "BD001", "mapping_id": "m1", "target_product_id": "111"}],
    )

    assert stats.get("delist_skipped") is True
    assert stats.get("errors") == []
    delist.assert_not_called()


def test_delist_only_verified_product_ids(monkeypatch):
    from pdd_agent.skills.delist import pipeline_relist_prep as mod

    monkeypatch.setattr(mod, "open_goods_list_on_sale", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mod,
        "verify_shop_for_account",
        lambda *_a, **_k: MagicMock(ok=True, expected="兔兔潮玩屋", actual="兔兔潮玩屋", error=""),
    )
    monkeypatch.setattr(mod, "filter_goods_by_merchant_codes", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mod,
        "scan_filtered_product_rows_all_pages",
        lambda *_a, **_k: [{"product_id": "111", "merchant_code": "BD001"}],
    )

    delist_calls: list[list[dict]] = []

    def _fake_delist(_page, _cfg, plan, *, dry_run=False):
        delist_calls.append(list(plan))
        return [{"target_product_id": "111", "status": "delisted", "mapping_id": "m1"}]

    monkeypatch.setattr(mod, "_delist_verified_product_ids", _fake_delist)

    stats = mod.process_pipeline_relist_prep_delist(
        MagicMock(),
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        [{"selector": "a/b/BD001", "merchant_code": "BD001", "mapping_id": "m1", "target_product_id": "111"}],
    )

    assert stats.get("delist_skipped") is not True
    assert delist_calls[0][0]["target_product_id"] == "111"
    assert stats["hit"] == 1


def test_handle_pipeline_delist_skipped_continues_listing():
    from pdd_agent.api.services.pipeline_relist_strategy import handle_pipeline_delist_task_finished

    row = MagicMock()
    row.meta = {"relist_strategy": "delist_and_relist", "pending_listing": {"product_codes": ["a/b/BD001"]}}
    row.pipeline_id = "pipe-1"

    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.get_integrated_pipeline",
        return_value=row,
    ), patch(
        "pdd_agent.api.services.pipeline_relist_strategy.update_integrated_pipeline",
    ) as update_mock, patch(
        "pdd_agent.api.services.pipeline_relist_strategy.enqueue_pending_listing_after_relist_prep",
    ) as enqueue_mock, patch(
        "pdd_agent.api.services.pipeline_relist_strategy.finalize_relist_prep_after_delist",
    ) as finalize_mock:
        handled = handle_pipeline_delist_task_finished(
            pipeline_id="pipe-1",
            run_id="run-1",
            success=True,
            result={
                "delist_skipped": True,
                "skip_reason": "filter_verification_failed",
                "warnings": ["已跳过下架"],
            },
        )

    assert handled is True
    finalize_mock.assert_not_called()
    enqueue_mock.assert_called_once()
    assert any(
        call.kwargs.get("meta_patch", {}).get("relist_prep_skipped") is True
        for call in update_mock.call_args_list
    )
