"""Login health checks and manual login windows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from pdd_agent.browser.dp_compat_sync import DpPage
from pdd_agent.browser.profile_lock import AccountProfileBusy, account_profile_lock
from pdd_agent.browser.sync_job import _launch_persistent
from pdd_agent.browser.sync_login import HOME_URL, _click_login_button, ensure_login_sync, is_login_url
from pdd_agent.core.config import AccountConfig, YamlSettings
from pdd_agent.db.repositories import upsert_login_status


@dataclass
class ShopNameScrapeResult:
    account_id: str
    shop_display_name: str = ""
    ok: bool = False
    reason: str = ""


def scrape_shop_display_name_sync(
    settings: YamlSettings,
    account: AccountConfig,
) -> ShopNameScrapeResult:
    """打开可见浏览器、自动登录（含验证码等待），抓取店铺名并写入数据库。"""
    account_id = account.account_id
    print(f"[{account_id}] 开始抓取店铺名称（将打开浏览器窗口）...", flush=True)
    current_url = ""
    try:
        with account_profile_lock(
            settings,
            account_id,
            reason="scrape_shop_name",
            wait_seconds=60,
        ):
            # 抓取店铺名必须可见窗口，便于人工过验证码/滑块
            pw, context, page = _launch_persistent(
                settings, account_id, headless=False
            )
            try:
                dp = ensure_login_sync(account, page)
                current_url = str(dp.url or "")
                if is_login_url(current_url):
                    return ShopNameScrapeResult(
                        account_id=account_id,
                        ok=False,
                        reason="仍在登录页，请检查账号密码或完成验证码",
                    )

                from pdd_agent.browser.shop_display_name import refresh_shop_display_name

                name = refresh_shop_display_name(
                    account_id,
                    dp,
                    login_username=account.username,
                )
                if name:
                    print(f"[{account_id}] 抓取店铺名成功：{name}", flush=True)
                    time.sleep(1.5)
                    return ShopNameScrapeResult(
                        account_id=account_id,
                        shop_display_name=name,
                        ok=True,
                        reason="scraped",
                    )
                print(
                    f"[{account_id}] 页面已登录但未识别到店铺名，url={current_url}",
                    flush=True,
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
        print(f"[{account_id}] 抓取店铺名失败：{exc}", flush=True)
        return ShopNameScrapeResult(
            account_id=account_id,
            ok=False,
            reason=str(exc),
        )
    except RuntimeError as exc:
        print(f"[{account_id}] 抓取店铺名登录失败：{exc}", flush=True)
        return ShopNameScrapeResult(
            account_id=account_id,
            ok=False,
            reason=str(exc),
        )
    except Exception as exc:
        print(f"[{account_id}] 抓取店铺名异常：{exc}", flush=True)
        return ShopNameScrapeResult(
            account_id=account_id,
            ok=False,
            reason=str(exc),
        )


@dataclass
class LoginCheckResult:
    account_id: str
    status: str
    reason: str = ""
    current_url: str = ""
    checked_at: datetime | None = None


def check_login_status_sync(settings: YamlSettings, account: AccountConfig) -> LoginCheckResult:
    """Open the store profile, check whether PDD session is valid, then close."""
    try:
        with account_profile_lock(settings, account.account_id, reason="login_check", wait_seconds=1):
            pw, context, page = _launch_persistent(settings, account.account_id)
            try:
                page.goto(HOME_URL, wait_until="domcontentloaded")
                time.sleep(2)
                result = _classify_login_page(account, DpPage(page))
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
            current_url="",
            checked_at=datetime.now(),
        )
        _persist(result)
        return result
    except Exception as exc:
        result = LoginCheckResult(
            account_id=account.account_id,
            status="failed",
            reason=str(exc),
            current_url="",
            checked_at=datetime.now(),
        )
        _persist(result)
        return result


def open_manual_login_window_sync(
    settings: YamlSettings,
    account: AccountConfig,
    *,
    keep_open_seconds: int = 300,
) -> LoginCheckResult:
    """Open a visible login window and keep it available for manual verification."""
    try:
        with account_profile_lock(settings, account.account_id, reason="manual_login", wait_seconds=1):
            pw, context, page = _launch_persistent(settings, account.account_id)
            dp = DpPage(page)
            try:
                return _run_manual_login_window(
                    account,
                    dp,
                    page,
                    keep_open_seconds=keep_open_seconds,
                )
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
            current_url="",
            checked_at=datetime.now(),
        )
        _persist(result)
        return result
    except Exception as exc:
        result = LoginCheckResult(
            account_id=account.account_id,
            status="failed",
            reason=str(exc),
            current_url="",
            checked_at=datetime.now(),
        )
        _persist(result)
        return result


def _run_manual_login_window(
    account: AccountConfig,
    dp: DpPage,
    page,
    *,
    keep_open_seconds: int,
) -> LoginCheckResult:
    page.goto(HOME_URL, wait_until="domcontentloaded")
    time.sleep(2)
    if "login" not in page.url:
        from pdd_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        maybe_refresh_shop_display_name(account.account_id, dp, login_username=account.username)
        result = LoginCheckResult(
            account_id=account.account_id,
            status="logged_in",
            reason="session valid",
            current_url=page.url,
            checked_at=datetime.now(),
        )
        _persist(result)
        time.sleep(3)
        return result

    _prepare_password_login(dp, account)
    result = LoginCheckResult(
        account_id=account.account_id,
        status="needs_manual",
        reason="login window opened; finish captcha/sms/qr if required",
        current_url=page.url,
        checked_at=datetime.now(),
    )
    _persist(result)

    for _ in range(max(1, keep_open_seconds)):
        if "login" not in page.url:
            from pdd_agent.browser.shop_display_name import maybe_refresh_shop_display_name

            maybe_refresh_shop_display_name(account.account_id, dp, login_username=account.username)
            result = LoginCheckResult(
                account_id=account.account_id,
                status="logged_in",
                reason="manual login completed",
                current_url=page.url,
                checked_at=datetime.now(),
            )
            _persist(result)
            time.sleep(3)
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


def _persist_scrape_result(result: ShopNameScrapeResult) -> None:
    if result.ok:
        status = "logged_in"
        reason = f"shop name scraped: {result.shop_display_name}"
    elif "登录" in (result.reason or "") or result.reason in {
        "not logged in",
        "仍在登录页，请检查账号密码或完成验证码",
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
        from pdd_agent.db.repositories import update_shop_display_name

        update_shop_display_name(result.account_id, result.shop_display_name)


def mark_checking(account_id: str, reason: str) -> None:
    upsert_login_status(
        account_id=account_id,
        status="checking",
        reason=reason,
        current_url="",
        checked_at=datetime.now(),
    )


def _prepare_password_login(dp: DpPage, account: AccountConfig) -> None:
    tab = dp.ele("text:账号登录", timeout=3)
    if tab:
        tab.click()
        time.sleep(1)

    user_input = dp.ele("#usernameId", timeout=5)
    if user_input and account.username:
        user_input.input(account.username, clear=True)
    time.sleep(0.3)

    pwd_input = dp.ele("#passwordId", timeout=5)
    if pwd_input and account.password:
        pwd_input.input(account.password, clear=True)
    time.sleep(0.5)

    if account.username and account.password:
        _click_login_button(dp)
        time.sleep(1)


def _classify_login_page(account: AccountConfig, dp: DpPage) -> LoginCheckResult:
    now = datetime.now()
    if "login" not in dp.url:
        from pdd_agent.browser.shop_display_name import maybe_refresh_shop_display_name

        maybe_refresh_shop_display_name(
            account.account_id,
            dp,
            login_username=account.username,
        )
        return LoginCheckResult(
            account_id=account.account_id,
            status="logged_in",
            reason="session valid",
            current_url=dp.url,
            checked_at=now,
        )

    text = _body_text(dp)
    if "验证码" in text or "滑块" in text or "拼图" in text or "扫码" in text:
        status = "needs_manual"
        reason = "captcha/sms/qr required"
    elif not account.username or not account.password:
        status = "needs_login"
        reason = "username or password missing"
    else:
        status = "needs_login"
        reason = "session expired"

    return LoginCheckResult(
        account_id=account.account_id,
        status=status,
        reason=reason,
        current_url=dp.url,
        checked_at=now,
    )


def _body_text(dp: DpPage) -> str:
    try:
        return str(dp.run_js("return document.body?.innerText || '';") or "")
    except Exception:
        return ""


def _persist(result: LoginCheckResult) -> None:
    upsert_login_status(
        account_id=result.account_id,
        status=result.status,
        reason=result.reason,
        current_url=result.current_url,
        checked_at=result.checked_at or datetime.now(),
    )
