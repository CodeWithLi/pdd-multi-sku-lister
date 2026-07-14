"""上架拼单价浮动：同商品同一定价共享 0~N 元浮动。"""

from __future__ import annotations

import random
from contextvars import ContextVar
from typing import Any

_registry_ctx: ContextVar["ListingPriceFloatRegistry | None"] = ContextVar(
    "listing_price_float_registry",
    default=None,
)


class ListingPriceFloatRegistry:
    """按 (套图 scope, 定价) 缓存浮动值；同一定价在同一商品内浮动一致。"""

    def __init__(
        self,
        *,
        float_min: float = 0.0,
        float_max: float = 5.0,
        enabled: bool = True,
        single_float_min: float = 1.01,
        single_float_max: float = 2.0,
    ) -> None:
        self.float_min = max(0.0, float(float_min))
        self.float_max = max(self.float_min, float(float_max))
        self.enabled = bool(enabled)
        self.single_float_min = max(0.0, float(single_float_min))
        self.single_float_max = max(self.single_float_min, float(single_float_max))
        self._floats: dict[tuple[str, float], float] = {}
        self._single_floats: dict[tuple[str, float], float] = {}

    def get_float_delta(self, listing_scope: str, base_price: float) -> float:
        scope = str(listing_scope or "").strip()
        base = round(float(base_price or 0), 2)
        if not self.enabled or not scope or base <= 0:
            return 0.0
        key = (scope, base)
        if key not in self._floats:
            self._floats[key] = round(random.uniform(self.float_min, self.float_max), 2)
        return self._floats[key]

    def effective_price(self, listing_scope: str, base_price: float) -> float:
        base = round(float(base_price or 0), 2)
        if base <= 0:
            return base
        return round(base + self.get_float_delta(listing_scope, base), 2)

    def get_single_price_delta(self, listing_scope: str, group_price: float) -> float:
        scope = str(listing_scope or "").strip() or "__default__"
        base = round(float(group_price or 0), 2)
        if base <= 0:
            return 0.0
        key = (scope, base)
        if key not in self._single_floats:
            self._single_floats[key] = round(
                random.uniform(self.single_float_min, self.single_float_max),
                2,
            )
        return self._single_floats[key]

    def effective_single_price(self, listing_scope: str, group_price: float) -> float:
        gp = round(float(group_price or 0), 2)
        if gp <= 0:
            return gp
        return round(gp + self.get_single_price_delta(listing_scope, gp), 2)

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "float_min": self.float_min,
            "float_max": self.float_max,
            "single_float_min": self.single_float_min,
            "single_float_max": self.single_float_max,
            "entries": [
                {"listing_scope": scope, "base_price": base, "float_delta": delta}
                for (scope, base), delta in sorted(self._floats.items())
            ],
            "single_entries": [
                {"listing_scope": scope, "group_price": base, "float_delta": delta}
                for (scope, base), delta in sorted(self._single_floats.items())
            ],
        }


def get_listing_price_float_registry() -> ListingPriceFloatRegistry:
    registry = _registry_ctx.get()
    if registry is None:
        registry = ListingPriceFloatRegistry()
        _registry_ctx.set(registry)
    return registry


def reset_listing_price_float_registry(
    *,
    float_min: float = 0.0,
    float_max: float = 5.0,
    enabled: bool = True,
    single_float_min: float = 1.01,
    single_float_max: float = 2.0,
) -> ListingPriceFloatRegistry:
    registry = ListingPriceFloatRegistry(
        float_min=float_min,
        float_max=float_max,
        enabled=enabled,
        single_float_min=single_float_min,
        single_float_max=single_float_max,
    )
    _registry_ctx.set(registry)
    return registry


def clear_listing_price_float_registry() -> None:
    _registry_ctx.set(None)
