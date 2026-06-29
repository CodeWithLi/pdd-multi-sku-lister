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

    downloaded, skipped, pruned = staging.stage_minio_image_set(
        family_code="BD043",
        image_set="第一套图",
        config=cfg,
        cache_root=tmp_path,
    )

    assert downloaded == 1
    assert pruned == 1
    assert not stale.exists()
    assert (set_dir / "BD043B帕恰狗印花笔袋" / "1.png").is_file()
