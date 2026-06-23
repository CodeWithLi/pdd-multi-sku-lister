"""飞书缓存清理测试。"""

from __future__ import annotations

from pdd_agent.integrations.feishu.cache import clear_feishu_data_caches
from pdd_agent.integrations.feishu.pdd_price_compare_sync import _CACHE as price_cache
from pdd_agent.integrations.feishu.pdd_product_catalog_sync import _CACHE as catalog_cache


def test_clear_feishu_data_caches():
    price_cache["range_catalog"] = object()
    price_cache["loaded_at"] = 999.0
    catalog_cache["catalog"] = {"X": object()}
    catalog_cache["loaded_at"] = 999.0

    result = clear_feishu_data_caches()

    assert result["success"] is True
    assert "price_compare" in result["cleared"]
    assert "product_catalog" in result["cleared"]
    assert price_cache.get("range_catalog") is None
    assert catalog_cache.get("catalog") is None
