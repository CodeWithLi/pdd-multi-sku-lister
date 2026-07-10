"""常量与 meta 键。"""

from __future__ import annotations

META_ENABLED_KEY = "listing_per_batch_lt_traffic_activity_enabled"
META_PROMOTE_LT_SUCCESS_ONLY_KEY = "listing_per_batch_promote_lt_success_only_enabled"
META_STATE_KEY = "listing_per_batch_lt_traffic_activity"

ACCUMULATED_LT_PDD_IDS_KEY = "ltta_accumulated_lt_success_pdd_product_ids"
ACCUMULATED_LT_MAPPING_IDS_KEY = "ltta_accumulated_lt_success_mapping_ids"

PHASE_TRAFFIC = "traffic"
PHASE_CAMPAIGN = "campaign"
PHASE_DONE = "done"

STAGE_PENDING = "pending"
STAGE_SUCCESS = "success"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"
