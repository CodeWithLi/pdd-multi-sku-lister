"""领域数据结构（纯 Pydantic，不依赖 LangGraph / Playwright）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pdd_agent.domain.enums import AgentKind, RunStatus, TaskPhase


class SkuCombo(BaseModel):
    """单个 SKU 组合：款式 × 型号 + 价格库存 + 预览图。"""

    style_code: str
    style_name: str  # 页面展示的中文款式名
    model_code: str
    model_name: str  # 页面展示的中文型号名（通常来自 Excel）
    combo_folder: str  # 素材目录名，如 BD046A+YKL2005A
    preview_image: Path
    inventory: str = "10"
    group_price: str = "199.9"
    single_price: str = "299.9"


class ListingUnit(BaseModel):
    """一个可上架单元 = 商品编码 × 一套图。"""

    product_code: str
    family_code: str = ""
    image_set: str = ""  # 如「第一套图」，空表示旧版单套结构
    root: Path
    carousel_images: list[Path] = Field(default_factory=list)
    detail_images: list[Path] = Field(default_factory=list)
    style_codes: list[str] = Field(default_factory=list)
    model_codes: list[str] = Field(default_factory=list)
    skus: list[SkuCombo] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # 非致命解析警告

    @property
    def listing_label(self) -> str:
        """日志/报告用短标签。"""
        if self.image_set:
            return f"{self.product_code}/{self.image_set}"
        return self.product_code

    @property
    def merchant_code(self) -> str:
        """写入拼多多「商品编码/货号」字段（文件夹名，如 BD046A）。"""
        return self.product_code


class PreflightIssue(BaseModel):
    """上架前校验发现的问题。"""

    level: str  # error | warning
    message: str
    listing_label: str = ""


class PreflightReport(BaseModel):
    """批量 preflight 结果。"""

    units: list[ListingUnit] = Field(default_factory=list)
    issues: list[PreflightIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        """无 error 级别问题时为 True。"""
        return not any(i.level == "error" for i in self.issues)

    @property
    def valid_units(self) -> list[ListingUnit]:
        """排除有 error 的套图后，仍可上架的单元。"""
        error_labels = {i.listing_label for i in self.issues if i.level == "error" and i.listing_label}
        return [u for u in self.units if u.listing_label not in error_labels]


class PlannedTask(BaseModel):
    """Orchestrator 输出的单条可执行任务。"""

    agent: AgentKind
    account_id: str
    product_codes: list[str] = Field(default_factory=list)
    dry_run: bool = False
    params: dict[str, Any] = Field(default_factory=dict)  # 扩展参数（活动类型等）


class RunRecord(BaseModel):
    """单次运行的持久化记录，对应 data/runs/{run_id}.json。"""

    run_id: str
    agent: AgentKind
    account_id: str
    status: RunStatus = RunStatus.PENDING
    phase: TaskPhase = TaskPhase.PLAN
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None
    message: str = ""
    listing_labels: list[str] = Field(default_factory=list)
    artifacts: dict[str, str] = Field(default_factory=dict)  # 截图路径等
    result: dict[str, Any] = Field(default_factory=dict)  # API/CLI 执行结果摘要
