export type RunStatus = 'pending' | 'running' | 'success' | 'failed' | 'needs_human' | 'skipped'

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
  image_set: string
  listing_label: string
  merchant_code: string
  root: string
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

export interface RunInterpretResponse {
  run_id: string
  interpretation: string
  llm_model: string
}

export interface AgentInfo {
  id: string
  enabled: boolean
  description: string
}
