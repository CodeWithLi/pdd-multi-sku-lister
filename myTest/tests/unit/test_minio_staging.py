"""MinIO 本地缓存同步测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from pdd_agent.integrations.minio import staging


def test_object_needs_download_when_local_missing(tmp_path):
    client = MagicMock()
    dest = tmp_path / "1.png"
    assert staging._object_needs_download(client, "bucket", "key", dest) is True
    client.stat_object.assert_not_called()


def test_object_needs_download_skips_when_size_and_mtime_match(tmp_path):
    client = MagicMock()
    dest = tmp_path / "1.png"
    dest.write_bytes(b"x" * 10)
    remote_mtime = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    stat = MagicMock()
    stat.size = 10
    stat.last_modified = remote_mtime
    client.stat_object.return_value = stat
    dest.touch()
    import os

    os.utime(dest, (remote_mtime.timestamp() + 1, remote_mtime.timestamp() + 1))
    assert staging._object_needs_download(client, "bucket", "key", dest) is False


def test_object_needs_download_when_remote_newer(tmp_path):
    client = MagicMock()
    dest = tmp_path / "1.png"
    dest.write_bytes(b"x" * 10)
    remote_mtime = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)
    stat = MagicMock()
    stat.size = 10
    stat.last_modified = remote_mtime
    client.stat_object.return_value = stat
    import os

    os.utime(dest, (remote_mtime.timestamp() - 100, remote_mtime.timestamp() - 100))
    assert staging._object_needs_download(client, "bucket", "key", dest) is True


def test_prune_stale_local_product_folders_removes_renamed_legacy_dir(tmp_path):
    set_dir = tmp_path / "BD043" / "第一套图"
    legacy = set_dir / "BD043B"
    current = set_dir / "BD043B帕恰狗印花笔袋"
    legacy.mkdir(parents=True)
    current.mkdir(parents=True)
    (legacy / "old.png").write_bytes(b"old")
    (current / "new.png").write_bytes(b"new")

    removed = staging._prune_stale_local_product_folders(
        dest_root=tmp_path,
        family_code="BD043",
        image_set="第一套图",
        remote_product_folders={"BD043B帕恰狗印花笔袋"},
    )

    assert removed == 1
    assert not legacy.exists()
    assert current.is_dir()
    assert (current / "new.png").is_file()


def test_prune_stale_local_product_folders_keeps_matching_dirs(tmp_path):
    set_dir = tmp_path / "BD043" / "第一套图"
    keep_a = set_dir / "BD043A"
    keep_b = set_dir / "BD043B帕恰狗印花笔袋"
    keep_a.mkdir(parents=True)
    keep_b.mkdir(parents=True)

    removed = staging._prune_stale_local_product_folders(
        dest_root=tmp_path,
        family_code="BD043",
        image_set="第一套图",
        remote_product_folders={"BD043A", "BD043B帕恰狗印花笔袋"},
    )

    assert removed == 0
    assert keep_a.is_dir()
    assert keep_b.is_dir()


def test_prune_stale_local_product_folders_skips_when_remote_empty(tmp_path):
    stale = tmp_path / "BD043" / "第一套图" / "BD043B"
    stale.mkdir(parents=True)

    removed = staging._prune_stale_local_product_folders(
        dest_root=tmp_path,
        family_code="BD043",
        image_set="第一套图",
        remote_product_folders=set(),
    )

    assert removed == 0
    assert stale.is_dir()


def test_stage_minio_image_set_prunes_after_download(tmp_path, monkeypatch):
    cfg = MagicMock()
    cfg.bucket = "beilemei-images"
    monkeypatch.setattr(staging, "minio_configured", lambda config=None: True)
    monkeypatch.setattr(staging, "load_minio_config", lambda: cfg)
    monkeypatch.setattr(staging, "resolve_minio_set_prefix", lambda family, image_set, config=None: "笔袋/BD043/第一套图/")

    set_dir = tmp_path / "BD043" / "第一套图"
    stale = set_dir / "BD043B"
    stale.mkdir(parents=True)
    (stale / "1.png").write_bytes(b"x")

    class FakeObj:
        def __init__(self, name: str):
            self.object_name = name

    fake_client = MagicMock()
    fake_client.list_objects.return_value = [
        FakeObj("笔袋/BD043/第一套图/BD043B帕恰狗印花笔袋/1.png"),
    ]
    fake_client.stat_object.side_effect = Exception("force download")
    fake_client.fget_object.side_effect = lambda bucket, key, dest: Path(dest).write_bytes(b"new")

    monkeypatch.setattr(staging, "get_minio_client", lambda config=None: fake_client)

    downloaded, skipped, pruned_dirs, pruned_files, mismatches = staging.stage_minio_image_set(
        family_code="BD043",
        image_set="第一套图",
        config=cfg,
        cache_root=tmp_path,
    )

    assert downloaded == 1
    assert pruned_dirs == 1
    assert pruned_files == 0
    assert mismatches == []
    assert not stale.exists()
    assert (set_dir / "BD043B帕恰狗印花笔袋" / "1.png").is_file()


def test_prune_stale_local_image_files_removes_deleted_remote_images(tmp_path):
    dest_dir = tmp_path / "BD328A"
    dest_dir.mkdir(parents=True)
    for name in ("1.png", "2.png", "3.png", "4.png", "5.png", "old_a.png", "old_b.png", "old_c.png"):
        (dest_dir / name).write_bytes(b"x")

    removed = staging._prune_stale_local_image_files(
        dest_dir,
        {"1.png", "2.png", "3.png", "4.png", "5.png"},
    )

    assert removed == 3
    assert sorted(p.name for p in dest_dir.iterdir() if p.is_file()) == [
        "1.png",
        "2.png",
        "3.png",
        "4.png",
        "5.png",
    ]


def test_stage_minio_image_set_prunes_stale_files_within_product_folder(tmp_path, monkeypatch):
    cfg = MagicMock()
    cfg.bucket = "beilemei-images"
    monkeypatch.setattr(staging, "minio_configured", lambda config=None: True)
    monkeypatch.setattr(staging, "load_minio_config", lambda: cfg)
    monkeypatch.setattr(staging, "resolve_minio_set_prefix", lambda family, image_set, config=None: "笔袋/BD328/第一套图/")

    product_dir = tmp_path / "BD328" / "第一套图" / "BD328A"
    product_dir.mkdir(parents=True)
    for name in ("1.png", "2.png", "3.png", "4.png", "5.png", "6.png", "7.png", "8.png"):
        (product_dir / name).write_bytes(b"old")

    class FakeObj:
        def __init__(self, name: str):
            self.object_name = name

    fake_client = MagicMock()
    fake_client.list_objects.return_value = [
        FakeObj(f"笔袋/BD328/第一套图/BD328A/{name}")
        for name in ("1.png", "2.png", "3.png", "4.png", "5.png")
    ]
    fake_client.stat_object.side_effect = Exception("force download")
    fake_client.fget_object.side_effect = lambda bucket, key, dest: Path(dest).write_bytes(b"new")

    monkeypatch.setattr(staging, "get_minio_client", lambda config=None: fake_client)

    downloaded, skipped, pruned_dirs, pruned_files, mismatches = staging.stage_minio_image_set(
        family_code="BD328",
        image_set="第一套图",
        config=cfg,
        cache_root=tmp_path,
    )

    assert downloaded == 5
    assert pruned_dirs == 0
    assert pruned_files == 3
    assert mismatches == []
    assert sorted(p.name for p in product_dir.iterdir() if p.is_file()) == [
        "1.png",
        "2.png",
        "3.png",
        "4.png",
        "5.png",
    ]


def test_format_sync_mismatch_reports_count_diff(tmp_path):
    dest_dir = tmp_path / "BD328A"
    dest_dir.mkdir(parents=True)
    (dest_dir / "1.png").write_bytes(b"x")
    (dest_dir / "2.png").write_bytes(b"x")
    (dest_dir / "stale.png").write_bytes(b"x")

    message = staging._format_sync_mismatch(
        family_code="BD328",
        image_set="第一套图",
        product_code="BD328A",
        remote_filenames={"1.png", "2.png", "3.png"},
        dest_dir=dest_dir,
    )

    assert message is not None
    assert "MinIO 3 张，本地 3 张" in message
    assert "缺 3.png" in message
    assert "多 stale.png" in message


def test_stage_minio_for_product_codes_raises_when_counts_mismatch(tmp_path, monkeypatch):
    cfg = MagicMock()
    cfg.bucket = "beilemei-images"
    monkeypatch.setattr(staging, "minio_configured", lambda config=None: True)
    monkeypatch.setattr(staging, "load_minio_config", lambda: cfg)
    monkeypatch.setattr(staging, "minio_cache_root", lambda config=None: tmp_path)
    monkeypatch.setattr(
        staging,
        "stage_minio_image_set",
        lambda **kwargs: (0, 0, 0, 0, ["BD328/第一套图/BD328A: MinIO 5 张，本地 8 张；多 6.png, 7.png, 8.png"]),
    )

    try:
        staging.stage_minio_for_product_codes(["BD328/第一套图/BD328A"], config=cfg)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "图片数量不一致" in str(exc)
