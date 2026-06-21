"""PDD推广日志表单元测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.config import FeishuConfig, PddPromotionLogConfig
from pdd_agent.integrations.feishu.pdd_promotion_log_sync import (
    build_promotion_log_entries,
    push_pdd_promotion_log,
)
from pdd_agent.skills.traffic.promotion_create import PROMOTION_SEARCH_EMPTY_FEISHU_MESSAGE


def test_build_promotion_log_entries_success():
    ids, messages = build_promotion_log_entries(
        selected_product_ids=["968544622705"],
        result={
            "results": [
                {
                    "status": "success",
                    "edit_bid_result": {
                        "found_product_ids": ["968544622705"],
                        "message": "推广创建成功",
                    },
                }
            ]
        },
        success=True,
    )
    assert ids == ["968544622705"]
    assert messages["968544622705"] == "推广创建成功"


def test_build_promotion_log_entries_search_empty_failure():
    ids, messages = build_promotion_log_entries(
        selected_product_ids=["968544622705"],
        result={
            "results": [
                {
                    "status": "failed",
                    "step": "promotion_search_empty",
                    "error": PROMOTION_SEARCH_EMPTY_FEISHU_MESSAGE,
                }
            ]
        },
        success=False,
    )
    assert ids == ["968544622705"]
    assert messages["968544622705"] == PROMOTION_SEARCH_EMPTY_FEISHU_MESSAGE


def test_push_pdd_promotion_log_writes_failure_row(monkeypatch):
    from pdd_agent.integrations.feishu import pdd_promotion_log_sync

    cfg = FeishuConfig(
        app_id="x",
        app_secret="y",
        bitable_app_token="z",
        pdd_promotion_log=PddPromotionLogConfig(
            enabled=True,
            table_id="tbl_promotion",
        ),
    )

    monkeypatch.setattr(
        pdd_promotion_log_sync,
        "ensure_pdd_promotion_log_table_ready",
        lambda *args, **kwargs: {
            "ready": True,
            "table_id": "tbl_promotion",
        },
    )
    monkeypatch.setattr(
        pdd_promotion_log_sync,
        "_resolve_account_display_name",
        lambda account_id, config: "测试店",
    )
    captured: dict = {}

    def _fake_batch_create_records(client, app_token, table_id, rows):
        captured["table_id"] = table_id
        captured["rows"] = rows
        return ["rec_1"]

    monkeypatch.setattr(pdd_promotion_log_sync, "batch_create_records", _fake_batch_create_records)
    monkeypatch.setattr(
        pdd_promotion_log_sync,
        "map_fields_to_table_names",
        lambda client, app_token, table_id, row: row,
    )

    result = push_pdd_promotion_log(
        account_id="store_A",
        product_ids=["968544622705"],
        success=False,
        result={
            "results": [
                {
                    "status": "failed",
                    "step": "promotion_search_empty",
                    "error": PROMOTION_SEARCH_EMPTY_FEISHU_MESSAGE,
                }
            ]
        },
        run_id="run_1",
        config=cfg,
        client=object(),
    )

    assert result["success"] is True
    assert captured["table_id"] == "tbl_promotion"
    assert captured["rows"][0]["推广结果"] == "失败"
    assert captured["rows"][0]["失败原因"] == PROMOTION_SEARCH_EMPTY_FEISHU_MESSAGE
    assert captured["rows"][0]["商品ID"] == "968544622705"
    assert captured["rows"][0]["店铺名称"] == "测试店"
    assert captured["rows"][0]["运行ID"] == "run_1"


def test_pdd_promotion_log_config_migrates_legacy_success_table_id():
    cfg = PddPromotionLogConfig.model_validate(
        {
            "success_table_id": "tbl_legacy",
            "success_table_name": "PDD推广成功日志",
        }
    )
    assert cfg.table_id == "tbl_legacy"
    assert cfg.table_name == "PDD推广日志表"
