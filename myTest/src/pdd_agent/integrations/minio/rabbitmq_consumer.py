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
from pdd_agent.integrations.minio.auto_pipeline import maybe_trigger_auto_pipeline
from pdd_agent.integrations.minio.upload_batch import (
    batch_introduces_new_products,
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
            logger.info("minio rabbitmq consumer skipped (refresh_mode=%s)", cfg.refresh_mode)
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

    def stop(self) -> None:
        self._stop.set()
        if self._debouncer is not None:
            self._debouncer.cancel()
            self._debouncer = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._running = False

    def _on_upload_batch(self, events: list[MinioUploadEvent], raw_message_count: int) -> None:
        cfg = load_minio_config()
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
            if batch_introduces_new_products(batch_summary):
                batch_summary["auto_pipeline"] = maybe_trigger_auto_pipeline(batch_summary)
            else:
                batch_summary["auto_pipeline"] = {
                    "triggered": False,
                    "reason": "append_only_batch",
                    "reason_label": "本批次为追加图片或重复通知，已跳过自动上架",
                }
        record_rabbitmq_upload_batch(batch_summary)
        if indexed and batch_introduces_new_products(batch_summary):
            publish_minio_event(batch_summary)
            logger.info(
                "minio upload batch summary=%s raw=%s matched=%s auto=%s",
                batch_summary.get("summary"),
                raw_message_count,
                batch_summary.get("matched_file_count"),
                batch_summary.get("auto_pipeline"),
            )

    def process_upload_events(self, events: list[MinioUploadEvent]) -> dict[str, Any]:
        """本地处理上传事件（素材检查上传 / 测试接口；真实 MQ 仍走 _on_message）。"""
        if not events:
            return {"indexed": 0, "selectors": [], "product_codes": []}
        cfg = load_minio_config()
        batch_summary, _snapshot = prepare_upload_batch(events, raw_message_count=len(events), config=cfg)
        indexed: list[MinioUploadEvent] = []
        seen: set[str] = set()
        for event in events:
            if event.object_key in seen:
                continue
            seen.add(event.object_key)
            if apply_minio_upload_event(event, config=cfg) is not None:
                indexed.append(event)
        batch_summary["indexed_file_count"] = len(indexed)
        batch_summary["ts"] = time.time()
        if indexed and batch_introduces_new_products(batch_summary):
            batch_summary["auto_pipeline"] = maybe_trigger_auto_pipeline(batch_summary)
        elif indexed:
            batch_summary["auto_pipeline"] = {
                "triggered": False,
                "reason": "append_only_batch",
                "reason_label": "本批次为追加图片，已跳过自动上架",
            }
        else:
            batch_summary["auto_pipeline"] = {"triggered": False, "reason": "no_indexed_files"}
        record_rabbitmq_upload_batch(batch_summary)
        if not indexed:
            return {
                "indexed": 0,
                "selectors": [],
                "product_codes": [],
                "auto_pipeline": batch_summary.get("auto_pipeline"),
            }
        publish_minio_event(batch_summary)
        return {
            "indexed": len(indexed),
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
                        return
                    try:
                        events = parse_rabbitmq_upload_message(body)
                        if self._debouncer is not None:
                            self._debouncer.add(events)
                        ch.basic_ack(method.delivery_tag)
                    except Exception:
                        logger.exception("minio rabbitmq message handling failed")
                        ch.basic_nack(method.delivery_tag, requeue=False)

                channel.basic_consume(queue=rabbit.queue, on_message_callback=_on_message, auto_ack=False)
                self._last_error = ""
                logger.info("minio rabbitmq consumer connected queue=%s", rabbit.queue)
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
                if self._stop.wait(5):
                    break
        self._running = False


_consumer = MinioRabbitMQConsumer()


def get_minio_rabbitmq_consumer() -> MinioRabbitMQConsumer:
    return _consumer
