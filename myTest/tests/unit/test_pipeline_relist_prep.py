"""整合链路下架预备单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_verify_scanned_rows_filters_unmatched_merchant_code():
    from pdd_agent.skills.delist.pipeline_relist_prep import _verify_scanned_rows_for_merchant_codes

    rows = [
        {"product_id": "111", "merchant_code": "BD001"},
        {"product_id": "999", "merchant_code": "OTHER"},
    ]
    verified, err = _verify_scanned_rows_for_merchant_codes(rows, ["BD001"])
    assert verified == [{"product_id": "111", "merchant_code": "BD001"}]
    assert err == ""


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
        "batch_delist_by_verified_checkboxes",
        lambda *_a, **_k: {
            "ok": False,
            "filter_error": "filter_verification_failed",
            "total_checked": 0,
            "total_delisted": 0,
            "delisted_items": [],
            "errors": ["filter_verification_failed"],
        },
    )

    stats = mod.process_pipeline_relist_prep_delist(
        MagicMock(),
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        [{"selector": "a/b/BD001", "merchant_code": "BD001", "mapping_id": "m1"}],
    )

    assert stats.get("delist_skipped") is not True
    assert stats["hit"] == 0
    assert any("filter_verification_failed" in str(item.get("error") or "") for item in stats["results"])


def test_batch_delist_merchant_codes(monkeypatch):
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
        "batch_delist_by_verified_checkboxes",
        lambda *_a, **_k: {
            "ok": True,
            "filter_error": "",
            "total_checked": 2,
            "total_delisted": 2,
            "pages_processed": 1,
            "delisted_items": [
                {"product_id": "111", "merchant_code": "BD001", "matched_code": "BD001"},
                {"product_id": "112", "merchant_code": "BD001", "matched_code": "BD001"},
            ],
            "errors": [],
        },
    )

    stats = mod.process_pipeline_relist_prep_delist(
        MagicMock(),
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        [{"selector": "a/b/BD001", "merchant_code": "BD001", "mapping_id": "m1"}],
    )

    assert stats.get("delist_skipped") is not True
    assert stats["hit"] == 2
    assert all(item.get("status") == "delisted" for item in stats["results"])


def test_delist_by_known_product_id(monkeypatch):
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
        "batch_delist_by_verified_checkboxes",
        lambda *_a, **_k: {
            "total_delisted": 1,
            "delisted_items": [
                {
                    "product_id": "970478951304",
                    "merchant_code": "BD001",
                    "matched_code": "BD001",
                }
            ],
            "found_codes": ["BD001"],
            "errors": [],
        },
    )

    stats = mod.process_pipeline_relist_prep_delist(
        MagicMock(),
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        [
            {
                "selector": "a/b/BD001",
                "merchant_code": "BD001",
                "mapping_id": "m1",
                "target_product_id": "970478951304",
            }
        ],
    )

    assert stats["hit"] == 1
    assert stats["results"][0]["status"] == "delisted"


def test_delist_spec_code_search_disabled_skips_fallback(monkeypatch):
    from pdd_agent.skills.delist import pipeline_relist_prep as mod

    filter_kwargs: list[dict] = []

    def fake_filter(_page, _account_id, codes, **kwargs):
        filter_kwargs.append(dict(kwargs))
        return True

    monkeypatch.setattr(mod, "open_goods_list_on_sale", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mod,
        "verify_shop_for_account",
        lambda *_a, **_k: MagicMock(ok=True, expected="兔兔潮玩屋", actual="兔兔潮玩屋", error=""),
    )
    monkeypatch.setattr(mod, "filter_goods_by_merchant_codes", fake_filter)
    monkeypatch.setattr(
        mod,
        "batch_delist_by_verified_checkboxes",
        lambda *_a, **_k: {
            "total_delisted": 0,
            "delisted_items": [],
            "found_codes": [],
            "errors": [],
        },
    )

    mod.process_pipeline_relist_prep_delist(
        MagicMock(),
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        [{"selector": "a/b/BD001", "merchant_code": "BD001", "mapping_id": "m1"}],
        delist_spec_code_search_enabled=False,
    )

    assert filter_kwargs
    assert filter_kwargs[0].get("try_spec_code_search") is False


def test_delist_batches_merchant_codes_in_groups_of_five(monkeypatch):
    from pdd_agent.skills.delist import pipeline_relist_prep as mod

    filter_calls: list[list[str]] = []

    def fake_filter(_page, _account_id, codes, **_kwargs):
        filter_calls.append(list(codes))
        return True

    monkeypatch.setattr(mod, "open_goods_list_on_sale", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mod,
        "verify_shop_for_account",
        lambda *_a, **_k: MagicMock(ok=True, expected="兔兔潮玩屋", actual="兔兔潮玩屋", error=""),
    )
    monkeypatch.setattr(mod, "filter_goods_by_merchant_codes", fake_filter)
    monkeypatch.setattr(
        mod,
        "batch_delist_by_verified_checkboxes",
        lambda *_a, **_k: {
            "total_delisted": 1,
            "delisted_items": [{"product_id": "111", "merchant_code": "BD001", "matched_code": "BD001"}],
            "found_codes": ["BD001"],
            "errors": [],
        },
    )

    targets = [
        {
            "selector": f"a/b/{code}",
            "merchant_code": code,
            "mapping_id": f"m{i}",
        }
        for i, code in enumerate(
            ["BD001", "BD002", "BD003", "BD004", "BD005", "BD006"],
            start=1,
        )
    ]
    mod.process_pipeline_relist_prep_delist(
        MagicMock(),
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        targets,
    )

    assert len(filter_calls) == 2
    assert filter_calls[0] == ["BD001", "BD002", "BD003", "BD004", "BD005"]
    assert filter_calls[1] == ["BD006"]


def test_handle_pipeline_delist_failed_run_still_enqueues_listing():
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
        "pdd_agent.api.services.pipeline_relist_strategy.update_integrated_pipeline",
    ) as update_mock, patch(
        "pdd_agent.api.services.pipeline_relist_strategy.enqueue_pending_listing_after_relist_prep",
    ) as enqueue_mock:
        handled = handle_pipeline_delist_task_finished(
            pipeline_id="pipe-1",
            run_id="delist-1",
            success=False,
            result={"errors": ["打开商品列表失败"]},
            error="打开商品列表失败",
        )

    assert handled is True
    enqueue_mock.assert_called_once()
    failed_updates = [
        call for call in update_mock.call_args_list if call.kwargs.get("status") == "failed"
    ]
    assert failed_updates == []
    assert any(
        call.kwargs.get("meta_patch", {}).get("relist_prep_delist_run_failed") is True
        for call in update_mock.call_args_list
    )


def test_handle_pipeline_delist_continues_listing_when_search_no_hit(monkeypatch):
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

    results = [
        {
            "mapping_id": "m1",
            "selector": "a/b/CODE1",
            "error": "merchant_code_search_no_hit",
        }
    ]

    with patch(
        "pdd_agent.api.services.pipeline_relist_strategy.get_integrated_pipeline",
        return_value=row,
    ), patch(
        "pdd_agent.api.services.pipeline_relist_strategy.update_integrated_pipeline",
    ) as update_mock, patch(
        "pdd_agent.api.services.pipeline_relist_strategy.enqueue_pending_listing_after_relist_prep",
    ) as enqueue_mock:
        handled = handle_pipeline_delist_task_finished(
            pipeline_id="pipe-1",
            run_id="delist-1",
            success=True,
            result={"results": results, "warnings": ["a/b/CODE1: merchant_code_search_no_hit"]},
        )

    assert handled is True
    enqueue_mock.assert_called_once()
    failed_updates = [
        call
        for call in update_mock.call_args_list
        if call.kwargs.get("status") == "failed"
    ]
    assert failed_updates == []


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
