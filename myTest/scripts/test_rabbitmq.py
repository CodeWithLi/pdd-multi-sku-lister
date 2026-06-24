#!/usr/bin/env python3
"""探测 RabbitMQ 连接并列出已有队列。"""

from __future__ import annotations

import json
import sys

from pdd_agent.integrations.minio.rabbitmq_admin import (
    check_rabbitmq_amqp,
    list_rabbitmq_queues,
    peek_rabbitmq_message,
)


def main() -> int:
    print("=== AMQP 连接测试 ===")
    amqp = check_rabbitmq_amqp()
    print(json.dumps(amqp, ensure_ascii=False, indent=2))
    if not amqp.get("available"):
        return 1

    print("\n=== 队列列表 ===")
    result = list_rabbitmq_queues()
    print(json.dumps(result, ensure_ascii=False, indent=2))

    suggested = str(result.get("suggested_queue") or "").strip()
    if suggested:
        print(f"\n推荐队列: {suggested}")
        print("\n=== 窥探一条消息 ===")
        try:
            peek = peek_rabbitmq_message(suggested, requeue=True)
            print(json.dumps(peek, ensure_ascii=False, indent=2))
        except Exception as exc:
            print(f"窥探失败: {exc}")

    return 0 if result.get("queues") else 1


if __name__ == "__main__":
    raise SystemExit(main())
