"""PDD 上传日志飞书字段映射与行解析单元测试。"""

from __future__ import annotations

import pytest
from datetime import datetime
from typing import Any

from pdd_agent.integrations.feishu.config import FeishuConfig, PddUploadLogConfig
from pdd_agent.integrations.feishu.pdd_upload_sync import (
    build_pdd_upload_failure_log_fields,
    build_pdd_upload_log_fields,
    extract_product_ids_for_limited_time_status,
    format_pdd_upload_log_context,
    map_activity_register_status_to_feishu,
    map_limited_time_status_to_feishu,
    map_listing_failure_record_type,
    map_promotion_status_to_feishu,
    map_pdd_upload_status_to_feishu,
    push_pdd_upload_activity_register_status,
    push_pdd_upload_failure_log,
    push_pdd_upload_limited_time_status,
    push_pdd_upload_log,
    push_pdd_upload_promotion_status,
    resolve_activity_register_field_name,
    _format_brief_listing_failure_reason,
    _humanize_listing_failure_message,
    parse_listing_label_from_text,
)
from pdd_agent.skills.listing.goods_list_capture import (
    extract_list_status_from_text,
    is_plain_goods_template_link,
    parse_goods_list_row_meta,
)


@pytest.fixture(autouse=True)
def _skip_feishu_ensure_fields(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_upload_sync

    monkeypatch.setattr(pdd_upload_sync, "_ensure_pdd_upload_table_fields", lambda *args, **kwargs: None)
    monkeypatch.setattr(pdd_upload_sync, "_ensure_pdd_upload_failure_table_fields", lambda *args, **kwargs: None)


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


def test_build_pdd_upload_log_fields_maps_taobao_columns():
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(
            enabled=True,
            table_id="tbldwkpLuvBVwc9",
        ),
    )
    verified_at = datetime(2026, 6, 20, 10, 32, 0)
    publish_start = datetime(2026, 6, 20, 10, 29, 0)
    fields = build_pdd_upload_log_fields(
        config=cfg,
        title="可爱草莓软糯造型毛绒零钱包",
        merchant_code="BD737A",
        product_id="966965874378",
        product_link=(
            "https://mobile.yangkeduo.com/goods.html?goods_id=966965874378"
            "&refer_page_app=mms&refer_page_name=mms_goods"
        ),
        account_name="测试店铺",
        publish_start=publish_start,
        publish_end=verified_at,
        verified_at=verified_at,
    )

    assert fields["标题"] == "可爱草莓软糯造型毛绒零钱包"
    assert fields["商品编码"] == "BD737A"
    assert fields["店铺名称"] == "测试店铺"
    assert fields["商品ID"] == "966965874378"
    assert isinstance(fields["日期"], int)
    assert isinstance(fields["发布开始时间"], int)
    assert isinstance(fields["发布结束时间"], int)
    assert fields["耗时秒"] == 180.0
    assert fields["商品链接"]["text"] == "查看商品"
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


