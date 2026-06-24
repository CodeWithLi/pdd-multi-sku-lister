"""上传批次快照分类：删除后重传不应误判为追加。"""

from unittest.mock import patch

from pdd_agent.integrations.minio.config import MinioConfig
from pdd_agent.integrations.minio.events import MinioUploadEvent
from pdd_agent.integrations.minio.upload_batch import (
    apply_snapshot_to_batch_summary,
    batch_introduces_new_products,
    classify_change_from_snapshot,
    prepare_upload_batch,
    snapshot_set_product_codes,
)


def _cfg() -> MinioConfig:
    return MinioConfig(
        endpoint="127.0.0.1:9000",
        access_key="ak",
        secret_key="sk",
        bucket="beilemei-images",
        categories=["笔袋"],
    )


def _event(key: str) -> MinioUploadEvent:
    return MinioUploadEvent(object_key=key, filename=key.rsplit("/", 1)[-1])


def test_classify_from_empty_snapshot_is_new_image_set():
    change = classify_change_from_snapshot(
        selector="BD713719/第一套图",
        product_code="BD713A",
        snapshot={},
    )
    assert change == "new_image_set"


def test_classify_from_snapshot_with_existing_set_but_new_product():
    change = classify_change_from_snapshot(
        selector="BD713719/第一套图",
        product_code="BD713B",
        snapshot={"BD713719/第一套图": {"BD713A"}},
    )
    assert change == "new_product_folder"


def test_prepare_upload_batch_uses_snapshot_not_current_index():
    cfg = _cfg()
    events = [_event("笔袋/BD713719/第一套图/BD713A/1.jpg")]
    snapshot = {"BD713719/第一套图": None}

    with patch(
        "pdd_agent.integrations.minio.upload_batch.snapshot_set_product_codes",
        return_value=snapshot,
    ):
        batch, _ = prepare_upload_batch(events, config=cfg)

    assert batch["groups"][0]["change_type"] == "new_image_set"
    assert batch_introduces_new_products(batch) is True


def test_apply_snapshot_rewrites_summary_text():
    batch = {
        "status": "success",
        "groups": [
            {
                "change_type": "append_to_product",
                "change_label": "追加图片",
                "path": "笔袋/BD713719/第一套图/BD713A",
                "selector": "BD713719/第一套图",
                "product_code": "BD713A",
                "file_count": 14,
            }
        ],
    }
    apply_snapshot_to_batch_summary(batch, {})
    assert batch["groups"][0]["change_type"] == "new_image_set"
    assert "新增套图" in batch["summary"]
