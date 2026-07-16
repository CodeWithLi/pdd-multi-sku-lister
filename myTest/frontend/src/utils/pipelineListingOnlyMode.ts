import type {
  IntegratedPipelineBatchStartPayload,
  IntegratedPipelineStartPayload,
} from '@/types'

const LISTING_ONLY_KEY = 'pdd_agent.pipeline.listing_only'

type PipelinePayload = IntegratedPipelineStartPayload | IntegratedPipelineBatchStartPayload

export function loadListingOnlyMode(): boolean {
  try {
    return localStorage.getItem(LISTING_ONLY_KEY) === '1'
  } catch {
    return false
  }
}

export function saveListingOnlyMode(enabled: boolean): void {
  try {
    localStorage.setItem(LISTING_ONLY_KEY, enabled ? '1' : '0')
  } catch {
    // ignore
  }
}

export function applyListingOnlyPayload<T extends PipelinePayload>(payload: T, listingOnly: boolean): T {
  if (!listingOnly) return { ...payload, listing_only: false }
  return {
    ...payload,
    activity_id: '',
    activity_ids: [],
    listing_only: true,
    auto_promotion: false,
    auto_limited_time_setup: false,
    continue_after_limited_time_failure: false,
    continue_after_activity_failure: false,
    promote_after_limited_time_failure: false,
    activity_limited_time_success_only: false,
    listing_per_batch_limited_time_enabled: false,
    listing_per_batch_campaign_enabled: false,
    listing_per_batch_lt_traffic_activity_enabled: false,
    activity_traffic_batch_enabled: false,
    batch_limited_time_auto_retry_enabled: false,
  }
}

export function listingOnlySubmitLabel(batchEnabled: boolean): string {
  return batchEnabled ? '批量启动仅上架' : '启动仅上架'
}

