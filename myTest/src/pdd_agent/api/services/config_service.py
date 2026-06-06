"""配置读写服务：店铺 CRUD + 摘要。"""

from __future__ import annotations

from fastapi import HTTPException

from pdd_agent.api.schemas.config import (
    AccountCreateIn,
    AccountDetailOut,
    AccountOut,
    AccountUpdateIn,
    ConfigSummaryOut,
)
from pdd_agent.core.config import (
    AccountConfig,
    YamlSettings,
    get_env_settings,
    load_yaml_settings,
    save_yaml_settings,
)


def _to_account_out(acc: AccountConfig) -> AccountOut:
    return AccountOut(
        account_id=acc.account_id,
        enabled=acc.enabled,
        username=acc.username,
        has_password=bool(acc.password),
        product_codes=acc.product_codes,
    )


def _to_account_detail(acc: AccountConfig) -> AccountDetailOut:
    return AccountDetailOut(
        account_id=acc.account_id,
        enabled=acc.enabled,
        username=acc.username,
        has_password=bool(acc.password),
        product_codes=acc.product_codes,
        password=acc.password,
    )


def get_config_summary() -> ConfigSummaryOut:
    settings = load_yaml_settings()
    env = get_env_settings()
    accounts = settings.accounts
    return ConfigSummaryOut(
        app_name=settings.app.get("name", "pdd-agent-platform"),
        log_level=settings.app.get("log_level", "INFO"),
        assets_root=str(settings.paths.resolve("assets_root")),
        excel_path=str(settings.multi_spec.excel_path),
        llm_configured=bool(env.llm_api_key),
        account_count=len(accounts),
        enabled_account_count=sum(1 for a in accounts if a.enabled),
    )


def list_accounts(*, enabled_only: bool = False) -> list[AccountOut]:
    settings = load_yaml_settings()
    rows: list[AccountOut] = []
    for acc in settings.accounts:
        if enabled_only and not acc.enabled:
            continue
        rows.append(_to_account_out(acc))
    return rows


def get_account_detail(account_id: str) -> AccountDetailOut:
    settings = load_yaml_settings()
    acc = _find_account(settings, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {account_id}")
    return _to_account_detail(acc)


def create_account(body: AccountCreateIn) -> AccountDetailOut:
    settings = load_yaml_settings()
    if _find_account(settings, body.account_id):
        raise HTTPException(status_code=409, detail=f"店铺 ID 已存在: {body.account_id}")

    settings.accounts.append(
        AccountConfig(
            account_id=body.account_id,
            enabled=body.enabled,
            username=body.username.strip(),
            password=body.password,
            product_codes=_clean_codes(body.product_codes),
        )
    )
    save_yaml_settings(settings)
    return get_account_detail(body.account_id)


def update_account(account_id: str, body: AccountUpdateIn) -> AccountDetailOut:
    settings = load_yaml_settings()
    acc = _find_account(settings, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {account_id}")

    acc.enabled = body.enabled
    acc.username = body.username.strip()
    if body.password:
        acc.password = body.password
    acc.product_codes = _clean_codes(body.product_codes)

    save_yaml_settings(settings)
    return get_account_detail(account_id)


def delete_account(account_id: str) -> None:
    settings = load_yaml_settings()
    before = len(settings.accounts)
    settings.accounts = [a for a in settings.accounts if a.account_id != account_id]
    if len(settings.accounts) == before:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {account_id}")
    save_yaml_settings(settings)


def get_account_or_none(account_id: str, settings: YamlSettings | None = None):
    settings = settings or load_yaml_settings()
    return _find_account(settings, account_id)


def _find_account(settings: YamlSettings, account_id: str) -> AccountConfig | None:
    for acc in settings.accounts:
        if acc.account_id == account_id:
            return acc
    return None


def _clean_codes(codes: list[str]) -> list[str]:
    return list(dict.fromkeys(c.strip() for c in codes if c and c.strip()))
