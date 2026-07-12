"""领域数据结构（纯 Pydantic）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from dy_agent.domain.enums import AgentKind, RunStatus, TaskPhase


class SkuCombo(BaseModel):
    """单个 SKU 组合。"""

    style_code: str
    style_name: str
    model_code: str
    model_name: str
    combo_folder: str
    preview_image: Path
    inventory: str = "10"
    price: str = "199.9"
    market_price: str = "299.9"


class ListingUnit(BaseModel):
    """一个可上架单元 = 商品编码 × 一套图。"""

    product_code: str
    family_code: str = ""
    image_set: str = ""
    root: Path
    carousel_images: list[Path] = Field(default_factory=list)
    detail_images: list[Path] = Field(default_factory=list)
    material_image: Path | None = None
    style_codes: list[str] = Field(default_factory=list)
    model_codes: list[str] = Field(default_factory=list)
    skus: list[SkuCombo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def listing_label(self) -> str:
        if self.image_set:
            return f"{self.product_code}/{self.image_set}"
        return self.product_code

    @property
    def merchant_code(self) -> str:
        """抖店「货号/商家编码」字段（默认用文件夹名）。"""
        return self.product_code


class PreflightIssue(BaseModel):
    level: str  # error | warning
    message: str
    listing_label: str = ""
    reason_code: str = ""


class PreflightReport(BaseModel):
    units: list[ListingUnit] = Field(default_factory=list)
    issues: list[PreflightIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    @property
    def valid_units(self) -> list[ListingUnit]:
        error_labels = {i.listing_label for i in self.issues if i.level == "error" and i.listing_label}
        return [u for u in self.units if u.listing_label not in error_labels]


class PlannedTask(BaseModel):
    agent: AgentKind
    account_id: str
    product_codes: list[str] = Field(default_factory=list)
    dry_run: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class RunRecord(BaseModel):
    run_id: str
    agent: AgentKind
    account_id: str
    status: RunStatus = RunStatus.PENDING
    phase: TaskPhase = TaskPhase.PLAN
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None
    message: str = ""
    listing_labels: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
