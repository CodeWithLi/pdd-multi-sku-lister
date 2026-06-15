"""搜索弹窗商品可报名性检测。"""

from pdd_agent.skills.campaign.marketing_activities import _format_modal_eligibility_failure


def test_format_time_requirement_failure():
    eligibility = {
        "eligible_ids": ["965182969751"],
        "time_blocked": [
            {
                "product_id": "966631777744",
                "reason_text": "该商品近期有更新规格，需等待1天后才可报名",
            }
        ],
        "missing_ids": ["966631777744"],
    }
    result = _format_modal_eligibility_failure(eligibility, ["965182969751", "966631777744"])
    assert result["step"] == "product_time_requirement_not_met"
    assert "未满足时间要求" in result["error"]
    assert "966631777744" in result["error"]


def test_format_partial_ineligible_failure():
    eligibility = {
        "eligible_ids": ["965182969751", "962138900436"],
        "time_blocked": [],
        "other_ineligible": [],
        "missing_ids": ["966631777744"],
    }
    result = _format_modal_eligibility_failure(
        eligibility,
        ["965182969751", "962138900436", "966631777744"],
    )
    assert result["step"] == "product_not_eligible_for_activity"
    assert "不可报名" in result["error"]
    assert "966631777744" in result["error"]


def test_format_all_eligible_returns_empty():
    eligibility = {
        "eligible_ids": ["111", "222"],
        "time_blocked": [],
        "missing_ids": [],
    }
    assert _format_modal_eligibility_failure(eligibility, ["111", "222"]) == {}
