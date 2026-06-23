"""飞书上架定价读取诊断 API 模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class FeishuInspectListingPricesIn(BaseModel):
    codes: list[str] = Field(default_factory=list, description="商品编码或 BDxxx/套图/编码 selector")
    pipeline_id: str = Field(default="", description="整合链路 ID；提供则结果写入该链路记录")
    force_refresh: bool = Field(
        default=True,
        description="是否清空缓存后重新从飞书拉取（推荐开启以便看到最新数据）",
    )

    @model_validator(mode="after")
    def validate_codes_or_pipeline(self) -> "FeishuInspectListingPricesIn":
        if not self.codes and not str(self.pipeline_id or "").strip():
            raise ValueError("codes 或 pipeline_id 至少填一项")
        return self


class FeishuInspectListingPricesOut(BaseModel):
    codes: list[str] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    field_names: dict[str, str] = Field(default_factory=dict)
    table_name: str = ""
    table_id: str = ""
    snapshot_source: str = ""
    snapshot_keys: list[str] = Field(default_factory=list)
    pricing_catalog_source: str = ""
    range_catalog_source: str = ""
    pipeline_id: str = ""
    saved_at: str = ""
    from_cache: bool = False
