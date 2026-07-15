"""子商品按定价档位浮动（配件成本定价模式可选）。

开启「子商品浮动」后，配件浮动不再统一 0~5，而按组合装定价档位：
- 成本 <= 0.5 元：浮动 1~1.5
- 0.5 < 成本 <= 1 元：浮动 1.5~2.5
- 1 < 成本 <= 2 元：浮动 3~4
- 成本 > 2 元：浮动 5~7

主商品浮动规则不变（仍由配件成本定价模式的 float_min/float_max 控制）。
"""

from __future__ import annotations

import random
from typing import Callable

# (成本下限, 成本上限, 浮动下限, 浮动上限) — 上限为 None 表示无上限
TIERED_ACCESSORY_FLOAT_TIERS: tuple[tuple[float, float | None, float, float], ...] = (
    (0.0, 0.5, 1.0, 1.5),
    (0.5, 1.0, 1.5, 2.5),
    (1.0, 2.0, 3.0, 4.0),
    (2.0, None, 5.0, 7.0),
)


def tiered_float_bounds_for_cost(cost: float) -> tuple[float, float]:
    """按成本返回配件浮动增量区间 (min, max)。"""
    value = round(float(cost or 0), 2)
    if value <= 0.5:
        return 1.0, 1.5
    if value <= 1.0:
        return 1.5, 2.5
    if value <= 2.0:
        return 3.0, 4.0
    return 5.0, 7.0


def draw_tiered_accessory_float_delta(cost: float) -> float:
    """返回配件浮动增量（不含成本本身）。"""
    float_min, float_max = tiered_float_bounds_for_cost(cost)
    return round(random.uniform(float_min, float_max), 2)


def tiered_accessory_float_drawer() -> Callable[[float], float]:
    """供 reconcile / 定价模块引用的配件浮动绘制函数。"""
    return draw_tiered_accessory_float_delta


def format_tiered_float_rule_summary() -> str:
    """前端提示文案。"""
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
