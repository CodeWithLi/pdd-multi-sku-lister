"""每日上架记录仓储单元测试。"""

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from pdd_agent.db.repositories import create_daily_listing_record


def test_create_daily_listing_record_idempotent_by_run_and_product():
    existing = MagicMock()
    existing.record_id = "existing-id"
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = existing

    with patch("pdd_agent.db.repositories.is_database_available", return_value=True):
        with patch("pdd_agent.db.repositories.session_scope") as scope:
            scope.return_value.__enter__.return_value = session
            row = create_daily_listing_record(
                account_id="store_A",
                pdd_product_id="12345",
                product_code="BD046A",
                listing_label="BD046A/第一套",
                source_run_id="run-1",
            )
    assert row is existing
    session.add.assert_not_called()


def test_day_bounds_used_for_count():
    from pdd_agent.db.repositories import count_daily_listing_records

    with patch("pdd_agent.db.repositories.is_database_available", return_value=True):
        with patch("pdd_agent.db.repositories.session_scope") as scope:
            session = MagicMock()
            session.query.return_value.filter.return_value.scalar.return_value = 3
            scope.return_value.__enter__.return_value = session
            total = count_daily_listing_records(listed_date=date(2026, 6, 29))
    assert total == 3
    filters = session.query.return_value.filter.call_args[0]
    start = filters[0].right.value
    end = filters[1].right.value
    assert start == datetime(2026, 6, 29)
    assert end == datetime(2026, 6, 30)
