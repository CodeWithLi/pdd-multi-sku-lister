"""登录失败文案与飞书短句。"""

from __future__ import annotations

from pdd_agent.browser.login_failure import (
    SMS_VERIFY_REQUIRED_MSG,
    feishu_brief_for_login_error,
    format_sms_verify_required,
    is_manual_login_error_text,
    is_sms_verify_error_text,
)
from pdd_agent.domain.listing_errors import ListingErrorCode, ListingErrors
from pdd_agent.skills.listing.upload import _classify_exception


def test_sms_verify_message_classified_as_manual_login():
    msg = format_sms_verify_required("153")
    assert "短信验证码" in msg
    assert is_sms_verify_error_text(msg)
    reason, retryable = _classify_exception(RuntimeError(msg))
    assert reason == ListingErrorCode.NEEDS_MANUAL_LOGIN_OR_CAPTCHA
    assert retryable is True


def test_username_fill_timeout_classified_as_manual_login():
    exc = RuntimeError(
        'Locator.fill: Timeout 30000ms exceeded.\nCall log:\n  - waiting for locator("#usernameId").first'
    )
    assert is_manual_login_error_text(str(exc))
    reason, _ = _classify_exception(exc)
    assert reason == ListingErrorCode.NEEDS_MANUAL_LOGIN_OR_CAPTCHA


def test_feishu_brief_prefers_sms_over_unexpected():
    line = ListingErrors.compact_feishu_line(
        format_sms_verify_required("153"),
        reason_code=ListingErrorCode.UNEXPECTED_ERROR,
        merchant_code="BD103A",
    )
    assert "短信验证码" in line
    assert "运行异常" not in line
    assert line.startswith("BD103A")


def test_feishu_brief_from_playwright_username_timeout():
    raw = (
        'playwright._impl._errors.TimeoutError: Locator.fill: Timeout 30000ms exceeded. '
        'waiting for locator("#usernameId")'
    )
    line = ListingErrors.compact_feishu_line(
        raw,
        reason_code=ListingErrorCode.UNEXPECTED_ERROR,
        merchant_code="BD103A",
    )
    assert "运行异常" not in line
    assert feishu_brief_for_login_error(raw) is not None
    assert "短信" in line or "验证" in line


def test_needs_manual_feishu_label_mentions_sms():
    label = ListingErrors.feishu_label(ListingErrorCode.NEEDS_MANUAL_LOGIN_OR_CAPTCHA)
    assert "短信" in label or "滑块" in label
    assert SMS_VERIFY_REQUIRED_MSG
