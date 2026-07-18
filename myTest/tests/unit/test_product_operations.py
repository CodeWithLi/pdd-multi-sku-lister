"""商品操作封装单元测试。"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pdd_agent.product_operations.automation import (
    _find_submit_button,
    _is_product_edit_url,
    _resolve_edit_destination,
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
        {"spec_code": "BD070Z", "group_price": "9.47", "single_price": "12.00"},
        {"spec_code": "BD070Z+YKL001AC", "group_price": "10.47", "single_price": "15.00"},
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
            [{"spec_code": "BD070Z", "single_price": "12.00"}],
            [
                {"spec_code": "BD070Z", "group_price": "9.99"},
                {"spec_code": "bd070z", "group_price": "10.99"},
            ],
        )


def test_validate_price_updates_allows_one_yuan_gap():
    result = validate_price_updates(
        [{"spec_code": "BD070Z", "single_price": "10.72"}],
        [{"spec_code": "BD070Z", "group_price": "9.72"}],
    )

    assert result == [{"spec_code": "BD070Z", "group_price": "9.72"}]


def test_validate_price_updates_rejects_price_above_one_yuan_gap():
    with pytest.raises(ValueError, match=r"不能高于 9\.72.*至少低 1\.00 元"):
        validate_price_updates(
            [{"spec_code": "BD070Z", "single_price": "10.72"}],
            [{"spec_code": "BD070Z", "group_price": "9.73"}],
        )


def test_validate_price_updates_uses_lowest_single_price_for_duplicate_code():
    with pytest.raises(ValueError, match="不能高于 9.72"):
        validate_price_updates(
            [
                {"spec_code": "BD070Z", "single_price": "11.00"},
                {"spec_code": "BD070Z", "single_price": "10.72"},
            ],
            [{"spec_code": "BD070Z", "group_price": "9.80"}],
        )


def test_normalize_price_keeps_two_decimals():
    assert normalize_price("9.9") == "9.90"


def test_product_edit_url_recognizes_current_routes():
    assert _is_product_edit_url("https://mms.pinduoduo.com/goods/goods_add/index?type=edit")
    assert _is_product_edit_url("https://mms.pinduoduo.com/goods/edit/123")
    assert not _is_product_edit_url("https://mms.pinduoduo.com/goods/goods_list")


def test_find_submit_button_scrolls_to_lazy_footer():
    class FakeButton:
        def is_visible(self, timeout):
            return True

        def is_enabled(self, timeout):
            return True

    button = FakeButton()

    class FakeLocator:
        def count(self):
            return 1

        def nth(self, index):
            assert index == 0
            return button

    evaluated = []
    raw_page = SimpleNamespace(
        evaluate=lambda script: evaluated.append(script),
        locator=lambda selector: FakeLocator() if selector == "#submit_button" else None,
        get_by_role=lambda *args, **kwargs: FakeLocator(),
    )

    found = _find_submit_button(SimpleNamespace(_page=raw_page))

    assert found is button
    assert evaluated == ["() => window.scrollTo(0, document.documentElement.scrollHeight)"]


def test_resolve_edit_destination_prefers_captured_window_open_url():
    raw_page = SimpleNamespace(
        url="https://mms.pinduoduo.com/goods/goods_list",
        evaluate=lambda _script: "/goods/goods_add/index?goods_id=978262777327&type=edit",
        context=SimpleNamespace(pages=[]),
    )

    edit_url, edit_page = _resolve_edit_destination(
        SimpleNamespace(_page=raw_page),
        pages_before=[],
        source_url=raw_page.url,
    )

    assert edit_url.endswith("goods_id=978262777327&type=edit")
    assert edit_page is None


def test_resolve_edit_destination_accepts_current_page_or_new_tab():
    source_url = "https://mms.pinduoduo.com/goods/goods_list"
    current_page = SimpleNamespace(
        url="https://mms.pinduoduo.com/goods/goods_add/index?type=edit",
        evaluate=lambda _script: "",
        context=SimpleNamespace(pages=[]),
    )
    edit_url, edit_page = _resolve_edit_destination(
        SimpleNamespace(_page=current_page),
        pages_before=[],
        source_url=source_url,
    )
    assert edit_url == ""
    assert edit_page is current_page

    list_page = SimpleNamespace(
        url=source_url,
        evaluate=lambda _script: "",
        is_closed=lambda: False,
    )
    new_page = SimpleNamespace(
        url="https://mms.pinduoduo.com/goods/goods_add/index?type=edit",
        is_closed=lambda: False,
    )
    list_page.context = SimpleNamespace(pages=[list_page, new_page])
    edit_url, edit_page = _resolve_edit_destination(
        SimpleNamespace(_page=list_page),
        pages_before=[list_page],
        source_url=source_url,
    )
    assert edit_url == ""
    assert edit_page is new_page


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
