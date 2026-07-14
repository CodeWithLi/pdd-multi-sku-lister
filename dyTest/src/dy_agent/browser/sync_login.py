"""抖店登录：官网 → 登录抖店 → 手机验证码（验证码手动输入）。"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import BrowserContext, Frame, Page, TimeoutError as PlaywrightTimeoutError

from dy_agent.core.config import load_yaml_settings
from dy_agent.core.exceptions import BrowserError
from dy_agent.core.logging import get_logger

if TYPE_CHECKING:
    from dy_agent.core.config import AccountConfig

logger = get_logger(__name__)

HOME_URL = "https://fxg.jinritemai.com/"
LOGIN_URL_HINTS = ("login", "passport")
MERCHANT_URL_HINTS = ("/ffa/", "/dashboard", "/mshop", "/goods", "/ffa/gov/settle/choose-role")


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


def page_looks_logged_in(page: Page) -> bool:
    """URL 或页面头部看起来已经进入抖店后台/入驻页。"""
    try:
        if is_likely_logged_in(page.url) and not is_login_url(page.url):
            return True
        return bool(
            page.evaluate(
                """
                () => {
                  function visible(el) {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                  }
                  const bodyText = (document.body?.innerText || '').replace(/\\s+/g, '');
                  if (bodyText.includes('请选择主体类型') || bodyText.includes('学习中心')) return true;
                  const headerArea = Array.from(document.querySelectorAll(
                    'header, [class*="header"], [class*="Header"], [class*="top"], [class*="Top"]'
                  ));
                  for (const el of headerArea) {
                    if (!visible(el)) continue;
                    const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
                    if (/1\\d{10}/.test(text) || text.includes('学习中心') || text.includes('消息')) return true;
                  }
                  return false;
                }
                """
            )
        )
    except Exception:
        return False


def wait_existing_login_redirect(page: Page, account_id: str, *, max_wait_seconds: int = 10) -> bool:
    """已有 session 会从登录页自动跳后台；先等跳转完成，避免误找手机号框。"""
    saw_existing_hint = False
    for index in range(max(1, max_wait_seconds)):
        if page_looks_logged_in(page):
            _log(account_id, "检测到已有登录态，已自动跳转")
            return True
        try:
            text = page.locator("body").inner_text(timeout=1_000).replace(" ", "")
            if "已登录" in text or "跳转中" in text:
                saw_existing_hint = True
            if index >= 3 and not saw_existing_hint and _has_visible_phone_input(page):
                return False
        except Exception:
            if index >= 3:
                return False
        time.sleep(1)
    return page_looks_logged_in(page)


def _has_visible_phone_input(page: Page) -> bool:
    for selector in (
        'input[placeholder="手机号码"]',
        'input[placeholder*="手机"]',
        'input[name="mobile"]',
    ):
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible(timeout=300):
                return True
        except Exception:
            continue
    return False


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


def _activate_login_page(original: Page, opened: Page | None, account_id: str) -> Page:
    """如果登录打开了新标签页，则切到新页并关闭原官网页。"""
    if opened is None:
        time.sleep(1.5)
        return original

    try:
        opened.wait_for_load_state("domcontentloaded", timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    try:
        opened.bring_to_front()
    except Exception:
        pass

    if opened != original and not original.is_closed():
        try:
            original.close()
            _log(account_id, "登录页已在新标签打开，已关闭原官网标签")
        except Exception:
            pass
    time.sleep(0.8)
    return opened


def _click_and_capture_new_page(page: Page, locator) -> Page | None:
    try:
        with page.context.expect_page(timeout=3_000) as page_info:
            locator.click(timeout=10_000)
        return page_info.value
    except PlaywrightTimeoutError:
        return None


def click_home_login_button(page: Page, account_id: str) -> Page:
    """官网右上角「登录抖店」。返回后续应继续操作的页面。"""
    selectors = [
        'a[href="/login/common"]',
        'a[href*="login/common"]',
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        if locator.count() > 0:
            opened = _click_and_capture_new_page(page, locator)
            _log(account_id, "已点击「登录抖店」")
            return _activate_login_page(page, opened, account_id)

    link = page.get_by_role("link", name="登录抖店").first
    opened = _click_and_capture_new_page(page, link)
    _log(account_id, "已点击「登录抖店」（role）")
    return _activate_login_page(page, opened, account_id)


def ensure_mobile_login_tab(page: Page, account_id: str) -> None:
    for label in ("手机登录", "验证码登录", "短信登录"):
        tab = page.get_by_text(label, exact=True).first
        if tab.count() == 0:
            continue
        try:
            tab.click(timeout=3_000)
            _log(account_id, f"已切换到「{label}」")
            time.sleep(0.8)
            return
        except PlaywrightTimeoutError:
            continue


_PHONE_INPUT_SELECTORS = (
    'input[placeholder="手机号码"]',
    'input[name="mobile"]',
    'input[autocomplete="mobile"]',
    'input[placeholder="请输入手机号码"]',
    'input[placeholder*="手机号码"]',
    'input[placeholder*="手机"]',
    ".account-center-sdk-container input[type='number']",
    ".account-center-sdk-container input[type='tel']",
)

_SMS_INPUT_SELECTORS = (
    'input[name="captcha"]',
    'input[placeholder*="验证码"]',
    'input[autocomplete="one-time-code"]',
    ".mobile-login input",
)

_FILL_PHONE_JS = """
(phone) => {
  const selectors = [
    'input[placeholder="手机号码"]',
    'input[name="mobile"]',
    'input[autocomplete="mobile"]',
    'input[placeholder="请输入手机号码"]',
    'input[placeholder*="手机号码"]',
    'input[placeholder*="手机"]',
  ];
  function visible(el) {
    if (!el || el.disabled || el.readOnly) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 80 && r.height > 20 && s.display !== 'none' && s.visibility !== 'hidden';
  }
  function fillInput(inp, val) {
    if (!visible(inp)) return false;
    try { inp.scrollIntoView({ block: 'center', inline: 'center' }); } catch (e) {}
    try { inp.focus(); } catch (e) {}
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    if (setter) setter.call(inp, val);
    else inp.value = val;
    inp.dispatchEvent(new InputEvent('input', { bubbles: true, data: val, inputType: 'insertText' }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    return String(inp.value || '').replace(/\\s+/g, '') === String(val || '').replace(/\\s+/g, '');
  }
  for (const sel of selectors) {
    for (const inp of document.querySelectorAll(sel)) {
      if (!inp) continue;
      if (fillInput(inp, phone)) return { ok: true, selector: sel };
    }
  }
  return { ok: false };
}
"""


def _login_contexts(page: Page) -> list[Page | Frame]:
    contexts: list[Page | Frame] = [page]
    for frame in page.frames:
        if frame != page.main_frame:
            contexts.append(frame)
    return contexts


def _first_visible_locator(ctx: Page | Frame, selectors: tuple[str, ...], *, timeout_ms: int = 800):
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for selector in selectors:
            loc = ctx.locator(selector)
            count = loc.count()
            for index in range(count):
                item = loc.nth(index)
                try:
                    if item.is_visible(timeout=200):
                        return item
                except Exception:
                    continue
        time.sleep(0.2)
    return None


def _phone_input(page: Page):
    for ctx in _login_contexts(page):
        found = _first_visible_locator(ctx, _PHONE_INPUT_SELECTORS, timeout_ms=1200)
        if found is not None:
            return found
    return page.locator('input[name="mobile"]').first


def _sms_code_input(page: Page):
    for ctx in _login_contexts(page):
        found = _first_visible_locator(ctx, _SMS_INPUT_SELECTORS, timeout_ms=800)
        if found is not None:
            return found
    for ctx in _login_contexts(page):
        for selector in _SMS_INPUT_SELECTORS:
            loc = ctx.locator(selector)
            if loc.count() > 1:
                return loc.nth(1)
            if loc.count() == 1 and "验证码" in selector:
                return loc.first
    return None


def _fill_phone_via_js(page: Page, phone: str) -> bool:
    for ctx in _login_contexts(page):
        try:
            result = ctx.evaluate(_FILL_PHONE_JS, phone)
            if isinstance(result, dict) and result.get("ok"):
                return True
        except Exception:
            continue
    return False


def _read_phone_input_value(locator) -> str:
    try:
        return str(locator.input_value(timeout=1_000) or "").replace(" ", "").strip()
    except Exception:
        return ""


def _phone_input_is_filled(page: Page, phone: str) -> bool:
    expected = str(phone or "").replace(" ", "").strip()
    locator = _phone_input(page)
    try:
        if not locator.is_visible(timeout=800):
            return False
    except Exception:
        return False
    current = _read_phone_input_value(locator)
    return current == expected


def _fill_phone_like_user(locator, phone: str) -> bool:
    """用真实键盘事件填写，避免抖店 React/ACE 输入框只改 DOM value 不进组件状态。"""
    try:
        locator.click(timeout=3_000)
        locator.press("Control+A", timeout=2_000)
        locator.press("Backspace", timeout=2_000)
        if hasattr(locator, "press_sequentially"):
            locator.press_sequentially(phone, delay=25, timeout=8_000)
        else:
            locator.type(phone, delay=25, timeout=8_000)
        return _read_phone_input_value(locator) == phone
    except Exception:
        return False


def fill_phone(page: Page, account_id: str, phone: str) -> None:
    locator = _phone_input(page)
    filled = False

    try:
        locator.wait_for(state="attached", timeout=8_000)
    except PlaywrightTimeoutError as exc:
        if page_looks_logged_in(page):
            _log(account_id, "检测到已有登录态，跳过手机号填写")
            return
        raise BrowserError(f"[{account_id}] 未找到手机号输入框") from exc

    for attempt in range(3):
        try:
            if locator.is_visible(timeout=1_500):
                filled = _fill_phone_like_user(locator, phone)
                if not filled:
                    locator.click(timeout=3_000)
                    locator.fill("", timeout=3_000)
                    locator.fill(phone, timeout=3_000)
            else:
                locator.fill(phone, force=True, timeout=3_000)
            current = _read_phone_input_value(locator)
            if current == phone and _phone_input_is_filled(page, phone):
                filled = True
                break
        except PlaywrightTimeoutError:
            if page_looks_logged_in(page):
                _log(account_id, "检测到已有登录态，跳过手机号填写")
                return
            pass
        except Exception:
            pass
        if _fill_phone_via_js(page, phone) and _phone_input_is_filled(page, phone):
            filled = True
            break
        ensure_mobile_login_tab(page, account_id)
        time.sleep(0.6)
        locator = _phone_input(page)

    if not filled and not (_fill_phone_via_js(page, phone) and _phone_input_is_filled(page, phone)):
        raise BrowserError(f"[{account_id}] 手机号填写失败，请检查登录页是否已切换到手机/验证码登录")

    _log(account_id, f"已填写手机号: {phone[:3]}****{phone[-4:]}")


def click_send_sms(page: Page, account_id: str) -> None:
    time.sleep(0.3)
    for selector in (
        "text=发送验证码",
        "button:has-text('发送验证码')",
        "[role='button']:has-text('发送验证码')",
        "div:has-text('发送验证码')",
        "span:has-text('发送验证码')",
    ):
        loc = page.locator(selector).first
        if loc.count() == 0:
            continue
        try:
            loc.wait_for(state="visible", timeout=3_000)
            disabled = bool(
                loc.evaluate(
                    """
                    (el) => {
                      const node = el.closest('button,[role="button"]') || el;
                      return Boolean(
                        node.disabled ||
                        node.getAttribute('aria-disabled') === 'true' ||
                        (node.className || '').toString().includes('disabled')
                      );
                    }
                    """
                )
            )
            if disabled:
                continue
            try:
                loc.click(timeout=5_000)
            except Exception:
                loc.evaluate(
                    """
                    (el) => {
                      const target = el.closest('button,[role="button"],a,div,span') || el;
                      target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                      target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                      target.click();
                    }
                    """
                )
            _log(account_id, "已点击「发送验证码」")
            return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue

    _log(account_id, "「发送验证码」按钮不可点击，请确认手机号已显示后手动发送")


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
    clicked = page.evaluate(
        """
        () => {
          function visible(el) {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          }
          function checked(el) {
            return Boolean(
              el.checked ||
              el.getAttribute('aria-checked') === 'true' ||
              (el.className || '').toString().includes('checked')
            );
          }
          const textNodes = Array.from(document.querySelectorAll('label, div, span, p')).filter((el) => {
            if (!visible(el)) return false;
            const t = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
            return t.includes('登录即代表同意') || t.includes('用户协议') || t.includes('隐私条款');
          });
          for (const textEl of textNodes) {
            const root = textEl.closest('label, form, [class*="login"], [class*="Login"], [class*="container"]') || textEl.parentElement;
            const inputs = Array.from((root || document).querySelectorAll('input[type="checkbox"]'));
            for (const input of inputs) {
              if (!visible(input)) continue;
              if (!checked(input)) input.click();
              return true;
            }
            const boxes = Array.from((root || document).querySelectorAll(
              '[role="checkbox"], [class*="checkbox"], [class*="Checkbox"]'
            ));
            for (const box of boxes) {
              if (!visible(box)) continue;
              if (!checked(box)) box.click();
              return true;
            }
          }
          const inputs = Array.from(document.querySelectorAll('input[type="checkbox"]')).filter(visible);
          if (inputs.length) {
            if (!checked(inputs[0])) inputs[0].click();
            return true;
          }
          return false;
        }
        """
    )
    if clicked:
        _log(account_id, "已勾选用户协议")
        time.sleep(0.5)
        return

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

    for text in ("登录即代表同意", "用户协议", "隐私条款", "我已阅读并同意"):
        label = page.get_by_text(text, exact=False).first
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
            page = click_home_login_button(page, account_id)

    if wait_existing_login_redirect(page, account_id, max_wait_seconds=10):
        from dy_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        logged_in_dp = DpPage(page, page.context)
        maybe_refresh_shop_display_name(account_id, logged_in_dp, login_phone=phone)
        return logged_in_dp

    page.wait_for_load_state("domcontentloaded")
    ensure_mobile_login_tab(page, account_id)
    if wait_existing_login_redirect(page, account_id, max_wait_seconds=4):
        from dy_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        logged_in_dp = DpPage(page, page.context)
        maybe_refresh_shop_display_name(account_id, logged_in_dp, login_phone=phone)
        return logged_in_dp

    fill_phone(page, account_id, phone)
    if page_looks_logged_in(page):
        from dy_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        logged_in_dp = DpPage(page, page.context)
        maybe_refresh_shop_display_name(account_id, logged_in_dp, login_phone=phone)
        return logged_in_dp

    ensure_agreement_checked(page, account_id)
    if auto_send_sms:
        click_send_sms(page, account_id)
    wait_for_sms_code_filled(page, account_id, sms_wait_seconds)
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

    if page_looks_logged_in(page):
        _log(account_id, "读取本地 Session 成功，已登录")
        from dy_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        maybe_refresh_shop_display_name(account_id, dp, login_phone=resolve_account_phone(account))
        return dp

    login_links = page.get_by_role("link", name="登录抖店")
    if login_links.count() == 0 and not is_login_url(dp.url):
        _log(account_id, "未检测到登录入口，判定为已登录")
        from dy_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        maybe_refresh_shop_display_name(account_id, dp, login_phone=resolve_account_phone(account))
        return dp

    _log(account_id, "检测到未登录，开始手机验证码登录…")
    return perform_sms_login_sync(account, page)
