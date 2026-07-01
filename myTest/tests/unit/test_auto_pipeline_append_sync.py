"""追加图片自动上架：先全量同步套图再触发整合链路。"""

from unittest.mock import patch

from pdd_agent.integrations.minio.auto_pipeline import (
    batch_should_broadcast_upload,
    listing_includes_append_products,
    maybe_trigger_auto_pipeline,
    selectors_from_product_codes,
)


def _append_batch() -> dict:
    return {
        "status": "success",
        "indexed_file_count": 3,
        "groups": [
            {
                "change_type": "append_to_product",
                "selector": "BD046/第一套图",
                "product_code": "BD046A",
            }
        ],
    }


def test_selectors_from_product_codes():
    assert selectors_from_product_codes(["BD046/第一套图/BD046A", "BD046/第一套图/BD046B"]) == [
        "BD046/第一套图"
    ]


def test_listing_includes_append_products():
    batch = _append_batch()
    assert listing_includes_append_products(["BD046/第一套图/BD046A"], batch) is True
    assert listing_includes_append_products(["BD720/第一套图/ABC123"], batch) is False


def test_batch_should_broadcast_when_append_matches_trigger_mode():
    batch = _append_batch()
    cfg = patch(
        "pdd_agent.integrations.minio.auto_pipeline.load_auto_pipeline_config",
        return_value=type("Cfg", (), {"enabled": True, "trigger_mode": "all"})(),
    )
    with cfg:
        assert batch_should_broadcast_upload(batch) is True


def test_maybe_trigger_append_uses_full_set_sync():
    batch = _append_batch()
    cfg_obj = type(
        "Cfg",
        (),
        {
            "enabled": True,
            "trigger_mode": "append_to_product",
            "account_id": "store_A",
            "activity_ids": ["20981"],
            "material_source": "minio",
            "auto_sync_minio": False,
            "category_keyword": "玩偶",
            "auto_promotion": True,
            "auto_limited_time_setup": True,
            "continue_after_limited_time_failure": False,
            "continue_after_activity_failure": False,
            "demo_mode": True,
            "activity_delay_hours": 24.0,
            "slot_alignment_test": True,
        },
    )()

    with patch("pdd_agent.integrations.minio.auto_pipeline.load_auto_pipeline_config", return_value=cfg_obj):
        with patch("pdd_agent.integrations.minio.auto_pipeline._mark_dedup", return_value=False):
            result = maybe_trigger_auto_pipeline(batch)

    assert result["triggered"] is True
    assert result["append_sync_full_image_set"] is True
    assert result["synced_selectors"] == ["BD046/第一套图"]
