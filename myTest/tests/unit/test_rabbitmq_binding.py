"""RabbitMQ MinIO 事件 binding 测试。"""

from unittest.mock import MagicMock, patch

from pdd_agent.integrations.minio.config import MinioConfig, MinioRabbitMQConfig
from pdd_agent.integrations.minio.rabbitmq_admin import (
    ensure_rabbitmq_binding,
    list_rabbitmq_queue_bindings,
)


def _cfg() -> MinioConfig:
    return MinioConfig(
        endpoint="127.0.0.1:9000",
        access_key="ak",
        secret_key="sk",
        bucket="beilemei-images",
        rabbitmq=MinioRabbitMQConfig(
            enabled=True,
            host="192.168.1.129",
            username="admin",
            password="123456",
            queue="beilemei.pdd.image.ingest",
            exchange="minio.events",
            routing_key="beilemei.images",
        ),
    )


def test_ensure_rabbitmq_binding_binds_queue_to_exchange():
    cfg = _cfg()
    channel = MagicMock()
    connection = MagicMock()
    connection.channel.return_value = channel

    with patch("pika.BlockingConnection", return_value=connection):
        result = ensure_rabbitmq_binding(config=cfg)

    channel.queue_declare.assert_called_once_with(queue="beilemei.pdd.image.ingest", durable=True)
    channel.queue_bind.assert_called_once_with(
        queue="beilemei.pdd.image.ingest",
        exchange="minio.events",
        routing_key="beilemei.images",
    )
    assert result["bound"] is True


def test_list_rabbitmq_queue_bindings_detects_minio_events():
    cfg = _cfg()
    payload = [
        {"source": "", "routing_key": "beilemei.pdd.image.ingest", "destination": "beilemei.pdd.image.ingest"},
        {"source": "minio.events", "routing_key": "beilemei.images", "destination": "beilemei.pdd.image.ingest"},
    ]

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = None
    fake_client.get.return_value = FakeResponse()

    with patch("pdd_agent.integrations.minio.rabbitmq_admin.httpx.Client", return_value=fake_client):
        result = list_rabbitmq_queue_bindings(config=cfg)

    assert result["available"] is True
    assert result["minio_events_bound"] is True
