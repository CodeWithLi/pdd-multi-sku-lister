export interface HealthResponse {
  status: string
  service: string
  version: string
  runtime_profile: string
  database: string
  database_configured: boolean
  database_available: boolean
  database_error: string
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
  database_name: string
  account_count: number
  enabled_account_count: number
}

export interface Account {
  account_id: string
  enabled: boolean
  phone: string
  username: string
  login_mode: string
  shop_display_name: string
  display_name: string
  has_password: boolean
  product_codes: string[]
}

export interface AccountDetail extends Account {
  password: string
}

export interface AccountCreatePayload {
  account_id: string
  enabled: boolean
  phone: string
  username: string
  password: string
  login_mode: string
  product_codes: string[]
}

export interface AccountUpdatePayload {
  enabled: boolean
  phone: string
  username: string
  password: string
  login_mode: string
  product_codes: string[]
}

export interface ListingTargetOption {
  selector: string
  family_code: string
  image_set: string
  product_codes: string[]
  product_count: number
}

export interface ListingTaskResponse {
  run_id: string
  status: string
  message: string
  result?: Record<string, unknown>
}

export interface RunRecord {
  run_id: string
  agent: string
  account_id: string
  status: string
  phase: string
  started_at: string
  finished_at?: string | null
  message: string
  listing_labels: string[]
  result: Record<string, unknown>
}

export interface RunListResponse {
  items: RunRecord[]
  total: number
}

export interface RuntimeConfig {
  app: { name: string; log_level: string }
  login: { sms_wait_seconds: number; auto_send_sms: boolean }
  paths: { assets_root: string; profiles_root: string; runs_root: string }
  browser: {
    headless: boolean
    slow_mo: number
    default_timeout_ms: number
    base_url: string
    channel: string
  }
  multi_spec: { excel: string; defaults: Record<string, string> }
  listing: {
    category_keyword: string
    title_mode: string
    brand_name: string
    manufacturer_name: string
    slot_alignment_test: boolean
    spec_fill_verify_test: boolean
    primary_style_first_test: boolean
    category_next_burst_demo: boolean
    accessory_cost_pricing: boolean
    accessory_tiered_float: boolean
  }
}

export interface PreflightResponse {
  units: unknown[]
  issues: Array<{ level: string; message: string; listing_label?: string }>
  ok?: boolean
}

export interface LoginStatus {
  account_id: string
  status: string
  reason: string
  current_url: string
  shop_display_name: string
  checked_at: string | null
}

export interface LoginBatchResponse {
  status: string
  total: number
  delay_min_seconds: number
  delay_max_seconds: number
  message: string
}

export interface ShopNameScrapeResult {
  account_id: string
  shop_display_name: string
  ok: boolean
  reason: string
}

export interface FeishuClearCacheResult {
  success: boolean
  cleared: string[]
  errors: string[]
  message: string
}

export interface FeishuOAuthStatus {
  authorized: boolean
  message: string
  need_oauth: boolean
  redirect_uri: string
}

export interface FeishuOAuthAuthorizeResult {
  authorize_url: string
  state: string
  redirect_uri: string
}

export interface FeishuOAuthExchangeResult {
  ok: boolean
  message: string
}
