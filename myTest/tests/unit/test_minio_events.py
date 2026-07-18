"""MinIO RabbitMQ 上传事件解析测试。"""

from __future__ import annotations

import json
from unittest.mock import patch

from pdd_agent.integrations.minio.config import (
    MinioConfig,
    MinioRabbitMQConfig,
    minio_poll_interval_seconds,
    save_minio_refresh_mode,
)
from pdd_agent.integrations.minio.events import (
    MinioUploadEvent,
    apply_minio_upload_event,
    parse_rabbitmq_upload_message,
    summarize_upload_events,
)
from pdd_agent.integrations.minio.index import MinioSetIndexRecord


def test_parse_minio_s3_notification():
    payload = {
        "Records": [
            {
                "eventName": "s3:ObjectCreated:Put",
                "s3": {
                    "bucket": {"name": "beilemei-images"},
                    "object": {"key": "笔袋/BD021/第一套图/BD021A卡皮巴拉笔袋/1.jpg"},
                },
            }
        ]
    }
    events = parse_rabbitmq_upload_message(json.dumps(payload))
    assert len(events) == 1
    assert events[0].object_key == "笔袋/BD021/第一套图/BD021A卡皮巴拉笔袋/1.jpg"
    assert events[0].family_code == "BD021"
    assert events[0].image_set == "第一套图"
    assert events[0].product_code == "BD021A卡皮巴拉笔袋"


def test_parse_simple_object_key_message():
    events = parse_rabbitmq_upload_message("笔袋/BD029/第一套图/BD029A/2.png")
    assert len(events) == 1
    assert events[0].product_code == "BD029A"


def test_parse_alist_style_json():
    payload = {"path": "笔袋/BD032/第一套图/BD032A樱桃蛋糕笔袋/3.jpg", "action": "upload"}
    events = parse_rabbitmq_upload_message(json.dumps(payload))
    assert len(events) == 1
    assert events[0].selector == "BD032/第一套图"


def test_summarize_upload_events():
    events = [
        MinioUploadEvent(object_key="笔袋/BD021/第一套图/BD021A/1.jpg"),
        MinioUploadEvent(object_key="笔袋/BD021/第一套图/BD021A/2.jpg"),
    ]
    summary = summarize_upload_events(events)
    assert summary["kind"] == "minio_upload"
    assert summary["selectors"] == ["BD021/第一套图"]
    assert "BD021A" in summary["product_codes"]


def test_apply_minio_upload_event_updates_index():
    cfg = MinioConfig(
        enabled=True,
        endpoint="127.0.0.1:9000",
        access_key="key",
        secret_key="secret",
        bucket="beilemei-images",
        categories=["笔袋"],
    )
    event = MinioUploadEvent(object_key="笔袋/BD021/第一套图/BD021A卡皮巴拉笔袋/1.jpg")
    with patch("pdd_agent.integrations.minio.events.upsert_minio_set_record") as upsert:
        upsert.return_value = MinioSetIndexRecord(
            selector="BD021/第一套图",
            family_code="BD021",
            image_set="第一套图",
            object_prefix="笔袋/BD021/第一套图/",
            product_codes=("BD021A卡皮巴拉笔袋",),
        )
        with patch("pdd_agent.integrations.minio.events.clear_minio_listing_targets_cache"):
            result = apply_minio_upload_event(event, config=cfg)
    upsert.assert_called_once()
    assert result is not None


def test_poll_interval_zero_in_rabbitmq_mode():
    cfg = MinioConfig(
        enabled=True,
        endpoint="127.0.0.1:9000",
        access_key="k",
        secret_key="s",
        bucket="b",
        refresh_mode="rabbitmq",
        rabbitmq=MinioRabbitMQConfig(enabled=True),
        listing_poll_seconds=30,
    )
    assert minio_poll_interval_seconds(cfg) == 0


def test_save_refresh_mode_writes_yaml(tmp_path):
    cfg_path = tmp_path / "minio.yaml"
    cfg_path.write_text("listing_poll_seconds: 30\nrabbitmq:\n  enabled: false\n", encoding="utf-8")
    mode = save_minio_refresh_mode("rabbitmq", path=cfg_path)
    assert mode == "rabbitmq"
    text = cfg_path.read_text(encoding="utf-8")
    assert "refresh_mode: rabbitmq" in text
    assert "enabled: true" in text
