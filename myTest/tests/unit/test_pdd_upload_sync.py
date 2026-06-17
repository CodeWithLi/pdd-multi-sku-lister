"""PDD 上传日志飞书字段映射与行解析单元测试。"""

from __future__ import annotations

from datetime import datetime

from pdd_agent.integrations.feishu.config import FeishuConfig, PddUploadLogConfig
from pdd_agent.integrations.feishu.pdd_upload_sync import (
    build_pdd_upload_log_fields,
    extract_product_ids_for_limited_time_status,
    format_pdd_upload_log_context,
    map_activity_register_status_to_feishu,
    map_limited_time_status_to_feishu,
    map_promotion_status_to_feishu,
    map_pdd_upload_status_to_feishu,
    push_pdd_upload_activity_register_status,
    push_pdd_upload_limited_time_status,
    push_pdd_upload_log,
    push_pdd_upload_promotion_status,
    resolve_activity_register_field_name,
)
from pdd_agent.skills.listing.goods_list_capture import (
    extract_list_status_from_text,
    is_plain_goods_template_link,
    parse_goods_list_row_meta,
)


def test_parse_goods_list_row_meta_extracts_created_at_and_status():
    row_text = """
    可爱草莓软糯造型毛绒零钱包
    ID: 966965874378
    商家编码: BD737A
    2026-06-16 13:21
    销售中
    """
    meta = parse_goods_list_row_meta(row_text)
    assert meta["matched_created_at"] == "2026-06-16 13:21:00"
    assert meta["list_status"] == "销售中"


def test_extract_list_status_from_text():
    assert extract_list_status_from_text("2026-06-16 13:21\n销售中") == "销售中"
    assert extract_list_status_from_text("已驳回") == "已驳回"


def test_is_plain_goods_template_link():
    pid = "967054361524"
    plain = f"https://mobile.yangkeduo.com/goods.html?goods_id={pid}"
    full = (
        f"{plain}&refer_page_app=mms&refer_page_name=mms_goods"
    )
    assert is_plain_goods_template_link(plain, pid) is True
    assert is_plain_goods_template_link(full, pid) is False
    assert is_plain_goods_template_link("", pid) is False


def test_map_pdd_upload_status_to_feishu():
    assert map_pdd_upload_status_to_feishu("销售中") == "已上架"
    assert map_pdd_upload_status_to_feishu("") == "已上架"
    assert map_pdd_upload_status_to_feishu("已驳回") == "报错上架失败"
    assert map_pdd_upload_status_to_feishu("已上架") == "已上架"


def test_build_pdd_upload_log_fields_maps_seven_columns():
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(
            enabled=True,
            table_id="tbldwkpLuvBVwc9",
        ),
    )
    verified_at = datetime(2026, 6, 16, 13, 25, 0)
    fields = build_pdd_upload_log_fields(
        config=cfg,
        title="可爱草莓软糯造型毛绒零钱包",
        merchant_code="BD737A",
        product_id="966965874378",
        product_link=(
            "https://mobile.yangkeduo.com/goods.html?goods_id=966965874378"
            "&refer_page_app=mms&refer_page_name=mms_goods"
        ),
        list_status="销售中",
        created_at_raw="2026-06-16 13:21",
        verified_at=verified_at,
    )

    assert fields["宝贝标题"] == "可爱草莓软糯造型毛绒零钱包"
    assert fields["商品编码"] == "BD737A"
    assert fields["状态"] == "已上架"
    assert fields["商品ID"] == "966965874378"
    assert isinstance(fields["日期"], int)
    assert isinstance(fields["创建时间"], int)
    assert "966965874378" in fields["商品链接"]["link"]


def test_build_pdd_upload_log_fields_skips_plain_template_link():
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(enabled=True, table_id="tbl"),
    )
    fields = build_pdd_upload_log_fields(
        config=cfg,
        title="标题",
        merchant_code="BD737A",
        product_id="966965874378",
        product_link="https://mobile.yangkeduo.com/goods.html?goods_id=966965874378",
        list_status="销售中",
        created_at_raw="2026-06-16 13:21",
        verified_at=datetime(2026, 6, 16, 13, 25, 0),
    )
    assert "商品链接" not in fields


