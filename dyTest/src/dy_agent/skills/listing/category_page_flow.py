"""发布页分类等待策略（对齐 PDD category_page_flow，供后续多页面复用）。"""

from __future__ import annotations

import random
from typing import Literal

CategoryPageMode = Literal["direct_next", "render_wait", "manual_picker"]

CATEGORY_RENDER_WAIT_OPTIONS = (20, 25, 30, 35, 40, 45)
DEFAULT_SIMPLE_RENDER_WAIT = 10


def random_category_render_wait_seconds() -> int:
    return random.choice(CATEGORY_RENDER_WAIT_OPTIONS)


def resolve_category_render_wait(*, burst_demo: bool) -> int:
    if burst_demo:
        return random_category_render_wait_seconds()
    return DEFAULT_SIMPLE_RENDER_WAIT
