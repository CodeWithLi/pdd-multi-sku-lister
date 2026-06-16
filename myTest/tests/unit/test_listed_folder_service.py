"""已上架素材文件夹记录单元测试。"""

from unittest.mock import patch

from pdd_agent.api.services.listed_folder_service import record_listed_folder_from_item
from pdd_agent.db.repositories import build_folder_selector


def test_build_folder_selector_three_level():
    assert (
        build_folder_selector(family_code="BD720", image_set="第一套图", product_code="BD720A")
        == "BD720/第一套图/BD720A"
    )


def test_build_folder_selector_two_level_without_product():
    assert build_folder_selector(family_code="BD720", image_set="第一套图", product_code="") == "BD720/第一套图"


def test_record_listed_folder_from_item_calls_upsert():
    item = {
        "status": "success",
        "pdd_product_id": "965182969751",
        "product_code": "BD720A",
        "family_code": "BD720",
        "image_set": "第一套图",
        "listing_label": "BD720A/第一套图",
        "spec_metadata": {"root": "data/assets/商品上架规格文件/BD720/第一套图/BD720A"},
    }
    with patch(
        "pdd_agent.api.services.listed_folder_service.resolve_listing_source_meta",
        return_value=("integrated_pipeline", "pipe_1"),
    ):
        with patch("pdd_agent.api.services.listed_folder_service.upsert_listed_asset_folder") as upsert:
            record_listed_folder_from_item("run_1", "store_A", item)
    upsert.assert_called_once()
    kwargs = upsert.call_args.kwargs
    assert kwargs["account_id"] == "store_A"
    assert kwargs["folder_selector"] == "BD720/第一套图/BD720A"
    assert kwargs["source_kind"] == "integrated_pipeline"
    assert kwargs["pipeline_id"] == "pipe_1"


def test_record_listed_folder_skips_non_success():
    with patch("pdd_agent.api.services.listed_folder_service.upsert_listed_asset_folder") as upsert:
        record_listed_folder_from_item("run_1", "store_A", {"status": "failed"})
    upsert.assert_not_called()


def test_remove_listed_folder_for_published_product():
    with patch(
        "pdd_agent.api.services.listed_folder_service.delete_listed_asset_folder_for_product",
        return_value=True,
    ) as delete_fn:
        from pdd_agent.api.services.listed_folder_service import remove_listed_folder_for_published_product

        ok = remove_listed_folder_for_published_product(
            account_id="store_A",
            product_code="BD719B",
            family_code="BD719",
            image_set="第一套图",
        )
    assert ok is True
    delete_fn.assert_called_once_with(
        account_id="store_A",
        product_code="BD719B",
        family_code="BD719",
        image_set="第一套图",
    )