def test_push_pdd_upload_log_accepts_listing_label_kwarg(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_upload_sync

    class FakeClient:
        def __init__(self, config):
            self.config = config

    monkeypatch.setattr(pdd_upload_sync, "FeishuClient", FakeClient)
    monkeypatch.setattr(pdd_upload_sync, "batch_create_records", lambda *args, **kwargs: ["rec_test"])
    monkeypatch.setattr(pdd_upload_sync, "search_records_by_field", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        pdd_upload_sync,
        "resolve_pdd_upload_table_id",
        lambda cfg, client, save_table_id=True: ("tbldwkpLiuvBWwe9", "test"),
    )
    monkeypatch.setattr(
        pdd_upload_sync,
        "map_fields_to_table_names",
        lambda client, app_token, table_id, fields: fields,
    )

    result = pdd_upload_sync.push_pdd_upload_log(
        account_id="store_A",
        listing_label="BD724A/第一套图",
        title="测试标题",
        merchant_code="BD724A",
        product_id="966965874378",
        product_link=(
            "https://mobile.yangkeduo.com/goods.html?goods_id=966965874378"
            "&refer_page_app=mms&refer_page_name=mms_goods"
        ),
        list_status="销售中",
        created_at_raw="2026-06-16 13:21",
        verified_at=datetime(2026, 6, 16, 13, 25, 0),
        config=FeishuConfig(
            app_id="x",
            app_secret="y",
            bitable_app_token="z",
            pdd_upload_log=PddUploadLogConfig(
                enabled=True,
                table_id="tbldwkpLuvBVwc9",
            ),
        ),
    )

    assert result.get("created") is True
    assert result.get("record_ids") == ["rec_test"]


def test_format_pdd_upload_log_context_includes_link_source():
    text = format_pdd_upload_log_context(
        account_id="store_A",
        listing_label="BD724C/第一套图",
        title="测试标题",
        merchant_code="BD724C",
        product_id="967050860402",
        product_link=(
            "https://mobile.yangkeduo.com/goods.html?goods_id=967050860402"
            "&refer_page_app=mms&refer_page_name=mms_goods"
        ),
        product_link_method="modal_text",
        list_status="销售中",
        created_at_raw="2026-06-16 17:41",
        verified_at=datetime(2026, 6, 16, 17, 41, 50),
    )
    assert "product_id=967050860402" in text
    assert "link_source=弹窗抓取(modal_text)" in text
    assert "yangkeduo.com" in text


def test_map_limited_time_status_to_feishu():
    assert map_limited_time_status_to_feishu(success=True) == "成功"
    assert map_limited_time_status_to_feishu(success=False) == "失败"


def test_extract_product_ids_for_limited_time_status_prefers_input_list():
    ids = extract_product_ids_for_limited_time_status(
        ["967058176181", "967084305452"],
        {"results": [{"selected_pdd_product_ids": ["999"]}]},
    )
    assert ids == ["967058176181", "967084305452"]


def test_extract_product_ids_for_limited_time_status_from_result():
    ids = extract_product_ids_for_limited_time_status(
        [],
        {
            "results": [
                {"selected_pdd_product_ids": ["967058176181", "967084305452"]},
            ]
        },
    )
    assert ids == ["967058176181", "967084305452"]


def test_push_pdd_upload_limited_time_status_updates_by_product_id(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_upload_sync

    class FakeClient:
        def __init__(self, config):
            self.config = config

    captured_updates: list[dict] = []

    def fake_search(client, app_token, table_id, *, field_name, value):
        if value == "967058176181":
            return [{"record_id": "rec_967058", "fields": {"商品ID": value}}]
        return []

    def fake_batch_update(client, app_token, table_id, updates):
        captured_updates.extend(updates)
        return [item["record_id"] for item in updates]

    monkeypatch.setattr(pdd_upload_sync, "FeishuClient", FakeClient)
    monkeypatch.setattr(pdd_upload_sync, "search_records_by_field", fake_search)
    monkeypatch.setattr(pdd_upload_sync, "batch_update_records", fake_batch_update)
    monkeypatch.setattr(
        pdd_upload_sync,
        "resolve_pdd_upload_table_id",
        lambda cfg, client, save_table_id=True: ("tbldwkpLiuvBWwe9", "test"),
    )
    monkeypatch.setattr(
        pdd_upload_sync,
        "map_fields_to_table_names",
        lambda client, app_token, table_id, fields: fields,
    )
    monkeypatch.setattr(pdd_upload_sync.time, "sleep", lambda *_args, **_kwargs: None)

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(
            enabled=True,
            table_id="tbldwkpLiuvBWwe9",
            update_limited_time_status=True,
            limited_time_lookup_retries=1,
        ),
    )

    result = push_pdd_upload_limited_time_status(
        account_id="store_A",
        product_ids=["967058176181", "967084305452"],
        success=True,
        config=cfg,
    )

    assert result.get("updated") is True
    assert result.get("status") == "成功"
    assert result.get("missing_product_ids") == ["967084305452"]
    assert len(captured_updates) == 1
    assert captured_updates[0]["record_id"] == "rec_967058"
    assert captured_updates[0]["fields"]["限时限量购状态"] == "成功"


def test_map_activity_register_status_to_feishu():
    assert map_activity_register_status_to_feishu(success=True) == "成功"
    assert map_activity_register_status_to_feishu(success=False) == "失败"


def test_resolve_activity_register_field_name():
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(
            enabled=True,
            activity_register_fields={"20981": "618报名", "21365": "21365限量七折"},
        ),
    )
    assert resolve_activity_register_field_name("20981", cfg) == "618报名"
    assert resolve_activity_register_field_name("21365", cfg) == "21365限量七折"
    assert resolve_activity_register_field_name("99999", cfg) == ""


