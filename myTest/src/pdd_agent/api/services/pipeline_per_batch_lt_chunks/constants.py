"""标准分批限时 — 每批上架商品再拆成多趟限时限量购。"""

from __future__ import annotations

DEFAULT_CHUNK_SIZE = 10
MAX_CHUNK_SIZE = 500

META_CHUNK_ENABLED_KEY = "per_batch_limited_time_chunk_enabled"
META_BATCH_SIZE_KEY = "per_batch_limited_time_chunk_size"
META_STATE_KEY = "listing_per_batch_lt_chunks"
META_DISPLAY_KEY = "per_batch_limited_time_chunk_display"
META_AGGREGATE_RUN_ID_KEY = "listing_per_batch_lt_chunks_aggregate_run_id"
META_RETRY_AGGREGATE_KEY = "listing_per_batch_lt_chunks_retry_aggregate"
META_BATCH_SUCCESS_COUNT_KEY = "listing_per_batch_lt_chunks_batch_success_count"
META_BATCH_TOTAL_COUNT_KEY = "listing_per_batch_lt_chunks_batch_total_count"

MODE_LISTING_BATCH = "listing_batch"
MODE_BATCH_RETRY = "batch_retry"

POST_CHUNK_DELAY_SECONDS = 5
