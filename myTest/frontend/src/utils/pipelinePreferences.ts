import type { RelistStrategy } from '@/types'

const RELIST_STRATEGY_KEY = 'pdd_agent.pipeline.relist_strategy'
const LISTING_THROTTLE_ENABLED_KEY = 'pdd_agent.pipeline.listing_throttle_enabled'
const LISTING_BATCH_SET_COUNT_KEY = 'pdd_agent.pipeline.listing_batch_set_count'
const RANDOM_SELECT_COUNT_KEY = 'pdd_agent.pipeline.random_select_count'
const LISTING_BATCH_INTERVAL_KEY = 'pdd_agent.pipeline.listing_batch_interval_minutes'
const LISTING_PER_BATCH_LIMITED_TIME_KEY = 'pdd_agent.pipeline.listing_per_batch_limited_time_enabled'
const LISTING_PER_BATCH_CAMPAIGN_KEY = 'pdd_agent.pipeline.listing_per_batch_campaign_enabled'
const LISTING_PER_BATCH_LT_TRAFFIC_ACTIVITY_KEY =
  'pdd_agent.pipeline.listing_per_batch_lt_traffic_activity_enabled'
const LISTING_PER_BATCH_PROMOTE_LT_SUCCESS_ONLY_KEY =
  'pdd_agent.pipeline.listing_per_batch_promote_lt_success_only_enabled'
const DELIST_SPEC_CODE_SEARCH_KEY = 'pdd_agent.pipeline.delist_spec_code_search_enabled'
const ACTIVITY_LIMITED_TIME_SUCCESS_ONLY_KEY = 'pdd_agent.pipeline.activity_limited_time_success_only'
const ACTIVITY_TRAFFIC_BATCH_ENABLED_KEY = 'pdd_agent.pipeline.activity_traffic_batch_enabled'
const ACTIVITY_TRAFFIC_BATCH_SIZE_KEY = 'pdd_agent.pipeline.activity_traffic_batch_size'
const PER_BATCH_LIMITED_TIME_CHUNK_SIZE_KEY = 'pdd_agent.pipeline.per_batch_limited_time_chunk_size'
const BATCH_LIMITED_TIME_AUTO_RETRY_ENABLED_KEY =
  'pdd_agent.pipeline.batch_limited_time_auto_retry_enabled'
const BATCH_LIMITED_TIME_AUTO_RETRY_MAX_ATTEMPTS_KEY =
  'pdd_agent.pipeline.batch_limited_time_auto_retry_max_attempts'
const MINIO_MATERIAL_REFRESH_PAUSED_KEY = 'pdd_agent.minio_material_refresh_paused'
const SLOT_ALIGNMENT_TEST_KEY = 'pdd_agent.pipeline.slot_alignment_test'
const SPEC_FILL_VERIFY_TEST_KEY = 'pdd_agent.pipeline.spec_fill_verify_test'
const PRIMARY_STYLE_FIRST_TEST_KEY = 'pdd_agent.pipeline.primary_style_first_test'
const PAREN_SIZE_AS_PRODUCT_TYPE_KEY = 'pdd_agent.pipeline.paren_size_as_product_type'
const CATEGORY_NEXT_BURST_DEMO_KEY = 'pdd_agent.pipeline.category_next_burst_demo'

const VALID_RELIST_STRATEGIES = new Set<RelistStrategy>([
  'ignore',
  'delist_and_relist',
])

function loadBoolPref(key: string, defaultValue: boolean): boolean {
  try {
    const raw = localStorage.getItem(key)
    if (raw === '0') return false
    if (raw === '1') return true
  } catch {
    // ignore
  }
  return defaultValue
}