def test_push_pdd_upload_log_updates_existing_row_by_product_id(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_upload_sync

    class FakeClient:
        def __init__(self, config):
            self.config = config

    captured_updates: list[list[dict[str, Any]]] = []

    def fake_batch_update(_client, _app_token, _table_id, updates):
        captured_updates.append(list(updates))
        return [item["record_id"] for item in updates]

    monkeypatch.setattr(pdd_upload_sync, "FeishuClient", FakeClient)
    monkeypatch.setattr(
        pdd_upload_sync,
        "search_records_by_field",
        lambda *args, **kwargs: [{"record_id": "rec_exist", "fields": {}}],
    )
    monkeypatch.setattr(pdd_upload_sync, "batch_create_records", lambda *args, **kwargs: ["rec_new"])
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

    result = pdd_upload_sync.push_pdd_upload_log(
        account_id="store_A",
        listing_label="BD724A/第一套图",
        title="测试标题",
        merchant_code="BD724A",
        product_id="966965874378",
        product_link="https://mobile.yangkeduo.com/goods.html?goods_id=966965874378",
        list_status="销售中",
        created_at_raw="2026-06-16 13:21",
        verified_at=datetime(2026, 6, 16, 13, 25, 0),
        config=FeishuConfig(
            app_id="x",
            app_secret="y",
            bitable_app_token="z",
            pdd_upload_log=PddUploadLogConfig(
                enabled=True,
                table_id="tbldwkpLiuvBWwe9",
                dedupe_field="商品ID",
            ),
        ),
    )

    assert result.get("updated") is True
    assert result.get("record_ids") == ["rec_exist"]
    assert captured_updates
    assert captured_updates[0][0]["record_id"] == "rec_exist"


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


def test_format_brief_listing_failure_reason_is_short():
    text = _format_brief_listing_failure_reason(
        listing_label="BD736/第三套图/BD736A",
        reason_code="preflight_no_carousel",
        record_type="跳过",
    )
    assert text == "跳过: BD736/第三套图/BD736A: 缺少主图（需 1-5 编号图）"


def test_humanize_slot_alignment_uses_plain_language():
    text = _humanize_listing_failure_message(
        reason_code="slot_alignment_failed",
        message="[BD722C/第一套图] 槽位对齐失败：兄弟款预览图数量不一致（BD722B=3张，BD722C=2张）",
    )
    assert text == "兄弟款预览图张数不一致（BD722B=3张，BD722C=2张）"

    brief = _format_brief_listing_failure_reason(
        listing_label="BD722C/第一套图",
        reason_code="slot_alignment_failed",
        message="槽位对齐失败：兄弟款规格数量不一致",
        record_type="跳过",
    )
    assert brief == "跳过: BD722C/第一套图: 兄弟款预览图张数不一致，请核对各款图数"


def test_humanize_skip_missing_numbered_images():
    text = _format_brief_listing_failure_reason(
        listing_label="BD736/第三套图/BD736A",
        reason_code="preflight_catalog",
        message="无任何数字命名图 (1-9)",
        record_type="跳过",
    )
    assert text == "跳过: BD736/第三套图/BD736A: 缺少按数字命名的图片 (1-9)"


def test_schedule_feishu_listing_result_log_dedupes_one_failure(monkeypatch):
    from pdd_agent.api.services import task_runner
    from pdd_agent.integrations.feishu import pdd_upload_sync

    captured: list[dict] = []

    def fake_schedule_failure(**kwargs):
        captured.append(kwargs)
        return {"created": True}

    monkeypatch.setattr(pdd_upload_sync, "schedule_pdd_upload_failure_log", fake_schedule_failure)

    task_runner._schedule_feishu_listing_result_log(
        account_id="store_A",
        product_codes=["BD722"],
        result={
            "results": [{"summary": "无有效上架单元"}],
            "preflight": {
                "issues": [
                    {
                        "level": "error",
                        "listing_label": "BD722B/第一套图",
                        "message": "槽位对齐失败：兄弟款规格数量不一致",
                    }
                ]
            },
            "errors": ["[BD722B/第一套图] 槽位对齐失败：兄弟款规格数量不一致"],
        },
    )

    assert len(captured) == 1
    assert captured[0]["merchant_code"] == "BD722B"
    assert captured[0]["listing_label"] == "BD722B/第一套图"
    assert captured[0]["reason_code"] == "slot_alignment_failed"


def test_map_listing_failure_record_type_skip_vs_fail():
    assert map_listing_failure_record_type(reason_code="slot_alignment_failed", retryable=True) == "跳过"
    assert map_listing_failure_record_type(status="failed", reason_code="submit_blocked") == "失败"
    assert map_listing_failure_record_type(
        reason_code="rejected_after_publish",
        status="failed",
    ) == "失败"
    assert map_listing_failure_record_type(
        reason_code="published_but_not_found_in_on_sale_or_rejected",
        status="retryable",
        retryable=True,
    ) == "失败"


def test_schedule_feishu_listing_result_log_records_post_submit_failures(monkeypatch):
    from pdd_agent.api.services import task_runner
    from pdd_agent.integrations.feishu import pdd_upload_sync

    captured: list[dict] = []

    def fake_schedule_failure(**kwargs):
        captured.append(kwargs)
        return {"created": True}

    monkeypatch.setattr(pdd_upload_sync, "schedule_pdd_upload_failure_log", fake_schedule_failure)

    task_runner._schedule_feishu_listing_result_log(
        account_id="store_A",
        product_codes=["BD722"],
        result={
            "results": [
                {
                    "status": "failed",
                    "reason": "rejected_after_publish",
                    "listing_label": "BD722C/第一套图",
                    "platform_listing_code": "BD722C",
                    "error": "提交后在「已驳回」找到商品，平台已驳回",
                },
                {
                    "status": "retryable",
                    "reason": "published_but_not_found_in_on_sale_or_rejected",
                    "listing_label": "BD722D/第一套图",
                    "platform_listing_code": "BD722D",
                    "error": "提交后在在售/驳回列表没找到刚上的商品，请人工核对",
                    "retryable": True,
                },
            ]
        },
    )

    assert len(captured) == 1
    assert captured[0]["reason_code"] == "rejected_after_publish"
    assert "另1项失败" in captured[0]["message"]
    assert map_listing_failure_record_type(
        reason_code=captured[0]["reason_code"],
        status="failed",
    ) == "失败"


def test_humanize_post_submit_failure_messages():
    rejected = _humanize_listing_failure_message(
        reason_code="rejected_after_publish",
        error="提交后在「已驳回」找到商品，平台已驳回",
    )
    assert "已驳回" in rejected

    not_found = _format_brief_listing_failure_reason(
        listing_label="BD722D/第一套图",
        reason_code="published_but_not_found_in_on_sale_or_rejected",
        error="提交后在在售/驳回列表没找到刚上的商品，请人工核对",
        record_type="失败",
    )
    assert not_found.startswith("失败: BD722D/第一套图:")
    assert "没找到刚上" in not_found


def test_build_pdd_upload_failure_log_fields():
    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_upload_log=PddUploadLogConfig(enabled=True),
    )
    start = datetime(2026, 6, 20, 10, 28, 0)
    end = datetime(2026, 6, 20, 10, 29, 6)
    fields = build_pdd_upload_failure_log_fields(
        config=cfg,
        merchant_code="BD736A",
        account_name="store_A",
        record_type="跳过",
        failure_reason="BD736/第三套图/BD736A: 图片文件不存在或无法读取",
        publish_start=start,
        publish_end=end,
    )
    assert fields["商品编码"] == "BD736A"
    assert fields["记录类型"] == "跳过"
    assert "图片文件" in fields["失败原因"]
    assert fields["耗时秒"] == 66.0


