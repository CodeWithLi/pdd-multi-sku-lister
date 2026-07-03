"""已驳回商品列表核验：编码匹配与状态判定。"""

from __future__ import annotations

from pdd_agent.skills.listing import upload as listing_upload


def test_evaluate_all_tab_row_treats_edit_rejected_as_rejected():
    selected = {
        "pdd_product_id": "916918437299",
        "merchant_code": "BD675",
        "row_text": (
            "清新少女系文具\nID: 916918437299\n商品编码: BD675\n"
            "总库存 100\n2026-07-03 10:00\n编辑已驳回\n"
            "驳回原因：您发布商品的分类与商品信息不匹配，请核实您的商品信息并选择正确分类。"
        ),
        "matched_created_at": "2026-07-03 10:00:00",
        "list_status": "编辑已驳回",
        "rejection_reason": "您发布商品的分类与商品信息不匹配，请核实您的商品信息并选择正确分类。",
        "total_inventory": 100,
    }
    result = listing_upload._evaluate_all_tab_row(selected, "BD675")
    assert result["status"] == "rejected"
    assert result["tab"] == "all"
    assert "分类与商品信息不匹配" in result["rejection_reason"]


def test_parse_goods_list_matches_skips_title_for_rejected_tab(monkeypatch):
    row_text = (
        "列表展示标题与上架标题完全不同\n"
        "ID: 916918437299\n商品编码: BD675\n"
        "编辑已驳回\n驳回原因：平台驳回测试"
    )

    class _Row:
        text = row_text

    monkeypatch.setattr(listing_upload, "merchant_code_matches_query", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(listing_upload, "extract_product_id_from_text", lambda _text: "916918437299")
    monkeypatch.setattr(
        listing_upload,
        "parse_goods_list_row_meta",
        lambda _text: {
            "matched_created_at": "",
            "list_status": "编辑已驳回",
            "rejection_reason": "平台驳回测试",
        },
    )

    class _Page:
        def eles(self, *_args, **_kwargs):
            return [_Row()]

    matches = listing_upload._parse_goods_list_matches(
        _Page(),
        "BD675",
        "上架时填的标题完全对不上",
        require_title_match=False,
    )
    assert len(matches) == 1
    assert matches[0]["rejection_reason"] == "平台驳回测试"

    no_match = listing_upload._parse_goods_list_matches(
        _Page(),
        "BD675",
        "上架时填的标题完全对不上",
        require_title_match=True,
    )
    assert no_match == []
