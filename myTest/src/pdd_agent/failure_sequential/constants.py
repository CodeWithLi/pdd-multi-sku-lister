"""分阶段流水线常量。"""

from __future__ import annotations

STAGE_PENDING = "pending"
STAGE_RUNNING = "running"
STAGE_SUCCESS = "success"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"

TERMINAL_STAGES = frozenset({STAGE_SUCCESS, STAGE_FAILED, STAGE_SKIPPED})

PHASE_LISTING = "listing"
PHASE_LIMITED_TIME = "limited_time"
PHASE_ACTIVITY_618 = "activity_618"
PHASE_ACTIVITY_DISCOUNT = "activity_discount"
PHASE_PROMOTION = "promotion"
PHASE_COMPLETED = "completed"

BATCH_LISTING = "listing"
BATCH_POST_LISTING = "post_listing"
BATCH_AWAITING_ACTIVITY = "awaiting_activity"
BATCH_COMPLETED = "completed"

OVERALL_ACTIVE = "active"
OVERALL_COMPLETED = "completed"

ACTIVITY_618_ID = "20981"
ACTIVITY_DISCOUNT_ID = "21365"
