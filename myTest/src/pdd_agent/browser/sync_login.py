"""同步 Playwright 登录（供页面操作线程使用）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from playwright.sync_api import Page

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.browser.login_failure import (
    format_captcha_verify_required,
    format_login_timeout,
    format_sms_verify_required,
)

if TYPE_CHECKING:
    from pdd_agent.core.config import AccountConfig

HOME_URL = "https://mms.pinduoduo.com/home/"
_SMS_HINTS = (
    "短信验证码",
    "请输入短信验证码",
    "验证手机后继续登录",
    "请验证手机后继续登录",
    "为保障您账号的安全，请验证手机",
)
_CAPTCHA_HINTS = ("请向右滑块", "完成拼图", "滑块")


def is_login_url(url: str) -> bool:
    return "login" in str(url or "").lower()


def ensure_login_sync(account: AccountConfig, page: Page) -> DpPage:
    """任务开始时：打开首页，若未登录则账号密码登录。"""
    dp = DpPage(page)
    account_id = account.account_id
    print(f"\n--- [{account_id}] 正在检查登录状态 ---")

    from pdd_agent.browser.sync_login_home_goto_retry import goto_home_with_aborted_retry

    goto_home_with_aborted_retry(page, HOME_URL)
    time.sleep(2)

    if not is_login_url(dp.url):
        print(f"[{account_id}] 读取本地 Session 成功，已免密进入后台")
        from pdd_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        maybe_refresh_shop_display_name(account_id, dp, login_username=account.username)
        return dp

    return _perform_password_login_sync(account, page)


def ensure_login_if_needed_sync(account: AccountConfig, page: Page) -> DpPage:
    """任务中途 Session 失效跳到登录页时，在当前页复用账号密码登录。"""
    dp = DpPage(page)
    if not is_login_url(dp.url):
        return dp
    print(f"[{account.account_id}] Session 已失效，正在重新登录...")
    return _perform_password_login_sync(account, page)


def ensure_session_sync(page: DpPage, account: AccountConfig | None) -> dict[str, object]:
    """若当前在登录页且提供了账号配置，则自动登录。返回诊断信息。"""
    url = str(page.url or "")
    if not is_login_url(url):
        return {"logged_in": True, "relogin": False, "url": url}
    if account is None:
        return {
            "logged_in": False,
            "relogin": False,
            "reason": "login_required_no_account",
            "url": url,
        }
    before = url
    ensure_login_if_needed_sync(account, page._page)
    after = str(page.url or "")
    logged_in = not is_login_url(after)
    return {
        "logged_in": logged_in,
        "relogin": True,
        "url_before": before,
        "url_after": after,
        "reason": "" if logged_in else "relogin_failed",
    }


def _perform_password_login_sync(account: AccountConfig, page: Page) -> DpPage:
    """在当前登录页执行账号密码登录（含滑块/短信等待）。"""
    dp = DpPage(page)
    account_id = account.account_id

    if not account.username or not account.password:
        raise RuntimeError(f"[{account_id}] 未配置账号或密码")

    # 已在短信验证页：不要再填 #usernameId（元素不存在会报 Timeout → 飞书记成运行异常）
    if _is_sms_verify_page(dp):
        print(f"[{account_id}] 检测到短信验证码页，等待人工输入...")
        return _wait_until_logged_in(account, dp, wait_sec=180, manual_reason="sms")

    print(f"[{account_id}] 未登录，正在使用账号密码登录...")
    tab = dp.ele("text:账号登录", timeout=5)
    if tab:
        tab.click()
        time.sleep(1)

    if _is_sms_verify_page(dp):
        print(f"[{account_id}] 切换账号登录后仍在短信验证页，等待人工输入...")
        return _wait_until_logged_in(account, dp, wait_sec=180, manual_reason="sms")

    _fill_password_login_form(account, dp)
    time.sleep(1)

    if not _click_login_button(dp):
        # 可能已跳到短信页，登录按钮区域变了
        if _is_sms_verify_page(dp):
            return _wait_until_logged_in(account, dp, wait_sec=180, manual_reason="sms")
        raise RuntimeError(f"[{account_id}] 未找到登录按钮")
    time.sleep(1)

    if _is_sms_verify_page(dp):
        print(f"[{account_id}] 登录后进入短信验证码页，请在浏览器输入验证码...")
        return _wait_until_logged_in(account, dp, wait_sec=180, manual_reason="sms")

    if _is_qr_login_page(dp):
        print(f"[{account_id}] 检测到误入扫码登录，切回账号登录后重试...")
        tab = dp.ele("text:账号登录", timeout=3)
        if tab:
            tab.click()
            time.sleep(1)
        if _is_sms_verify_page(dp):
            return _wait_until_logged_in(account, dp, wait_sec=180, manual_reason="sms")
        # 重新定位输入框，禁止复用旧 locator（页面已变时会 30s Timeout）
        _fill_password_login_form(account, dp)
        time.sleep(0.5)
        if not _click_login_button(dp):
            if _is_sms_verify_page(dp):
                return _wait_until_logged_in(account, dp, wait_sec=180, manual_reason="sms")
            raise RuntimeError(f"[{account_id}] 重试后仍未找到登录按钮")
        time.sleep(1)
        if _is_sms_verify_page(dp):
            return _wait_until_logged_in(account, dp, wait_sec=180, manual_reason="sms")

    wait_sec = 180 if _needs_manual_verify(dp) else 30
    manual_reason = ""
    if wait_sec == 180:
        manual_reason = "captcha" if _is_captcha_page(dp) else "sms"
        print(f"[{account_id}] 请在浏览器窗口完成滑块或短信验证...")
    return _wait_until_logged_in(account, dp, wait_sec=wait_sec, manual_reason=manual_reason)


def _fill_password_login_form(account: AccountConfig, dp: DpPage) -> None:
    """填写账号密码；若页面已是短信验证则立刻抛出可读错误。"""
    account_id = account.account_id
    if _is_sms_verify_page(dp):
        raise RuntimeError(format_sms_verify_required(account_id))

    user_input = dp.ele("#usernameId", timeout=5)
    if not user_input:
        if _is_sms_verify_page(dp) or _needs_manual_verify(dp):
            raise RuntimeError(format_sms_verify_required(account_id))
        raise RuntimeError(f"[{account_id}] 未找到账号输入框，无法自动登录")
    _safe_input(user_input, account.username, account_id=account_id, dp=dp)
    time.sleep(0.5)

    pwd_input = dp.ele("#passwordId", timeout=5)
    if not pwd_input:
        if _is_sms_verify_page(dp):
            raise RuntimeError(format_sms_verify_required(account_id))
        raise RuntimeError(f"[{account_id}] 未找到密码输入框，无法自动登录")
    _safe_input(pwd_input, account.password, account_id=account_id, dp=dp)


def _safe_input(ele, value: str, *, account_id: str, dp: DpPage) -> None:
    try:
        ele.input(value, clear=True)
    except Exception as exc:
        if _is_sms_verify_page(dp) or _needs_manual_verify(dp):
            raise RuntimeError(format_sms_verify_required(account_id)) from exc
        err = str(exc)
        if "usernameId" in err or "passwordId" in err or "Timeout" in type(exc).__name__:
            raise RuntimeError(format_sms_verify_required(account_id)) from exc
        raise


def _wait_until_logged_in(
    account: AccountConfig,
    dp: DpPage,
    *,
    wait_sec: int,
    manual_reason: str = "",
) -> DpPage:
    account_id = account.account_id
    for remaining in range(max(1, int(wait_sec)), 0, -1):
        if not is_login_url(dp.url):
            print(f"[{account_id}] 登录成功")
            time.sleep(2)
            from pdd_agent.browser.shop_display_name import maybe_refresh_shop_display_name

            maybe_refresh_shop_display_name(account_id, dp, login_username=account.username)
            return dp
        if wait_sec >= 180 and remaining % 15 == 0:
            print(f"[{account_id}] 等待人工验证… 剩余约 {remaining}s")
        time.sleep(1)

    if _is_sms_verify_page(dp) or manual_reason == "sms":
        raise RuntimeError(format_sms_verify_required(account_id))
    if _is_captcha_page(dp) or manual_reason == "captcha":
        raise RuntimeError(format_captcha_verify_required(account_id))
    raise RuntimeError(format_login_timeout(account_id, detail="请检查账号密码或是否弹出验证码"))


def _is_sms_verify_page(dp: DpPage) -> bool:
    for hint in _SMS_HINTS:
        if dp.ele(f"text:{hint}", timeout=0.8):
            return True
    try:
        return bool(
            dp.run_js(
                """
                const text = document.body?.innerText || '';
                return text.includes('短信验证码')
                    || text.includes('请输入短信验证码')
                    || (text.includes('验证手机') && text.includes('继续登录'));
                """
            )
        )
    except Exception:
        return False


def _is_captcha_page(dp: DpPage) -> bool:
    for hint in _CAPTCHA_HINTS:
        if dp.ele(f"text:{hint}", timeout=0.5):
            return True
    return False


def _needs_manual_verify(dp: DpPage) -> bool:
    if _is_sms_verify_page(dp) or _is_captcha_page(dp):
        return True
    for hint in _CAPTCHA_HINTS + _SMS_HINTS:
        if dp.ele(f"text:{hint}", timeout=0.5):
            return True
    return False


def _is_qr_login_page(dp: DpPage) -> bool:
    try:
        return bool(
            dp.run_js(
                """
                const text = document.body?.innerText || '';
                const hasQr = document.querySelector('canvas, img[src*="qr"], img[src*="QRCode"]');
                return (text.includes('扫码登录') || text.includes('扫码')) && Boolean(hasQr);
                """
            )
        )
    except Exception:
        return False


def _click_login_button(dp: DpPage) -> bool:
    """Click the password-login submit button, not the QR/account tab."""
    try:
        return bool(
            dp.run_js(
                """
                function isVisible(el) {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 20 && r.height > 20
                        && s.display !== 'none'
                        && s.visibility !== 'hidden'
                        && Number(s.opacity || '1') > 0.05;
                }

                const password = document.querySelector('#passwordId, input[type="password"]');
                if (!password) return false;
                const pwdRect = password.getBoundingClientRect();
                const pwdCenterX = pwdRect.left + pwdRect.width / 2;

                function clickableParent(el) {
                    let cur = el;
                    for (let i = 0; i < 5 && cur && cur !== document.body; i++) {
                        const tag = (cur.tagName || '').toLowerCase();
                        const role = cur.getAttribute?.('role') || '';
                        const cursor = window.getComputedStyle(cur).cursor;
                        if (tag === 'button' || tag === 'a' || role === 'button' || cursor === 'pointer') {
                            return cur;
                        }
                        cur = cur.parentElement;
                    }
                    return el;
                }

                const candidates = [];
                for (const el of document.querySelectorAll('button, [role="button"], input[type="submit"], div, span, a')) {
                    if (!isVisible(el)) continue;
                    const text = (el.innerText || el.textContent || '').trim();
                    const r = el.getBoundingClientRect();
                    if (text !== '登录') continue;
                    if (r.top < pwdRect.bottom - 5) continue;
                    if (r.width < 100 || r.height < 30) continue;
                    const centerX = r.left + r.width / 2;
                    const distance = Math.abs(centerX - pwdCenterX) + Math.max(0, r.top - pwdRect.bottom);
                    candidates.push({ el: clickableParent(el), distance, area: r.width * r.height });
                }
                candidates.sort((a, b) => a.distance - b.distance || b.area - a.area);
                if (candidates.length) {
                    candidates[0].el.click();
                    return true;
                }

                const fallbackPoints = [
                    [pwdCenterX, pwdRect.bottom + 60],
                    [pwdCenterX, pwdRect.bottom + 80],
                    [pwdCenterX, pwdRect.bottom + 100],
                ];
                for (const [x, y] of fallbackPoints) {
                    const el = document.elementFromPoint(x, y);
                    if (!isVisible(el)) continue;
                    const text = (el.innerText || el.textContent || '').trim();
                    if (text === '登录') {
                        clickableParent(el).click();
                        return true;
                    }
                }
                return false;
                """
            )
        )
    except Exception:
        return False
