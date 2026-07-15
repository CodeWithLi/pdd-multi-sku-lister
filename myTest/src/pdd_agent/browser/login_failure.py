"""登录失败文案与归类（短信验证码 / 滑块等），供 sync_login 与飞书失败表共用。"""

from __future__ import annotations

from typing import Any

# 飞书「失败原因」与日志用的固定短句（含「短信」关键字，便于 reason 归类）
SMS_VERIFY_REQUIRED_MSG = "登录失败：需要短信验证码，请在浏览器中输入短信验证码后继续"
CAPTCHA_VERIFY_REQUIRED_MSG = "登录失败：需要完成滑块/拼图验证，请在浏览器中处理后继续"
LOGIN_TIMEOUT_MSG = "登录超时：仍停留在登录页"


def format_sms_verify_required(account_id: str = "") -> str:
    prefix = f"[{account_id}] " if str(account_id or "").strip() else ""
    return f"{prefix}{SMS_VERIFY_REQUIRED_MSG}"


def format_captcha_verify_required(account_id: str = "") -> str:
    prefix = f"[{account_id}] " if str(account_id or "").strip() else ""
    return f"{prefix}{CAPTCHA_VERIFY_REQUIRED_MSG}"


def format_login_timeout(account_id: str = "", *, detail: str = "") -> str:
    prefix = f"[{account_id}] " if str(account_id or "").strip() else ""
    extra = str(detail or "").strip()
    if extra:
        return f"{prefix}{LOGIN_TIMEOUT_MSG}（{extra}）"
    return f"{prefix}{LOGIN_TIMEOUT_MSG}"


def is_sms_verify_error_text(text: Any) -> bool:
    s = str(text or "")
    return any(
        token in s
        for token in (
            "短信验证码",
            "验证手机",
            "请验证手机",
            SMS_VERIFY_REQUIRED_MSG,
        )
    )


def is_manual_login_error_text(text: Any) -> bool:
    s = str(text or "")
    if is_sms_verify_error_text(s):
        return True
    if any(token in s for token in ("滑块", "拼图", "扫码登录", CAPTCHA_VERIFY_REQUIRED_MSG)):
        return True
    low = s.lower()
    # Playwright 在短信页仍去填账号：典型超时
    if "usernameid" in low and ("timeout" in low or "超时" in s):
        return True
    if "passwordid" in low and ("timeout" in low or "超时" in s):
        return True
    return False


def feishu_brief_for_login_error(text: Any) -> str | None:
    """若是登录人工验证类错误，返回飞书失败原因短句；否则 None。"""
    s = str(text or "").strip()
    if not s:
        return None
    if is_sms_verify_error_text(s):
        return "登录需输入短信验证码（未完成验证）"
    if any(token in s for token in ("滑块", "拼图", CAPTCHA_VERIFY_REQUIRED_MSG)):
        return "登录需完成滑块验证（未完成验证）"
    low = s.lower()
    if "usernameid" in low and ("timeout" in low or "超时" in s):
        return "登录需输入短信验证码或完成验证（账号输入框不可用）"
    if is_manual_login_error_text(s):
        return "需要人工处理验证码或重新登录"
    return None
