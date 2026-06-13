"""同步 Playwright 登录（供页面操作线程使用）。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from playwright.sync_api import Page

from pdd_agent.browser.dp_compat_sync import DpPage

if TYPE_CHECKING:
    from pdd_agent.core.config import AccountConfig

HOME_URL = "https://mms.pinduoduo.com/home/"
_SMS_HINTS = ("短信验证码", "请输入短信验证码")
_CAPTCHA_HINTS = ("请向右滑块", "完成拼图", "滑块")


def is_login_url(url: str) -> bool:
    return "login" in str(url or "").lower()


def ensure_login_sync(account: AccountConfig, page: Page) -> DpPage:
    """任务开始时：打开首页，若未登录则账号密码登录。"""
    dp = DpPage(page)
    account_id = account.account_id
    print(f"\n--- [{account_id}] 正在检查登录状态 ---")

    dp.get(HOME_URL)
    time.sleep(2)

    if not is_login_url(dp.url):
        print(f"[{account_id}] 读取本地 Session 成功，已免密进入后台")
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

    print(f"[{account_id}] 未登录，正在使用账号密码登录...")
    tab = dp.ele("text:账号登录", timeout=5)
    if tab:
        tab.click()
        time.sleep(1)

    user_input = dp.ele("#usernameId", timeout=5)
    if user_input:
        user_input.input(account.username, clear=True)
    time.sleep(0.5)

    pwd_input = dp.ele("#passwordId", timeout=5)
    if pwd_input:
        pwd_input.input(account.password, clear=True)
    time.sleep(1)

    if not _click_login_button(dp):
        raise RuntimeError(f"[{account_id}] 未找到登录按钮")
    time.sleep(1)
    if _is_qr_login_page(dp):
        print(f"[{account_id}] 检测到误入扫码登录，切回账号登录后重试...")
        tab = dp.ele("text:账号登录", timeout=3)
        if tab:
            tab.click()
            time.sleep(1)
        if user_input:
            user_input.input(account.username, clear=True)
        if pwd_input:
            pwd_input.input(account.password, clear=True)
        time.sleep(0.5)
        if not _click_login_button(dp):
            raise RuntimeError(f"[{account_id}] 重试后仍未找到登录按钮")
        time.sleep(1)

    wait_sec = 180 if _needs_manual_verify(dp) else 30
    if wait_sec == 180:
        print(f"[{account_id}] 请在浏览器窗口完成滑块或短信验证...")

    for remaining in range(wait_sec, 0, -1):
        if not is_login_url(dp.url):
            print(f"[{account_id}] 登录成功")
            time.sleep(2)
            return dp
        if wait_sec == 180 and remaining % 15 == 0:
            print(f"[{account_id}] 等待人工验证… 剩余约 {remaining}s")
        time.sleep(1)

    raise RuntimeError(f"[{account_id}] 登录超时")


def _needs_manual_verify(dp: DpPage) -> bool:
    for hint in _CAPTCHA_HINTS + _SMS_HINTS:
        if dp.ele(f"text:{hint}", timeout=1):
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
