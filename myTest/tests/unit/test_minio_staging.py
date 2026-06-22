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
