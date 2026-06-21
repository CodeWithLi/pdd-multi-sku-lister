"""MinIO 素材目录扫描测试。"""

from unittest.mock import MagicMock, patch

from pdd_agent.integrations.minio.catalog import (
    build_minio_catalog_set_index,
    extract_product_code,
    list_minio_listing_targets,
)
from pdd_agent.integrations.minio.config import MinioConfig


def _object(name: str):
    obj = MagicMock()
    obj.object_name = name
    return obj


def test_extract_product_code_from_folder_name():
    assert extract_product_code("BD021A卡皮巴拉笔袋") == "BD021A"
    assert extract_product_code("BD029A") == "BD029A"
    assert extract_product_code("AXBD001B") == "AXBD001B"


def test_list_minio_listing_targets_groups_by_family_and_image_set():
    objects = [
        _object("笔袋/BD021/第一套图/BD021A卡皮巴拉笔袋/1.jpg"),
        _object("笔袋/BD021/第一套图/BD021A卡皮巴拉笔袋/2.jpg"),
        _object("笔袋/BD021/第一套图/BD021B毛绒小猫笔袋/1.jpg"),
        _object("笔袋/BD029/第一套图/BD029A/1.png"),
        _object("笔袋/BD029/第一套图/BD029B/1.png"),
        _object("公仔/GJ01/GJ01A灰太狼成品/主图1.jpg"),
    ]
    cfg = MinioConfig(
        enabled=True,
        endpoint="127.0.0.1:9000",
        access_key="key",
        secret_key="secret",
        bucket="beilemei-images",
        categories=["笔袋"],
    )

    client = MagicMock()
    client.list_objects.return_value = objects

    with patch("pdd_agent.integrations.minio.catalog.get_minio_client", return_value=client):
        with patch("pdd_agent.integrations.minio.catalog.minio_configured", return_value=True):
            targets = list_minio_listing_targets(cfg)

    selectors = {item.selector: set(item.product_codes) for item in targets}
    assert selectors["BD021/第一套图"] == {"BD021A", "BD021B"}
    assert selectors["BD029/第一套图"] == {"BD029A", "BD029B"}
    assert "GJ01/GJ01A灰太狼成品" not in selectors


def test_build_minio_catalog_set_index():
    item = MagicMock()
    item.selector = "BD021/第一套图"
    item.product_codes = ("BD021A", "BD021B")

    with patch("pdd_agent.integrations.minio.catalog.list_minio_listing_targets", return_value=[item]):
        index = build_minio_catalog_set_index()
    assert index["BD021/第一套图"] == frozenset({"BD021A", "BD021B"})


def test_listing_target_options_with_minio_source():
    from pdd_agent.api.services.catalog_service import list_listing_target_options
    from pdd_agent.skills.listing.catalog import ListingTargetOption

    target = ListingTargetOption(
        selector="BD021/第一套图",
        family_code="BD021",
        image_set="第一套图",
        product_codes=("BD021A", "BD021B"),
    )

    with patch("pdd_agent.api.services.catalog_service._listing_targets_for_source", return_value=[target]):
        with patch(
            "pdd_agent.api.services.listed_folder_service.listed_product_codes_by_set",
            return_value={"BD021/第一套图": ["BD021A"]},
        ):
            options = list_listing_target_options(account_id="store_A", material_source="minio")

    assert len(options) == 1
    opt = options[0]
    assert opt.listed_product_codes == ["BD021A"]
    assert opt.unlisted_product_codes == ["BD021B"]
    assert opt.is_fully_listed is False
