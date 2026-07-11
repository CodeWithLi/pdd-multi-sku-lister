"""新店铺规格 UI 检测与分流单元测试。"""

from unittest.mock import MagicMock

from pdd_agent.skills.listing import multi_spec_page_new_shop as nsp


def test_parse_new_shop_detect_result_true():
    assert nsp.parse_new_shop_detect_result({"isNew": True, "reason": "wrapper"}) == (
        True,
        "wrapper",
    )


def test_parse_new_shop_detect_result_false():
    assert nsp.parse_new_shop_detect_result({"isNew": False, "reason": "old_row_box"}) == (
        False,
        "old_row_box",
    )


def test_parse_new_shop_detect_result_none():
    assert nsp.parse_new_shop_detect_result(None) == (False, "none")


def test_is_new_shop_spec_ui_via_js():
    page = MagicMock()
    page.run_js.return_value = {"isNew": True, "reason": "wrapper"}
    assert nsp.is_new_shop_spec_ui(page, account_id="acc1") is True


def test_is_new_shop_spec_ui_old_row_box():
    page = MagicMock()
    page.run_js.return_value = {"isNew": False, "reason": "old_row_box"}
    assert nsp.is_new_shop_spec_ui(page, account_id="acc1") is False


def test_is_new_shop_spec_ui_fallback_wrapper():
    page = MagicMock()
    page.run_js.side_effect = RuntimeError("no js")
    container = MagicMock()
    container.eles.side_effect = lambda sel: [] if "row-box" in sel else []
    container.ele.side_effect = lambda sel, **kw: MagicMock() if "wrapper" in sel else None
    page.ele.side_effect = lambda sel, **kw: (
        container
        if sel == "#spec"
        else MagicMock()
        if "添加规格类型" in str(sel)
        else None
    )
    assert nsp.is_new_shop_spec_ui(page, account_id="acc1") is True


def test_add_style_and_model_specs_auto_routes_new_shop(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(nsp, "is_new_shop_spec_ui", lambda _p, account_id="": True)
    monkeypatch.setattr(
        nsp,
        "add_style_and_model_specs_new_shop",
        lambda *_a, **_k: "new",
    )
    monkeypatch.setattr(
        nsp,
        "add_style_and_model_specs",
        lambda *_a, **_k: "old",
    )
    assert nsp.add_style_and_model_specs_auto(page, "acc1", ["红"], ["大"]) == "new"


def test_add_style_and_model_specs_auto_routes_old_shop(monkeypatch):
    page = MagicMock()
    monkeypatch.setattr(nsp, "is_new_shop_spec_ui", lambda _p, account_id="": False)
    monkeypatch.setattr(
        nsp,
        "add_style_and_model_specs_new_shop",
        lambda *_a, **_k: "new",
    )
    monkeypatch.setattr(
        nsp,
        "add_style_and_model_specs",
        lambda *_a, **_k: "old",
    )
    assert nsp.add_style_and_model_specs_auto(page, "acc1", ["红"], ["大"]) == "old"
