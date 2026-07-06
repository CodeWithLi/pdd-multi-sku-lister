from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pdd_agent.skills.campaign.limited_time_partial_selection import (
    continue_product_selection_after_partial_rows,
    is_partial_rows_failure,
    narrow_scope_to_selected_products,
    select_campaign_products_allow_partial,
)


def test_is_partial_rows_failure_true_when_some_selected():
    assert is_partial_rows_failure(
        {
            "status": "failed",
            "step": "select_product_rows",
            "selected_ids": ["111"],
            "missing_ids": ["222"],
        }
    )


def test_is_partial_rows_failure_false_when_no_selected():
    assert not is_partial_rows_failure(
        {
            "status": "failed",
            "step": "select_product_rows",
            "selected_ids": [],
            "missing_ids": ["222"],
        }
    )


def test_is_partial_rows_failure_false_on_success():
    assert not is_partial_rows_failure({"status": "success", "step": "product_selected"})


@patch("pdd_agent.skills.campaign.limited_time_partial_selection.continue_product_selection_after_partial_rows")
@patch("pdd_agent.skills.campaign.limited_time._select_campaign_products")
def test_select_campaign_products_allow_partial_continues(mock_select, mock_continue):
    page = MagicMock()
    mock_select.return_value = {
        "status": "failed",
        "step": "select_product_rows",
        "selected_ids": ["111", "222"],
        "missing_ids": ["333"],
        "target_ids": ["111", "222", "333"],
        "batches": [],
        "error": "未能勾选商品ID：333",
    }
    mock_continue.return_value = {"status": "success", "partial_success": True, "selected_ids": ["111", "222"]}

    result = select_campaign_products_allow_partial(page, "store_A", ["111", "222", "333"])

    mock_continue.assert_called_once()
    assert result["status"] == "success"
    assert result["partial_success"] is True


@patch("pdd_agent.skills.campaign.limited_time._select_campaign_products")
def test_select_campaign_products_allow_partial_passthrough_success(mock_select):
    page = MagicMock()
    mock_select.return_value = {"status": "success", "selected_ids": ["111"]}

    result = select_campaign_products_allow_partial(page, "store_A", ["111"])

    assert result["status"] == "success"
    mock_select.assert_called_once_with(page, "store_A", ["111"])


@patch("pdd_agent.skills.campaign.limited_time._wait_activity_selected_products")
@patch("pdd_agent.skills.campaign.limited_time._wait_activity_settings")
@patch("pdd_agent.skills.campaign.limited_time._ensure_page_binding", return_value=True)
@patch("pdd_agent.skills.campaign.limited_time._dismiss_product_modal_after_confirm")
@patch("pdd_agent.skills.campaign.limited_time._confirm_product_selection")
@patch("pdd_agent.skills.campaign.limited_time._activity_has_selected_products", return_value=True)
@patch("pdd_agent.skills.campaign.limited_time_partial_selection.time.sleep")
def test_continue_product_selection_after_partial_rows_success(
    _sleep,
    _has_selected,
    mock_confirm,
    mock_dismiss,
    _ensure_bind,
    _wait_settings,
    mock_wait_selected,
):
    page = MagicMock()
    mock_confirm.return_value = {"clicked": True}
    mock_dismiss.return_value = {"closed": True}
    mock_wait_selected.return_value = {"ids": ["111", "222"]}

    result = continue_product_selection_after_partial_rows(
        page,
        "store_A",
        selected_ids=["111", "222"],
        missing_ids=["333"],
        target_ids=["111", "222", "333"],
        batches=[],
    )

    assert result["status"] == "success"
    assert result["partial_success"] is True
    assert result["selected_ids"] == ["111", "222"]
    assert "333" in result["partial_skip_reason"]
    mock_dismiss.assert_called_once()
    assert mock_dismiss.call_args.args[2] == ["111", "222"]


@patch(
    "pdd_agent.skills.campaign.limited_time_partial_selection.get_published_products_by_pdd_product_ids",
    return_value=[SimpleNamespace(mapping_id="map_1"), SimpleNamespace(mapping_id="map_2")],
)
def test_narrow_scope_to_selected_products_filters_mapping(_mock_rows):
    selection = {
        "status": "success",
        "selected_ids": ["111", "222"],
        "missing_ids": ["333"],
        "partial_success": True,
    }
    pdd_ids, mapping_ids, meta = narrow_scope_to_selected_products(
        "store_A",
        ["111", "222", "333"],
        ["map_1", "map_2", "map_3"],
        selection,
    )

    assert pdd_ids == ["111", "222"]
    assert mapping_ids == ["map_1", "map_2"]
    assert meta["scope_applied"] is True
    assert meta["skipped_pdd_product_ids"] == ["333"]


def test_narrow_scope_unchanged_when_all_selected():
    selection = {"status": "success", "selected_ids": ["111", "222"]}
    pdd_ids, mapping_ids, meta = narrow_scope_to_selected_products(
        "store_A",
        ["111", "222"],
        ["map_1", "map_2"],
        selection,
    )

    assert pdd_ids == ["111", "222"]
    assert mapping_ids == ["map_1", "map_2"]
    assert meta["scope_applied"] is False
