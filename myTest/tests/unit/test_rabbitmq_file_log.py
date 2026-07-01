"""RabbitMQ 文件日志。"""

from datetime import datetime

from pdd_agent.integrations.minio import rabbitmq_file_log as mq_log


def test_log_rabbitmq_event_writes_daily_file(tmp_path, monkeypatch):
    monkeypatch.setattr(mq_log, "_LOG_DIR", tmp_path / "rabbitmq_logs")
    monkeypatch.setattr(mq_log, "_CURRENT_DATE", "")
    monkeypatch.setattr(mq_log, "_CURRENT_PATH", None)

    mq_log.log_rabbitmq_event(
        mq_log.EVENT_MESSAGE_RECEIVED,
        "测试消息",
        source="mq",
        queue="beilemei.pdd.image.ingest",
        object_keys=["笔袋/BD021/第一套图/BD021A/1.jpg"],
    )

    today = datetime.now().strftime("%Y-%m-%d")
    path = tmp_path / "rabbitmq_logs" / f"{today}.log"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "MESSAGE_RECEIVED" in text
    assert "BD021A" in text


def test_summarize_auto_pipeline():
    result = mq_log.summarize_auto_pipeline(
        {
            "triggered": True,
            "product_codes": ["BD046/第一套图/BD046A"],
            "append_sync_full_image_set": True,
            "synced_selectors": ["BD046/第一套图"],
        }
    )
    assert result["triggered"] is True
    assert result["append_sync_full_image_set"] is True
