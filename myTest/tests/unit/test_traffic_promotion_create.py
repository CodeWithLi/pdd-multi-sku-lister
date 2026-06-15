from unittest.mock import patch

from pdd_agent.skills.traffic.promotion_create import (
    _click_begin_promotion_button,
    _click_promotion_edit_bid_icons,
    _ensure_global_boost_checkbox_unchecked,
    _is_add_promotion_product_drawer,
    _is_product_promotion_create_page,
    _is_promotion_overview_page,
    _is_promotion_search_empty_text,
    _is_promotion_search_result_empty,
    _is_unwanted_tab_url,
    _parse_roi_bid_limit_price,
)


class FakeDpPage:
    def __init__(self, url: str, body_text: str):
        self.url = url
        self._body_text = body_text

    def run_js(self, *_args, **_kwargs):
        return {}


def test_is_promotion_overview_page_detects_product_tab_and_create_button():
    page = FakeDpPage(
        "https://yingxiao.pinduoduo.com/mains/promotionOverview",
        "商品推广 全店推广 实时概况 推广中 余额不足 + 新建推广 账户余额 数据总览",
    )
    with patch("pdd_agent.skills.traffic.promotion_create._body_text", return_value=page._body_text):
        assert _is_promotion_overview_page(page) is True


def test_is_promotion_overview_page_rejects_mms_goods_list():
    page = FakeDpPage(
        "https://mms.pinduoduo.com/goods/goods_list",
        "商品推广 商品列表 发布新商品",
    )
    with patch("pdd_agent.skills.traffic.promotion_create._body_text", return_value=page._body_text):
        assert _is_promotion_overview_page(page) is False


def test_is_product_promotion_create_page_by_url():
    page = FakeDpPage(
        "https://yingxiao.pinduoduo.com/marketing/main/create/double",
        "",
    )
    assert _is_product_promotion_create_page(page) is True


def test_is_product_promotion_create_page_by_mms_url():
    page = FakeDpPage(
        "https://mms.pinduoduo.com/mms/promotion/create",
        "",
    )
    assert _is_product_promotion_create_page(page) is True


def test_is_product_promotion_create_page_by_content():
    page = FakeDpPage(
        "https://mms.pinduoduo.com/mms/promotion/overview",
        "推广计划 基础信息 推广方案 oCPX 单元配置 选择商品 完成",
    )
    with patch("pdd_agent.skills.traffic.promotion_create._body_text", return_value=page._body_text):
        assert _is_product_promotion_create_page(page) is True


def test_is_product_promotion_create_page_rejects_overview():
    page = FakeDpPage(
        "https://yingxiao.pinduoduo.com/mms/overview",
        "商品推广 实时概况 新建推广",
    )
    with patch("pdd_agent.skills.traffic.promotion_create._body_text", return_value=page._body_text):
        assert _is_product_promotion_create_page(page) is False


def test_is_add_promotion_product_drawer_detects_drawer():
    page = FakeDpPage(
        "https://yingxiao.pinduoduo.com/mains/promotionOverview",
        "添加推广商品 可推广商品 633 商品ID 查询 重置",
    )
    with patch(
        "pdd_agent.skills.traffic.promotion_create._read_add_product_drawer_state",
        return_value={"visible": True, "has_query": True},
    ):
        assert _is_add_promotion_product_drawer(page) is True


def test_is_add_promotion_product_drawer_rejects_overview_only():
    page = FakeDpPage(
        "https://mms.pinduoduo.com/mms/promotion/overview",
        "商品推广 实时概况 新建推广",
    )
    with patch("pdd_agent.skills.traffic.promotion_create._body_text", return_value=page._body_text):
        assert _is_add_promotion_product_drawer(page) is False


def test_is_unwanted_tab_url_detects_home():
    assert _is_unwanted_tab_url("https://mms.pinduoduo.com/home/") is True
    assert _is_unwanted_tab_url("https://yingxiao.pinduoduo.com/mains/promotionOverview") is False


def test_is_product_promotion_create_page_accepts_drawer():
    page = FakeDpPage(
        "https://yingxiao.pinduoduo.com/mains/promotionOverview",
        "添加推广商品 可推广商品 633 商品ID 查询 重置",
    )
    with patch(
        "pdd_agent.skills.traffic.promotion_create._read_add_product_drawer_state",
        return_value={"visible": True, "has_query": True},
    ):
        assert _is_product_promotion_create_page(page) is True


def test_is_promotion_search_empty_text_detects_zero_header_only():
    text = "推广商品 (0) 未查询到目标商品，可 查看商品是否已创建推广"
    assert _is_promotion_search_empty_text(text) is True


def test_is_promotion_search_empty_text_ignores_footer_help_when_product_found():
    text = (
        "推广商品 (1) 965180544666 净目标投产比 "
        "若未查询到目标商品，可 查看商品是否已创建推广"
    )
    assert _is_promotion_search_empty_text(text) is False


def test_is_promotion_search_result_empty_rejects_found_product_state():
    state = {
        "empty": True,
        "has_products": True,
        "product_count": 1,
        "header_count": 1,
        "product_ids": ["965180544666"],
    }
    assert _is_promotion_search_result_empty(state) is False


