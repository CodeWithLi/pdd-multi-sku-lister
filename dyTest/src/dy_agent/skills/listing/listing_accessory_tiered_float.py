"""子商品按成本档位浮动（配件成本定价模式可选）。"""

from __future__ import annotations

import random
from typing import Callable

TIERED_ACCESSORY_FLOAT_TIERS: tuple[tuple[float, float | None, float, float], ...] = (
    (0.0, 0.5, 1.0, 1.5),
    (0.5, 1.0, 1.5, 2.5),
    (1.0, 2.0, 3.0, 4.0),
    (2.0, None, 5.0, 7.0),
)


def tiered_float_bounds_for_cost(cost: float) -> tuple[float, float]:
    value = round(float(cost or 0), 2)
    if value <= 0.5:
        return 1.0, 1.5
    if value <= 1.0:
        return 1.5, 2.5
    if value <= 2.0:
        return 3.0, 4.0
    return 5.0, 7.0


def draw_tiered_accessory_float_delta(cost: float) -> float:
    float_min, float_max = tiered_float_bounds_for_cost(cost)
    return round(random.uniform(float_min, float_max), 2)


def tiered_accessory_float_drawer() -> Callable[[float], float]:
    return draw_tiered_accessory_float_delta


def format_tiered_float_rule_summary() -> str:
    return (
        "子商品按成本档位浮动：≤0.5 元 +1~1.5；"
        "0.5~1 元 +1.5~2.5；1~2 元 +3~4；>2 元 +5~7"
    )


__all__ = [
    "TIERED_ACCESSORY_FLOAT_TIERS",
    "draw_tiered_accessory_float_delta",
    "format_tiered_float_rule_summary",
    "tiered_accessory_float_drawer",
    "tiered_float_bounds_for_cost",
]
