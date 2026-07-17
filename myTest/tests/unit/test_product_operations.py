"""商品操作封装单元测试。"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from pdd_agent.product_operations.automation import normalize_price, validate_price_updates
from pdd_agent.product_operations.schemas import DelistAllStoresIn
from pdd_agent.product_operations.service import enqueue_product_id_delist_all_stores


def test_delist_product_id_requires_digits():
    with pytest.raises(ValueError):
        DelistAllStoresIn(product_id="abc123")


def test_validate_price_updates_matches_exact_spec_codes():
    current = [
        {"spec_code": "BD070Z", "group_price": "9.47"},
        {"spec_code": "BD070Z+YKL001AC", "group_price": "10.47"},
    ]
    result = validate_price_updates(
        current,
        [{"spec_code": " bd070z+ykl001ac ", "group_price": Decimal("11.2")}],
    )
    assert result == [{"spec_code": "BD070Z+YKL001AC", "group_price": "11.20"}]


def test_validate_price_updates_rejects_unknown_spec_code():
    with pytest.raises(ValueError, match="页面未找到规格编码"):
        validate_price_updates(
            [{"spec_code": "BD070Z"}],
            [{"spec_code": "BD070A", "group_price": "9.99"}],
        )


def test_validate_price_updates_rejects_duplicate_spec_code():
    with pytest.raises(ValueError, match="规格编码重复"):
        validate_price_updates(
            [{"spec_code": "BD070Z"}],
            [
                {"spec_code": "BD070Z", "group_price": "9.99"},
                {"spec_code": "bd070z", "group_price": "10.99"},
            ],
        )


def test_normalize_price_keeps_two_decimals():
    assert normalize_price("9.9") == "9.90"


@patch("pdd_agent.product_operations.service.enqueue_delist_task")
@patch("pdd_agent.product_operations.service.create_delist_run")
@patch("pdd_agent.product_operations.service.resolve_enabled_account_ids")
@patch("pdd_agent.product_operations.service.TaskRunStore")
def test_delist_all_stores_reuses_existing_delist_queue(
    store_cls,
    resolve_accounts,
    create_run,
    enqueue,
):
    resolve_accounts.return_value = (["store_A", "store_B"], [])
    create_run.side_effect = ["run-a", "run-b"]

    rows = enqueue_product_id_delist_all_stores("978432707043")

    assert [row["account_id"] for row in rows] == ["store_A", "store_B"]
    assert enqueue.call_count == 2
    assert enqueue.call_args_list[0].kwargs["delist_params"] == {
        "target_product_id": "978432707043",
        "dry_run": False,
        "mode": "product_operations_exact",
    }
    assert store_cls.return_value.update_status.call_count == 2
