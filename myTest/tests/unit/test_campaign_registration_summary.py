"""活动报名结果摘要文案。"""

from pdd_agent.api.services.task_runner import _activity_registration_summary_line


def test_registration_summary_submitted_when_product_not_in_validation_rows():
    item = {
        "status": "success",
        "step": "register_completed",
        "product_ids": ["965182969751", "965180544666"],
        "finalize_result": {
            "status": "success",
            "confirm_submit": {"clicked": True},
            "submit_verification": {"verified": True},
            "price_filter": {
                "status": "success",
                "action": "continue_submit",
                "validation": {"results": []},
                "filter_result": {
                    "removed_product_ids": ["965180544666"],
                    "partial_product_ids": ["965180544666"],
                    "kept_product_ids": ["965182969751"],
                },
            },
        },
    }
    msg = _activity_registration_summary_line(item)
    assert "报名已提交" in msg
    assert "1/" in msg or "1 个" in msg


def test_registration_summary_submitted_after_partial_product_removed():
    item = {
        "status": "success",
        "step": "register_completed",
        "product_ids": ["965836045952", "965180544666"],
        "finalize_result": {
            "status": "success",
            "confirm_submit": {"clicked": True},
            "submit_verification": {"verified": True},
            "price_filter": {
                "status": "success",
                "action": "continue_submit",
                "filter_summary": "将继续提交报名：965836045952",
                "validation": {
                    "results": [
                        {"pdd_product_id": "965836045952", "valid": True, "should_remove": False},
                        {"pdd_product_id": "965836045952", "valid": True, "should_remove": False},
                        {"pdd_product_id": "965180544666", "valid": True, "should_remove": False},
                        {"pdd_product_id": "965180544666", "valid": False, "should_remove": True},
                    ]
                },
                "filter_result": {
                    "partial_product_ids": ["965180544666"],
                    "removed_product_ids": ["965180544666"],
                },
            },
        },
    }
    msg = _activity_registration_summary_line(item)
    assert "报名已提交" in msg


def test_registration_summary_all_removed():
    item = {
        "status": "cancelled",
        "step": "filter_activity_prices",
        "product_ids": ["111"],
        "finalize_result": {
            "status": "cancelled",
            "price_filter": {"status": "all_products_removed"},
        },
    }
    assert _activity_registration_summary_line(item) == "未提交报名：全部商品不符合条件"


def test_registration_summary_price_page_only():
    item = {
        "status": "success",
        "step": "price_page_prepared",
        "product_ids": ["111"],
    }
    assert "未点击确认提交" in _activity_registration_summary_line(item)
