"""素材目录与已上架状态对齐测试。"""

from unittest.mock import MagicMock, patch

from pdd_agent.api.services.catalog_service import list_listing_target_options
from pdd_agent.api.services.listed_folder_service import listed_product_codes_by_set
from pdd_agent.db.repositories import get_listed_product_codes_for_set, prune_listed_folders_against_catalog


def test_listing_target_pending_when_catalog_grows():
    catalog_item = MagicMock()
    catalog_item.selector = "BD716/第一套图"
    catalog_item.family_code = "BD716"
    catalog_item.image_set = "第一套图"
    catalog_item.product_codes = ("BD716A", "BD716B", "BD716C", "BD716D")

    with patch("pdd_agent.api.services.catalog_service.list_listing_targets", return_value=[catalog_item]):
        with patch(
            "pdd_agent.api.services.listed_folder_service.listed_product_codes_by_set",
            return_value={"BD716/第一套图": ["BD716A", "BD716B", "BD716C"]},
        ):
            options = list_listing_target_options(account_id="store_A")

    assert len(options) == 1
    opt = options[0]
    assert opt.product_count == 4
    assert opt.listed_count == 3
    assert opt.unlisted_count == 1
    assert opt.unlisted_product_codes == ["BD716D"]
    assert opt.is_fully_listed is False
    assert opt.has_pending_listing is True


def test_prune_listed_folders_when_product_removed_from_catalog():
    row = MagicMock()
    row.account_id = "store_A"
    row.family_code = "BD716"
    row.image_set = "第一套图"
    row.product_code = "BD716D"
    row.folder_selector = "BD716/第一套图/BD716D"

    catalog_index = {"BD716/第一套图": frozenset({"BD716A", "BD716B", "BD716C"})}

    with patch("pdd_agent.db.repositories.is_database_available", return_value=True):
        with patch("pdd_agent.db.repositories.list_listed_asset_folders", return_value=[row]):
            with patch("pdd_agent.db.repositories.delete_listed_asset_folder_for_product", return_value=True) as delete_fn:
                removed = prune_listed_folders_against_catalog(account_id="store_A", catalog_index=catalog_index)

    assert removed == 1
    delete_fn.assert_called_once()


def test_get_listed_product_codes_remapped_when_image_set_differs():
    row = MagicMock()
    row.account_id = "store_A"
    row.family_code = "AXBD001"
    row.image_set = "第一奔跑"
    row.product_code = "AXBD001A"
    row.folder_selector = "AXBD001/第一奔跑/AXBD001A"

    minio_catalog = {"AXBD001/第一套图": frozenset({"AXBD001A", "AXBD001B"})}

    with patch("pdd_agent.db.repositories.list_listed_asset_folders", return_value=[row]):
        listed = get_listed_product_codes_for_set("store_A", catalog_index=minio_catalog)

    assert listed["AXBD001/第一套图"] == ["AXBD001A"]


def test_listed_product_codes_by_set_minio_uses_on_sale_published():
    minio_catalog = {"AXBD001/第一奔跑": frozenset({"AXBD001A", "AXBD001B"})}

    with patch(
        "pdd_agent.integrations.minio.catalog.build_minio_catalog_set_index",
        return_value=minio_catalog,
    ):
        with patch(
            "pdd_agent.api.services.listed_folder_service.prune_listed_folders_against_catalog",
            return_value=0,
        ):
            with patch(
                "pdd_agent.api.services.listed_folder_service.get_listed_product_codes_for_set",
                return_value={},
            ):
                with patch(
                    "pdd_agent.api.services.listed_folder_service.list_on_sale_published_product_codes",
                    return_value=frozenset({"AXBD001A", "AXBD001B"}),
                ):
                    listed = listed_product_codes_by_set("store_A", material_source="minio")

    assert listed["AXBD001/第一奔跑"] == ["AXBD001A", "AXBD001B"]


def test_listing_target_options_minio_shows_listed_from_published():
    from pdd_agent.skills.listing.catalog import ListingTargetOption

    target = ListingTargetOption(
        selector="AXBD001/第一奔跑",
        family_code="AXBD001",
        image_set="第一奔跑",
        product_codes=("AXBD001A", "AXBD001B"),
    )

    with patch("pdd_agent.api.services.catalog_service._listing_targets_for_source", return_value=[target]):
        with patch(
            "pdd_agent.api.services.listed_folder_service.listed_product_codes_by_set",
            return_value={"AXBD001/第一奔跑": ["AXBD001A", "AXBD001B"]},
        ):
            options = list_listing_target_options(account_id="store_A", material_source="minio")

    assert options[0].listed_product_codes == ["AXBD001A", "AXBD001B"]
    assert options[0].unlisted_product_codes == []
    assert options[0].is_fully_listed is True


def test_prune_minio_keeps_row_when_product_code_still_in_catalog():
    row = MagicMock()
    row.account_id = "store_A"
    row.family_code = "AXBD001"
    row.image_set = "第一奔跑"
    row.product_code = "AXBD001A"
    row.folder_selector = "AXBD001/第一奔跑/AXBD001A"

    catalog_index = {"AXBD001/第一套图": frozenset({"AXBD001A", "AXBD001B"})}

    with patch("pdd_agent.db.repositories.is_database_available", return_value=True):
        with patch("pdd_agent.db.repositories.list_listed_asset_folders", return_value=[row]):
            with patch("pdd_agent.db.repositories.delete_listed_asset_folder_for_product") as delete_fn:
                removed = prune_listed_folders_against_catalog(
                    account_id="store_A",
                    catalog_index=catalog_index,
                    match_by_product_code=True,
                )

    assert removed == 0
    delete_fn.assert_not_called()
