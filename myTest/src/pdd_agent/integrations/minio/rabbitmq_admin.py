"""RabbitMQ 管理：列队列、测连接、窥探消息、推送上传通知。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.config import (
    DEFAULT_MINIO_EVENTS_EXCHANGE,
    DEFAULT_MINIO_EVENTS_ROUTING_KEY,
    DEFAULT_PDD_RABBITMQ_QUEUE,
    MinioConfig,
    load_minio_config,
)

logger = get_logger(__name__)


def _rabbit_cfg(config: MinioConfig | None = None):
    cfg = config or load_minio_config()
    return cfg.rabbitmq


def _rabbit_connection_params(rabbit, *, socket_timeout: int = 10):
    import pika

    credentials = pika.PlainCredentials(rabbit.username, rabbit.password)
    return pika.ConnectionParameters(
        host=rabbit.host,
        port=rabbit.port,
        credentials=credentials,
        heartbeat=30,
        blocked_connection_timeout=10,
        socket_timeout=socket_timeout,
    )


def ensure_rabbitmq_queue(
    queue: str = "",
    *,
    config: MinioConfig | None = None,
    durable: bool = True,
) -> dict[str, Any]:
    """声明 PDD 专用队列（不存在则创建，已存在则复用）。"""
    import pika

    cfg = config or load_minio_config()
    rabbit = cfg.rabbitmq
    target = str(queue or rabbit.queue or DEFAULT_PDD_RABBITMQ_QUEUE).strip()
    if not target:
        raise ValueError("未配置 RabbitMQ 队列")

    connection = pika.BlockingConnection(_rabbit_connection_params(rabbit))
    try:
        channel = connection.channel()
        declared = channel.queue_declare(queue=target, durable=durable)
        return {
            "queue": target,
            "created_or_exists": True,
            "messages": int(declared.method.message_count),
            "consumers": int(declared.method.consumer_count),
            "durable": durable,
        }
    finally:
        connection.close()


def ensure_rabbitmq_binding(
    queue: str = "",
    *,
    exchange: str = "",
    routing_key: str = "",
    config: MinioConfig | None = None,
) -> dict[str, Any]:
    """将 MinIO 事件 exchange 绑定到 PDD 队列（Unbind 后可调用恢复）。"""
    import pika

    cfg = config or load_minio_config()
    rabbit = cfg.rabbitmq
    target = str(queue or rabbit.queue or DEFAULT_PDD_RABBITMQ_QUEUE).strip()
    target_exchange = str(exchange or rabbit.exchange or DEFAULT_MINIO_EVENTS_EXCHANGE).strip()
    target_routing_key = str(routing_key or rabbit.routing_key or DEFAULT_MINIO_EVENTS_ROUTING_KEY).strip()
    if not target:
        raise ValueError("未配置 RabbitMQ 队列")
    if not target_exchange or not target_routing_key:
        raise ValueError("未配置 exchange 或 routing_key")

    connection = pika.BlockingConnection(_rabbit_connection_params(rabbit))
    try:
        channel = connection.channel()
        channel.queue_declare(queue=target, durable=True)
        try:
            channel.exchange_declare(exchange=target_exchange, passive=True)
        except Exception:
            channel.exchange_declare(exchange=target_exchange, exchange_type="topic", durable=True)
        channel.queue_bind(queue=target, exchange=target_exchange, routing_key=target_routing_key)
        logger.info(
            "rabbitmq binding ensured queue=%s exchange=%s routing_key=%s",
            target,
            target_exchange,
            target_routing_key,
        )
        return {
            "queue": target,
            "exchange": target_exchange,
            "routing_key": target_routing_key,
            "bound": True,
        }
    finally:
        connection.close()


def list_rabbitmq_queue_bindings(
    queue: str = "",
    *,
    config: MinioConfig | None = None,
) -> dict[str, Any]:
    """列出队列当前 bindings（Management API）。"""
    cfg = config or load_minio_config()
    rabbit = cfg.rabbitmq
    target = str(queue or rabbit.queue or DEFAULT_PDD_RABBITMQ_QUEUE).strip()
    if not target:
        raise ValueError("未配置 RabbitMQ 队列")

    mgmt_port = int(getattr(rabbit, "management_port", 15672) or 15672)
    from urllib.parse import quote

    encoded = quote(target, safe="")
    url = f"http://{rabbit.host}:{mgmt_port}/api/queues/%2F/{encoded}/bindings"
    try:
        with httpx.Client(timeout=10.0, auth=(rabbit.username, rabbit.password)) as client:
            resp = client.get(url)
            resp.raise_for_status()
            rows = resp.json()
    except Exception as exc:
        return {
            "queue": target,
            "available": False,
            "error": str(exc),
            "bindings": [],
        }

    bindings: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "").strip()
        routing_key = str(row.get("routing_key") or "").strip()
        if not source:
            continue
        bindings.append(
            {
                "exchange": source,
                "routing_key": routing_key,
                "destination": str(row.get("destination") or target).strip(),
            }
        )
    expected_exchange = str(rabbit.exchange or DEFAULT_MINIO_EVENTS_EXCHANGE).strip()
    expected_routing_key = str(rabbit.routing_key or DEFAULT_MINIO_EVENTS_ROUTING_KEY).strip()
    minio_bound = any(
        item["exchange"] == expected_exchange and item["routing_key"] == expected_routing_key
        for item in bindings
    )
    return {
        "queue": target,
        "available": True,
        "bindings": bindings,
        "minio_events_bound": minio_bound,
        "expected_exchange": expected_exchange,
        "expected_routing_key": expected_routing_key,
    }


def ensure_rabbitmq_setup(
    queue: str = "",
    *,
    config: MinioConfig | None = None,
) -> dict[str, Any]:
    """创建队列并恢复 MinIO 事件 binding。"""
    queue_info = ensure_rabbitmq_queue(queue, config=config)
    binding_info = ensure_rabbitmq_binding(queue=queue_info["queue"], config=config)
    bindings = list_rabbitmq_queue_bindings(queue=queue_info["queue"], config=config)
    return {
        **queue_info,
        **binding_info,
        "bindings": bindings,
    }


def check_rabbitmq_amqp(config: MinioConfig | None = None) -> dict[str, Any]:
    """测试 AMQP 5672 连接。"""
    rabbit = _rabbit_cfg(config)
    try:
        connection = __import__("pika").BlockingConnection(_rabbit_connection_params(rabbit))
        connection.close()
        return {
            "available": True,
            "host": rabbit.host,
            "port": rabbit.port,
            "username": rabbit.username,
        }
    except Exception as exc:
        return {
            "available": False,
            "host": rabbit.host,
            "port": rabbit.port,
            "username": rabbit.username,
            "error": str(exc),
        }


def list_rabbitmq_queues(config: MinioConfig | None = None) -> dict[str, Any]:
    """通过 Management API 列出已有队列；失败时回退到当前配置队列探测。"""
    cfg = config or load_minio_config()
    rabbit = cfg.rabbitmq
    amqp = check_rabbitmq_amqp(cfg)

    mgmt_port = int(getattr(rabbit, "management_port", 15672) or 15672)
    url = f"http://{rabbit.host}:{mgmt_port}/api/queues"
    try:
        with httpx.Client(timeout=10.0, auth=(rabbit.username, rabbit.password)) as client:
            resp = client.get(url)
            resp.raise_for_status()
            rows = resp.json()
        queues: list[dict[str, Any]] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            queues.append(
                {
                    "name": name,
                    "vhost": str(row.get("vhost") or "/"),
                    "messages": int(row.get("messages") or 0),
                    "messages_ready": int(row.get("messages_ready") or 0),
                    "consumers": int(row.get("consumers") or 0),
                    "durable": bool(row.get("durable")),
                }
            )
        queues.sort(key=lambda item: (-int(item["messages"]), item["name"]))
        suggested = _suggest_queue(queues, rabbit.queue)
        return {
            "available": True,
            "method": "management_api",
            "amqp": amqp,
            "management_url": url,
            "configured_queue": rabbit.queue,
            "suggested_queue": suggested,
            "pdd_default_queue": DEFAULT_PDD_RABBITMQ_QUEUE,
            "queues": queues,
        }
    except Exception as mgmt_exc:
        fallback = _probe_configured_queue(cfg) if amqp.get("available") else None
        return {
            "available": bool(fallback and fallback.get("exists")),
            "method": "queue_probe",
            "amqp": amqp,
            "management_url": url,
            "management_error": str(mgmt_exc),
            "configured_queue": rabbit.queue,
            "suggested_queue": rabbit.queue if fallback and fallback.get("exists") else DEFAULT_PDD_RABBITMQ_QUEUE,
            "pdd_default_queue": DEFAULT_PDD_RABBITMQ_QUEUE,
            "queues": [fallback] if fallback and fallback.get("exists") else [],
        }


def _suggest_queue(queues: list[dict[str, Any]], configured: str) -> str:
    if configured and any(q["name"] == configured for q in queues):
        return configured
    for q in queues:
        if q["name"] == DEFAULT_PDD_RABBITMQ_QUEUE:
            return q["name"]
    keywords = ("pdd", "minio", "upload", "alist", "image", "beilemei")
    for q in queues:
        name_lower = q["name"].lower()
        if "pdd" in name_lower:
            return q["name"]
    for q in queues:
        name_lower = q["name"].lower()
        if any(word in name_lower for word in keywords):
            return q["name"]
    if len(queues) == 1:
        return queues[0]["name"]
    return configured or DEFAULT_PDD_RABBITMQ_QUEUE


def _probe_configured_queue(cfg: MinioConfig) -> dict[str, Any] | None:
    rabbit = cfg.rabbitmq
    if not rabbit.queue:
        return None
    try:
        import pika

        connection = pika.BlockingConnection(_rabbit_connection_params(rabbit))
        channel = connection.channel()
        declared = channel.queue_declare(queue=rabbit.queue, passive=True)
        connection.close()
        return {
            "name": rabbit.queue,
            "vhost": "/",
            "messages": int(declared.method.message_count),
            "messages_ready": int(declared.method.message_count),
            "consumers": int(declared.method.consumer_count),
            "durable": True,
            "exists": True,
        }
    except Exception:
        return {"name": rabbit.queue, "exists": False}


def peek_rabbitmq_message(
    queue: str | None = None,
    *,
    config: MinioConfig | None = None,
    requeue: bool = True,
) -> dict[str, Any]:
    """取一条消息预览（默认放回队列，不消费）。"""
    cfg = config or load_minio_config()
    rabbit = cfg.rabbitmq
    target = str(queue or rabbit.queue or "").strip()
    if not target:
        raise ValueError("请指定队列名")

    connection = __import__("pika").BlockingConnection(_rabbit_connection_params(rabbit))
    try:
        channel = connection.channel()
        method, properties, body = channel.basic_get(queue=target, auto_ack=False)
        if method is None:
            return {"queue": target, "found": False}
        if requeue:
            channel.basic_nack(method.delivery_tag, requeue=True)
        else:
            channel.basic_ack(method.delivery_tag)
        text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        return {
            "queue": target,
            "found": True,
            "requeued": requeue,
            "body_preview": text[:2000],
            "content_type": getattr(properties, "content_type", "") or "",
        }
    finally:
        connection.close()


def build_upload_notification_payload(object_key: str, *, bucket: str = "") -> dict[str, Any]:
    """构造与 Alist/MinIO 上传兼容的 RabbitMQ 消息体。"""
    key = str(object_key or "").strip().lstrip("/")
    bucket_name = str(bucket or "").strip()
    return {
        "path": key,
        "object_key": key,
        "bucket": bucket_name,
        "action": "upload",
        "event": "ObjectCreated:Put",
    }


def publish_rabbitmq_upload_notifications(
    object_keys: list[str],
    *,
    bucket: str = "",
    queue: str = "",
    config: MinioConfig | None = None,
) -> int:
    """向 PDD 队列推送上传通知（测试/补发用）。"""
    import pika

    cfg = config or load_minio_config()
    rabbit = cfg.rabbitmq
    target_queue = str(queue or rabbit.queue or DEFAULT_PDD_RABBITMQ_QUEUE).strip()
    if not target_queue:
        raise ValueError("未配置 RabbitMQ 队列")

    keys = [str(key or "").strip().lstrip("/") for key in object_keys if str(key or "").strip()]
    if not keys:
        return 0

    ensure_rabbitmq_queue(target_queue, config=cfg)
    connection = pika.BlockingConnection(_rabbit_connection_params(rabbit))
    try:
        channel = connection.channel()
        published = 0
        for key in keys:
            payload = build_upload_notification_payload(key, bucket=bucket or cfg.bucket)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            channel.basic_publish(
                exchange="",
                routing_key=target_queue,
                body=body,
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            )
            published += 1
            logger.info("rabbitmq published queue=%s key=%s", target_queue, key)
        return published
    finally:
        connection.close()
