"""抖店登录：官网 → 登录抖店 → 手机验证码（验证码手动输入）。"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from dy_agent.core.config import load_yaml_settings
from dy_agent.core.exceptions import BrowserError
from dy_agent.core.logging import get_logger

if TYPE_CHECKING:
    from dy_agent.core.config import AccountConfig

logger = get_logger(__name__)

HOME_URL = "https://fxg.jinritemai.com/"
LOGIN_URL_HINTS = ("login", "passport")
MERCHANT_URL_HINTS = ("/ffa/", "/dashboard", "/mshop", "/goods")


class DpPage:
    """Playwright Page 轻量包装。"""

    def __init__(self, page: Page, context: BrowserContext | None = None) -> None:
        self._page = page
        self._context = context or page.context

    @property
    def raw(self) -> Page:
        return self._page

    @property
    def context(self) -> BrowserContext | None:
        return self._context

    def goto(self, url: str, *, wait_until: str = "domcontentloaded") -> None:
        self._page.goto(url, wait_until=wait_until)

    @property
    def url(self) -> str:
        return self._page.url


def is_login_url(url: str) -> bool:
    lower = str(url or "").lower()
    return any(hint in lower for hint in LOGIN_URL_HINTS)


def is_likely_logged_in(url: str) -> bool:
    """URL 是否像已进入商家后台（首页本身不能作为已登录依据）。"""
    lower = str(url or "").lower()
    if is_login_url(lower):
        return False
    if "fxg.jinritemai.com" not in lower:
        return False
    return any(hint in lower for hint in MERCHANT_URL_HINTS)


def resolve_account_phone(account: AccountConfig) -> str:
    phone = str(getattr(account, "phone", "") or "").strip()
    if phone:
        return phone
    username = str(account.username or "").strip()
    if re.fullmatch(r"1\d{10}", username):
        return username
    return ""


def _log(account_id: str, message: str) -> None:
    print(f"[{account_id}] {message}", flush=True)
    logger.info("[%s] %s", account_id, message)


def open_homepage(dp: DpPage) -> None:
    dp.goto(HOME_URL)
    time.sleep(1.5)


def click_home_login_button(page: Page, account_id: str) -> None:
    """官网右上角「登录抖店」。"""
    selectors = [
        'a[href="/login/common"]',
        'a[href*="login/common"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        if locator.count() > 0:
            locator.click()
            _log(account_id, "已点击「登录抖店」")
            time.sleep(1.5)
            return

    link = page.get_by_role("link", name="登录抖店").first
    link.click(timeout=10_000)
    _log(account_id, "已点击「登录抖店」（role）")
    time.sleep(1.5)


def ensure_mobile_login_tab(page: Page, account_id: str) -> None:
    tab = page.get_by_text("手机登录", exact=True).first
    if tab.count() == 0:
        return
    try:
        tab.click(timeout=3_000)
        _log(account_id, "已切换到「手机登录」")
        time.sleep(0.5)
    except PlaywrightTimeoutError:
        pass


def _phone_input(page: Page):
    candidates = [
        page.get_by_placeholder("手机号码"),
        page.locator('input[placeholder*="手机"]'),
        page.locator(".mobile-login input").first,
    ]
    for locator in candidates:
        if locator.count() > 0:
            return locator.first
    return page.locator("input").first


def _sms_code_input(page: Page):
    candidates = [
        page.get_by_placeholder("验证码"),
        page.locator('input[placeholder*="验证码"]'),
        page.locator(".mobile-login input").nth(1),
    ]
    for locator in candidates:
        if locator.count() > 0:
            return locator.first
    return None


def fill_phone(page: Page, account_id: str, phone: str) -> None:
    locator = _phone_input(page)
    locator.wait_for(state="visible", timeout=10_000)
    locator.fill("")
    locator.fill(phone)
    _log(account_id, f"已填写手机号: {phone[:3]}****{phone[-4:]}")


def click_send_sms(page: Page, account_id: str) -> None:
    button = page.get_by_text("发送验证码", exact=True).first
    if button.count() == 0:
        _log(account_id, "未找到「发送验证码」按钮，请手动点击")
        return
    try:
        button.click(timeout=5_000)
        _log(account_id, "已点击「发送验证码」")
    except PlaywrightTimeoutError:
        _log(account_id, "「发送验证码」按钮不可点击，请手动发送")


def wait_for_sms_code_filled(page: Page, account_id: str, timeout_sec: int) -> None:
    code_input = _sms_code_input(page)
    if code_input is None:
        raise BrowserError(f"[{account_id}] 未找到验证码输入框")

    _log(account_id, f"请在浏览器中手动输入短信验证码（最多等待 {timeout_sec}s）…")
    for remaining in range(timeout_sec, 0, -1):
        try:
            value = str(code_input.input_value(timeout=500)).strip()
        except PlaywrightTimeoutError:
            value = ""
        if len(value) >= 4:
            _log(account_id, "检测到验证码已填写")
            return
        if remaining % 15 == 0:
            _log(account_id, f"等待验证码输入… 剩余约 {remaining}s")
        time.sleep(1)
    raise BrowserError(f"[{account_id}] 等待验证码输入超时（{timeout_sec}s）")


def ensure_agreement_checked(page: Page, account_id: str) -> None:
    """勾选用户协议（图三底部复选框）。"""
    selectors = [
        ".account-center-sdk-container input[type='checkbox']",
        ".ecomLoginForm-container input[type='checkbox']",
        "input[type='checkbox']",
    ]
    for selector in selectors:
        boxes = page.locator(selector)
        if boxes.count() == 0:
            continue
        box = boxes.first
        try:
            if not box.is_checked():
                box.check(force=True)
                _log(account_id, "已勾选用户协议")
            return
        except Exception:
            try:
                box.click(force=True)
                _log(account_id, "已点击用户协议复选框")
                return
            except Exception:
                continue

    label = page.get_by_text("我已阅读并同意", exact=False).first
    if label.count() > 0:
        label.click(timeout=3_000)
        _log(account_id, "已通过协议文案勾选用户协议")
        return

    _log(account_id, "未找到协议复选框，尝试直接点击登录")


def click_submit_login(page: Page, account_id: str) -> None:
    """图四蓝色「登录」按钮。"""
    selectors = [
        "button.account-center-action-button",
        "button.ace-ui-btn-primary",
        "button:has-text('登录')",
    ]
    for selector in selectors:
        button = page.locator(selector).filter(has_text="登录").first
        if button.count() > 0:
            button.click(timeout=10_000)
            _log(account_id, "已点击「登录」按钮")
            time.sleep(1)
            return

    page.get_by_role("button", name="登录").first.click(timeout=10_000)
    _log(account_id, "已点击「登录」按钮（role）")
    time.sleep(1)


def wait_login_success(page: Page, account_id: str, timeout_sec: int = 60) -> None:
    for remaining in range(timeout_sec, 0, -1):
        if is_likely_logged_in(page.url) and not is_login_url(page.url):
            _log(account_id, "登录成功")
            time.sleep(2)
            return
        if remaining % 10 == 0:
            _log(account_id, f"等待登录跳转… 剩余约 {remaining}s")
        time.sleep(1)
    raise BrowserError(f"[{account_id}] 登录后跳转超时，当前 URL: {page.url}")


def perform_sms_login_sync(account: AccountConfig, page: Page) -> DpPage:
    """手机验证码登录：自动填手机号 + 点登录，验证码需人工输入。"""
    account_id = account.account_id
    dp = DpPage(page, page.context)
    phone = resolve_account_phone(account)
    if not phone:
        raise BrowserError(f"[{account_id}] 未配置手机号（accounts.phone 或 11 位 username）")

    settings = load_yaml_settings()
    sms_wait_seconds = settings.login.sms_wait_seconds
    auto_send_sms = settings.login.auto_send_sms

    if not is_login_url(dp.url):
        open_homepage(dp)
        if not is_login_url(dp.url):
            click_home_login_button(page, account_id)

    page.wait_for_load_state("domcontentloaded")
    ensure_mobile_login_tab(page, account_id)
    fill_phone(page, account_id, phone)
    if auto_send_sms:
        click_send_sms(page, account_id)
    wait_for_sms_code_filled(page, account_id, sms_wait_seconds)
    ensure_agreement_checked(page, account_id)
    click_submit_login(page, account_id)
    wait_login_success(page, account_id)
    from dy_agent.browser.shop_display_name import maybe_refresh_shop_display_name

    maybe_refresh_shop_display_name(account_id, dp, login_phone=phone)
    return DpPage(page, page.context)


def ensure_login_sync(account: AccountConfig, page: Page) -> DpPage:
    """任务开始时检查登录态；未登录则走手机验证码流程。"""
    dp = DpPage(page, page.context)
    account_id = account.account_id
    _log(account_id, "正在检查登录状态…")

    open_homepage(dp)
    time.sleep(1)

    if is_likely_logged_in(dp.url):
        _log(account_id, "读取本地 Session 成功，已登录")
        from dy_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        maybe_refresh_shop_display_name(account_id, dp, login_phone=resolve_account_phone(account))
        return dp

    login_links = page.get_by_role("link", name="登录抖店")
    if login_links.count() == 0 and not is_login_url(dp.url):
        _log(account_id, "未检测到登录入口，判定为已登录")
        return dp

    _log(account_id, "检测到未登录，开始手机验证码登录…")
    return perform_sms_login_sync(account, page)
