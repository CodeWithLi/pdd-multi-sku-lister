"""RabbitMQ MinIO 上传事件消费者（与定时轮询互斥）。"""

from __future__ import annotations

import threading
import time
from typing import Any

from pdd_agent.core.logging import get_logger
from pdd_agent.integrations.minio.broadcast import publish_minio_event
from pdd_agent.integrations.minio.rabbitmq_admin import ensure_rabbitmq_queue
from pdd_agent.integrations.minio.config import (
    MinioConfig,
    load_minio_config,
    minio_rabbitmq_enabled,
    minio_refresh_mode,
)
from pdd_agent.integrations.minio.events import (
    MinioUploadEvent,
    apply_minio_upload_event,
    parse_rabbitmq_upload_message,
)
from pdd_agent.integrations.minio.auto_pipeline import (
    batch_should_broadcast_upload,
    maybe_trigger_auto_pipeline,
)
from pdd_agent.integrations.minio.rabbitmq_file_log import (
    EVENT_AUTO_PIPELINE,
    EVENT_BATCH_DONE,
    EVENT_BATCH_START,
    EVENT_CONSUMER_CONNECTED,
    EVENT_CONSUMER_ERROR,
    EVENT_CONSUMER_SKIP,
    EVENT_CONSUMER_START,
    EVENT_CONSUMER_STOP,
    EVENT_DEBOUNCE_FLUSH,
    EVENT_LOCAL_PROCESS,
    EVENT_MESSAGE_ACK,
    EVENT_MESSAGE_NACK,
    EVENT_MESSAGE_RECEIVED,
    EVENT_SSE_PUSH,
    log_rabbitmq_event,
    summarize_auto_pipeline,
    summarize_batch_groups,
)
from pdd_agent.integrations.minio.upload_batch import (
    prepare_upload_batch,
)

logger = get_logger(__name__)

_RECENT_LOCK = threading.Lock()
_RECENT_BATCHES: list[dict[str, Any]] = []
_RECENT_LIMIT = 30


def record_rabbitmq_upload_batch(batch: dict[str, Any]) -> None:
    item = dict(batch)
    item.setdefault("ts", time.time())
    with _RECENT_LOCK:
        _RECENT_BATCHES.insert(0, item)
        del _RECENT_BATCHES[_RECENT_LIMIT:]


def list_recent_rabbitmq_events(limit: int = 20) -> list[dict[str, Any]]:
    """最近上传批次（合并后的可读摘要，非逐条原始 MQ）。"""
    with _RECENT_LOCK:
        return list(_RECENT_BATCHES[: max(1, min(int(limit), _RECENT_LIMIT))])


