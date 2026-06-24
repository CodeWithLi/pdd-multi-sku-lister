"""PDD 发布日志按规格编码展开 — 单元测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.config import (
    FeishuConfig,
    PddUploadLogConfig,
    save_pdd_upload_log_spec_rows_to_config,
)
from pdd_agent.integrations.feishu.pdd_upload_spec_log import (
    build_pdd_upload_spec_log_rows,
    build_spec_upload_log_title,
    log_spec_sku_rows_enabled,
    parse_spec_code_parts,
    resolve_spec_color_labels,
)
from pdd_agent.skills.listing.pdd_product_catalog import PddProductEntry


def _sample_catalog() -> dict[str, PddProductEntry]:
    return {
        "BD034B": PddProductEntry(
            code="BD034B",
            color_spec="粉棕樱桃奶油蛋糕毛绒公仔",
            product_type="公仔",
        ),
        "YKL001I": PddProductEntry(
            code="YKL001I",
            color_spec="白色挂件",
            product_type="挂件",
        ),
        "YKL004L": PddProductEntry(
            code="YKL004L",
            color_spec="粉色尺子",
            product_type="尺子",
        ),
    }


def test_parse_spec_code_parts():
    assert parse_spec_code_parts("BD034B+YKL001I") == ["BD034B", "YKL001I"]
    assert parse_spec_code_parts("  ") == []


def test_resolve_spec_color_labels_from_catalog():
    catalog = _sample_catalog()
    label = resolve_spec_color_labels(
        "BD034B+YKL001I",
        merchant_code="BD034B",
        catalog=catalog,
    )
    assert label == "白色挂件"


def test_build_spec_upload_log_title_summary():
    title = build_spec_upload_log_title(
        listing_title="BD034B 粉棕樱桃奶油蛋糕毛绒公仔",
        merchant_code="BD034B",
        combo_barcode="",
        catalog=_sample_catalog(),
    )
    assert title == "粉棕樱桃奶油蛋糕毛绒公仔"


def test_build_spec_upload_log_title_combo():
    title = build_spec_upload_log_title(
        listing_title="BD034B 粉棕樱桃奶油蛋糕毛绒公仔",
        merchant_code="BD034B",
        combo_barcode="BD034B+YKL001I",
        catalog=_sample_catalog(),
    )
    assert title == "粉棕樱桃奶油蛋糕毛绒公仔 白色挂件"


def test_build_pdd_upload_spec_log_rows_summary_and_specs():
    catalog = _sample_catalog()
    sku_rows = [
        {
            "combo_folder": "BD034B",
            "group_price": "10",
            "single_price": "15",
        },
        {
            "combo_folder": "BD034B+YKL001I",
            "group_price": "11.98",
            "single_price": "111.98",
        },
        {
            "combo_folder": "BD034B+YKL004L",
            "group_price": "14.23",
            "single_price": "114.23",
        },
    ]
    rows = build_pdd_upload_spec_log_rows(
        merchant_code="BD034B",
        listing_title="BD034B 粉棕樱桃奶油蛋糕毛绒公仔",
        sku_rows=sku_rows,
        catalog=catalog,
    )
    assert len(rows) == 3
    assert rows[0]["row_kind"] == "summary"
    assert rows[0]["combo_barcode"] == ""
    assert rows[0]["group_price"] == "10"
    assert rows[1]["combo_barcode"] == "BD034B+YKL001I"
    assert "白色挂件" in rows[1]["title"]
    assert rows[2]["combo_barcode"] == "BD034B+YKL004L"
    assert "粉色尺子" in rows[2]["title"]


def test_log_spec_sku_rows_enabled_reads_config_flag():
    cfg_on = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(log_spec_sku_rows_enabled=True),
    )
    assert log_spec_sku_rows_enabled(cfg_on) is True

    cfg_off = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(log_spec_sku_rows_enabled=False),
    )
    assert log_spec_sku_rows_enabled(cfg_off) is False


def test_save_pdd_upload_log_spec_rows_to_config(tmp_path):
    path = tmp_path / "feishu.yaml"
    path.write_text("app_id: x\napp_secret: y\nbitable_app_token: z\n", encoding="utf-8")
    save_pdd_upload_log_spec_rows_to_config(True, path=path)
    text = path.read_text(encoding="utf-8")
    assert "log_spec_sku_rows_enabled: true" in text
