"""配置读写服务：店铺 CRUD + 摘要。"""

from __future__ import annotations

from fastapi import HTTPException

from pdd_agent.api.schemas.config import (
    AccountCreateIn,
    AccountDetailOut,
    AccountOut,
    AccountUpdateIn,
    AppConfigIn,
    BatchConfigIn,
    BrowserConfigIn,
    ConfigSummaryOut,
    DelistConfigIn,
    ListingConfigIn,
    MultiSpecConfigIn,
    PathsConfigIn,
    RuntimeConfigOut,
    RuntimeConfigUpdateIn,
)
from pdd_agent.core.account_display import resolve_account_display_name
from pdd_agent.core.config import (
    AccountConfig,
    BrowserConfig,
    BatchConfig,
    DelistConfig,
    ListingConfig,
    MultiSpecConfig,
    PathsConfig,
    YamlSettings,
    get_env_settings,
    load_yaml_settings,
    save_yaml_settings,
)
from pdd_agent.db.repositories import (
    create_account_config,
    db_accounts_enabled,
    delete_account_config,
    get_account_config,
    get_cached_shop_display_name,
    list_account_configs,
    update_account_config,
)
from pdd_agent.db.session import database_status


def _to_account_out(acc: AccountConfig) -> AccountOut:
    shop_name = get_cached_shop_display_name(acc.account_id)
    return AccountOut(
        account_id=acc.account_id,
        enabled=acc.enabled,
        username=acc.username,
        shop_display_name=shop_name,
        display_name=shop_name or resolve_account_display_name(acc.account_id),
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
    accounts = list_account_configs(settings)
    db = database_status()
    return ConfigSummaryOut(
        app_name=settings.app.get("name", "pdd-agent-platform"),
        log_level=settings.app.get("log_level", "INFO"),
        assets_root=str(settings.paths.resolve("assets_root")),
        excel_path=str(settings.multi_spec.excel_path),
        llm_configured=bool(env.llm_api_key),
        database_configured=bool(db["configured"]),
        database_available=bool(db["available"]),
        database_error=str(db["error"] or ""),
        account_count=len(accounts),
        enabled_account_count=sum(1 for a in accounts if a.enabled),
    )


def list_accounts(*, enabled_only: bool = False) -> list[AccountOut]:
    settings = load_yaml_settings()
    return [_to_account_out(acc) for acc in list_account_configs(settings, enabled_only=enabled_only)]


def get_account_detail(account_id: str) -> AccountDetailOut:
    settings = load_yaml_settings()
    acc = get_account_config(settings, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {account_id}")
    return _to_account_detail(acc)


def create_account(body: AccountCreateIn) -> AccountDetailOut:
    settings = load_yaml_settings()
    if get_account_config(settings, body.account_id):
        raise HTTPException(status_code=409, detail=f"店铺 ID 已存在: {body.account_id}")

    acc = AccountConfig(
        account_id=body.account_id,
        enabled=body.enabled,
        username=body.username.strip(),
        password=body.password,
        product_codes=_clean_codes(body.product_codes),
    )
    if db_accounts_enabled():
        create_account_config(acc)
    else:
        settings.accounts.append(acc)
        save_yaml_settings(settings)
    return get_account_detail(body.account_id)


def update_account(account_id: str, body: AccountUpdateIn) -> AccountDetailOut:
    settings = load_yaml_settings()
    acc = get_account_config(settings, account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {account_id}")

    next_acc = AccountConfig(
        account_id=account_id,
        enabled=body.enabled,
        username=body.username.strip(),
        password=body.password,
        product_codes=_clean_codes(body.product_codes),
    )

    if db_accounts_enabled():
        updated = update_account_config(account_id, next_acc, keep_empty_password=True)
        if not updated:
            raise HTTPException(status_code=404, detail=f"店铺不存在: {account_id}")
    else:
        acc.enabled = body.enabled
        acc.username = body.username.strip()
        if body.password:
            acc.password = body.password
        acc.product_codes = _clean_codes(body.product_codes)
        save_yaml_settings(settings)
    return get_account_detail(account_id)


def delete_account(account_id: str) -> None:
    settings = load_yaml_settings()
    if db_accounts_enabled():
        if not delete_account_config(account_id):
            raise HTTPException(status_code=404, detail=f"店铺不存在: {account_id}")
        return

    before = len(settings.accounts)
    settings.accounts = [a for a in settings.accounts if a.account_id != account_id]
    if len(settings.accounts) == before:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {account_id}")
    save_yaml_settings(settings)


def get_account_or_none(account_id: str, settings: YamlSettings | None = None):
    settings = settings or load_yaml_settings()
    return get_account_config(settings, account_id)


def _find_account(settings: YamlSettings, account_id: str) -> AccountConfig | None:
    for acc in settings.accounts:
        if acc.account_id == account_id:
            return acc
    return None


def _clean_codes(codes: list[str]) -> list[str]:
    return list(dict.fromkeys(c.strip() for c in codes if c and c.strip()))


def get_runtime_config() -> RuntimeConfigOut:
    settings = load_yaml_settings()
    return RuntimeConfigOut(
        app=AppConfigIn(
            name=settings.app.get("name", "pdd-agent-platform"),
            log_level=settings.app.get("log_level", "INFO"),
        ),
        paths=PathsConfigIn(**settings.paths.model_dump()),
        browser=BrowserConfigIn(**settings.browser.model_dump()),
        multi_spec=MultiSpecConfigIn(**settings.multi_spec.model_dump()),
        listing=ListingConfigIn(**settings.listing.model_dump()),
        delist=DelistConfigIn(**settings.delist.model_dump()),
        batch=BatchConfigIn(**settings.batch.model_dump()),
    )


def update_runtime_config(body: RuntimeConfigUpdateIn) -> RuntimeConfigOut:
    settings = load_yaml_settings()
    settings.app = body.app.model_dump()
    settings.paths = PathsConfig(**body.paths.model_dump())
    settings.browser = BrowserConfig(**body.browser.model_dump())
    settings.multi_spec = MultiSpecConfig(**body.multi_spec.model_dump())
    settings.listing = ListingConfig(**body.listing.model_dump())
    settings.delist = DelistConfig(**body.delist.model_dump())
    settings.batch = BatchConfig(**body.batch.model_dump())
    save_yaml_settings(settings)
    return get_runtime_config()
