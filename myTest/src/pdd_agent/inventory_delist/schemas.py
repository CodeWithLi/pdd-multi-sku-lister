"""库存下架 API — Pydantic 模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ExecutionMode = Literal["parallel", "sequential"]


class InventoryDelistScheduleOut(BaseModel):
    enabled: bool = False
    interval_hours: float = 6.0
    account_ids: list[str] = Field(default_factory=list)
    execution_mode: ExecutionMode = "parallel"
    delist_spec_code_search_enabled: bool = False
    scheduler_running: bool = False
    database_available: bool = False
    last_scheduled_run_at: str = ""


class InventoryDelistScheduleUpdateIn(BaseModel):
    enabled: bool = False
    interval_hours: float = Field(default=6.0, ge=0.5, le=168.0)
    account_ids: list[str] = Field(default_factory=list)
    execution_mode: ExecutionMode = "parallel"
    delist_spec_code_search_enabled: bool = False


class InventoryDelistPreviewIn(BaseModel):
    account_ids: list[str] = Field(default_factory=list)
    force_feishu_refresh: bool = True
    test_override_enabled: bool = False
    test_inventory_overrides: dict[str, int] = Field(default_factory=dict)
    test_override_text: str = ""


class AccountProductBreakdownOut(BaseModel):
    account_id: str
    on_sale_codes: list[str] = Field(default_factory=list)
    exclusive_codes: list[str] = Field(default_factory=list)
    negative_inventory_codes: list[str] = Field(default_factory=list)
    delist_candidate_codes: list[str] = Field(default_factory=list)
    inventory_by_code: dict[str, int] = Field(default_factory=dict)
    published_counts: dict[str, int] = Field(default_factory=dict)


class InventoryDelistPreviewOut(BaseModel):
    ok: bool = True
    account_ids: list[str] = Field(default_factory=list)
    requested_account_ids: list[str] = Field(default_factory=list)
    resolved_account_ids: list[str] = Field(default_factory=list)
    common_on_sale_codes: list[str] = Field(default_factory=list)
    all_on_sale_codes: list[str] = Field(default_factory=list)
    negative_inventory_codes: list[str] = Field(default_factory=list)
    inventory_by_code: dict[str, int] = Field(default_factory=dict)
    feishu_query_count: int = 0
    feishu_called: bool = False
    feishu_rows_matched: int = 0
    feishu_force_refresh: bool = False
    feishu_error: str = ""
    database_available: bool = False
    test_override_enabled: bool = False
    test_overrides_applied: list[dict] = Field(default_factory=list)
    diagnostics: dict = Field(default_factory=dict)
    per_account: list[AccountProductBreakdownOut] = Field(default_factory=list)


class InventoryDelistTriggerIn(BaseModel):
    account_ids: list[str] = Field(default_factory=list)
    execution_mode: ExecutionMode | None = None
    delist_spec_code_search_enabled: bool | None = None
    test_override_enabled: bool = False
    test_inventory_overrides: dict[str, int] = Field(default_factory=dict)
    test_override_text: str = ""
    delist_dry_run: bool = False


class OnSaleCodesIn(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


class OnSaleCodesAccountOut(BaseModel):
    account_id: str
    on_sale_codes: list[str] = Field(default_factory=list)
    count: int = 0


class OnSaleCodesOut(BaseModel):
    ok: bool = True
    account_ids: list[str] = Field(default_factory=list)
    all_on_sale_codes: list[str] = Field(default_factory=list)
    total: int = 0
    per_account: list[OnSaleCodesAccountOut] = Field(default_factory=list)


class AccountDelistTaskOut(BaseModel):
    account_id: str
    status: str = "pending"
    run_id: str = ""
    candidate_codes: list[str] = Field(default_factory=list)
    target_count: int = 0
    deleted_mapping_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str = ""


class InventoryDelistJobOut(BaseModel):
    job_id: str
    status: str = "pending"
    trigger: str = "manual"
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    account_ids: list[str] = Field(default_factory=list)
    execution_mode: str = "parallel"
    common_on_sale_codes: list[str] = Field(default_factory=list)
    negative_inventory_codes: list[str] = Field(default_factory=list)
    per_account: list[AccountDelistTaskOut] = Field(default_factory=list)
    message: str = ""
    error: str = ""


class InventoryDelistTriggerOut(BaseModel):
    ok: bool = True
    job: InventoryDelistJobOut


class InventoryDelistJobListOut(BaseModel):
    ok: bool = True
    total: int = 0
    items: list[InventoryDelistJobOut] = Field(default_factory=list)


class InventoryDelistRecordOut(BaseModel):
    record_id: str
    job_id: str
    run_id: str = ""
    account_id: str
    shop_display_name: str = ""
    product_code: str
    merchant_code: str = ""
    mapping_id: str = ""
    pdd_product_id: str = ""
    erp_available_qty: int | None = None
    erp_original_qty: int | None = None
    is_test_override: bool = False
    is_common_on_sale: bool = False
    trigger: str = "manual"
    execution_mode: str = "parallel"
    dry_run: bool = False
    delist_status: str = ""
    message: str = ""
    delisted_at: str = ""


class InventoryDelistRecordListOut(BaseModel):
    ok: bool = True
    total: int = 0
    items: list[InventoryDelistRecordOut] = Field(default_factory=list)
