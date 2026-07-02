"""整合链路上架跳过记录模块单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from pdd_agent.api.services import pipeline_listing_skip_record as mod


def test_record_skips_no_op_without_pipeline_id():
    assert (
        mod.record_pipeline_listing_skips(
            pipeline_id="",
            listing_run_id="run1",
            account_id="store_A",
            skip_kind=mod.SKIP_KIND_PLATFORM_DEDUPE,
            items=[{"selector": "BD001/第一套图/BD001A", "merchant_code": "BD001A"}],
        )
        == 0
    )


def test_maybe_record_platform_skip_dedupe_maps_items():
    items = [{"selector": "x", "merchant_code": "BD001A", "listing_label": "BD001A/第一套图"}]
    with patch.object(mod, "record_pipeline_listing_skips", return_value=1) as record:
        assert (
            mod.maybe_record_platform_skip_dedupe(
                pipeline_id="pipe1",
                listing_run_id="run1",
                account_id="store_A",
                dedupe_skipped=items,
            )
            == 1
        )
        record.assert_called_once()
        kwargs = record.call_args.kwargs
        assert kwargs["pipeline_id"] == "pipe1"
        assert kwargs["skip_kind"] == mod.SKIP_KIND_PLATFORM_DEDUPE
        assert kwargs["items"] == items


def test_maybe_record_bag_view_missing_builds_items():
    folder_by_selector = {
        "BD739/第一套图/BD739A": "BD739A",
        "BD739/第一套图/BD739B": "BD739B",
    }
    with patch.object(mod, "record_pipeline_listing_skips", return_value=1) as record:
        assert (
            mod.maybe_record_bag_view_missing(
                pipeline_id="pipe1",
                listing_run_id="run1",
                account_id="store_A",
                folder_by_selector=folder_by_selector,
                missing_folders={"BD739A"},
            )
            == 1
        )
        items = record.call_args.kwargs["items"]
        assert len(items) == 1
        assert items[0]["merchant_code"] == "BD739A"
        assert items[0]["selector"] == "BD739/第一套图/BD739A"


def test_get_pipeline_listing_skip_summary_empty_when_db_unavailable():
    with patch.object(mod, "is_database_available", return_value=False):
        summary = mod.get_pipeline_listing_skip_summary("pipe1")
    assert summary["total"] == 0
    assert summary["platform_skip_dedupe"] == 0
    assert summary["bag_view_missing"] == 0


def test_get_pipeline_listing_skip_summary_counts_by_kind():
    row_dedupe = MagicMock(
        record_id="r1",
        skip_kind=mod.SKIP_KIND_PLATFORM_DEDUPE,
        listing_run_id="run1",
        account_id="store_A",
        product_selector="sel1",
        merchant_code="BD001A",
        listing_label="BD001A/第一套图",
        message="skip",
        created_at=None,
    )
    row_bag = MagicMock(
        record_id="r2",
        skip_kind=mod.SKIP_KIND_BAG_VIEW_MISSING,
        listing_run_id="run1",
        account_id="store_A",
        product_selector="sel2",
        merchant_code="BD002A",
        listing_label="BD002A/第一套图",
        message="bag",
        created_at=None,
    )

    class _Scalars:
        def all(self):
            return [row_dedupe, row_bag]

    session = MagicMock()
    session.scalars.return_value = _Scalars()

    with patch.object(mod, "is_database_available", return_value=True), patch.object(
        mod, "session_scope"
    ) as mock_scope:
        mock_scope.return_value.__enter__.return_value = session
        summary = mod.get_pipeline_listing_skip_summary("pipe1")
        assert summary["platform_skip_dedupe"] == 1
        assert summary["bag_view_missing"] == 1
        assert summary["total"] == 2
        assert len(summary["items"]) == 2


def test_summarize_daily_pipeline_listing_skips_empty_when_db_unavailable():
    with patch.object(mod, "is_database_available", return_value=False):
        summary = mod.summarize_daily_pipeline_listing_skips(
            skip_date=__import__("datetime").date(2026, 7, 2)
        )
    assert summary["total"] == 0
    assert summary["pipeline_count"] == 0


def test_list_daily_pipeline_listing_skips_empty_when_db_unavailable():
    with patch.object(mod, "is_database_available", return_value=False):
        rows = mod.list_daily_pipeline_listing_skips(
            skip_date=__import__("datetime").date(2026, 7, 2)
        )
    assert rows == []