def test_push_pdd_upload_activity_register_status_updates_field(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_upload_sync

    class FakeClient:
        def __init__(self, config):
            self.config = config

    captured_updates: list[dict] = []

    def fake_search(client, app_token, table_id, *, field_name, value):
        if value == "965182969751":
            return [{"record_id": "rec_act", "fields": {"商品ID": value}}]
        return []

    def fake_batch_update(client, app_token, table_id, updates):
        captured_updates.extend(updates)
        return [item["record_id"] for item in updates]

    monkeypatch.setattr(pdd_upload_sync, "FeishuClient", FakeClient)
    monkeypatch.setattr(pdd_upload_sync, "search_records_by_field", fake_search)
    monkeypatch.setattr(pdd_upload_sync, "batch_update_records", fake_batch_update)
    monkeypatch.setattr(
        pdd_upload_sync,
        "resolve_pdd_upload_table_id",
        lambda cfg, client, save_table_id=True: ("tbldwkpLiuvBWwe9", "test"),
    )
    monkeypatch.setattr(
        pdd_upload_sync,
        "map_fields_to_table_names",
        lambda client, app_token, table_id, fields: fields,
    )
    monkeypatch.setattr(pdd_upload_sync.time, "sleep", lambda *_args, **_kwargs: None)

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(
            enabled=True,
            table_id="tbldwkpLiuvBWwe9",
            update_activity_register_status=True,
            activity_register_fields={"20981": "618报名"},
            limited_time_lookup_retries=1,
        ),
    )

    ok = push_pdd_upload_activity_register_status(
        account_id="store_A",
        activity_id="20981",
        product_ids=["965182969751"],
        success=True,
        config=cfg,
    )
    assert ok.get("updated") is True
    assert ok.get("status") == "成功"
    assert captured_updates[0]["fields"]["618报名"] == "成功"

    fail = push_pdd_upload_activity_register_status(
        account_id="store_A",
        activity_id="20981",
        product_ids=["965182969751"],
        success=False,
        config=cfg,
    )
    assert fail.get("status") == "失败"


def test_push_pdd_upload_promotion_status_updates_field(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_upload_sync

    class FakeClient:
        def __init__(self, config):
            self.config = config

    captured_updates: list[dict] = []

    def fake_search(client, app_token, table_id, *, field_name, value):
        if value == "967058176181":
            return [{"record_id": "rec_promo", "fields": {"商品ID": value}}]
        return []

    def fake_batch_update(client, app_token, table_id, updates):
        captured_updates.extend(updates)
        return [item["record_id"] for item in updates]

    monkeypatch.setattr(pdd_upload_sync, "FeishuClient", FakeClient)
    monkeypatch.setattr(pdd_upload_sync, "search_records_by_field", fake_search)
    monkeypatch.setattr(pdd_upload_sync, "batch_update_records", fake_batch_update)
    monkeypatch.setattr(
        pdd_upload_sync,
        "resolve_pdd_upload_table_id",
        lambda cfg, client, save_table_id=True: ("tbldwkpLiuvBWwe9", "test"),
    )
    monkeypatch.setattr(
        pdd_upload_sync,
        "map_fields_to_table_names",
        lambda client, app_token, table_id, fields: fields,
    )
    monkeypatch.setattr(pdd_upload_sync.time, "sleep", lambda *_args, **_kwargs: None)

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(
            enabled=True,
            table_id="tbldwkpLiuvBWwe9",
            update_promotion_status=True,
            limited_time_lookup_retries=1,
        ),
    )

    ok = push_pdd_upload_promotion_status(
        account_id="store_A",
        product_ids=["967058176181"],
        success=True,
        config=cfg,
    )
    assert ok.get("updated") is True
    assert ok.get("status") == "成功"
    assert captured_updates[0]["fields"]["推广状态"] == "成功"

    fail = push_pdd_upload_promotion_status(
        account_id="store_A",
        product_ids=["967058176181"],
        success=False,
        config=cfg,
    )
    assert fail.get("status") == "失败"
    assert map_promotion_status_to_feishu(success=False) == "失败"
