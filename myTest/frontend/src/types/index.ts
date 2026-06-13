export type RunStatus = 'pending' | 'running' | 'success' | 'failed' | 'canceled' | 'needs_human' | 'skipped'

export interface HealthResponse {
  status: string
  service: string
  version: string
}

export interface ConfigSummary {
  app_name: string
  log_level: string
  assets_root: string
  excel_path: string
  llm_configured: boolean
  database_configured: boolean
  database_available: boolean
  database_error: string
  account_count: number
  enabled_account_count: number
}

export interface RuntimeConfig {
  app: {
    name: string
    log_level: string
  }
  paths: {
    assets_root: string
    profiles_root: string
    runs_root: string
  }
  browser: {
    headless: boolean
    slow_mo: number
    default_timeout_ms: number
    base_url: string
    channel: string
  }
  multi_spec: {
    excel: string
    defaults: Record<string, string>
  }
  listing: {
    category_keyword: string
    title_mode: string
  }
  delist: {
    min_created_after: string
    dry_run: boolean
    merchant_code_contains: string
    max_delist_per_run: number
    account_ids: string[]
  }
  batch: {
    max_concurrent_stores: number
    store_start_delay_min_seconds: number
    store_start_delay_max_seconds: number
  }
}

export interface Account {
  account_id: string
  enabled: boolean
  username: string
  has_password: boolean
  product_codes: string[]
}

export interface AccountDetail extends Account {
  password: string
}

export interface AccountCreatePayload {
  account_id: string
  enabled: boolean
  username: string
  password: string
  product_codes: string[]
}

export interface AccountUpdatePayload {
  enabled: boolean
  username: string
  password: string
  product_codes: string[]
}

export interface ProductSummary {
  product_code: string
  image_sets: string[]
  listing_unit_count: number
}

export interface ListingTargetOption {
  selector: string
  family_code: string
  image_set: string
  product_codes: string[]
  product_count: number
}

export interface SkuCombo {
  style_code: string
  style_name: string
  model_code: string
  model_name: string
  combo_folder: string
  preview_image: string
  inventory: string
  group_price: string
  single_price: string
}

export interface ListingUnit {
  product_code: string
  family_code: string
  image_set: string
  listing_label: string
  merchant_code: string
  root: string
  carousel_images: string[]
  detail_images: string[]
  carousel_count: number
  detail_count: number
  sku_count: number
  style_codes: string[]
  model_codes: string[]
  warnings: string[]
  skus: SkuCombo[]
}

export interface PreflightIssue {
  level: string
  message: string
  listing_label: string
}

export interface PreflightResponse {
  ok: boolean
  unit_count: number
  error_count: number
  warning_count: number
  units: ListingUnit[]
  issues: PreflightIssue[]
}

export interface PlanResponse {
  plan_summary: string
  planned_tasks: Record<string, unknown>[]
}

export interface ListingTaskResponse {
  run_id: string
  status: RunStatus
  message?: string
  result?: Record<string, unknown>
}

export interface DelistTaskResponse {
  run_id: string
  status: RunStatus
  message?: string
  result?: Record<string, unknown>
}

export interface CampaignTaskResponse {
  run_id: string
  status: RunStatus
  message?: string
  result?: Record<string, unknown>
}

export interface MarketingActivityOption {
  activity_id: string
  name: string
}

export interface MarketingActivityListResponse {
  items: MarketingActivityOption[]
}

export interface BatchRunItem {
  account_id: string
  run_id: string
  status: RunStatus
  message?: string
}

export interface BatchTaskResponse {
  batch_id: string
  status: RunStatus
  total: number
  max_concurrent_stores: number
  store_start_delay_min_seconds: number
  store_start_delay_max_seconds: number
  runs: BatchRunItem[]
  message?: string
}

export interface RunRecord {
  run_id: string
  agent: string
  account_id: string
  status: RunStatus
  phase: string
  started_at: string
  finished_at: string | null
  message: string
  listing_labels: string[]
  result: Record<string, unknown>
}

export interface RunListResponse {
  items: RunRecord[]
  total: number
  page: number
  page_size: number
}

export interface RunInterpretResponse {
  run_id: string
  interpretation: string
  llm_model: string
}

export interface QueueTask {
  task_id: string
  run_id: string
  agent: string
  account_id: string
  status: string
  scheduled_at: string
  started_at: string | null
  finished_at: string | null
  attempts: number
  max_attempts: number
  error: string
  payload: Record<string, unknown>
}

export interface QueueControl {
  scope: string
  account_id: string
  paused: boolean
  reason: string
  updated_at: string | null
}

export interface QueueStatus {
  paused: boolean
  counts: Record<string, number>
  controls: QueueControl[]
  tasks: QueueTask[]
}

export interface QueueCancelResponse {
  canceled: number
  run_ids: string[]
}

export interface FailureItem {
  item_id: string
  source_run_id: string
  account_id: string
  listing_label: string
  product_code: string
  image_set: string
  merchant_code: string
  item_status: string
  reason: string
  error: string
  retryable: boolean
  decision_status: string
  decision_note: string
  retry_run_id: string
  created_at: string | null
  updated_at: string | null
}

export interface FailureListResponse {
  items: FailureItem[]
  total: number
  page: number
  page_size: number
  summary: Record<string, number>
}

export interface FailureRetryResponse {
  total: number
  results: {
    item_id: string
    run_id: string
    status: string
    message: string
  }[]
}

export interface FailureSyncResponse {
  scanned_runs: number
  upserted_items: number
}

export interface PublishedProduct {
  mapping_id: string
  account_id: string
  source_run_id: string
  product_code: string
  family_code: string
  image_set: string
  listing_label: string
  merchant_code: string
  pdd_product_id: string
  status: string
  published_at: string | null
  created_at: string | null
  updated_at: string | null
  spec_metadata: Record<string, unknown>
}

export interface PublishedProductListResponse {
  items: PublishedProduct[]
  total: number
  page: number
  page_size: number
}

export interface PublishedProductDetailResponse {
  published: PublishedProduct
  run_result_item: Record<string, unknown>
  source_run_result: Record<string, unknown>
  unit_detail: ListingUnit | null
}

export interface PublishedProductDelistResponse {
  run_id: string
  status: RunStatus | string
  message: string
}

export interface StyleColor {
  product_code: string
  color_label: string
  source: string
  image_path: string
  image_mtime: number
  created_at: string | null
  updated_at: string | null
}

export interface StyleColorListResponse {
  items: StyleColor[]
  total: number
  page: number
  page_size: number
}

export interface StyleColorCreatePayload {
  product_code: string
  color_label: string
  image_path?: string
}

export interface StyleColorUpdatePayload {
  color_label: string
  image_path?: string | null
}

export interface ProductDetail {
  product_code: string
  image_sets: string[]
  units: ListingUnit[]
}

export interface LoginStatus {
  account_id: string
  status: string
  reason: string
  current_url: string
  checked_at: string | null
}

export interface LoginBatchCheckResponse {
  status: string
  total: number
  delay_min_seconds: number
  delay_max_seconds: number
  message: string
}

export interface AgentInfo {
  id: string
  enabled: boolean
  description: string
}
