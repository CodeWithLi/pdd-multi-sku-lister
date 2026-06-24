"""套图联动删除测试。"""

from unittest.mock import MagicMock, patch

import pytest

from pdd_agent.integrations.minio.config import MinioConfig
from pdd_agent.integrations.minio.image_set_delete import (
    ImageSetDeleteError,
    _candidate_prefixes,
    _delete_all_under_prefixes,
    _family_prefix_candidates,
    _family_prefix_from_set_prefix,
    _is_safe_family_delete_prefix,
    delete_minio_image_set,
    should_remove_family_folder,
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


def test_candidate_prefixes_includes_category_and_index_prefix():
    cfg = _cfg()
    prefixes = _candidate_prefixes(
        cfg,
        family_code="BD021",
        image_set="第一套图",
        object_prefix="笔袋/BD021/第一套图/",
    )
    assert "笔袋/BD021/第一套图/" in prefixes
    assert "BD021/第一套图/" in prefixes
    assert "公仔/BD021/第一套图/" in prefixes


def test_family_prefix_from_set_prefix():
    assert _family_prefix_from_set_prefix("笔袋/BD037/第一套图/", family_code="BD037") == "笔袋/BD037/"
    assert _family_prefix_from_set_prefix("笔袋/BD037/", family_code="BD037") == "笔袋/BD037/"
    assert _family_prefix_from_set_prefix("笔袋/第一套图/", family_code="BD037") == ""


def test_is_safe_family_delete_prefix_blocks_category_only():
    assert not _is_safe_family_delete_prefix("笔袋/", "BD037")
    assert not _is_safe_family_delete_prefix("BD037/", "BD037")
    assert _is_safe_family_delete_prefix("笔袋/BD037/", "BD037")


def test_family_prefix_candidates_never_includes_category_only():
    cfg = _cfg()
    prefixes = _family_prefix_candidates(cfg, "BD037", hint_prefix="笔袋/BD037/")
    assert "笔袋/" not in prefixes
    assert "笔袋/BD037/" in prefixes
    assert "公仔/BD037/" in prefixes


def test_family_prefix_candidates_from_image_set_hint():
    cfg = _cfg()
    prefixes = _family_prefix_candidates(cfg, "BD037", hint_prefix="笔袋/BD037/第一套图/")
    assert "笔袋/" not in prefixes
    assert "笔袋/BD037/" in prefixes


def test_delete_all_under_prefixes_skips_unsafe_prefixes():
    cfg = _cfg()
    fake_client = MagicMock()
    fake_client.list_objects.return_value = []

    with patch("pdd_agent.integrations.minio.image_set_delete.get_minio_client", return_value=fake_client):
        deleted = _delete_all_under_prefixes(cfg, ["笔袋/", "笔袋/BD037/"], family_code="BD037")

    assert deleted == 0
    fake_client.list_objects.assert_called_once()
    assert fake_client.list_objects.call_args.kwargs["prefix"] == "笔袋/BD037/"


def test_should_remove_family_when_no_other_sets():
    cfg = _cfg()
    with (
        patch(
            "pdd_agent.integrations.minio.image_set_delete.list_indexed_image_sets_for_family",
            return_value=set(),
        ),
        patch(
            "pdd_agent.integrations.minio.image_set_delete._image_sets_with_listing_in_minio",
            return_value={"第一套图"},
        ),
    ):
        assert should_remove_family_folder(
            cfg,
            "BD021",
            exclude_image_set="第一套图",
            family_prefix_hint="笔袋/BD021/",
        )


def test_should_keep_family_when_other_set_exists():
    cfg = _cfg()
    with (
        patch(
            "pdd_agent.integrations.minio.image_set_delete.list_indexed_image_sets_for_family",
            return_value={"第二套图"},
        ),
        patch(
            "pdd_agent.integrations.minio.image_set_delete._image_sets_with_listing_in_minio",
            return_value={"第一套图", "第二套图"},
        ),
    ):
        assert not should_remove_family_folder(
            cfg,
            "BD021",
            exclude_image_set="第一套图",
            family_prefix_hint="笔袋/BD021/",
        )


def test_delete_minio_image_set_removes_family_when_last_set():
    cfg = _cfg()
    record = MinioSetIndexRecord(
        selector="BD021/第一套图",
        family_code="BD021",
        image_set="第一套图",
        object_prefix="笔袋/BD021/第一套图/",
        product_codes=("SKU001",),
    )

    class FakeObj:
        def __init__(self, name: str):
            self.object_name = name

    fake_client = MagicMock()
    fake_client.list_objects.return_value = [
        FakeObj("笔袋/BD021/第一套图/SKU001/1.jpg"),
    ]
    fake_client.remove_objects.return_value = []

    with (
        patch("pdd_agent.integrations.minio.image_set_delete.load_minio_config", return_value=cfg),
        patch("pdd_agent.integrations.minio.image_set_delete.minio_configured", return_value=True),
        patch("pdd_agent.integrations.minio.image_set_delete.load_set_index_record", return_value=record),
        patch("pdd_agent.integrations.minio.image_set_delete.resolve_minio_set_prefix", return_value=record.object_prefix),
        patch("pdd_agent.integrations.minio.image_set_delete.get_minio_client", return_value=fake_client),
        patch("pdd_agent.integrations.minio.image_set_delete.should_remove_family_folder", return_value=True),
        patch(
            "pdd_agent.integrations.minio.image_set_delete._collect_remaining_image_sets",
            return_value=set(),
        ),
        patch("pdd_agent.integrations.minio.image_set_delete.alist_configured", return_value=True),
        patch("pdd_agent.integrations.minio.image_set_delete.login_alist", return_value="token"),
        patch("pdd_agent.integrations.minio.image_set_delete.delete_alist_path") as delete_alist,
        patch("pdd_agent.integrations.minio.image_set_delete._delete_all_under_prefixes", return_value=1) as family_delete,
        patch("pdd_agent.integrations.minio.image_set_delete._verify_prefixes_cleared", return_value=0),
        patch("pdd_agent.integrations.minio.image_set_delete.remove_minio_set_record", return_value=True),
        patch("pdd_agent.integrations.minio.image_set_delete._clear_local_cache", return_value=True),
        patch("pdd_agent.integrations.minio.image_set_delete.clear_minio_listing_targets_cache"),
    ):
        result = delete_minio_image_set(selector="BD021/第一套图")

    assert result.family_folder_removed is True
    assert delete_alist.call_count >= 1
    family_delete.assert_called_once()
    assert family_delete.call_args.kwargs["family_code"] == "BD021"


def test_delete_minio_image_set_raises_when_not_found():
    cfg = _cfg()
    fake_client = MagicMock()
    fake_client.list_objects.return_value = []

    with (
        patch("pdd_agent.integrations.minio.image_set_delete.load_minio_config", return_value=cfg),
        patch("pdd_agent.integrations.minio.image_set_delete.minio_configured", return_value=True),
        patch("pdd_agent.integrations.minio.image_set_delete.load_set_index_record", return_value=None),
        patch("pdd_agent.integrations.minio.image_set_delete.resolve_minio_set_prefix", return_value=None),
        patch("pdd_agent.integrations.minio.image_set_delete.get_minio_client", return_value=fake_client),
    ):
        with pytest.raises(ImageSetDeleteError):
            delete_minio_image_set(selector="BD021/第一套图")
