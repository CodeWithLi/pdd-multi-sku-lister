"""inventory_goods_list_relist 行匹配单元测试。"""

from pdd_agent.skills.relist.inventory_goods_list_relist import (
    PRODUCT_ID_MISMATCH_MESSAGE,
    _pick_row_by_product_id,
    _pick_row_by_strategy,
)


def _row(product_id: str, merchant_code: str = "BD069") -> dict:
    return {
        "product_id": product_id,
        "merchant_code": merchant_code,
        "row_text": f"ID {product_id} 商品编码:{merchant_code}",
    }


def test_pick_row_by_product_id_matches_second_row():
    rows = [_row("773133242445", "BD069-4.8"), _row("615639558451", "BD069")]
    picked, index = _pick_row_by_product_id(rows, "615639558451")
    assert picked is not None
    assert picked["product_id"] == "615639558451"
    assert index == 2


def test_pick_row_by_product_id_returns_none_when_missing():
    rows = [_row("773133242445"), _row("615639558451")]
    picked, index = _pick_row_by_product_id(rows, "999999999999")
    assert picked is None
    assert index == 0


def test_pick_row_by_strategy_uses_product_id_when_provided():
    rows = [_row("773133242445"), _row("615639558451")]
    picked, index = _pick_row_by_strategy(
        rows,
        "BD069",
        strategy="by_product_id",
        target_product_id="615639558451",
    )
    assert picked is not None
    assert picked["product_id"] == "615639558451"
    assert index == 2


def test_pick_row_by_strategy_falls_back_to_first_without_target_id():
    rows = [_row("773133242445"), _row("615639558451")]
    picked, index = _pick_row_by_strategy(rows, "BD069", strategy="first")
    assert picked is not None
    assert picked["product_id"] == "773133242445"
    assert index == 1


def test_product_id_mismatch_message_constant():
    assert "商品id匹配不上" in PRODUCT_ID_MISMATCH_MESSAGE
