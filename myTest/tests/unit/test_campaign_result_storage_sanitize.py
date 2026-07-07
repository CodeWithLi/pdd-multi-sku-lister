"""campaign_result_storage_sanitize 单元测试。"""

import json

from pdd_agent.api.services.campaign_result_storage_sanitize import (
    json_safe_campaign_result_for_storage,
    sanitize_campaign_result_for_storage,
)


class FakePage:
    def url(self):
        return "https://mms.pinduoduo.com/act/index"


def test_sanitize_campaign_result_strips_page_objects():
    payload = {
        "status": "failed",
        "page_guard": {
            "focus": {
                "candidates": [
                    {
                        "page": FakePage(),
                        "url": "https://mms.pinduoduo.com/act/index",
                        "score": 120,
                    }
                ]
            }
        },
    }
    cleaned = sanitize_campaign_result_for_storage(payload)
    json.dumps(cleaned)
    candidate = cleaned["page_guard"]["focus"]["candidates"][0]
    assert "page" in candidate
    assert isinstance(candidate["page"], str)
    assert candidate["page"].startswith("<FakePage")


def test_json_safe_campaign_result_for_storage_roundtrip():
    raw = {
        "results": [{"status": "failed", "error": "商品需过24h后才可以报活动", "modal": FakePage()}],
        "errors": ["商品需过24h后才可以报活动"],
    }
    cleaned = json_safe_campaign_result_for_storage(raw)
    json.dumps(cleaned)
    assert cleaned["results"][0]["modal"].startswith("<FakePage")
