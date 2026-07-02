"""本地 minio_cache 废弃套图清理测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pdd_agent.integrations.minio import local_cache_prune


def test_list_local_image_set_names_filters_non_set_dirs(tmp_path):
    family_dir = tmp_path / "AXBC001"
    (family_dir / "第一套图").mkdir(parents=True)
    (family_dir / "第二套图").mkdir(parents=True)
    (family_dir / "备注").mkdir(parents=True)
    (family_dir / ".alist").mkdir(parents=True)

    names = local_cache_prune.list_local_image_set_names("AXBC001", cache_root=tmp_path)

    assert names == {"第一套图", "第二套图"}


def test_prune_stale_local_image_sets_for_family_removes_absent_sets(tmp_path, monkeypatch):
    family_dir = tmp_path / "AXBC001"
    for image_set in ("第一套图", "第二套图", "第三套图"):
        (family_dir / image_set / "AXBC001A").mkdir(parents=True)
        (family_dir / image_set / "AXBC001A" / "1.png").write_bytes(b"x")

    monkeypatch.setattr(
        local_cache_prune,
        "list_remote_image_sets_for_family",
        lambda family_code, config=None: {"第一套图"},
    )

    removed, names = local_cache_prune.prune_stale_local_image_sets_for_family(
        "AXBC001",
        cache_root=tmp_path,
    )

    assert removed == 2
    assert set(names) == {"第二套图", "第三套图"}
    assert (family_dir / "第一套图").is_dir()
    assert not (family_dir / "第二套图").exists()
    assert not (family_dir / "第三套图").exists()


def test_prune_stale_local_image_sets_for_family_skips_when_remote_empty(tmp_path, monkeypatch):
    family_dir = tmp_path / "AXBC001"
    (family_dir / "第一套图").mkdir(parents=True)

    monkeypatch.setattr(
        local_cache_prune,
        "list_remote_image_sets_for_family",
        lambda family_code, config=None: set(),
    )

    removed, names = local_cache_prune.prune_stale_local_image_sets_for_family(
        "AXBC001",
        cache_root=tmp_path,
    )

    assert removed == 0
    assert names == []
    assert (family_dir / "第一套图").is_dir()


def test_prune_stale_local_image_sets_for_families_batches(tmp_path, monkeypatch):
    for family in ("AXBC001", "BD043"):
        (tmp_path / family / "第一套图").mkdir(parents=True)
        (tmp_path / family / "第二套图").mkdir(parents=True)

    def fake_remote(family_code: str, config=None):
        return {"第一套图"} if family_code == "AXBC001" else {"第一套图", "第二套图"}

    monkeypatch.setattr(local_cache_prune, "list_remote_image_sets_for_family", fake_remote)

    removed, by_family = local_cache_prune.prune_stale_local_image_sets_for_families(
        ["AXBC001", "BD043"],
        cache_root=tmp_path,
    )

    assert removed == 1
    assert by_family == {"AXBC001": ["第二套图"]}
    assert (tmp_path / "BD043" / "第二套图").is_dir()


def test_list_remote_image_sets_for_family_scans_minio(monkeypatch):
    cfg = MagicMock()
    cfg.bucket = "beilemei-images"
    cfg.categories = ["笔袋"]
    cfg.prefix = ""

    class FakeObj:
        def __init__(self, name: str):
            self.object_name = name

    fake_client = MagicMock()
    fake_client.list_objects.return_value = [
        FakeObj("笔袋/AXBC001/第一套图/AXBC001A/1.png"),
        FakeObj("笔袋/AXBC001/第一套图/AXBC001A/2.png"),
    ]

    monkeypatch.setattr(local_cache_prune, "minio_configured", lambda config=None: True)
    monkeypatch.setattr(local_cache_prune, "get_minio_client", lambda config=None: fake_client)
    monkeypatch.setattr(local_cache_prune, "_scan_prefixes", lambda config: [])

    image_sets = local_cache_prune.list_remote_image_sets_for_family("AXBC001", config=cfg)

    assert image_sets == {"第一套图"}
    fake_client.list_objects.assert_called_once_with("beilemei-images", prefix="笔袋/AXBC001/", recursive=True)
