"""Login health routes."""

from __future__ import annotations

import asyncio
import random

from fastapi import APIRouter, BackgroundTasks, HTTPException

from dy_agent.api.schemas.login import (
    LoginBatchCheckRequest,
    LoginBatchCheckResponse,
    LoginStatusOut,
    OpenLoginWindowRequest,
    ShopNameScrapeBatchRequest,
    ShopNameScrapeBatchResponse,
    ShopNameScrapeResultOut,
)
from dy_agent.browser.login_health import (
    _persist_scrape_result,
    check_login_status_sync,
    mark_checking,
    open_manual_login_window_sync,
    scrape_shop_display_name_sync,
)
from dy_agent.core.config import AccountConfig, load_yaml_settings
from dy_agent.db.repositories import (
    get_account_config,
    get_cached_shop_display_name,
    list_account_configs,
    list_login_status_rows,
    upsert_login_status,
)

router = APIRouter(prefix="/login", tags=["login"])

_DEFAULT_DELAY_MIN = 30
_DEFAULT_DELAY_MAX = 180


@router.get("/statuses", response_model=list[LoginStatusOut])
def list_login_statuses(enabled_only: bool = True):
    settings = load_yaml_settings()
    accounts = list_account_configs(settings, enabled_only=enabled_only)
    rows = {row.account_id: row for row in list_login_status_rows()}
    result: list[LoginStatusOut] = []
    for acc in accounts:
        row = rows.get(acc.account_id)
        shop_name = get_cached_shop_display_name(acc.account_id)
        result.append(
            LoginStatusOut(
                account_id=acc.account_id,
                status=row.status if row else "unknown",
                reason=row.reason if row else "",
                current_url=row.current_url if row else "",
                shop_display_name=shop_name or acc.account_id,
                checked_at=row.checked_at if row else None,
            )
        )
    return result


@router.post("/check/{account_id}", response_model=LoginStatusOut)
async def check_login_status(account_id: str):
    settings = load_yaml_settings()
    account = _get_account_or_404(settings, account_id)
    mark_checking(account_id, "checking login status")
    result = await asyncio.to_thread(check_login_status_sync, settings, account)
    return _to_out(result)


@router.post("/check-batch", response_model=LoginBatchCheckResponse)
async def check_login_status_batch(body: LoginBatchCheckRequest, background: BackgroundTasks):
    settings = load_yaml_settings()
    accounts = _resolve_accounts(settings, body.account_ids)
    delay_min, delay_max = _resolve_delay(body.delay_min_seconds, body.delay_max_seconds)

    for account in accounts:
        upsert_login_status(
            account_id=account.account_id,
            status="pending",
            reason="waiting for login check",
        )

    async def _job():
        for index, account in enumerate(accounts):
            mark_checking(account.account_id, "checking login status")
            await asyncio.to_thread(check_login_status_sync, settings, account)
            if index < len(accounts) - 1 and delay_max > 0:
                await asyncio.sleep(random.randint(delay_min, delay_max))

    background.add_task(_job)
    return LoginBatchCheckResponse(
        total=len(accounts),
        delay_min_seconds=delay_min,
        delay_max_seconds=delay_max,
        message=f"login check submitted: {len(accounts)} stores, delay {delay_min}-{delay_max}s",
    )


@router.post("/scrape-shop-names-batch", response_model=ShopNameScrapeBatchResponse)
async def scrape_shop_names_batch(body: ShopNameScrapeBatchRequest, background: BackgroundTasks):
    settings = load_yaml_settings()
    accounts = _resolve_accounts(settings, body.account_ids)
    delay_min, delay_max = _resolve_delay(body.delay_min_seconds, body.delay_max_seconds)

    async def _job():
        for index, account in enumerate(accounts):
            mark_checking(account.account_id, "scraping shop display name")
            result = await asyncio.to_thread(scrape_shop_display_name_sync, settings, account)
            _persist_scrape_result(result)
            if index < len(accounts) - 1 and delay_max > 0:
                await asyncio.sleep(random.randint(delay_min, delay_max))

    background.add_task(_job)
    return ShopNameScrapeBatchResponse(
        total=len(accounts),
        delay_min_seconds=delay_min,
        delay_max_seconds=delay_max,
        message=f"shop name scrape submitted: {len(accounts)} stores, delay {delay_min}-{delay_max}s",
    )


@router.post("/scrape-shop-name/{account_id}", response_model=ShopNameScrapeResultOut)
async def scrape_shop_name_one(account_id: str):
    settings = load_yaml_settings()
    account = _get_account_or_404(settings, account_id)
    mark_checking(account_id, "scraping shop display name")
    result = await asyncio.to_thread(scrape_shop_display_name_sync, settings, account)
    _persist_scrape_result(result)
    return ShopNameScrapeResultOut(
        account_id=result.account_id,
        shop_display_name=result.shop_display_name,
        ok=result.ok,
        reason=result.reason,
    )


@router.post("/open/{account_id}", response_model=LoginStatusOut)
async def open_login_window(
    account_id: str,
    body: OpenLoginWindowRequest,
    background: BackgroundTasks,
):
    settings = load_yaml_settings()
    account = _get_account_or_404(settings, account_id)
    mark_checking(account_id, "manual login window opening")

    async def _job():
        await asyncio.to_thread(
            open_manual_login_window_sync,
            settings,
            account,
            keep_open_seconds=body.keep_open_seconds,
        )

    background.add_task(_job)
    return LoginStatusOut(
        account_id=account_id,
        status="needs_manual",
        reason="manual login window opening",
    )


def _get_account_or_404(settings, account_id: str) -> AccountConfig:
    account = get_account_config(settings, account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"unknown account: {account_id}")
    return account


def _resolve_accounts(settings, account_ids: list[str]) -> list[AccountConfig]:
    if account_ids:
        accounts = [_get_account_or_404(settings, account_id) for account_id in account_ids]
    else:
        accounts = list_account_configs(settings, enabled_only=True)
    if not accounts:
        raise HTTPException(status_code=422, detail="no enabled accounts")
    return accounts


def _resolve_delay(min_requested: int | None, max_requested: int | None) -> tuple[int, int]:
    min_seconds = _DEFAULT_DELAY_MIN if min_requested is None else min_requested
    max_seconds = _DEFAULT_DELAY_MAX if max_requested is None else max_requested
    min_seconds = max(0, min(3600, min_seconds))
    max_seconds = max(0, min(3600, max_seconds))
    if max_seconds < min_seconds:
        max_seconds = min_seconds
    return min_seconds, max_seconds


def _to_out(result) -> LoginStatusOut:
    shop_name = get_cached_shop_display_name(result.account_id)
    return LoginStatusOut(
        account_id=result.account_id,
        status=result.status,
        reason=result.reason,
        current_url=result.current_url,
        shop_display_name=shop_name or result.account_id,
        checked_at=result.checked_at,
    )
