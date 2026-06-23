"""拼多多比价定价 / pdd.xls 迁移测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pdd_agent.integrations.feishu.config import FeishuConfig, PddPriceCompareConfig, PddPriceCompareFieldNames
from pdd_agent.integrations.feishu.pdd_price_compare_sync import (
    FEISHU_DATA_MISSING_MESSAGE,
    FEISHU_PRICE_NOT_FOUND_MESSAGE,
    _build_catalog_from_feishu_records,
    _build_code_price_catalog_from_feishu_records,
    is_feishu_price_data_missing,
    load_control_xls_rows,
    load_pdd_xls_rows,
    load_pricing_xls_rows,
    migrate_control_xls_to_feishu,
    migrate_pdd_xls_to_feishu,
    migrate_pricing_xls_to_feishu,
    resolve_code_price_from_catalog,
    resolve_feishu_range_aspect,
)
from pdd_agent.skills.campaign.limited_time import _price_filter_failure_message
from pdd_agent.skills.campaign.price_rules import find_pdd_price_range


@pytest.fixture
def pricing_xls_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "data" / "assets" / "拼多多定价.xls"
    assert path.is_file()
    return path


@pytest.fixture
def control_xls_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "data" / "assets" / "拼多多控价.xls"
    assert path.is_file()
    return path


@pytest.fixture
def pdd_xls_path() -> Path:
    path = Path(__file__).resolve().parents[2] / "data" / "assets" / "pdd.xls"
    assert path.is_file()
    return path


def test_load_pdd_xls_rows_reads_headers(pdd_xls_path: Path):
    rows = load_pdd_xls_rows(path=pdd_xls_path)
    assert len(rows) > 0
    sample = rows[0]
    assert sample.norm_code
    assert sample.max_price > 0


def test_build_catalog_from_feishu_records_marks_incomplete():
    records = [
        {
            "record_id": "rec1",
            "fields": {
                "商品编码": "BD735A",
                "PDD控价下限价格": 28.0,
                "PDD控价上限价格": 35.0,
            },
        },
        {
            "record_id": "rec2",
            "fields": {
                "商品编码": "BD074A",
                "PDD控价下限价格": None,
                "PDD控价上限价格": None,
            },
        },
    ]
    catalog = _build_catalog_from_feishu_records(
        records,
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert catalog.source == "feishu"
    assert find_pdd_price_range(catalog.ranges, ["BD735A"]) is not None
    assert "BD074A" in catalog.incomplete_codes
    assert is_feishu_price_data_missing(catalog, ["BD074A"])
    assert not is_feishu_price_data_missing(catalog, ["BD735A"])
    assert not is_feishu_price_data_missing(catalog, ["UNKNOWN"])


def test_is_feishu_price_data_missing_empty_catalog_not_blanket():
    catalog = _build_catalog_from_feishu_records(
        [],
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert catalog.source == "feishu"
    assert not catalog.ranges
    assert not is_feishu_price_data_missing(catalog, ["BD032A"])


def test_build_catalog_from_feishu_records_uses_pricing_upper_field():
    records = [
        {
            "record_id": "rec1",
            "fields": {
                "商品编码": "BD032A樱桃蛋糕笔袋",
                "PDD控价下限价格": 9.7,
                "PDD控价上限价格": 11.0,
            },
        },
    ]
    catalog = _build_catalog_from_feishu_records(
        records,
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert find_pdd_price_range(catalog.ranges, ["BD032A"]) is not None
    assert not is_feishu_price_data_missing(catalog, ["BD032A"])


def test_resolve_feishu_range_aspect_splits_min_and_max():
    full = _build_catalog_from_feishu_records(
        [
            {
                "fields": {
                    "商品编码": "BD022A音乐小猫笔袋",
                    "PDD控价下限价格": 8.6,
                    "PDD控价上限价格": 11.0,
                }
            }
        ],
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert resolve_feishu_range_aspect(full, ["BD022A音乐小猫笔袋"]) is None

    max_only = _build_catalog_from_feishu_records(
        [
            {
                "fields": {
                    "商品编码": "BD022A音乐小猫笔袋",
                    "PDD控价下限价格": 8.6,
                    "PDD控价上限价格": None,
                }
            }
        ],
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert resolve_feishu_range_aspect(max_only, ["BD022A"]) == "range_max_missing"

    min_only = _build_catalog_from_feishu_records(
        [
            {
                "fields": {
                    "商品编码": "BD022A音乐小猫笔袋",
                    "PDD控价下限价格": None,
                    "PDD控价上限价格": 11.0,
                }
            }
        ],
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert resolve_feishu_range_aspect(min_only, ["BD022A音乐小猫笔袋"]) == "range_min_missing"


def test_bd022a_control_present_pricing_missing_only():
    """拼多多控价有值、上下限齐全时，不应报控价或上下限缺失。"""
    range_catalog = _build_catalog_from_feishu_records(
        [
            {
                "fields": {
                    "商品编码": "BD022A音乐小猫笔袋",
                    "PDD控价下限价格": 8.6,
                    "PDD控价上限价格": 11.0,
                }
            }
        ],
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    pricing_catalog = _build_code_price_catalog_from_feishu_records(
        [{"fields": {"商品编码": "BD022A音乐小猫笔袋", "拼多多定价": None, "拼多多控价": 8.6}}],
        code_field="商品编码",
        price_field="拼多多定价",
    )
    control_catalog = _build_code_price_catalog_from_feishu_records(
        [{"fields": {"商品编码": "BD022A音乐小猫笔袋", "拼多多定价": None, "拼多多控价": 8.6}}],
        code_field="商品编码",
        price_field="拼多多控价",
    )
    _, pricing_reason = resolve_code_price_from_catalog(pricing_catalog, "BD022A音乐小猫笔袋")
    _, control_reason = resolve_code_price_from_catalog(control_catalog, "BD022A音乐小猫笔袋")
    assert pricing_reason == FEISHU_DATA_MISSING_MESSAGE
    assert control_reason == ""
    assert resolve_feishu_range_aspect(range_catalog, ["BD022A音乐小猫笔袋"]) is None


def test_bd021a_upper_limit_one_not_reported_empty():
    catalog = _build_catalog_from_feishu_records(
        [
            {
                "fields": {
                    "商品编码": "BD021A卡皮巴拉笔袋",
                    "PDD控价下限价格": 8.6,
                    "PDD控价上限价格": 1.0,
                }
            }
        ],
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert resolve_feishu_range_aspect(catalog, ["BD021A卡皮巴拉笔袋"]) is None
    assert resolve_feishu_range_aspect(catalog, ["BD021A-卡皮巴拉笔袋"]) is None


def test_resolve_feishu_range_aspect_no_false_positive_when_range_exists():
    catalog = _build_catalog_from_feishu_records(
        [{"fields": {"商品编码": "BD021A卡皮巴拉笔袋", "PDD控价下限价格": 8.6, "PDD控价上限价格": 11.0}}],
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert "BD021A" in catalog.feishu_record_codes
    assert find_pdd_price_range(catalog.ranges, ["BD021A-卡皮巴拉笔袋"]) is not None
    assert resolve_feishu_range_aspect(catalog, ["BD021A-卡皮巴拉笔袋"]) is None


def test_build_catalog_duplicate_rows_good_row_clears_incomplete():
    catalog = _build_catalog_from_feishu_records(
        [
            {
                "fields": {
                    "商品编码": "BD025A",
                    "PDD控价下限价格": 7.45,
                    "PDD控价上限价格": None,
                }
            },
            {
                "fields": {
                    "商品编码": "BD025A面包小狗笔袋",
                    "PDD控价下限价格": 7.45,
                    "PDD控价上限价格": 9.3,
                }
            },
        ],
        code_field="商品编码",
        min_field="PDD控价下限价格",
        max_field="PDD控价上限价格",
    )
    assert resolve_feishu_range_aspect(catalog, ["BD025A面包小狗笔袋"]) is None
    assert "BD025A" not in catalog.incomplete_max_codes


def test_field_number_reads_list_value():
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import _field_number

    assert _field_number({"PDD控价上限价格": [9.3]}, "PDD控价上限价格") == 9.3


def test_field_number_reads_feishu_formula_number():
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import _field_number

    assert _field_number(
        {"PDD控价上限价格": {"type": 2, "value": [9.3]}},
        "PDD控价上限价格",
    ) == 9.3
    assert _field_number(
        {"PDD控价上限价格": {"type": 2, "value": [10]}},
        "PDD控价上限价格",
    ) == 10.0


def test_field_number_formula_empty_list():
    from pdd_agent.integrations.feishu.pdd_price_compare_sync import _field_number

    assert _field_number({"PDD控价上限价格": {"type": 2, "value": []}}, "PDD控价上限价格") is None


def test_price_filter_failure_message_feishu_missing():
    msg = _price_filter_failure_message({"status": "skipped", "reason": "feishu_data_missing"})
    assert msg == FEISHU_DATA_MISSING_MESSAGE
    msg2 = _price_filter_failure_message(
        {
            "status": "feishu_data_missing",
            "decisions": [{"reason": "feishu_data_missing"}],
        }
    )
    assert msg2 == FEISHU_DATA_MISSING_MESSAGE


def test_migrate_pdd_xls_to_feishu_dry_run(pdd_xls_path: Path, monkeypatch):
    cfg = FeishuConfig(
        app_id="app",
        app_secret="secret",
        bitable_app_token="base",
        pdd_price_compare=PddPriceCompareConfig(
            enabled=True,
            table_name="拼多多比价定价",
            field_names=PddPriceCompareFieldNames(),
        ),
    )

    excel_rows = load_pdd_xls_rows(path=pdd_xls_path, config=cfg)
    sample = excel_rows[0]

    class FakeClient:
        pass

    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.resolve_pdd_price_compare_table_id",
        lambda *_args, **_kwargs: ("tbl_test", "table_name"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.resolve_table_field_name",
        lambda _api, _token, _table, field_name: field_name,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync._resolve_price_range_field_names",
        lambda _api, _token, _table, names: (
            names.merchant_code,
            names.min_price,
            names.max_price,
        ),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.list_all_records",
        lambda *_args, **_kwargs: [
            {
                "record_id": "rec_match",
                "fields": {
                    "商品编码": sample.raw_code,
                    "PDD控价下限价格": None,
                    "PDD控价上限价格": None,
                },
            },
        ],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.map_fields_to_table_names",
        lambda _api, _token, _table, fields: dict(fields),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.batch_update_records",
        lambda *_args, **_kwargs: ["rec_match"],
    )

    result = migrate_pdd_xls_to_feishu(
        dry_run=True,
        excel_path=pdd_xls_path,
        config=cfg,
        client=FakeClient(),
    )
    assert result.get("success")
    assert result.get("updated_count") == 1
    assert result.get("dry_run")


def test_load_pricing_and_control_xls_rows(pricing_xls_path: Path, control_xls_path: Path):
    pricing_rows = load_pricing_xls_rows(path=pricing_xls_path)
    control_rows = load_control_xls_rows(path=control_xls_path)
    assert len(pricing_rows) > 0
    assert len(control_rows) > 0
    assert pricing_rows[0].price > 0
    assert control_rows[0].price > 0


def test_build_code_price_catalog_from_feishu_records():
    records = [
        {
            "record_id": "rec1",
            "fields": {"商品编码": "BD735A", "拼多多定价": 29.9},
        },
        {
            "record_id": "rec2",
            "fields": {"商品编码": "BD074A", "拼多多定价": None},
        },
    ]
    catalog = _build_code_price_catalog_from_feishu_records(
        records,
        code_field="商品编码",
        price_field="拼多多定价",
    )
    assert catalog.source == "feishu"
    price, reason = resolve_code_price_from_catalog(catalog, "BD735A")
    assert price == 29.9
    assert reason == ""
    price2, reason2 = resolve_code_price_from_catalog(catalog, "BD074A")
    assert price2 is None
    assert reason2 == FEISHU_DATA_MISSING_MESSAGE
    price3, reason3 = resolve_code_price_from_catalog(catalog, "UNKNOWN")
    assert price3 is None
    assert reason3 == FEISHU_PRICE_NOT_FOUND_MESSAGE


def _patch_migrate_code_price(monkeypatch, sample_raw_code: str):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.resolve_pdd_price_compare_table_id",
        lambda *_args, **_kwargs: ("tbl_test", "table_name"),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.resolve_table_field_name",
        lambda _api, _token, _table, field_name: field_name,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.list_all_records",
        lambda *_args, **_kwargs: [
            {
                "record_id": "rec_match",
                "fields": {
                    "商品编码": sample_raw_code,
                    "拼多多定价": None,
                    "拼多多控价": None,
                },
            },
        ],
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.map_fields_to_table_names",
        lambda _api, _token, _table, fields: dict(fields),
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_price_compare_sync.batch_update_records",
        lambda *_args, **_kwargs: ["rec_match"],
    )


def test_migrate_pricing_xls_to_feishu_dry_run(pricing_xls_path: Path, monkeypatch):
    cfg = FeishuConfig(
        app_id="app",
        app_secret="secret",
        bitable_app_token="base",
        pdd_price_compare=PddPriceCompareConfig(
            enabled=True,
            table_name="拼多多比价定价",
            field_names=PddPriceCompareFieldNames(),
        ),
    )
    sample = load_pricing_xls_rows(path=pricing_xls_path, config=cfg)[0]
    _patch_migrate_code_price(monkeypatch, sample.raw_code)

    result = migrate_pricing_xls_to_feishu(
        dry_run=True,
        excel_path=pricing_xls_path,
        config=cfg,
        client=type("FakeClient", (), {})(),
    )
    assert result.get("success")
    assert result.get("label") == "pricing"
    assert result.get("updated_count") == 1
    assert result.get("dry_run")


def test_migrate_control_xls_to_feishu_dry_run(control_xls_path: Path, monkeypatch):
    cfg = FeishuConfig(
        app_id="app",
        app_secret="secret",
        bitable_app_token="base",
        pdd_price_compare=PddPriceCompareConfig(
            enabled=True,
            table_name="拼多多比价定价",
            field_names=PddPriceCompareFieldNames(),
        ),
    )
    sample = load_control_xls_rows(path=control_xls_path, config=cfg)[0]
    _patch_migrate_code_price(monkeypatch, sample.raw_code)

    result = migrate_control_xls_to_feishu(
        dry_run=True,
        excel_path=control_xls_path,
        config=cfg,
        client=type("FakeClient", (), {})(),
    )
    assert result.get("success")
    assert result.get("label") == "control"
    assert result.get("updated_count") == 1
    assert result.get("dry_run")
