"""json_safe 单元测试。"""

from dataclasses import dataclass

from dy_agent.core.json_safe import json_safe
from dy_agent.skills.listing.listing_primary_style_first import PrimaryStyleFirstResult


@dataclass
class _Sample:
    name: str
    tags: tuple[str, ...]


def test_json_safe_dataclass_and_tuple():
    out = json_safe(_Sample(name="a", tags=("x", "y")))
    assert out == {"name": "a", "tags": ["x", "y"]}


def test_json_safe_primary_style_first_result():
    result = PrimaryStyleFirstResult(
        applied=True,
        product_code="BD021A",
        primary_style_code="BD021A卡皮巴拉笔袋",
        style_order=("BD021A卡皮巴拉笔袋", "BD021B"),
    )
    out = json_safe({"primary_style_first": result})
    assert out["primary_style_first"]["applied"] is True
    assert out["primary_style_first"]["style_order"] == [
        "BD021A卡皮巴拉笔袋",
        "BD021B",
    ]
    import json

    json.dumps(out)  # must not raise


def test_json_safe_nested_result_payload():
    payload = {
        "results": [
            {
                "status": "success",
                "prep": {
                    "primary_style_first": PrimaryStyleFirstResult(
                        applied=False,
                        product_code="BD021A",
                    )
                },
            }
        ],
        "errors": [],
    }
    import json

    encoded = json.dumps(json_safe(payload))
    assert "BD021A" in encoded
