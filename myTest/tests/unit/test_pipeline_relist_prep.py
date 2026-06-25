"""整合链路下架预备单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock


def test_verify_shop_mismatch_blocks_delist(monkeypatch):
    from pdd_agent.browser.shop_display_name import verify_shop_for_account

    monkeypatch.setattr(
        "pdd_agent.browser.shop_display_name.get_cached_shop_display_name",
        lambda _aid: "兔兔潮玩屋",
    )
    monkeypatch.setattr(
        "pdd_agent.browser.shop_display_name.scrape_shop_display_name",
        lambda _dp, **kw: "其他店铺",
    )

    result = verify_shop_for_account("多多李子2601", MagicMock(), login_username="多多李子2601")
    assert not result.ok
    assert result.error == "shop_display_name_mismatch"


def test_relist_prep_batch_filter_and_delist_once(monkeypatch):
    from pdd_agent.skills.delist import pipeline_relist_prep as mod

    page = MagicMock()
    filter_calls: list[list[str]] = []
    batch_calls: list[str] = []

    monkeypatch.setattr(mod, "open_goods_list_on_sale", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mod,
        "verify_shop_for_account",
        lambda *_a, **_k: MagicMock(ok=True, expected="兔兔潮玩屋", actual="兔兔潮玩屋", error=""),
    )
    monkeypatch.setattr(
        mod,
        "filter_goods_by_merchant_codes",
        lambda _page, aid, codes: filter_calls.append(list(codes)) or True,
    )
    monkeypatch.setattr(
        mod,
        "scan_filtered_product_rows_all_pages",
        lambda _page, _aid, merchant_codes=None: [
            {"product_id": "111", "merchant_code": "BD001"},
            {"product_id": "222", "merchant_code": "BD002"},
        ],
    )
    monkeypatch.setattr(
        mod,
        "batch_delist_filtered_goods",
        lambda _page, aid, dry_run=False: batch_calls.append(aid) or (2, []),
    )

    stats = mod.process_pipeline_relist_prep_delist(
        page,
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        [
            {"selector": "a/b/BD001", "merchant_code": "BD001", "mapping_id": "m1"},
            {"selector": "a/b/BD002", "merchant_code": "BD002", "mapping_id": "m2"},
        ],
    )

    assert filter_calls == [["BD001", "BD002"], ["BD001", "BD002"]]
    assert batch_calls == ["多多李子2601"]
    assert stats["hit"] == 2
    assert all(item.get("status") == "delisted" for item in stats["results"] if "target_product_id" in item)


def test_match_merchant_code_prefers_longest_full_name():
    from pdd_agent.skills.delist.automation import _match_merchant_code_in_row

    codes = ["BD029A", "BD029A卡皮巴拉笔袋"]
    text = "商品编码 BD029A卡皮巴拉笔袋 ID：969787125550"
    assert _match_merchant_code_in_row(text, codes) == "BD029A卡皮巴拉笔袋"


def test_relist_prep_aborts_on_shop_mismatch(monkeypatch):
    from pdd_agent.skills.delist import pipeline_relist_prep as mod

    monkeypatch.setattr(mod, "open_goods_list_on_sale", lambda *_a, **_k: True)
    monkeypatch.setattr(
        mod,
        "verify_shop_for_account",
        lambda *_a, **_k: MagicMock(
            ok=False,
            expected="兔兔潮玩屋",
            actual="别的店",
            error="shop_display_name_mismatch",
        ),
    )
    batch = MagicMock()
    monkeypatch.setattr(mod, "batch_delist_filtered_goods", batch)

    stats = mod.process_pipeline_relist_prep_delist(
        MagicMock(),
        {"account_id": "多多李子2601", "username": "多多李子2601"},
        [{"selector": "a/b/BD001", "merchant_code": "BD001"}],
    )

    assert "店铺校验失败" in stats["errors"][0]
    batch.assert_not_called()