class _UploadDebouncer:
    def __init__(self, settle_seconds: int, on_flush) -> None:
        self._settle_seconds = max(0, int(settle_seconds))
        self._on_flush = on_flush
        self._pending: list[MinioUploadEvent] = []
        self._raw_message_count = 0
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def add(self, events: list[MinioUploadEvent], *, raw_messages: int = 1) -> None:
        if not events and raw_messages <= 0:
            return
        with self._lock:
            self._pending.extend(events)
            self._raw_message_count += max(1, int(raw_messages))
            if self._timer is not None:
                self._timer.cancel()
            delay = self._settle_seconds if self._settle_seconds > 0 else 0.3
            self._timer = threading.Timer(delay, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            batch = self._pending
            raw_count = self._raw_message_count
            self._pending = []
            self._raw_message_count = 0
            self._timer = None
        if not batch:
            return
        object_keys = sorted({event.object_key for event in batch if event.object_key})
        log_rabbitmq_event(
            EVENT_DEBOUNCE_FLUSH,
            "防抖窗口结束，开始处理合并批次",
            source="mq",
            raw_message_count=raw_count,
            event_count=len(batch),
            object_keys=object_keys[:50],
            object_key_truncated=len(object_keys) > 50,
        )
        self._on_flush(batch, raw_count)

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._pending.clear()
            self._raw_message_count = 0


class MinioRabbitMQConsumer:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._debouncer: _UploadDebouncer | None = None
        self._running = False
        self._last_error = ""

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_error(self) -> str:
        return self._last_error

    def status(self) -> dict[str, Any]:
        cfg = load_minio_config()
        return {
            "enabled": minio_rabbitmq_enabled(cfg),
            "running": self._running,
            "refresh_mode": minio_refresh_mode(cfg),
            "queue": cfg.rabbitmq.queue if minio_rabbitmq_enabled(cfg) else "",
            "host": cfg.rabbitmq.host if minio_rabbitmq_enabled(cfg) else "",
            "last_error": self._last_error,
        }

    def restart(self) -> None:
        self.stop()
        self.start()

    def start(self) -> None:
        cfg = load_minio_config()
        if not minio_rabbitmq_enabled(cfg):
            self._running = False
            self._last_error = ""
            logger.info("minio rabbitmq consumer skipped (refresh_mode=%s)", cfg.refresh_mode)
            log_rabbitmq_event(
                EVENT_CONSUMER_SKIP,
                "消费者未启动",
                refresh_mode=minio_refresh_mode(cfg),
                reason="RabbitMQ 已禁用、refresh_mode 不是 rabbitmq 或 MinIO 未配置",
            )
            return
        if self._running:
            return

        self._stop.clear()
        self._debouncer = _UploadDebouncer(
            cfg.rabbitmq.settle_seconds,
            self._on_upload_batch,
        )
        self._thread = threading.Thread(target=self._run_loop, name="minio-rabbitmq", daemon=True)
        self._thread.start()
        self._running = True
        logger.info(
            "minio rabbitmq consumer starting queue=%s host=%s:%s settle=%ss",
            cfg.rabbitmq.queue,
            cfg.rabbitmq.host,
            cfg.rabbitmq.port,
            cfg.rabbitmq.settle_seconds,
        )
        log_rabbitmq_event(
            EVENT_CONSUMER_START,
            "消费者启动",
            queue=cfg.rabbitmq.queue,
            host=cfg.rabbitmq.host,
            port=cfg.rabbitmq.port,
            exchange=cfg.rabbitmq.exchange,
            routing_key=cfg.rabbitmq.routing_key,
            settle_seconds=cfg.rabbitmq.settle_seconds,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._debouncer is not None:
            self._debouncer.cancel()
            self._debouncer = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        was_running = self._running
        self._running = False
        if was_running:
            log_rabbitmq_event(EVENT_CONSUMER_STOP, "消费者停止")

    def _on_upload_batch(self, events: list[MinioUploadEvent], raw_message_count: int) -> None:
        self._process_upload_batch(events, raw_message_count=raw_message_count, source="mq")

    def _process_upload_batch(
        self,
        events: list[MinioUploadEvent],
        *,
        raw_message_count: int,
        source: str,
    ) -> dict[str, Any]:
        cfg = load_minio_config()
        object_keys = sorted({event.object_key for event in events if event.object_key})
        log_rabbitmq_event(
            EVENT_BATCH_START,
            "开始处理上传批次",
            source=source,
            raw_message_count=raw_message_count,
            event_count=len(events),
            object_keys=object_keys[:50],
            object_key_truncated=len(object_keys) > 50,
        )
        batch_summary, _snapshot = prepare_upload_batch(
            events,
            raw_message_count=raw_message_count,
            config=cfg,
        )

        indexed: list[MinioUploadEvent] = []
        seen_keys: set[str] = set()
        for event in events:
            if event.object_key in seen_keys:
                continue
            seen_keys.add(event.object_key)
            record = apply_minio_upload_event(event, config=cfg)
            if record is not None:
                indexed.append(event)
        if indexed:
            batch_summary["indexed_file_count"] = len(indexed)
        else:
            batch_summary["indexed_file_count"] = 0

        batch_summary["ts"] = time.time()
        if indexed:
            batch_summary["auto_pipeline"] = maybe_trigger_auto_pipeline(batch_summary)
        elif source == "local_api":
            batch_summary["auto_pipeline"] = {"triggered": False, "reason": "no_indexed_files"}
        record_rabbitmq_upload_batch(batch_summary)

        auto_result = batch_summary.get("auto_pipeline") if isinstance(batch_summary.get("auto_pipeline"), dict) else {}
        log_rabbitmq_event(
            EVENT_BATCH_DONE,
            str(batch_summary.get("summary") or "批次处理完成"),
            source=source,
            status=batch_summary.get("status"),
            raw_message_count=raw_message_count,
            matched_file_count=batch_summary.get("matched_file_count"),
            indexed_file_count=batch_summary.get("indexed_file_count"),
            selectors=batch_summary.get("selectors"),
            product_codes=batch_summary.get("product_codes"),
            groups=summarize_batch_groups(batch_summary),
        )
        log_rabbitmq_event(
            EVENT_AUTO_PIPELINE,
            "已触发自动上架" if auto_result.get("triggered") else "未触发自动上架",
            source=source,
            **summarize_auto_pipeline(auto_result),
        )

        sse_sent = False
        if indexed and batch_should_broadcast_upload(batch_summary):
            publish_minio_event(batch_summary)
            sse_sent = True
            log_rabbitmq_event(
                EVENT_SSE_PUSH,
                "已推送 SSE 到前端",
                source=source,
                summary=batch_summary.get("summary"),
                selectors=batch_summary.get("selectors"),
            )
        if source == "mq":
            logger.info(
                "minio upload batch summary=%s raw=%s matched=%s auto=%s",
                batch_summary.get("summary"),
                raw_message_count,
                batch_summary.get("matched_file_count"),
                batch_summary.get("auto_pipeline"),
            )
        return batch_summary

    def process_upload_events(self, events: list[MinioUploadEvent]) -> dict[str, Any]:
        """本地处理上传事件（素材检查上传 / 测试接口；真实 MQ 仍走 _on_message）。"""
        if not events:
            return {"indexed": 0, "selectors": [], "product_codes": []}
        log_rabbitmq_event(
            EVENT_LOCAL_PROCESS,
            "本地模拟处理（非 MQ 拉取）",
            event_count=len(events),
            object_keys=sorted({event.object_key for event in events if event.object_key}),
        )
        batch_summary = self._process_upload_batch(
            events,
            raw_message_count=len(events),
            source="local_api",
        )
        indexed_count = int(batch_summary.get("indexed_file_count") or 0)
        if not indexed_count:
            return {
                "indexed": 0,
                "selectors": [],
                "product_codes": [],
                "auto_pipeline": batch_summary.get("auto_pipeline"),
            }
        return {
            "indexed": indexed_count,
            "selectors": batch_summary.get("selectors", []),
            "product_codes": batch_summary.get("product_codes", []),
            "summary": batch_summary.get("summary", ""),
            "auto_pipeline": batch_summary.get("auto_pipeline"),
        }

    def _run_loop(self) -> None:
        import pika

        while not self._stop.is_set():
            cfg = load_minio_config()
            if not minio_rabbitmq_enabled(cfg):
                self._running = False
                return
            rabbit = cfg.rabbitmq
            try:
                credentials = pika.PlainCredentials(rabbit.username, rabbit.password)
                params = pika.ConnectionParameters(
                    host=rabbit.host,
                    port=rabbit.port,
                    credentials=credentials,
                    heartbeat=60,
                    blocked_connection_timeout=30,
                )
                connection = pika.BlockingConnection(params)
                channel = connection.channel()
                ensure_rabbitmq_queue(rabbit.queue, config=cfg)
                channel.basic_qos(prefetch_count=20)

                def _on_message(ch, method, _properties, body):
                    if self._stop.is_set():
                        ch.basic_nack(method.delivery_tag, requeue=True)
                        log_rabbitmq_event(
                            EVENT_MESSAGE_NACK,
                            "消费者停止中，消息重新入队",
                            delivery_tag=method.delivery_tag,
                            requeue=True,
                        )
                        return
                    body_preview = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
                    if len(body_preview) > 500:
                        body_preview = f"{body_preview[:500]}...(共{len(body_preview)}字)"
                    try:
                        events = parse_rabbitmq_upload_message(body)
                        parsed_keys = [event.object_key for event in events if event.object_key]
                        log_rabbitmq_event(
                            EVENT_MESSAGE_RECEIVED,
                            "收到 MQ 消息",
                            source="mq",
                            queue=rabbit.queue,
                            delivery_tag=method.delivery_tag,
                            body_preview=body_preview,
                            parsed_event_count=len(events),
                            object_keys=parsed_keys[:20],
                            object_key_truncated=len(parsed_keys) > 20,
                        )
                        if self._debouncer is not None:
                            self._debouncer.add(events)
                        ch.basic_ack(method.delivery_tag)
                        log_rabbitmq_event(
                            EVENT_MESSAGE_ACK,
                            "消息已 ACK",
                            delivery_tag=method.delivery_tag,
                            parsed_event_count=len(events),
                        )
                    except Exception as exc:
                        logger.exception("minio rabbitmq message handling failed")
                        ch.basic_nack(method.delivery_tag, requeue=False)
                        log_rabbitmq_event(
                            EVENT_MESSAGE_NACK,
                            "消息处理失败，已丢弃",
                            delivery_tag=method.delivery_tag,
                            requeue=False,
                            error=str(exc),
                            body_preview=body_preview,
                        )

                channel.basic_consume(queue=rabbit.queue, on_message_callback=_on_message, auto_ack=False)
                self._last_error = ""
                logger.info("minio rabbitmq consumer connected queue=%s", rabbit.queue)
                log_rabbitmq_event(
                    EVENT_CONSUMER_CONNECTED,
                    "已连接并开始消费",
                    queue=rabbit.queue,
                    host=rabbit.host,
                    port=rabbit.port,
                )
                while not self._stop.is_set():
                    connection.process_data_events(time_limit=1)
                try:
                    channel.stop_consuming()
                except Exception:
                    pass
                connection.close()
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("minio rabbitmq consumer error: %s", exc)
                log_rabbitmq_event(
                    EVENT_CONSUMER_ERROR,
                    "连接或消费异常，5 秒后重试",
                    error=str(exc),
                    queue=rabbit.queue,
                    host=rabbit.host,
                    port=rabbit.port,
                )
                if self._stop.wait(5):
                    break
        self._running = False


_consumer = MinioRabbitMQConsumer()


def get_minio_rabbitmq_consumer() -> MinioRabbitMQConsumer:
    return _consumer
