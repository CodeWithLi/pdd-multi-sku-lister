"""RabbitMQ 自动上架配置与商品编码提取。"""

from pdd_agent.integrations.minio.auto_pipeline import extract_auto_pipeline_product_codes


def _batch(groups: list[dict]) -> dict:
    return {"groups": groups, "status": "success", "indexed_file_count": 1}


def test_extract_new_product_folder_only():
    batch = _batch(
        [
            {
                "change_type": "new_product_folder",
                "selector": "BD720/第一套图",
                "product_code": "ABC123",
            },
            {
                "change_type": "append_to_product",
                "selector": "BD720/第一套图",
                "product_code": "DEF456",
            },
        ]
    )
    codes = extract_auto_pipeline_product_codes(batch, "new_product_folder")
    assert codes == ["BD720/第一套图/ABC123"]


def test_extract_new_product_folder_includes_new_image_set():
    batch = _batch(
        [
            {
                "change_type": "new_image_set",
                "selector": "BD713719/第一套图",
                "product_code": "BD713A",
            },
            {
                "change_type": "append_to_product",
                "selector": "BD720/第一套图",
                "product_code": "DEF456",
            },
        ]
    )
    codes = extract_auto_pipeline_product_codes(batch, "new_product_folder")
    assert codes == ["BD713719/第一套图/BD713A"]


def test_extract_append_only():
    batch = _batch(
        [
            {
                "change_type": "new_product_folder",
                "selector": "BD720/第一套图",
                "product_code": "ABC123",
            },
            {
                "change_type": "append_to_product",
                "selector": "BD720/第一套图",
                "product_code": "DEF456",
            },
        ]
    )
    codes = extract_auto_pipeline_product_codes(batch, "append_to_product")
    assert codes == ["BD720/第一套图/DEF456"]


def test_extract_all_includes_new_image_set():
    batch = _batch(
        [
            {
                "change_type": "new_image_set",
                "selector": "BD721/第二套图",
                "product_code": "SKU001",
            },
            {
                "change_type": "append_to_product",
                "selector": "BD720/第一套图",
                "product_code": "DEF456",
            },
        ]
    )
    codes = extract_auto_pipeline_product_codes(batch, "all")
    assert codes == ["BD721/第二套图/SKU001", "BD720/第一套图/DEF456"]