def test_push_pdd_upload_log_skips_without_product_id():
    result = push_pdd_upload_log(
        account_id="store_A",
        title="t",
        merchant_code="BD736A",
        product_id="",
        listing_result="失败",
        config=FeishuConfig(
            app_id="x",
            app_secret="y",
            bitable_app_token="z",
            pdd_upload_log=PddUploadLogConfig(enabled=True, table_id="tbl"),
        ),
    )
    assert result.get("skipped") is True


def test_parse_listing_label_from_text():
    label, code = parse_listing_label_from_text("[BD722B/第一套图] 槽位对齐失败")
    assert label == "BD722B/第一套图"
    assert code == "BD722B"


def test_push_pdd_upload_failure_log_without_merchant_code(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_upload_sync

    class FakeClient:
        def __init__(self, config):
            self.config = config

    monkeypatch.setattr(pdd_upload_sync, "FeishuClient", FakeClient)
    monkeypatch.setattr(pdd_upload_sync, "batch_create_records", lambda *args, **kwargs: ["rec_fail"])
    monkeypatch.setattr(
        pdd_upload_sync,
        "resolve_pdd_upload_failure_table_id",
        lambda cfg, client, save_table_id=True, create_if_missing=False: ("tbl_fail", "test"),
    )
    monkeypatch.setattr(
        pdd_upload_sync,
        "map_fields_to_table_names",
        lambda client, app_token, table_id, fields: fields,
    )

    result = push_pdd_upload_failure_log(
        account_id="store_A",
        account_name="测试店",
        message="[BD722B/第一套图] 槽位对齐失败：兄弟款规格数量不一致",
        reason_code="slot_alignment_failed",
        config=FeishuConfig(
            app_id="x",
            app_secret="y",
            bitable_app_token="z",
            pdd_upload_log=PddUploadLogConfig(enabled=True, failure_table_id="tbl_fail"),
        ),
    )
    assert result.get("created") is True
    assert result["fields"]["商品编码"] == "BD722B"
    assert "兄弟款预览图张数不一致" in result["fields"]["失败原因"]
    assert "槽位对齐" not in result["fields"]["失败原因"]
