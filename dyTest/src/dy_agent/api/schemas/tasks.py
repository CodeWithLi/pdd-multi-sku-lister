"""API 请求/响应模型。"""

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    message: str


class PlanResponse(BaseModel):
    plan_summary: str
    planned_tasks: list[dict] = Field(default_factory=list)


class ListingTaskRequest(BaseModel):
    account_id: str
    product_codes: list[str] = Field(default_factory=list)
    dry_run: bool = False
    category_keyword: str = ""
    slot_alignment_test: bool | None = None
    spec_fill_verify_test: bool | None = None
    primary_style_first_test: bool | None = None
    category_next_burst_demo: bool | None = None
    accessory_cost_pricing: bool | None = None
    accessory_tiered_float: bool | None = None


class ListingTaskResponse(BaseModel):
    run_id: str
    status: str
    message: str = ""
    result: dict = Field(default_factory=dict)
