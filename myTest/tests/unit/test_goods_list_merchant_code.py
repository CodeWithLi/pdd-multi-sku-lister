"""商品列表商品编码解析：截断与 hover 匹配。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.skills.listing.goods_list_capture import (
    _read_merchant_code_from_ellipsis_dom,
    _read_merchant_code_from_tooltips,
    is_truncated_merchant_code,
    merchant_code_matches_query,
    read_merchant_code_from_row_hover,
    resolve_row_merchant_code,
)


def test_is_truncated_merchant_code():
    assert is_truncated_merchant_code("AXBD00...") is True
    assert is_truncated_merchant_code("AXBD001A") is False


def test_merchant_code_matches_query_full_text():
    row = MagicMock()
    text = "商品编码: AXBD001A\nID:971990547400"
    assert merchant_code_matches_query(row, text, "AXBD001A") is True


def test_merchant_code_matches_query_rejects_truncated_without_hover():
    row = MagicMock()
    row._loc = None
    text = "商品编码: AXBD00...\nID:971990547400"
    assert merchant_code_matches_query(row, text, "AXBD001A") is True


def test_merchant_code_matches_query_rejects_unrelated_truncated_prefix():
    row = MagicMock()
    row._loc = None
    text = "商品编码: BD029...\nID:971990547400"
    assert merchant_code_matches_query(row, text, "AXBD001A") is False


def test_merchant_code_matches_query_with_hover_tooltip(monkeypatch):
    row = MagicMock()
    row._loc = MagicMock()
    row._page = MagicMock()
    text = "商品编码: AXBD00...\nID:971990547400"

    monkeypatch.setattr(
        "pdd_agent.skills.listing.goods_list_capture.read_merchant_code_from_row_hover",
        lambda _row: "AXBD001A",
    )
    assert merchant_code_matches_query(row, text, "AXBD001A") is True


def test_resolve_row_merchant_code_uses_hover_when_truncated(monkeypatch):
    row = MagicMock()
    text = "商品编码: AXBD00..."
    monkeypatch.setattr(
        "pdd_agent.skills.listing.goods_list_capture.read_merchant_code_from_row_hover",
        lambda _row: "AXBD001A",
    )
    assert resolve_row_merchant_code(row, text) == "AXBD001A"


def test_read_merchant_code_from_row_hover_reads_beast_core_tooltip():
    row = MagicMock()
    row_loc = MagicMock()
    hover_target = MagicMock()
    hover_target.count.return_value = 1
    hover_target.first = hover_target
    hover_target.bounding_box.return_value = {"x": 10, "y": 20, "width": 100, "height": 16}

    tip = MagicMock()
    tip.is_visible.return_value = True
    tip.inner_text.return_value = "商品编码: AXBD001A"

    tooltip_roots = MagicMock()
    tooltip_roots.count.return_value = 1
    tooltip_roots.nth.return_value = tip

    row._loc = row_loc
    row._page = MagicMock()
    row._page.locator.return_value = tooltip_roots
    row._page.mouse = MagicMock()

    row_loc.evaluate.return_value = ""
    row_loc.locator.return_value.filter.return_value.count.return_value = 1
    row_loc.locator.return_value.filter.return_value.first = hover_target
    hover_target.get_attribute.return_value = ""
    hover_target.locator.return_value.count.return_value = 0

    assert read_merchant_code_from_row_hover(row) == "AXBD001A"
    row._page.mouse.move.assert_called_once()


def test_read_merchant_code_from_ellipsis_dom():
    row_loc = MagicMock()
    row_loc.evaluate.return_value = "商品编码: AXBD001A"
    assert _read_merchant_code_from_ellipsis_dom(row_loc) == "AXBD001A"


def test_read_merchant_code_from_tooltips_reads_portal():
    raw_page = MagicMock()
    tip = MagicMock()
    tip.is_visible.return_value = True
    tip.inner_text.return_value = "商品编码: AXBD001A"

    tips = MagicMock()
    tips.count.return_value = 0

    portal = MagicMock()
    portal.count.return_value = 1
    portal.last = tip

    def locator_side_effect(selector: str):
        if selector == '[data-testid="beast-core-portal-main"]':
            filtered = MagicMock()
            filtered.count.return_value = 1
            filtered.last = tip
            return MagicMock(filter=MagicMock(return_value=filtered))
        roots = MagicMock()
        roots.count.return_value = 0
        return roots

    raw_page.locator.side_effect = locator_side_effect
    assert _read_merchant_code_from_tooltips(raw_page) == "AXBD001A"
