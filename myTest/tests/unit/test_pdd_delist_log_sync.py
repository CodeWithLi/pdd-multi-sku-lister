"""pdd_delist_log_sync 单元测试。"""

from datetime import datetime
from unittest.mock import MagicMock, patch

from pdd_agent.integrations.feishu.pdd_delist_log_sync import (
    build_pdd_delist_log_row,
    map_delist_status_label,
    map_relist_label,
    push_pdd_delist_log,
)


def test_map_delist_status_label():
    assert map_delist_status_label("completed") == "已下架"
    assert map_delist_status_label("failed") == "下架失败"
    assert map_delist_status_label("dry_run") == "模拟下架"


def test_map_relist_label():
    assert map_relist_label(False) == "否"
    assert map_relist_label(True) == "是"


def test_build_pdd_delist_log_row_from_dict():
    row = build_pdd_delist_log_row(
        {
            "record_id": "rec1",
            "shop_display_name": "兔兔潮玩屋",
            "product_code": "BD070A",
            "erp_available_qty": -3,
            "delist_status": "completed",
            "is_relisted": False,
            "delisted_at": datetime(2026, 7, 8, 14, 30, 0),
        }
    )
    assert row["店铺名"] == "兔兔潮玩屋"
    assert row["商品编码"] == "BD070A"
    assert row["当前可用数"] == -3
    assert row["状态"] == "已下架"
    assert row["是否重新上架"] == "否"
    assert row["记录ID"] == "rec1"


def test_push_pdd_delist_log_skips_when_disabled():
    cfg = MagicMock()
    cfg.pdd_delist_log.enabled = False
    result = push_pdd_delist_log({"product_code": "BD070A"}, config=cfg)
    assert result["skipped"] is True


@patch("pdd_agent.integrations.feishu.pdd_delist_log_sync.batch_create_records", return_value=["feishu1"])
@patch("pdd_agent.integrations.feishu.pdd_delist_log_sync.ensure_pdd_delist_log_table_ready")
@patch("pdd_agent.integrations.feishu.pdd_delist_log_sync.FeishuClient")
def test_push_pdd_delist_log_success(mock_client_cls, mock_ready, mock_batch):
    cfg = MagicMock()
    cfg.pdd_delist_log.enabled = True
    cfg.pdd_delist_log.field_names.date = "日期"
    cfg.pdd_delist_log.field_names.delisted_at = "下架时间"
    cfg.pdd_delist_log.field_names.account_name = "店铺名"
    cfg.pdd_delist_log.field_names.product_code = "商品编码"
    cfg.pdd_delist_log.field_names.available_qty = "当前可用数"
    cfg.pdd_delist_log.field_names.status = "状态"
    cfg.pdd_delist_log.field_names.is_relisted = "是否重新上架"
    cfg.pdd_delist_log.field_names.record_id = "记录ID"
    cfg.pdd_delist_log.status_options = ["已下架", "下架失败", "模拟下架", "跳过", "未找到"]
    cfg.pdd_delist_log.relist_options = ["否", "是"]
    cfg.bitable_app_token = "app"
    cfg.app_id = "id"
    cfg.app_secret = "secret"

    mock_ready.return_value = {"ready": True, "table_id": "tbl1"}
    mock_client_cls.return_value = MagicMock()

    result = push_pdd_delist_log(
        {
            "record_id": "rec1",
            "shop_display_name": "兔兔潮玩屋",
            "product_code": "BD070A",
            "erp_available_qty": -1,
            "delist_status": "completed",
            "is_relisted": False,
            "delisted_at": datetime(2026, 7, 8, 14, 30, 0),
        },
        config=cfg,
        client=mock_client_cls.return_value,
    )
    assert result["success"] is True
    assert result["created_count"] == 1
    mock_batch.assert_called_once()


@patch("pdd_agent.integrations.feishu.bitable.batch_update_records", return_value=["feishu1"])
@patch("pdd_agent.integrations.feishu.bitable.search_records_by_field")
@patch("pdd_agent.integrations.feishu.pdd_delist_log_sync.ensure_pdd_delist_log_table_ready")
@patch("pdd_agent.integrations.feishu.pdd_delist_log_sync.FeishuClient")
def test_update_pdd_delist_log_relist_success(mock_client_cls, mock_ready, mock_search, mock_update):
    cfg = MagicMock()
    cfg.pdd_delist_log.enabled = True
    cfg.pdd_delist_log.field_names.record_id = "记录ID"
    cfg.pdd_delist_log.field_names.is_relisted = "是否重新上架"
    cfg.pdd_delist_log.relist_options = ["否", "是"]
    cfg.bitable_app_token = "app"
    cfg.app_id = "id"
    cfg.app_secret = "secret"

    mock_ready.return_value = {"ready": True, "table_id": "tbl1"}
    mock_search.return_value = [{"record_id": "feishu_row_1"}]
    mock_client_cls.return_value = MagicMock()

    from pdd_agent.integrations.feishu.pdd_delist_log_sync import update_pdd_delist_log_relist

    result = update_pdd_delist_log_relist(
        {"record_id": "rec1", "is_relisted": True, "product_code": "BD070A"},
        config=cfg,
        client=mock_client_cls.return_value,
    )
    assert result["success"] is True
    assert result["updated_count"] == 1
    mock_update.assert_called_once()
    mock_search.assert_called_once()