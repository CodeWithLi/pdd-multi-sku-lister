from unittest.mock import patch

from pdd_agent.skills.traffic.promotion_create import (
    _is_add_promotion_product_drawer,
    _is_product_promotion_create_page,
    _is_promotion_overview_page,
    _is_unwanted_tab_url,
)


class FakeDpPage:
    def __init__(self, url: str, body_text: str):
        self.url = url
        self._body_text = body_text


def test_is_promotion_overview_page_detects_product_tab_and_create_button():
    page = FakeDpPage(
        "https://mms.pinduoduo.com/mms/promotion/overview",
        "商品推广 全店推广 实时概况 推广中 余额不足 + 新建推广 账户余额",
    )
    with patch("pdd_agent.skills.traffic.promotion_create._body_text", return_value=page._body_text):
        assert _is_promotion_overview_page(page) is True


def test_is_promotion_overview_page_rejects_not_found():
    page = FakeDpPage(
        "https://yingxiao.pinduoduo.com/mms/overview",
        "页面不存在 返回概况页",
    )
    with patch("pdd_agent.skills.traffic.promotion_create._body_text", return_value=page._body_text):
        assert _is_promotion_overview_page(page) is False


def test_is_promotion_overview_page_rejects_goods_list():
    page = FakeDpPage(
        "https://mms.pinduoduo.com/goods/goods_list",
        "商品列表 发布新商品 批量下架",
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
