#!/usr/bin/env python3

"""经 Alist 上传测试套图（生产路径），并查看 RabbitMQ 是否收到自动通知。"""



from __future__ import annotations



import json

import sys

import time



from pdd_agent.integrations.minio.rabbitmq_admin import peek_rabbitmq_message

from pdd_agent.integrations.minio.test_upload import upload_test_image_set





def main() -> int:

    print("=== 经 Alist 上传测试套图（等待 RabbitMQ 自动通知）===")

    result = upload_test_image_set(

        family_code="BD999",

        image_set="第一套图",

        product_code="BD999A测试笔袋",

        image_numbers=[1, 2, 3],

        upload_method="alist",

    )

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))



    print("\n=== 等待并窥探 PDD 队列（5s / 15s）===")

    for wait in (5, 15):

        time.sleep(wait if wait == 5 else 10)

        peek = peek_rabbitmq_message(requeue=True)

        print(f"~{wait}s:", json.dumps(peek, ensure_ascii=False))

        if peek.get("found"):

            return 0

    print("队列仍为空：请确认运维已将上传通知路由到 beilemei.pdd.image.ingest")

    return 1





if __name__ == "__main__":

    raise SystemExit(main())


