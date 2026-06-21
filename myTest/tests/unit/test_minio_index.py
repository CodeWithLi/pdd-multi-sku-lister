"""MinIO Redis 索引测试。"""

from __future__ import annotations

from unittest.mock import patch

from pdd_agent.integrations.minio.config import MinioConfig
from pdd_agent.integrations.minio.index import (
    MinioSetIndexRecord,
    find_sets_for_product_code,
    load_listing_targets_from_redis,
    object_prefix_from_object_key,
    resolve_minio_set_prefix,
    save_minio_index,
)
from pdd_agent.integrations.redis.config import RedisConfig


def _redis_cfg() -> RedisConfig:
    return RedisConfig(
        enabled=True,
        host="127.0.0.1",
        port=6380,
        password="secret",
        db=0,
        key_prefix="pdd",
    )


def _minio_cfg() -> MinioConfig:
    return MinioConfig(
        enabled=True,
        endpoint="127.0.0.1:9000",
        access_key="key",
        secret_key="secret",
        bucket="beilemei-images",
        categories=["笔袋"],
    )


def test_object_prefix_from_object_key():
    key = "笔袋/BD021/第一套图/BD021A卡皮巴拉笔袋/1.jpg"
    assert object_prefix_from_object_key(key, "BD021", "第一套图") == "笔袋/BD021/第一套图/"


def test_save_and_load_minio_index():
    cfg = _minio_cfg()
    records = [
        MinioSetIndexRecord(
            selector="BD021/第一套图",
            family_code="BD021",
            image_set="第一套图",
            object_prefix="笔袋/BD021/第一套图/",
            product_codes=("BD021A", "BD021B"),
        )
    ]

    store: dict[str, str | dict[str, str]] = {
        "pdd:minio:index:beilemei-images:sets": {},
        "pdd:minio:index:beilemei-images:codes": {},
    }

    class FakePipeline:
        def __init__(self):
            self.ops: list[tuple] = []

        def delete(self, *keys):
            self.ops.append(("delete", keys))
            return self

        def hset(self, key, mapping=None, **kwargs):
            self.ops.append(("hset", key, mapping or kwargs))
            return self

        def set(self, key, value):
            self.ops.append(("set", key, value))
            return self

        def execute(self):
            for op in self.ops:
                if op[0] == "delete":
                    for key in op[1]:
                        if key.endswith(":sets"):
                            store[key] = {}
                        elif key.endswith(":codes"):
                            store[key] = {}
                elif op[0] == "hset":
                    key, mapping = op[1], op[2]
                    store.setdefault(key, {})
                    store[key].update(mapping)
                elif op[0] == "set":
                    store[op[1]] = op[2]

    class FakeRedis:
        def pipeline(self):
            return FakePipeline()

        def hgetall(self, key):
            return dict(store.get(key) or {})

        def hget(self, key, field):
            bucket = store.get(key) or {}
            return bucket.get(field)

        def get(self, key):
            return store.get(key)

    fake = FakeRedis()

    with patch("pdd_agent.integrations.minio.index.redis_configured", return_value=True):
        with patch("pdd_agent.integrations.minio.index.get_redis_client", return_value=fake):
            with patch("pdd_agent.integrations.minio.index.load_redis_config", return_value=_redis_cfg()):
                assert save_minio_index(cfg, records) is True
                targets = load_listing_targets_from_redis(cfg)
                assert targets is not None
                assert targets[0].selector == "BD021/第一套图"
                assert targets[0].product_codes == ["BD021A", "BD021B"]
                assert resolve_minio_set_prefix("BD021", "第一套图", cfg) == "笔袋/BD021/第一套图/"
                found = find_sets_for_product_code("BD021A", cfg)
                assert len(found) == 1
                assert found[0].object_prefix == "笔袋/BD021/第一套图/"


def test_list_minio_listing_targets_reads_redis_before_scan():
    from pdd_agent.integrations.minio.catalog import clear_minio_listing_targets_cache, list_minio_listing_targets
    from pdd_agent.skills.listing.catalog import ListingTargetOption

    cfg = _minio_cfg()
    clear_minio_listing_targets_cache()
    target = ListingTargetOption(
        selector="BD021/第一套图",
        family_code="BD021",
        image_set="第一套图",
        product_codes=["BD021A"],
    )

    with patch("pdd_agent.integrations.minio.catalog.minio_configured", return_value=True):
        with patch("pdd_agent.integrations.minio.catalog.is_minio_index_fresh", return_value=True):
            with patch(
                "pdd_agent.integrations.minio.catalog.load_listing_targets_from_redis",
                return_value=[target],
            ) as load_fn:
                with patch("pdd_agent.integrations.minio.catalog._scan_minio_listing_targets") as scan_fn:
                    result = list_minio_listing_targets(cfg)
                    assert result[0].selector == "BD021/第一套图"
                    load_fn.assert_called_once()
                    scan_fn.assert_not_called()
