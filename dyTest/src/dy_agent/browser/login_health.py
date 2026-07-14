"""抖店登录体检：检查 Session、打开登录窗口、抓取店铺名。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from dy_agent.browser.profile_lock import AccountProfileBusy, account_profile_lock
from dy_agent.browser.shop_display_name import maybe_refresh_shop_display_name, refresh_shop_display_name
from dy_agent.browser.sync_job import _launch_persistent
from dy_agent.browser.sync_login import (
    DpPage,
    HOME_URL,
    click_home_login_button,
    click_send_sms,
    ensure_agreement_checked,
    ensure_mobile_login_tab,
    fill_phone,
    is_login_url,
    is_likely_logged_in,
    open_homepage,
    perform_sms_login_sync,
    resolve_account_phone,
)
from dy_agent.core.config import AccountConfig, YamlSettings, load_yaml_settings
from dy_agent.db.repositories import update_shop_display_name, upsert_login_status


@dataclass
class ShopNameScrapeResult:
    account_id: str
    shop_display_name: str = ""
    ok: bool = False
    reason: str = ""


@dataclass
class LoginCheckResult:
    account_id: str
    status: str
    reason: str = ""
    current_url: str = ""
    checked_at: datetime | None = None


def mark_checking(account_id: str, reason: str) -> None:
    upsert_login_status(
        account_id=account_id,
        status="checking",
        reason=reason,
        current_url="",
        checked_at=datetime.now(),
    )


def _persist(result: LoginCheckResult) -> None:
    upsert_login_status(
        account_id=result.account_id,
        status=result.status,
        reason=result.reason,
        current_url=result.current_url,
        checked_at=result.checked_at or datetime.now(),
    )


def _persist_scrape_result(result: ShopNameScrapeResult) -> None:
    if result.ok:
        status = "logged_in"
        reason = f"shop name scraped: {result.shop_display_name}"
    elif "登录" in (result.reason or "") or result.reason in {
        "not logged in",
        "仍在登录页，请完成短信验证码",
    }:
        status = "needs_login"
        reason = result.reason or "not logged in"
    else:
        status = "failed"
        reason = result.reason or "shop name scrape failed"
    upsert_login_status(
        account_id=result.account_id,
        status=status,
        reason=reason,
        current_url="",
        checked_at=datetime.now(),
    )
    if result.ok and result.shop_display_name:
        update_shop_display_name(result.account_id, result.shop_display_name)


def _body_text(page) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=3_000) or "")
    except Exception:
        return ""


def _classify_login_page(account: AccountConfig, dp: DpPage) -> LoginCheckResult:
    now = datetime.now()
    phone = resolve_account_phone(account)
    if is_likely_logged_in(dp.url) and not is_login_url(dp.url):
        maybe_refresh_shop_display_name(account.account_id, dp, login_phone=phone)
        return LoginCheckResult(
            account_id=account.account_id,
            status="logged_in",
            reason="session valid",
            current_url=dp.url,
            checked_at=now,
        )

    text = _body_text(dp.raw)
    if "验证码" in text or "滑块" in text or "拼图" in text or "扫码" in text:
        status = "needs_manual"
        reason = "sms/captcha required"
    elif not phone:
        status = "needs_login"
        reason = "phone missing"
    else:
        status = "needs_login"
        reason = "session expired or not logged in"

    return LoginCheckResult(
        account_id=account.account_id,
        status=status,
        reason=reason,
        current_url=dp.url,
        checked_at=now,
    )


def check_login_status_sync(settings: YamlSettings, account: AccountConfig) -> LoginCheckResult:
    try:
        with account_profile_lock(settings, account.account_id, reason="login_check", wait_seconds=1):
            pw, context, page = _launch_persistent(settings, account.account_id, headless=True)
            try:
                dp = DpPage(page, context)
                open_homepage(dp)
                time.sleep(2)
                result = _classify_login_page(account, dp)
                _persist(result)
                return result
            finally:
                try:
                    context.close()
                finally:
                    pw.stop()
    except AccountProfileBusy as exc:
        result = LoginCheckResult(
            account_id=account.account_id,
            status="checking",
            reason=str(exc),
            checked_at=datetime.now(),
        )
        _persist(result)
        return result
    except Exception as exc:
        result = LoginCheckResult(
            account_id=account.account_id,
            status="failed",
            reason=str(exc),
            checked_at=datetime.now(),
        )
        _persist(result)
        return result


def _prepare_sms_login(page, account: AccountConfig):
    phone = resolve_account_phone(account)
    if not phone:
        return page
    settings = load_yaml_settings()
    dp = DpPage(page, page.context)
    if not is_login_url(page.url):
        open_homepage(dp)
        if not is_login_url(page.url):
            page = click_home_login_button(page, account.account_id)
    existing = _wait_existing_session_redirect(page, account.account_id, max_wait_seconds=10)
    if existing is not None:
        return existing
    page.wait_for_load_state("domcontentloaded")
    ensure_mobile_login_tab(page, account.account_id)
    fill_phone(page, account.account_id, phone)
    ensure_agreement_checked(page, account.account_id)
    if settings.login.auto_send_sms:
        click_send_sms(page, account.account_id)
    return page


def _wait_existing_session_redirect(page, account_id: str, *, max_wait_seconds: int):
    """登录页如复用已有 session，会先显示登录表单再自动跳后台；先观察再填手机号。"""
    saw_existing_hint = False
    for index in range(max(1, max_wait_seconds)):
        try:
            if _page_looks_logged_in(page):
                print(f"[{account_id}] 检测到已有登录态，已自动跳转", flush=True)
                return page
            text = _body_text(page).replace(" ", "")
            if "已登录" in text or "跳转中" in text:
                saw_existing_hint = True
            if index >= 3 and not saw_existing_hint and _has_visible_phone_input(page):
                return None
        except Exception:
            if index >= 3:
                return None
        time.sleep(1)
    return page if _page_looks_logged_in(page) else None


def _page_looks_logged_in(page) -> bool:
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
                  const headerArea = Array.from(document.querySelectorAll('header, [class*="header"], [class*="Header"], [class*="top"], [class*="Top"]'));
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


def _has_visible_phone_input(page) -> bool:
    try:
        for selector in (
            'input[placeholder="手机号码"]',
            'input[placeholder*="手机"]',
            'input[name="mobile"]',
        ):
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible(timeout=300):
                return True
    except Exception:
        return False
    return False


def _find_logged_in_page(context, fallback_page):
    """登录成功后可能跳当前页，也可能新开/替换标签；扫描所有标签更稳。"""
    pages = []
    try:
        pages = [p for p in context.pages if not p.is_closed()]
    except Exception:
        pages = []
    for candidate in pages or [fallback_page]:
        try:
            if _page_looks_logged_in(candidate):
                return candidate
        except Exception:
            continue
    return None


def open_manual_login_window_sync(
    settings: YamlSettings,
    account: AccountConfig,
    *,
    keep_open_seconds: int = 300,
) -> LoginCheckResult:
    try:
        with account_profile_lock(settings, account.account_id, reason="manual_login", wait_seconds=1):
            pw, context, page = _launch_persistent(settings, account.account_id, headless=False)
            dp = DpPage(page, context)
            try:
                open_homepage(dp)
                time.sleep(2)
                phone = resolve_account_phone(account)

                if is_likely_logged_in(dp.url) and not is_login_url(dp.url):
                    maybe_refresh_shop_display_name(account.account_id, dp, login_phone=phone)
                    result = LoginCheckResult(
                        account_id=account.account_id,
                        status="logged_in",
                        reason="session valid",
                        current_url=dp.url,
                        checked_at=datetime.now(),
                    )
                    _persist(result)
                    return result

                page = _prepare_sms_login(page, account)
                dp = DpPage(page, context)
                result = LoginCheckResult(
                    account_id=account.account_id,
                    status="needs_manual",
                    reason="login window opened; enter SMS code and click login",
                    current_url=dp.url,
                    checked_at=datetime.now(),
                )
                _persist(result)

                for _ in range(max(1, keep_open_seconds)):
                    logged_in_page = _find_logged_in_page(context, page)
                    if logged_in_page is not None:
                        page = logged_in_page
                        maybe_refresh_shop_display_name(account.account_id, DpPage(page, context), login_phone=phone)
                        result = LoginCheckResult(
                            account_id=account.account_id,
                            status="logged_in",
                            reason="manual login completed",
                            current_url=page.url,
                            checked_at=datetime.now(),
                        )
                        _persist(result)
                        return result
                    time.sleep(1)

                result = LoginCheckResult(
                    account_id=account.account_id,
                    status="needs_manual",
                    reason="manual login timeout",
                    current_url=page.url,
                    checked_at=datetime.now(),
                )
                _persist(result)
                return result
            finally:
                try:
                    page.evaluate("window.onbeforeunload = null;")
                except Exception:
                    pass
                try:
                    context.close()
                finally:
                    pw.stop()
    except AccountProfileBusy as exc:
        result = LoginCheckResult(
            account_id=account.account_id,
            status="checking",
            reason=str(exc),
            checked_at=datetime.now(),
        )
        _persist(result)
        return result
    except Exception as exc:
        result = LoginCheckResult(
            account_id=account.account_id,
            status="failed",
            reason=str(exc),
            checked_at=datetime.now(),
        )
        _persist(result)
        return result


def scrape_shop_display_name_sync(
    settings: YamlSettings,
    account: AccountConfig,
) -> ShopNameScrapeResult:
    account_id = account.account_id
    phone = resolve_account_phone(account)
    print(f"[{account_id}] 开始抓取抖店名称（将打开浏览器）...", flush=True)
    try:
        with account_profile_lock(settings, account_id, reason="scrape_shop_name", wait_seconds=60):
            pw, context, page = _launch_persistent(settings, account_id, headless=False)
            try:
                dp = DpPage(page, context)
                open_homepage(dp)
                time.sleep(2)
                if not (is_likely_logged_in(dp.url) and not is_login_url(dp.url)):
                    try:
                        dp = perform_sms_login_sync(account, page)
                    except Exception as exc:
                        return ShopNameScrapeResult(
                            account_id=account_id,
                            ok=False,
                            reason=f"登录失败: {exc}",
                        )

                name = refresh_shop_display_name(account_id, dp, login_phone=phone)
                if name:
                    return ShopNameScrapeResult(
                        account_id=account_id,
                        shop_display_name=name,
                        ok=True,
                        reason="scraped",
                    )
                return ShopNameScrapeResult(
                    account_id=account_id,
                    ok=False,
                    reason="shop display name not found on page",
                )
            finally:
                try:
                    page.evaluate("window.onbeforeunload = null;")
                except Exception:
                    pass
                try:
                    context.close()
                finally:
                    pw.stop()
    except AccountProfileBusy as exc:
        return ShopNameScrapeResult(account_id=account_id, ok=False, reason=str(exc))
    except Exception as exc:
        return ShopNameScrapeResult(account_id=account_id, ok=False, reason=str(exc))
