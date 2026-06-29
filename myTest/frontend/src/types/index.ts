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
    activity_schedule_jitter_max_seconds: number
  }
}

export interface Account {
  account_id: string
  enabled: boolean
  username: string
  shop_display_name?: string
  display_name?: string
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
  listed_product_codes?: string[]
  unlisted_product_codes?: string[]
  listed_count?: number
  unlisted_count?: number
  is_fully_listed?: boolean
  has_pending_listing?: boolean
  is_material_ready?: boolean
}

export interface ListedAssetFolder {
  record_id: string
  account_id: string
  folder_selector: string
  family_code: string
  image_set: string
  product_code: string
  listing_label: string
  asset_path: string
  source_run_id: string
  source_kind: string
  pipeline_id: string
  pdd_product_id: string
  listed_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ListedAssetFolderListResponse {
  items: ListedAssetFolder[]
  total: number
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

export interface MinioSyncJob {
  job_id: string
  status: 'pending' | 'running' | 'success' | 'failed' | string
  product_codes: string[]
  total_sets: number
  completed_sets: number
  current_label: string
  downloaded_files: number
  skipped_files: number
  pruned_dirs?: number
  error: string
  progress_percent: number
  started_at: number
  finished_at: number
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

export interface TrafficTaskResponse {
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

export interface RunPlatformGuardResult {
  run_id: string
  has_guard_data: boolean
  input_codes: string[]
  matched_codes: string[]
  missing_codes: string[]
  ok?: boolean
  reason: string
  error: string
  view_name: string
  view_id: string
  table_id: string
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

export interface ListingFailureDetail {
  detail_id: string
  failure_item_id: string
  source_run_id: string
  account_id: string
  listing_label: string
  product_code: string
  image_set: string
  family_code: string
  merchant_code: string
  phase: string
  step: string
  severity: string
  reason_code: string
  message: string
  error: string
  detail: Record<string, unknown>
  screenshot_path: string
  page_url: string
  created_at: string | null
}

export interface ListingFailureDetailListResponse {
  items: ListingFailureDetail[]
  total: number
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

export interface PddFailureLogWorkflow {
  field_name: string
  label: string
  source: string
  mirror_text?: string
}

export interface PddFailureLogRecord {
  record_id: string
  date: string
  merchant_code: string
  report_platform: string
  account_name: string
  record_type: string
  failure_reason: string
  publish_start: string
  publish_end: string
  duration_seconds: string
  process_completed: PddFailureLogWorkflow
  cycle_relist: string
  processor: string
  processed_at: string
  fields_raw: Record<string, unknown>
}

export interface PddFailureLogFieldMeta {
  field_id: string
  field_name: string
  type: number
  ui_type: string
}

export interface PddFailureLogListResponse {
  ok: boolean
  error?: string
  app_token?: string
  table_id?: string
  table_name?: string
  resolve_method?: string
  mirror_field_name?: string
  mirror_api_readable?: boolean
  total: number
  items: PddFailureLogRecord[]
  field_meta?: PddFailureLogFieldMeta[]
  table_name_candidates?: string[]
}

export interface PddFailureCycleRelistAction {
  at: string
  record_id: string
  merchant_code: string
  status: string
  message: string
  pipeline_id: string
}

export interface PddFailureCycleRelistWatch {
  enabled: boolean
  poll_seconds: number
  completed_statuses: string[]
  exclude_failure_reason_contains: string
  scheduler_running: boolean
  last_poll_at: string
  last_error: string
  candidate_total: number
  new_count: number
  recent_actions: PddFailureCycleRelistAction[]
}

export interface PddFailureCycleRelistWatchUpdate {
  enabled: boolean
  poll_seconds: number
  completed_statuses: string[]
  exclude_failure_reason_contains: string
}

export interface PddFailureCycleRelistTriggerResult {
  ok: boolean
  skipped?: boolean
  reason?: string
  error?: string
  record_id: string
  merchant_code?: string
  account_name?: string
  account_id?: string
  pipeline_id?: string
  product_codes?: string[]
  claim?: Record<string, unknown>
}

export interface PddFailureCycleRelistTriggerPayload {
  record_id: string
  merchant_code?: string
  account_name?: string
  report_platform?: string
}

export interface PddFailureCycleRelistClaimResult {
  ok: boolean
  claimed: boolean
  record_id: string
  reason?: string
  error?: string
  redis_claimed?: boolean
  feishu_updated?: boolean
  placeholder?: string
  redis_payload?: Record<string, unknown>
}

export interface PddFailureCycleRelistClaimPayload {
  record_id: string
  merchant_code?: string
  account_name?: string
}

export interface PddFailureCycleRelistReleasePayload {
  record_id: string
  final_value?: string
  update_feishu?: boolean
}

export interface PddFailureCycleRelistCandidate {
  record_id: string
  merchant_code: string
  account_name: string
  report_platform: string
  record_type: string
  failure_reason: string
  process_status: string
  cycle_relist: string
  processor: string
  processed_at: string
  date: string
  action_status: string
  action_message: string
  action_at: string
  pipeline_id: string
}

export interface PddFailureCycleRelistCandidateListResponse {
  ok: boolean
  error?: string
  total: number
  items: PddFailureCycleRelistCandidate[]
  new_items: PddFailureCycleRelistCandidate[]
  table_id?: string
  table_name?: string
}

export interface PddFailureCycleRelistPollResponse {
  ok: boolean
  skipped?: boolean
  reason?: string
  error?: string
  polled_at?: string
  total?: number
  new_count?: number
  new_items?: PddFailureCycleRelistCandidate[]
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
  price_sync_status: 'none' | 'specs_synced' | 'local_skus' | 'list_price' | 'detail_opened' | 'edit_opened' | 'searched' | string
  price_sync_at: string | null
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

export interface PublishedProductLookupResponse {
  run_id: string
  status: RunStatus | string
  message: string
}

export interface PublishedProductDeleteResponse {
  ok: boolean
  mapping_id: string
  message: string
}

export interface PublishedProductManualCreatePayload {
  account_id: string
  pdd_product_id: string
  product_code: string
  listing_label: string
  family_code?: string
  image_set?: string
  merchant_code?: string
  status?: string
  note?: string
  import_catalog_skus?: boolean
}

export interface PublishedProductCreateResponse {
  published: PublishedProduct
  catalog_hints: string[]
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
  shop_display_name?: string
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

export interface IntegratedPipelineStepInfo {
  key: string
  label: string
  status: string
  run_id: string
  scheduled_at: string | null
  detail: string
}

export interface IntegratedPipelineCampaignResult {
  activity_id: string
  run_id?: string
  success?: boolean
  skipped?: boolean
  error?: string
  summary?: string
}

export interface IntegratedPipelineListingUnitStatus {
  selector: string
  listing_label: string
  status: string
  status_label: string
  reason_code: string
}

export interface IntegratedPipeline {
  pipeline_id: string
  account_id: string
  status: string
  current_step: string
  product_codes: string[]
  activity_id: string
  activity_ids?: string[]
  auto_promotion: boolean
  auto_limited_time_setup?: boolean
  continue_after_limited_time_failure?: boolean
  continue_after_activity_failure?: boolean
  limited_time_outcome?: string
  limited_time_skip_reason?: string
  activity_delay_hours: number
  demo_mode: boolean
  slot_alignment_test?: boolean
  category_next_burst_demo?: boolean
  batch_id?: string
  listing_run_id: string
  campaign_run_id: string
  traffic_run_id: string
  pdd_product_ids: string[]
  mapping_ids: string[]
  scheduled_activity_at: string | null
  error: string
  campaign_outcome?: string
  campaign_skip_reason?: string
  listing_outcome?: string
  listing_skip_reason?: string
  listing_unit_statuses?: IntegratedPipelineListingUnitStatus[]
  campaign_results?: IntegratedPipelineCampaignResult[]
  steps: IntegratedPipelineStepInfo[]
  feishu_inspect_at?: string
  has_feishu_inspect?: boolean
  created_at: string | null
  updated_at: string | null
}

export interface IntegratedPipelineListResponse {
  items: IntegratedPipeline[]
  total: number
  page?: number
  page_size?: number
}

export type AutoUploadTriggerMode = 'new_product_folder' | 'append_to_product' | 'all'

export interface AutoUploadConfig {
  enabled: boolean
  trigger_mode: AutoUploadTriggerMode
  account_id: string
  activity_ids: string[]
  category_keyword: string
  auto_promotion: boolean
  auto_limited_time_setup: boolean
  continue_after_limited_time_failure: boolean
  continue_after_activity_failure: boolean
  demo_mode: boolean
  activity_delay_hours: number
  slot_alignment_test: boolean
  material_source: 'local' | 'minio'
  auto_sync_minio: boolean
}

export type RelistStrategy = 'ignore' | 'append_to_existing' | 'delist_and_relist'

export interface IntegratedPipelineStartPayload {
  account_id: string
  product_codes: string[]
  activity_id?: string
  activity_ids: string[]
  category_keyword?: string
  auto_promotion?: boolean
  auto_limited_time_setup?: boolean
  continue_after_limited_time_failure?: boolean
  continue_after_activity_failure?: boolean
  activity_delay_hours?: number
  demo_mode?: boolean
  platform_listing_code?: string
  slot_alignment_test?: boolean
  category_next_burst_demo?: boolean
  skip_listing?: boolean
  listing_skip_selectors?: string[]
  material_source?: 'local' | 'minio'
  relist_strategy?: RelistStrategy
  listing_throttle_enabled?: boolean
  listing_batch_set_count?: number
  listing_batch_interval_minutes?: number
  listing_per_batch_limited_time_enabled?: boolean
  listing_per_batch_campaign_enabled?: boolean
  delist_spec_code_search_enabled?: boolean
}

export interface IntegratedPipelineBatchStartPayload {
  activity_id?: string
  activity_ids: string[]
  account_ids: string[]
  product_codes: string[]
  category_keyword?: string
  auto_promotion?: boolean
  auto_limited_time_setup?: boolean
  continue_after_limited_time_failure?: boolean
  continue_after_activity_failure?: boolean
  activity_delay_hours?: number
  demo_mode?: boolean
  platform_listing_code?: string
  slot_alignment_test?: boolean
  category_next_burst_demo?: boolean
  store_start_delay_min_seconds?: number
  store_start_delay_max_seconds?: number
  max_concurrent_stores?: number
  skip_listing?: boolean
  listing_skip_selectors?: string[]
  material_source?: 'local' | 'minio'
  relist_strategy?: RelistStrategy
  listing_throttle_enabled?: boolean
  listing_batch_set_count?: number
  listing_batch_interval_minutes?: number
  listing_per_batch_limited_time_enabled?: boolean
  listing_per_batch_campaign_enabled?: boolean
  store_sequential_enabled?: boolean
  delist_spec_code_search_enabled?: boolean
}

export interface IntegratedPipelineBatchRunItem {
  account_id: string
  pipeline_id: string
  listing_run_id: string
  listing_scheduled_at: string
}

export interface IntegratedPipelineBatchResponse {
  batch_id: string
  total: number
  max_concurrent_stores: number
  store_start_delay_min_seconds: number
  store_start_delay_max_seconds: number
  store_sequential_enabled?: boolean
  pending_stores?: number
  pipelines: IntegratedPipelineBatchRunItem[]
  message: string
}

export interface PipelineIssueReport {
  issue_id: string
  pipeline_id: string
  batch_id: string
  account_id: string
  stage: string
  stage_label: string
  chain_step: string
  severity: 'error' | 'warning' | 'critical' | string
  reason_code: string
  title: string
  message: string
  error_text: string
  context: Record<string, unknown>
  run_id: string
  activity_id: string
  product_selector: string
  source_location: string
  created_at: string | null
}

export interface PipelineIssueListResponse {
  items: PipelineIssueReport[]
  total: number
  page: number
  page_size: number
}

export interface PipelineIssueSummaryResponse {
  pipeline_id: string
  total: number
  error: number
  warning: number
  critical: number
}

export interface FeishuBitableHealth {
  ok: boolean
  auth_mode: string
  configured: boolean
  default_app_token: string
  default_table_id?: string
  default_table_name?: string
  user_token_ready?: boolean
}

export interface FeishuOAuthStatus {
  authorized: boolean
  message: string
  need_oauth?: boolean
  redirect_uri?: string
}

export interface FeishuClearCacheResult {
  success: boolean
  cleared: string[]
  errors: string[]
  message: string
  worker_scope: string
}

export interface FeishuFailureLogSettings {
  failure_log_enabled: boolean
  failure_table_name: string
  failure_table_id: string
}

export interface FeishuInspectRowSummary {
  商品编码?: string
  颜色规格?: string
  零售综合成本?: string
  拼多多定价?: string
  PDD控价?: string
}

export interface FeishuInspectListingPriceItem {
  query_code: string
  snapshot_matched_key: string
  snapshot_has_row: boolean
  feishu_row_count: number
  feishu_rows: FeishuInspectRowSummary[]
  parsed: FeishuInspectRowSummary
  catalog_pricing: string
  catalog_control: string
  catalog_retail_cost: string
  snapshot_retail_cost: string
  pricing_reason: string
  control_reason: string
  range_aspect: string
  snapshot_range_aspect: string
  diagnose_messages: string[]
}

export interface FeishuInspectListingPricesResult {
  codes: string[]
  items: FeishuInspectListingPriceItem[]
  field_names: Record<string, string>
  table_name: string
  table_id: string
  snapshot_source: string
  snapshot_keys: string[]
  pricing_catalog_source: string
  range_catalog_source: string
  pipeline_id?: string
  saved_at?: string
  from_cache?: boolean
}

export interface FeishuBagViewRow {
  record_id: string
  merchant_code: string
  raw_code?: string
}

export interface FeishuBagViewInspectResult {
  ok: boolean
  table_name: string
  table_id: string
  view_name: string
  view_id: string
  count: number
  rows: FeishuBagViewRow[]
}

export interface FeishuOAuthAuthorizeResult {
  authorize_url: string
  state: string
  scope: string
  redirect_uri: string
}

export interface FeishuOAuthExchangeResult {
  ok: boolean
  message: string
  access_token_length?: number
  expires_in?: number
  refresh_token_present?: boolean
}

export type WecomMsgType = 'text' | 'markdown' | 'markdown_v2' | 'raw'

export interface WecomConfig {
  enabled: boolean
  webhook_url: string
  webhook_url_masked: string
  webhook_configured: boolean
  notify_on_listing_failed: boolean
  notify_on_pipeline_failed: boolean
  config_path: string
}

export interface WecomConfigUpdatePayload {
  enabled: boolean
  webhook_url: string
  notify_on_listing_failed: boolean
  notify_on_pipeline_failed: boolean
}

export interface WecomTestSendPayload {
  msgtype: WecomMsgType
  content: string
  raw_payload?: Record<string, unknown>
  use_saved_webhook?: boolean
  webhook_url?: string
}

export interface WecomTestSendResult {
  ok: boolean
  errcode: number
  errmsg: string
  payload_sent: Record<string, unknown>
  response: Record<string, unknown>
}

export interface WecomHealth {
  configured: boolean
  enabled: boolean
  webhook_configured: boolean
  config_path: string
}

export interface TrafficReportSchedule {
  enabled: boolean
  traffic_report_enabled: boolean
  schedule_hour: number
  schedule_minute: number
  schedule_time: string
  timezone: string
  account_ids: string[]
  table_name: string
  scheduler_running: boolean
  database_available: boolean
  last_run_date: string
  description: string
}

export interface TrafficReportScheduleUpdate {
  traffic_report_enabled?: boolean
  schedule_hour?: number
  schedule_minute?: number
  account_ids?: string[]
}

export interface TrafficReportScheduleTriggerResult {
  enqueued: number
  account_ids: string[]
  message: string
}
