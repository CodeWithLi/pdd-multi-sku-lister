"""商品文件夹删除测试。"""

from unittest.mock import MagicMock, patch

import pytest

from pdd_agent.integrations.minio.config import MinioConfig
from pdd_agent.integrations.minio.image_set_delete import (
    ImageSetDeleteError,
    _is_safe_image_set_delete_prefix,
    _is_safe_product_delete_prefix,
    _product_prefix_candidates,
    delete_minio_product_folder,
)
from pdd_agent.integrations.minio.index import MinioSetIndexRecord


def _cfg() -> MinioConfig:
    return MinioConfig(
        endpoint="127.0.0.1:9000",
        access_key="ak",
        secret_key="sk",
        bucket="beilemei-images",
        categories=["笔袋", "公仔"],
    )


def test_is_safe_product_delete_prefix_blocks_shallow_paths():
    assert not _is_safe_product_delete_prefix("笔袋/", family_code="BD713", image_set="第一套图", product_code="BD713B")
    assert not _is_safe_product_delete_prefix(
        "笔袋/BD713/",
        family_code="BD713",
        image_set="第一套图",
        product_code="BD713B",
    )
    assert not _is_safe_product_delete_prefix(
        "笔袋/BD713/第一套图/",
        family_code="BD713",
        image_set="第一套图",
        product_code="BD713B",
    )
    assert _is_safe_product_delete_prefix(
        "笔袋/BD713/第一套图/BD713B/",
        family_code="BD713",
        image_set="第一套图",
        product_code="BD713B",
    )


def test_is_safe_image_set_delete_prefix_blocks_category_only():
    assert not _is_safe_image_set_delete_prefix("笔袋/", "BD713", "第一套图")
    assert _is_safe_image_set_delete_prefix("笔袋/BD713/第一套图/", "BD713", "第一套图")


def test_product_prefix_candidates_never_includes_category_or_set_only():
    cfg = _cfg()
    prefixes = _product_prefix_candidates(
        cfg,
        family_code="BD713",
        image_set="第一套图",
        product_code="BD713B",
        object_prefix="笔袋/BD713/第一套图/",
    )
    assert "笔袋/" not in prefixes
    assert "笔袋/BD713/" not in prefixes
    assert "笔袋/BD713/第一套图/" not in prefixes
    assert "笔袋/BD713/第一套图/BD713B/" in prefixes


def test_delete_minio_product_folder_keeps_set_when_other_product_exists():
    cfg = _cfg()
    record = MinioSetIndexRecord(
        selector="BD713/第一套图",
        family_code="BD713",
        image_set="第一套图",
        object_prefix="笔袋/BD713/第一套图/",
        product_codes=("BD713A", "BD713B"),
    )

    class FakeObj:
        def __init__(self, name: str):
            self.object_name = name

    fake_client = MagicMock()
    fake_client.list_objects.return_value = [
        FakeObj("笔袋/BD713/第一套图/BD713B/1.jpg"),
    ]
    fake_client.remove_objects.return_value = []

    with (
        patch("pdd_agent.integrations.minio.image_set_delete.load_minio_config", return_value=cfg),
        patch("pdd_agent.integrations.minio.image_set_delete.minio_configured", return_value=True),
        patch("pdd_agent.integrations.minio.image_set_delete.load_set_index_record", return_value=record),
        patch("pdd_agent.integrations.minio.image_set_delete.resolve_minio_set_prefix", return_value=record.object_prefix),
        patch("pdd_agent.integrations.minio.image_set_delete.get_minio_client", return_value=fake_client),
        patch(
            "pdd_agent.integrations.minio.image_set_delete._collect_remaining_products_in_set",
            return_value={"BD713A"},
        ),
        patch("pdd_agent.integrations.minio.image_set_delete.alist_configured", return_value=False),
        patch("pdd_agent.integrations.minio.image_set_delete.remove_product_from_minio_set_record", return_value=True) as remove_product,
        patch("pdd_agent.integrations.minio.image_set_delete._delete_all_under_image_set_prefixes") as remove_set,
        patch("pdd_agent.integrations.minio.image_set_delete._delete_all_under_prefixes") as remove_family,
        patch("pdd_agent.integrations.minio.image_set_delete._verify_prefixes_cleared", return_value=0),
        patch("pdd_agent.integrations.minio.image_set_delete.clear_minio_listing_targets_cache"),
    ):
        result = delete_minio_product_folder(selector="BD713/第一套图/BD713B")

    assert result.image_set_removed is False
    assert result.family_folder_removed is False
    remove_product.assert_called_once()
    remove_set.assert_not_called()
    remove_family.assert_not_called()


def test_delete_minio_product_folder_raises_when_not_found():
    cfg = _cfg()
    fake_client = MagicMock()
    fake_client.list_objects.return_value = []

    with (
        patch("pdd_agent.integrations.minio.image_set_delete.load_minio_config", return_value=cfg),
        patch("pdd_agent.integrations.minio.image_set_delete.minio_configured", return_value=True),
        patch("pdd_agent.integrations.minio.image_set_delete.load_set_index_record", return_value=None),
        patch("pdd_agent.integrations.minio.image_set_delete.get_minio_client", return_value=fake_client),
    ):
        with pytest.raises(ImageSetDeleteError):
            delete_minio_product_folder(selector="BD713/第一套图/BD713B")
