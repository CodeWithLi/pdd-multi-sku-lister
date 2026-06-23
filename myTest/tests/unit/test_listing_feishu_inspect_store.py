"""飞书定价 inspect 持久化测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from pdd_agent.integrations.feishu.listing_feishu_inspect_store import (
    load_pipeline_feishu_inspect,
    merchant_codes_for_pipeline,
    save_pipeline_feishu_inspect,
)


def test_merchant_codes_for_pipeline():
    data = {
        "product_codes": ["BD021/第一套图/BD021A", "BD025A面包小狗笔袋"],
        "listing_unit_statuses": [
            {"listing_label": "BD032A樱桃蛋糕笔袋/第一套图/BD032A"},
        ],
    }
    codes = merchant_codes_for_pipeline(data)
    assert "BD021A" in codes
    assert "BD025A面包小狗笔袋" in codes
    assert "BD032A樱桃蛋糕笔袋" in codes


def test_save_and_load_pipeline_feishu_inspect(monkeypatch):
    stored_meta: dict = {}

    def fake_update(pipeline_id, meta_patch=None, **kwargs):
        stored_meta.update(meta_patch or {})

    row = MagicMock()
    row.meta = stored_meta

    monkeypatch.setattr(
        "pdd_agent.db.repositories.update_integrated_pipeline",
        fake_update,
    )
    monkeypatch.setattr(
        "pdd_agent.db.repositories.get_integrated_pipeline",
        lambda pipeline_id: row if pipeline_id == "pipe-1" else None,
    )
    monkeypatch.setattr(
        "pdd_agent.integrations.redis.client.get_redis_client",
        lambda **kwargs: None,
    )

    payload = {"codes": ["BD021A"], "items": []}
    saved = save_pipeline_feishu_inspect("pipe-1", payload)
    assert saved["pipeline_id"] == "pipe-1"
    assert saved["saved_at"]
    assert saved["codes"] == ["BD021A"]

    loaded = load_pipeline_feishu_inspect("pipe-1")
    assert loaded is not None
    assert loaded["codes"] == ["BD021A"]