def test_is_promotion_search_result_empty_when_header_zero():
    state = {
        "has_products": True,
        "product_count": 1,
        "header_count": 0,
        "product_ids": ["962138900435"],
    }
    assert _is_promotion_search_result_empty(state) is True


def test_click_promotion_edit_bid_icons_fails_when_search_empty():
    page = FakeDpPage(
        "https://yingxiao.pinduoduo.com/mains/promotionOverview",
        "添加推广商品 推广商品 (0) 未查询到目标商品，可 查看商品是否已创建推广",
    )
    with (
        patch(
            "pdd_agent.skills.traffic.promotion_create._wait_promotion_search_result",
            return_value={
                "ready": True,
                "empty": True,
                "has_products": False,
                "product_count": 0,
                "header_count": 0,
                "product_ids": [],
            },
        ),
        patch("pdd_agent.skills.traffic.promotion_create._body_text", return_value=page._body_text),
    ):
        result = _click_promotion_edit_bid_icons(page, "store_A", ["965180544565"])
    assert result["status"] == "failed"
    assert result["step"] == "promotion_search_empty"


def test_click_begin_promotion_button_by_testid():
    page = FakeDpPage("https://yingxiao.pinduoduo.com/mains/promotionOverview", "")
    with patch.object(
        page,
        "run_js",
        return_value={
            "clicked": True,
            "text": "开启推广 (2/30)",
            "method": "beginPromotionButton_testid",
            "testid": "beginPromotionButton",
        },
    ):
        result = _click_begin_promotion_button(page, "store_A")
    assert result["clicked"] is True
    assert "开启推广" in result["text"]


def test_ensure_global_boost_checkbox_unchecked_when_already_off():
    page = FakeDpPage("https://yingxiao.pinduoduo.com/mains/promotionOverview", "")
    with patch(
        "pdd_agent.skills.traffic.promotion_create._read_global_boost_checkbox_state",
        return_value={"found": True, "checked": False, "testid": "create_goods_additional_max_cost_checkbox"},
    ):
        result = _ensure_global_boost_checkbox_unchecked(page, "store_A")
    assert result["status"] == "success"
    assert result["unchecked"] is True


def test_ensure_global_boost_checkbox_unchecked_clicks_when_checked():
    page = FakeDpPage("https://yingxiao.pinduoduo.com/mains/promotionOverview", "")
    with (
        patch(
            "pdd_agent.skills.traffic.promotion_create._wait_global_boost_checkbox",
            return_value={
                "found": True,
                "checked": True,
                "testid": "create_goods_additional_max_cost_checkbox",
            },
        ),
        patch(
            "pdd_agent.skills.traffic.promotion_create._read_global_boost_checkbox_state",
            return_value={"found": True, "checked": True, "testid": "create_goods_additional_max_cost_checkbox"},
        ),
        patch.object(
            page,
            "run_js",
            return_value={"changed": True, "found": True, "checked": True, "was_checked": True},
        ),
        patch(
            "pdd_agent.skills.traffic.promotion_create._finalize_global_boost_uncheck",
            return_value={
                "status": "success",
                "unchecked": True,
                "confirm_result": {"clicked": True, "method": "confirm_close_text_button"},
            },
        ) as finalize_mock,
    ):
        result = _ensure_global_boost_checkbox_unchecked(page, "store_A")
    assert result["status"] == "success"
    assert result["unchecked"] is True
    finalize_mock.assert_called()


def test_parse_roi_bid_limit_price_extracts_suggested_value():
    text = "请降低至 3.12 及以下，进入二阶段后你可以结合经营情况，自行调整出价"
    assert _parse_roi_bid_limit_price(text) == "3.12"


def test_click_promotion_edit_bid_icons_clicks_each_found_product():
    page = FakeDpPage("https://yingxiao.pinduoduo.com/mains/promotionOverview", "")
    with (
        patch(
            "pdd_agent.skills.traffic.promotion_create._wait_promotion_search_result",
            return_value={
                "ready": True,
                "empty": False,
                "product_count": 1,
                "product_ids": ["965180544565"],
                "header_count": 1,
                "edit_icons": [{"product_id": "965180544565", "testid": "editBid_965180544565_create_create"}],
            },
        ),
        patch(
            "pdd_agent.skills.traffic.promotion_create._click_promotion_edit_bid_icon",
            return_value={"clicked": True, "product_id": "965180544565"},
        ) as click_mock,
        patch(
            "pdd_agent.skills.traffic.promotion_create._wait_roi_bid_modal",
            return_value={"ready": True},
        ),
        patch(
            "pdd_agent.skills.traffic.promotion_create._configure_roi_bid_for_product",
            return_value={
                "status": "success",
                "product_id": "965180544565",
                "suggested_price": "3.12",
            },
        ) as config_mock,
    ):
        result = _click_promotion_edit_bid_icons(
            page,
            "store_A",
            ["965180544565", "962138900436"],
        )
    assert result["status"] == "success"
    assert result["step"] == "roi_bid_configured"
    assert result["found_product_ids"] == ["965180544565"]
    assert result["configured_prices"] == {"965180544565": "3.12"}
    click_mock.assert_called_once_with(page, "965180544565")
    config_mock.assert_called_once_with(page, "965180544565", "store_A")
