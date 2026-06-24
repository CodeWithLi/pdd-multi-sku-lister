#!/usr/bin/env python3
"""创建 PDD 专用 RabbitMQ 队列并列出当前队列。"""

from __future__ import annotations

import json
import sys

from pdd_agent.integrations.minio.config import DEFAULT_PDD_RABBITMQ_QUEUE, load_minio_config
from pdd_agent.integrations.minio.rabbitmq_admin import ensure_rabbitmq_setup, list_rabbitmq_queues


def main() -> int:
    cfg = load_minio_config()
    target = cfg.rabbitmq.queue or DEFAULT_PDD_RABBITMQ_QUEUE
    print(f"=== 创建/确认 PDD 队列并恢复 MinIO binding: {target} ===")
    created = ensure_rabbitmq_setup(target)
    print(json.dumps(created, ensure_ascii=False, indent=2))

    print("\n=== 当前 RabbitMQ 队列 ===")
    queues = list_rabbitmq_queues()
    print(json.dumps(queues, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
