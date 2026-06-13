from datetime import datetime

from pdd_agent.api.services.published_price_status import derive_price_sync_status


def test_price_sync_status_none():
    assert derive_price_sync_status({}) == ("none", None)
    assert derive_price_sync_status(None) == ("none", None)


def test_price_sync_status_local_skus():
    meta = {"skus": [{"style_code": "A", "group_price": "19.9"}]}
    status, synced_at = derive_price_sync_status(meta)
    assert status == "local_skus"
    assert synced_at is None


def test_price_sync_status_list_price():
    synced = "2026-06-12T10:00:00"
    meta = {
        "pdd_goods_lookup": {
            "status": "searched",
            "synced_at": synced,
            "list_row": {"group_price": "13.8", "activity_price": "12.8"},
        }
    }
    status, synced_at = derive_price_sync_status(meta)
    assert status == "list_price"
    assert isinstance(synced_at, datetime)


def test_price_sync_status_edit_opened():
    meta = {
        "pdd_goods_lookup": {
            "status": "detail_opened",
            "synced_at": "2026-06-12T10:00:00",
            "list_row": {"group_price": "13.8"},
        }
    }
    status, synced_at = derive_price_sync_status(meta)
    assert status == "list_price"
    assert synced_at is not None


def test_price_sync_status_specs_synced():
    meta = {
        "pdd_goods_lookup": {
            "status": "specs_synced",
            "synced_at": "2026-06-12T10:00:00",
            "pdd_skus": [
                {
                    "style_name": "蓝色笔袋",
                    "package_name": "单件装",
                    "group_price": "13.80",
                    "spec_code": "BD630D",
                }
            ],
        }
    }
    status, synced_at = derive_price_sync_status(meta)
    assert status == "specs_synced"
    assert synced_at is not None
