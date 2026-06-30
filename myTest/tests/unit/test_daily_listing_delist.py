"""每日上架记录逻辑删除单元测试。"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from pdd_agent.db.repositories import mark_daily_listing_records_delisted


def test_mark_daily_listing_records_delisted_by_pdd_product_id():
    row = MagicMock()
    row.status = "active"
    query_mock = MagicMock()
    query_mock.filter.return_value = query_mock
    query_mock.all.return_value = [row]
    session = MagicMock()
    session.query.return_value = query_mock

    with patch("pdd_agent.db.repositories.is_database_available", return_value=True):
        with patch("pdd_agent.db.repositories.session_scope") as scope:
            scope.return_value.__enter__.return_value = session
            count = mark_daily_listing_records_delisted(
                account_id="store_A",
                pdd_product_id="12345",
            )

    assert count == 1
    assert row.status == "delisted"
    assert row.delisted_at is not None


def test_mark_daily_listing_records_delisted_skips_without_account():
    with patch("pdd_agent.db.repositories.is_database_available", return_value=True):
        count = mark_daily_listing_records_delisted(
            account_id="",
            pdd_product_id="12345",
        )
    assert count == 0


def test_delete_published_product_marks_daily_listing():
    from pdd_agent.db.repositories import delete_published_product

    row = MagicMock()
    row.account_id = "store_A"
    row.pdd_product_id = "999"
    row.product_code = "BD046A"
    row.image_set = "第一套图"
    row.family_code = "BD046"
    session = MagicMock()
    session.get.side_effect = lambda model, key: row if key == "map-1" else None

    with patch("pdd_agent.db.repositories.is_database_available", return_value=True):
        with patch("pdd_agent.db.repositories.session_scope") as scope:
            scope.return_value.__enter__.return_value = session
            with patch(
                "pdd_agent.db.repositories.mark_daily_listing_records_delisted",
                return_value=1,
            ) as mark_fn:
                ok = delete_published_product("map-1")

    assert ok is True
    mark_fn.assert_called_once_with(
        account_id="store_A",
        pdd_product_id="999",
        product_code="BD046A",
        image_set="第一套图",
    )
    session.delete.assert_called()