function saveBoolPref(key: string, enabled: boolean): void {
  try {
    localStorage.setItem(key, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadPipelineRelistStrategy(): RelistStrategy {
  try {
    const raw = localStorage.getItem(RELIST_STRATEGY_KEY)
    if (raw && VALID_RELIST_STRATEGIES.has(raw as RelistStrategy)) {
      return raw as RelistStrategy
    }
  } catch {
    // ignore quota / private mode
  }
  return 'ignore'
}

export function savePipelineRelistStrategy(strategy: RelistStrategy): void {
  if (strategy === 'append_to_existing') return
  try {
    localStorage.setItem(RELIST_STRATEGY_KEY, strategy)
  } catch {
    // ignore
  }
}

export function loadListingThrottleEnabled(): boolean {
  try {
    return localStorage.getItem(LISTING_THROTTLE_ENABLED_KEY) === '1'
  } catch {
    return false
  }
}

export function saveListingThrottleEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(LISTING_THROTTLE_ENABLED_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadListingBatchSetCount(): number {
  try {
    const raw = Number(localStorage.getItem(LISTING_BATCH_SET_COUNT_KEY))
    if (Number.isFinite(raw) && raw >= 1) return Math.min(100, Math.floor(raw))
  } catch {
    // ignore
  }
  return 5
}

export function saveListingBatchSetCount(count: number): void {
  try {
    localStorage.setItem(LISTING_BATCH_SET_COUNT_KEY, String(Math.max(1, Math.min(100, count))))
  } catch {
    // ignore
  }
}

export function loadRandomSelectCount(): number {
  try {
    const raw = Number(localStorage.getItem(RANDOM_SELECT_COUNT_KEY))
    if (Number.isFinite(raw) && raw >= 1) return Math.min(100, Math.floor(raw))
  } catch {
    // ignore
  }
  return 3
}

export function saveRandomSelectCount(count: number): void {
  try {
    localStorage.setItem(RANDOM_SELECT_COUNT_KEY, String(Math.max(1, Math.min(100, count))))
  } catch {
    // ignore
  }
}

export function loadListingBatchIntervalMinutes(): number {
  try {
    const raw = Number(localStorage.getItem(LISTING_BATCH_INTERVAL_KEY))
    if (Number.isFinite(raw) && raw >= 1) return Math.min(1440, Math.floor(raw))
  } catch {
    // ignore
  }
  return 30
}

export function saveListingBatchIntervalMinutes(minutes: number): void {
  try {
    localStorage.setItem(
      LISTING_BATCH_INTERVAL_KEY,
      String(Math.max(1, Math.min(1440, minutes))),
    )
  } catch {
    // ignore
  }
}

export function loadListingPerBatchLimitedTimeEnabled(): boolean {
  try {
    return localStorage.getItem(LISTING_PER_BATCH_LIMITED_TIME_KEY) === '1'
  } catch {
    return false
  }
}

export function saveListingPerBatchLimitedTimeEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(LISTING_PER_BATCH_LIMITED_TIME_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadListingPerBatchCampaignEnabled(): boolean {
  try {
    return localStorage.getItem(LISTING_PER_BATCH_CAMPAIGN_KEY) === '1'
  } catch {
    return false
  }
}

export function saveListingPerBatchCampaignEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(LISTING_PER_BATCH_CAMPAIGN_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadListingPerBatchLtTrafficActivityEnabled(): boolean {
  try {
    return localStorage.getItem(LISTING_PER_BATCH_LT_TRAFFIC_ACTIVITY_KEY) === '1'
  } catch {
    return false
  }
}

export function saveListingPerBatchLtTrafficActivityEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(LISTING_PER_BATCH_LT_TRAFFIC_ACTIVITY_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadListingPerBatchPromoteLtSuccessOnlyEnabled(): boolean {
  try {
    const raw = localStorage.getItem(LISTING_PER_BATCH_PROMOTE_LT_SUCCESS_ONLY_KEY)
    if (raw === '0') return false
    if (raw === '1') return true
  } catch {
    // ignore
  }
  return true
}

export function saveListingPerBatchPromoteLtSuccessOnlyEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(LISTING_PER_BATCH_PROMOTE_LT_SUCCESS_ONLY_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadDelistSpecCodeSearchEnabled(): boolean {
  try {
    return localStorage.getItem(DELIST_SPEC_CODE_SEARCH_KEY) === '1'
  } catch {
    return false
  }
}

export function saveDelistSpecCodeSearchEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(DELIST_SPEC_CODE_SEARCH_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadActivityLimitedTimeSuccessOnly(): boolean {
  try {
    const raw = localStorage.getItem(ACTIVITY_LIMITED_TIME_SUCCESS_ONLY_KEY)
    if (raw === '0') return false
    if (raw === '1') return true
  } catch {
    // ignore quota / private mode
  }
  return true
}

export function saveActivityLimitedTimeSuccessOnly(enabled: boolean): void {
  try {
    localStorage.setItem(ACTIVITY_LIMITED_TIME_SUCCESS_ONLY_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadActivityTrafficBatchEnabled(): boolean {
  try {
    return localStorage.getItem(ACTIVITY_TRAFFIC_BATCH_ENABLED_KEY) === '1'
  } catch {
    return false
  }
}

export function saveActivityTrafficBatchEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(ACTIVITY_TRAFFIC_BATCH_ENABLED_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadActivityTrafficBatchSize(): number {
  try {
    const raw = Number(localStorage.getItem(ACTIVITY_TRAFFIC_BATCH_SIZE_KEY))
    if (Number.isFinite(raw) && raw >= 1) return Math.min(500, Math.floor(raw))
  } catch {
    // ignore
  }
  return 10
}

export function saveActivityTrafficBatchSize(size: number): void {
  try {
    localStorage.setItem(
      ACTIVITY_TRAFFIC_BATCH_SIZE_KEY,
      String(Math.max(1, Math.min(500, size))),
    )
  } catch {
    // ignore
  }
}

export function loadPerBatchLimitedTimeChunkSize(): number {
  try {
    const raw = Number(localStorage.getItem(PER_BATCH_LIMITED_TIME_CHUNK_SIZE_KEY))
    if (Number.isFinite(raw) && raw >= 1) return Math.min(500, Math.floor(raw))
  } catch {
    // ignore
  }
  return 10
}

export function savePerBatchLimitedTimeChunkSize(size: number): void {
  try {
    localStorage.setItem(
      PER_BATCH_LIMITED_TIME_CHUNK_SIZE_KEY,
      String(Math.max(1, Math.min(500, size))),
    )
  } catch {
    // ignore
  }
}

export function loadBatchLimitedTimeAutoRetryEnabled(): boolean {
  try {
    return localStorage.getItem(BATCH_LIMITED_TIME_AUTO_RETRY_ENABLED_KEY) === '1'
  } catch {
    return false
  }
}

export function saveBatchLimitedTimeAutoRetryEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(BATCH_LIMITED_TIME_AUTO_RETRY_ENABLED_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function loadBatchLimitedTimeAutoRetryMaxAttempts(): number {
  try {
    const raw = Number(localStorage.getItem(BATCH_LIMITED_TIME_AUTO_RETRY_MAX_ATTEMPTS_KEY))
    if (Number.isFinite(raw) && raw >= 1) return Math.min(10, Math.floor(raw))
  } catch {
    // ignore
  }
  return 1
}

export function saveBatchLimitedTimeAutoRetryMaxAttempts(attempts: number): void {
  try {
    localStorage.setItem(
      BATCH_LIMITED_TIME_AUTO_RETRY_MAX_ATTEMPTS_KEY,
      String(Math.max(1, Math.min(10, attempts))),
    )
  } catch {
    // ignore
  }
}

/** MinIO 素材自动拉取（定时轮询 / RabbitMQ）是否暂停；手动「刷新」不受影响。 */
export function loadMinioMaterialRefreshPaused(): boolean {
  try {
    return localStorage.getItem(MINIO_MATERIAL_REFRESH_PAUSED_KEY) === '1'
  } catch {
    return false
  }
}

export function saveMinioMaterialRefreshPaused(paused: boolean): void {
  try {
    if (paused) {
      localStorage.setItem(MINIO_MATERIAL_REFRESH_PAUSED_KEY, '1')
    } else {
      localStorage.removeItem(MINIO_MATERIAL_REFRESH_PAUSED_KEY)
    }
  } catch {
    // ignore
  }
}

/** 高级选项：槽位对齐（试验），默认关。 */
export function loadSlotAlignmentTest(): boolean {
  return loadBoolPref(SLOT_ALIGNMENT_TEST_KEY, false)
}

export function saveSlotAlignmentTest(enabled: boolean): void {
  saveBoolPref(SLOT_ALIGNMENT_TEST_KEY, enabled)
}

/** 高级选项：规格校验填表（试验），默认开。 */
export function loadSpecFillVerifyTest(): boolean {
  return loadBoolPref(SPEC_FILL_VERIFY_TEST_KEY, true)
}

export function saveSpecFillVerifyTest(enabled: boolean): void {
  saveBoolPref(SPEC_FILL_VERIFY_TEST_KEY, enabled)
}

/** 高级选项：主款款式优先（试验），默认开。 */
export function loadPrimaryStyleFirstTest(): boolean {
  return loadBoolPref(PRIMARY_STYLE_FIRST_TEST_KEY, true)
}

export function savePrimaryStyleFirstTest(enabled: boolean): void {
  saveBoolPref(PRIMARY_STYLE_FIRST_TEST_KEY, enabled)
}

/** 高级选项：挂件(公仔)→公仔（试验），默认关。 */
export function loadParenSizeAsProductType(): boolean {
  return loadBoolPref(PAREN_SIZE_AS_PRODUCT_TYPE_KEY, false)
}

export function saveParenSizeAsProductType(enabled: boolean): void {
  saveBoolPref(PAREN_SIZE_AS_PRODUCT_TYPE_KEY, enabled)
}

/** 高级选项：分类页下一步连点（演示），默认开。 */
export function loadCategoryNextBurstDemo(): boolean {
  return loadBoolPref(CATEGORY_NEXT_BURST_DEMO_KEY, true)
}

export function saveCategoryNextBurstDemo(enabled: boolean): void {
  saveBoolPref(CATEGORY_NEXT_BURST_DEMO_KEY, enabled)
}
