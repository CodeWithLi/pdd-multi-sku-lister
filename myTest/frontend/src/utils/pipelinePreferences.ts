import type { RelistStrategy } from '@/types'

const RELIST_STRATEGY_KEY = 'pdd_agent.pipeline.relist_strategy'
const LISTING_THROTTLE_ENABLED_KEY = 'pdd_agent.pipeline.listing_throttle_enabled'
const LISTING_BATCH_SET_COUNT_KEY = 'pdd_agent.pipeline.listing_batch_set_count'
const LISTING_BATCH_INTERVAL_KEY = 'pdd_agent.pipeline.listing_batch_interval_minutes'
const LISTING_PER_BATCH_LIMITED_TIME_KEY = 'pdd_agent.pipeline.listing_per_batch_limited_time_enabled'

const VALID_RELIST_STRATEGIES = new Set<RelistStrategy>([
  'ignore',
  'delist_and_relist',
])

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
