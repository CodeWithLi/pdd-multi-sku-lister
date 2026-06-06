"""同步 Playwright 登录（供页面操作线程使用）。"""

from __future__ import annotations

import time

from playwright.sync_api import BrowserContext, Page

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.core.config import AccountConfig

HOME_URL = "https://mms.pinduoduo.com/home/"
_SMS_HINTS = ("短信验证码", "请输入短信验证码")
_CAPTCHA_HINTS = ("请向右滑块", "完成拼图", "滑块")


def ensure_login_sync(account: AccountConfig, page: Page) -> DpPage:
    """同步版登录；短信/滑块需人工在窗口完成。"""
    dp = DpPage(page)
    account_id = account.account_id
    print(f"\n--- [{account_id}] 正在检查登录状态 ---")

    dp.get(HOME_URL)
    time.sleep(2)

    if "login" not in dp.url:
        print(f"[{account_id}] 读取本地 Session 成功，已免密进入后台")
        return dp

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

    login_btn = dp.ele("t:span@text()=登录", timeout=5)
    if login_btn:
        login_btn.click()

    wait_sec = 180 if _needs_manual_verify(dp) else 30
    if wait_sec == 180:
        print(f"[{account_id}] 请在浏览器窗口完成滑块或短信验证...")

    for remaining in range(wait_sec, 0, -1):
        if "login" not in dp.url:
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
