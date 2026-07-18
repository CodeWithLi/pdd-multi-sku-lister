from pathlib import Path
from unittest.mock import patch

from pdd_agent.integrations.minio.config import MinioConfig
from pdd_agent.integrations.minio.material import prepare_listing_assets


def test_prepare_listing_assets_uses_existing_cache_without_minio_calls():
    cache_root = Path("C:/cache/minio")
    cfg = MinioConfig(enabled=True)

    with patch("pdd_agent.integrations.minio.material.load_minio_config", return_value=cfg):
        with patch(
            "pdd_agent.integrations.minio.material.minio_cache_root",
            return_value=cache_root,
        ) as resolve_cache:
            with patch("pdd_agent.integrations.minio.material.minio_configured") as configured:
                with patch("pdd_agent.integrations.minio.material.stage_minio_for_product_codes") as stage:
                    source, assets_root = prepare_listing_assets(
                        ["BD720/第一套图/BD720A"],
                        material_source="minio",
                        use_minio_cache_only=True,
                    )

    assert source == "minio"
    assert assets_root == cache_root
    resolve_cache.assert_called_once_with(cfg)
    configured.assert_not_called()
    stage.assert_not_called()


def test_prepare_listing_assets_keeps_default_minio_sync_behavior():
    cache_root = Path("C:/cache/minio")
    selectors = ["BD720/第一套图/BD720A"]
    cfg = MinioConfig(enabled=True)

    with patch("pdd_agent.integrations.minio.material.load_minio_config", return_value=cfg):
        with patch("pdd_agent.integrations.minio.material.minio_configured", return_value=True):
            with patch(
                "pdd_agent.integrations.minio.material.stage_minio_for_product_codes",
                return_value=cache_root,
            ) as stage:
                source, assets_root = prepare_listing_assets(
                    selectors,
                    material_source="minio",
                )

    assert source == "minio"
    assert assets_root == cache_root
    stage.assert_called_once_with(selectors)


def test_prepare_listing_assets_uses_cache_when_minio_disabled():
    cache_root = Path("C:/cache/minio")
    cfg = MinioConfig(enabled=False)

    with patch("pdd_agent.integrations.minio.material.load_minio_config", return_value=cfg):
        with patch(
            "pdd_agent.integrations.minio.material.minio_cache_root",
            return_value=cache_root,
        ):
            with patch("pdd_agent.integrations.minio.material.minio_configured") as configured:
                with patch("pdd_agent.integrations.minio.material.stage_minio_for_product_codes") as stage:
                    source, assets_root = prepare_listing_assets(
                        ["BD720/第一套图/BD720A"],
                        material_source="minio",
                    )

    assert source == "minio"
    assert assets_root == cache_root
    configured.assert_not_called()
    stage.assert_not_called()
