"""批量下架 — 商品编码解析与匹配逻辑单元测试。"""

from unittest.mock import MagicMock

from pdd_agent.skills.delist.automation import (
    _normalize_merchant_code_list,
    _search_code_matches_row,
    extract_merchant_code_from_row_text,
    extract_spec_codes_from_row_text,
    match_row_merchant_code,
    merchant_code_matches_expected,
    verify_row_safe_to_delist,
)


def test_extract_merchant_code_from_row_text_full_name():
    text = "商品编码: BD020A抽绳KT笔袋 ID:970478951304"
    assert extract_merchant_code_from_row_text(text) == "BD020A抽绳KT笔袋"


def test_extract_merchant_code_from_row_text_with_space_before_id():
    text = "商品编码: BD029A 涂鸦KT笔袋 ID:123456"
    assert extract_merchant_code_from_row_text(text) == "BD029A"


def test_extract_merchant_code_stops_before_multiline_row_content():
    text = "商品编码: BD020A抽绳KT笔袋\n\n14.98～22.03\n修改价格\n23010"
    assert extract_merchant_code_from_row_text(text) == "BD020A抽绳KT笔袋"


def test_search_code_matches_row_exact_only():
    assert _search_code_matches_row("BD014A印花KT笔袋", "BD014A印花KT笔袋") is True
    assert _search_code_matches_row("BD014A", "BD014A印花KT笔袋") is False
    assert _search_code_matches_row("BD014", "BD014A印花KT笔袋") is False
    assert _search_code_matches_row("BD029A", "BD029A") is True


def test_search_code_matches_row_rejects_similar_prefix():
    assert _search_code_matches_row("BD029", "BD029A") is False
    assert _search_code_matches_row("BD029B", "BD029A") is False


def test_merchant_code_exact_match_only():
    expected = {"BD014A印花KT笔袋", "BD020A抽绳KT笔袋"}
    assert merchant_code_matches_expected("BD014A印花KT笔袋", expected) == "BD014A印花KT笔袋"
    assert merchant_code_matches_expected("BD014A", expected) == ""
    assert merchant_code_matches_expected("BD014", expected) == ""
    assert merchant_code_matches_expected("BD020A", expected) == ""


def test_verify_row_safe_to_delist_exact_code_and_id():
    row = MagicMock()
    row.text = "商品编码: BD014A印花KT笔袋 ID:970478951304"
    ok, reason = verify_row_safe_to_delist(
        row,
        product_id="970478951304",
        matched_code="BD014A印花KT笔袋",
        expected_codes={"BD014A印花KT笔袋"},
    )
    assert ok is True
    assert reason == "ok"


def test_verify_row_safe_to_delist_rejects_prefix_code():
    row = MagicMock()
    row.text = "商品编码: BD014A ID:970478951304"
    ok, reason = verify_row_safe_to_delist(
        row,
        product_id="970478951304",
        matched_code="BD014A印花KT笔袋",
        expected_codes={"BD014A印花KT笔袋"},
    )
    assert ok is False
    assert reason.startswith("merchant_code_mismatch")


def test_verify_row_safe_to_delist_allows_same_code_multiple_links():
    row = MagicMock()
    row.text = "商品编码: BD014A印花KT笔袋 ID:970478951304"
    ok, reason = verify_row_safe_to_delist(
        row,
        product_id="970478951304",
        matched_code="BD014A印花KT笔袋",
        expected_codes={"BD014A印花KT笔袋"},
        known_product_ids={"999999999999"},
    )
    assert ok is True
    assert reason == "ok"


def test_normalize_merchant_code_list_preserves_full_name():
    assert _normalize_merchant_code_list(["BD014A印花KT笔袋", "BD014B印花KT笔袋"]) == [
        "BD014A印花KT笔袋",
        "BD014B印花KT笔袋",
    ]


def test_normalize_merchant_code_list_split_multiple():
    assert _normalize_merchant_code_list(["BD001, BD002", "BD003 BD004"]) == [
        "BD001",
        "BD002",
        "BD003",
        "BD004",
    ]


def test_chunk_merchant_codes_for_search():
    from pdd_agent.skills.delist.automation import (
        DELIST_MERCHANT_CODE_SEARCH_BATCH_SIZE,
        chunk_merchant_codes_for_search,
    )

    codes = [f"BD{i:03d}" for i in range(1, 12)]
    batches = chunk_merchant_codes_for_search(codes)
    assert len(batches) == 3
    assert len(batches[0]) == DELIST_MERCHANT_CODE_SEARCH_BATCH_SIZE
    assert batches[-1] == ["BD011"]


def test_extract_spec_codes_from_row_text():
    text = "商品编码: BD076\n规格编码: BD667B\nID:969787125550"
    assert extract_spec_codes_from_row_text(text) == ["BD667B"]


def test_match_row_merchant_code_by_spec_code():
    text = "商品编码: BD076\n规格编码: BD667B\nID:969787125550"
    assert match_row_merchant_code(text, {"BD667B"}) == "BD667B"
    assert match_row_merchant_code(text, {"BD667A"}) == ""
    assert match_row_merchant_code(text, {"BD076"}) == "BD076"


def test_search_has_matching_rows_requires_exact_row_match():
    from unittest.mock import MagicMock, patch

    from pdd_agent.skills.delist.automation import _search_has_matching_rows

    page = MagicMock()
    rows = [
        {
            "row_text": "商品编码: BD014B印花KT笔袋 ID:970592396338",
            "merchant_code": "BD014B印花KT笔袋",
            "product_id": "970592396338",
        }
    ]
    with patch("pdd_agent.skills.delist.automation._scan_filtered_rows_on_page", return_value=rows):
        assert _search_has_matching_rows(page, ["BD014B印花KT笔袋"], filter_label="规格编码") is True
        assert _search_has_matching_rows(page, ["BD014A印花KT笔袋"], filter_label="规格编码") is False
        assert _search_has_matching_rows(page, ["BD014B"], filter_label="规格编码") is False
