"""goods_list_capture 解析单元测试。"""

from dy_agent.skills.listing.goods_list_capture import (
    extract_list_status_from_text,
    extract_list_time_from_text,
    extract_product_id_from_text,
)


def test_extract_product_id_from_text():
    text = "简约ins音乐小猫\nID: 3830912963376709924\n现货模式"
    assert extract_product_id_from_text(text) == "3830912963376709924"


def test_extract_list_time_from_text():
    text = "2026/07/13 10:27:44\n售卖中"
    assert extract_list_time_from_text(text) == "2026/07/13 10:27:44"


def test_extract_list_status_from_text():
    text = "2026/07/13 10:27:44\n售卖中"
    assert extract_list_status_from_text(text) == "售卖中"
