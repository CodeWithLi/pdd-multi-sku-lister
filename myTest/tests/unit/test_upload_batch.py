"""上传批次合并与分类测试。"""



from unittest.mock import patch



from pdd_agent.integrations.minio.config import MinioConfig, MinioRabbitMQConfig

from pdd_agent.integrations.minio.events import MinioUploadEvent, parse_rabbitmq_upload_message

from pdd_agent.integrations.minio.index import MinioSetIndexRecord

from pdd_agent.integrations.minio.upload_batch import build_upload_batch_summary

import json





def _cfg() -> MinioConfig:

    return MinioConfig(

        enabled=True,

        endpoint="127.0.0.1:9000",

        access_key="k",

        secret_key="s",

        bucket="beilemei-images",

        categories=["笔袋"],

        rabbitmq=MinioRabbitMQConfig(),

    )





def test_build_upload_batch_summary_merges_folder_upload():

    events = [

        MinioUploadEvent(object_key="笔袋/BD713717/第一套图/BD713A/1.png"),

        MinioUploadEvent(object_key="笔袋/BD713717/第一套图/BD713A/2.png"),

        MinioUploadEvent(object_key="笔袋/BD713717/第一套图/BD713A/BD713A+YKL001AC.png"),

    ]

    with patch("pdd_agent.integrations.minio.upload_batch.load_set_index_record", return_value=None):

        summary = build_upload_batch_summary(events, raw_message_count=14, config=_cfg())



    assert summary["kind"] == "upload_batch"

    assert summary["raw_message_count"] == 14

    assert summary["matched_file_count"] == 3

    assert len(summary["groups"]) == 1

    assert summary["groups"][0]["change_type"] == "new_image_set"

    assert "新增套图" in summary["summary"]

    assert "14 条" not in summary["summary"] or "BD713A" in summary["summary"]





def test_build_upload_batch_summary_append_to_existing():

    events = [MinioUploadEvent(object_key="笔袋/BD713717/第一套图/BD713A/10.png")]

    existing = MinioSetIndexRecord(

        selector="BD713717/第一套图",

        family_code="BD713717",

        image_set="第一套图",

        object_prefix="笔袋/BD713717/第一套图/",

        product_codes=("BD713A",),

    )

    with patch("pdd_agent.integrations.minio.upload_batch.load_set_index_record", return_value=existing):

        summary = build_upload_batch_summary(events, raw_message_count=1, config=_cfg())



    assert summary["groups"][0]["change_type"] == "append_to_product"

    assert "追加图片" in summary["summary"]





def test_parse_s3_key_strips_bucket_prefix():

    payload = {

        "Records": [

            {

                "eventName": "s3:ObjectCreated:Put",

                "s3": {

                    "bucket": {"name": "beilemei-images"},

                    "object": {"key": "beilemei-images/笔袋/BD713717/第一套图/BD713A/BD713A.png"},

                },

            }

        ]

    }

    events = parse_rabbitmq_upload_message(json.dumps(payload))

    assert len(events) == 1

    assert events[0].object_key == "笔袋/BD713717/第一套图/BD713A/BD713A.png"

    assert events[0].product_code == "BD713A"


