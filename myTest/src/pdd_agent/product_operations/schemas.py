"""商品操作 API 模型。"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name}不能为空")
    return text


class DelistAllStoresIn(BaseModel):
    product_code: str = Field(min_length=1, max_length=100)
    dry_run: bool = False

    @field_validator("product_code")
    @classmethod
    def validate_product_code(cls, value: str) -> str:
        return _required_text(value, "商品编码")


class StoreDelistRunOut(BaseModel):
    account_id: str
    run_id: str
    status: str = "pending"


class DelistAllStoresOut(BaseModel):
    ok: bool = True
    product_code: str
    dry_run: bool = False
    total: int = 0
    runs: list[StoreDelistRunOut] = Field(default_factory=list)
    message: str = ""


class PublishedProductOptionOut(BaseModel):
    product_code: str
    listing_label: str = ""
    account_ids: list[str] = Field(default_factory=list)
    product_ids: dict[str, str] = Field(default_factory=dict)
    shop_count: int = 0
    record_count: int = 0


class PublishedProductOptionListOut(BaseModel):
    ok: bool = True
    total: int = 0
    items: list[PublishedProductOptionOut] = Field(default_factory=list)


class PricePreviewIn(BaseModel):
    account_id: str = Field(min_length=1, max_length=100)
    product_code: str = Field(min_length=1, max_length=100)
    pdd_product_id: str = Field(default="", max_length=30)

    @field_validator("account_id", "product_code")
    @classmethod
    def validate_required(cls, value: str, info) -> str:
        label = "店铺" if info.field_name == "account_id" else "商品编码"
        return _required_text(value, label)

    @field_validator("pdd_product_id")
    @classmethod
    def validate_optional_product_id(cls, value: str) -> str:
        product_id = str(value or "").strip()
        if product_id and not product_id.isdigit():
            raise ValueError("商品ID只能包含数字")
        return product_id


class SpecPriceUpdateIn(BaseModel):
    spec_code: str = Field(min_length=1, max_length=160)
    group_price: Decimal = Field(gt=Decimal("0"), le=Decimal("999999.99"), decimal_places=2)
    single_price: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        le=Decimal("999999.99"),
        decimal_places=2,
    )

    @field_validator("spec_code")
    @classmethod
    def validate_spec_code(cls, value: str) -> str:
        return _required_text(value, "规格编码")


class PriceUpdateIn(PricePreviewIn):
    updates: list[SpecPriceUpdateIn] = Field(min_length=1, max_length=500)


class ProductOperationRunOut(BaseModel):
    ok: bool = True
    run_id: str
    status: str = "pending"
    message: str = ""
