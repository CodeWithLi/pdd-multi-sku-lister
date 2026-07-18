"""商品操作封装单元测试。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pdd_agent.product_operations.automation import (
    delist_product_by_code,
    normalize_price,
    validate_price_updates,
)
from pdd_agent.product_operations.schemas import DelistAllStoresIn
from pdd_agent.product_operations.service import (
    enqueue_product_code_delist_all_stores,
    list_published_product_options,
)


def test_delist_product_code_is_required():
    with pytest.raises(ValueError):
        DelistAllStoresIn(product_code=" ")


def test_delist_product_code_accepts_merchant_code():
    body = DelistAllStoresIn(product_code=" BD070Z ")
    assert body.product_code == "BD070Z"


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


@patch("pdd_agent.skills.delist.automation.process_single_product_delist")
def test_delist_by_code_treats_missing_store_product_as_skip(process):
    process.return_value = {"error": "product_id_not_found_on_sale", "hit": 0}

    result = delist_product_by_code(object(), {"account_id": "store_A"}, product_code="BD070Z")

    assert result["status"] == "not_found"
    assert result["message"] == "该店未找到此商品编码，已跳过"
    assert "error" not in result
    assert process.call_args.kwargs["merchant_code"] == "BD070Z"


@patch("pdd_agent.product_operations.service.search_published_products")
def test_published_product_options_group_same_code_across_stores(search):
    search.return_value = (
        [
            SimpleNamespace(
                status="on_sale",
                product_code="BD070Z",
                listing_label="BD070Z / 第一套图",
                account_id="store_A",
            ),
            SimpleNamespace(
                status="on_sale",
                product_code="BD070Z",
                listing_label="BD070Z / 第一套图",
                account_id="store_B",
            ),
            SimpleNamespace(
                status="delisted",
                product_code="BD999Z",
                listing_label="BD999Z",
                account_id="store_A",
            ),
        ],
        3,
    )

    options = list_published_product_options()

    assert options == [
        {
            "product_code": "BD070Z",
            "listing_label": "BD070Z / 第一套图",
            "account_ids": ["store_A", "store_B"],
            "record_count": 2,
            "shop_count": 2,
        }
    ]


@patch("pdd_agent.product_operations.service.enqueue_delist_task")
@patch("pdd_agent.product_operations.service.create_delist_run")
@patch("pdd_agent.product_operations.service.resolve_enabled_account_ids")
@patch("pdd_agent.product_operations.service.TaskRunStore")
def test_delist_all_stores_queues_same_product_code_for_every_store(
    store_cls,
    resolve_accounts,
    create_run,
    enqueue,
):
    resolve_accounts.return_value = (["store_A", "store_B"], [])
    create_run.side_effect = ["run-a", "run-b"]

    rows = enqueue_product_code_delist_all_stores("BD070Z")

    assert [row["account_id"] for row in rows] == ["store_A", "store_B"]
    assert enqueue.call_count == 2
    assert enqueue.call_args_list[0].kwargs["delist_params"] == {
        "merchant_code": "BD070Z",
        "dry_run": False,
        "mode": "product_operations_code",
    }
    assert store_cls.return_value.update_status.call_count == 2
