"""循环上架 MinIO 套图解析测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve import (
    extract_cycle_relist_family_code,
    resolve_cycle_relist_listing_selector,
)
from pdd_agent.integrations.minio.index import MinioSetIndexRecord
from pdd_agent.integrations.minio.config import MinioConfig


def test_extract_cycle_relist_family_code():
    assert extract_cycle_relist_family_code("BD685B") == "BD685"
    assert extract_cycle_relist_family_code("BD023B毛绒小猫笔袋") == "BD023"
    assert extract_cycle_relist_family_code("BD023") == "BD023"


def test_resolve_single_image_set_found(monkeypatch):
    records = [
        MinioSetIndexRecord(
            selector="BD023/第一套图",
            family_code="BD023",
            image_set="第一套图",
            object_prefix="笔袋/BD023/第一套图/",
            product_codes=("BD023B毛绒小猫笔袋", "BD023A"),
        )
    ]
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve.minio_configured",
        lambda config=None: True,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve._records_for_family",
        lambda family_code, config=None: records if family_code == "BD023" else [],
    )

    result = resolve_cycle_relist_listing_selector("BD023B毛绒小猫笔袋")
    assert result.ok is True
    assert result.family_code == "BD023"
    assert result.image_set == "第一套图"
    assert result.product_folder == "BD023B毛绒小猫笔袋"
    assert result.selector == "BD023/第一套图/BD023B毛绒小猫笔袋"


def test_resolve_single_image_set_missing(monkeypatch):
    records = [
        MinioSetIndexRecord(
            selector="BD685/第一套图",
            family_code="BD685",
            image_set="第一套图",
            object_prefix="笔袋/BD685/第一套图/",
            product_codes=("BD685A",),
        )
    ]
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve.minio_configured",
        lambda config=None: True,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve._records_for_family",
        lambda family_code, config=None: records,
    )

    result = resolve_cycle_relist_listing_selector("BD685B")
    assert result.ok is False
    assert "仅有一套图" in result.error
    assert "BD685B" in result.error


def test_resolve_multiple_image_sets_search_in_order(monkeypatch):
    records = [
        MinioSetIndexRecord(
            selector="BD023/第一套图",
            family_code="BD023",
            image_set="第一套图",
            object_prefix="笔袋/BD023/第一套图/",
            product_codes=("BD023A",),
        ),
        MinioSetIndexRecord(
            selector="BD023/第二套图",
            family_code="BD023",
            image_set="第二套图",
            object_prefix="笔袋/BD023/第二套图/",
            product_codes=("BD023B毛绒小猫笔袋",),
        ),
    ]
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve.minio_configured",
        lambda config=None: True,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve._records_for_family",
        lambda family_code, config=None: records,
    )

    result = resolve_cycle_relist_listing_selector("BD023B毛绒小猫笔袋")
    assert result.ok is True
    assert result.image_set == "第二套图"
    assert result.selector == "BD023/第二套图/BD023B毛绒小猫笔袋"


def test_resolve_family_not_found(monkeypatch):
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve.minio_configured",
        lambda config=None: True,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve._records_for_family",
        lambda family_code, config=None: [],
    )

    result = resolve_cycle_relist_listing_selector("BD999B")
    assert result.ok is False
    assert "未找到母款号目录" in result.error


def test_resolve_uses_local_cache_records_when_minio_disabled(monkeypatch):
    records = [
        MinioSetIndexRecord(
            selector="BD023/第一套图",
            family_code="BD023",
            image_set="第一套图",
            object_prefix="BD023/第一套图/",
            product_codes=("BD023B毛绒小猫笔袋",),
        )
    ]
    cfg = MinioConfig(enabled=False)
    monkeypatch.setattr(
        "pdd_agent.integrations.feishu.pdd_failure_cycle_relist_resolve._records_for_family",
        lambda family_code, config=None: records,
    )

    result = resolve_cycle_relist_listing_selector("BD023B毛绒小猫笔袋", config=cfg)

    assert result.ok is True
    assert result.selector == "BD023/第一套图/BD023B毛绒小猫笔袋"
