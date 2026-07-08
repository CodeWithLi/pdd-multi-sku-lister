export type InventoryDelistExecutionMode = 'parallel' | 'sequential'

export interface InventoryDelistSchedule {
  enabled: boolean
  interval_hours: number
  account_ids: string[]
  execution_mode: InventoryDelistExecutionMode
  delist_spec_code_search_enabled: boolean
  scheduler_running: boolean
  database_available: boolean
  last_scheduled_run_at: string
}

export interface AccountProductBreakdown {
  account_id: string
  on_sale_codes: string[]
  exclusive_codes: string[]
  negative_inventory_codes: string[]
  delist_candidate_codes: string[]
  inventory_by_code: Record<string, number>
  published_counts?: {
    total: number
    on_sale: number
    delisted: number
    other: number
  }
}

export interface OnSaleCodesResponse {
  ok: boolean
  account_ids: string[]
  all_on_sale_codes: string[]
  total: number
  per_account: Array<{
    account_id: string
    on_sale_codes: string[]
    count: number
  }>
}

export interface InventoryDelistPreview {
  ok: boolean
  account_ids: string[]
  requested_account_ids?: string[]
  resolved_account_ids?: string[]
  common_on_sale_codes: string[]
  all_on_sale_codes: string[]
  negative_inventory_codes: string[]
  inventory_by_code: Record<string, number>
  feishu_query_count: number
  feishu_called?: boolean
  feishu_rows_matched?: number
  feishu_force_refresh?: boolean
  feishu_error?: string
  database_available?: boolean
  test_override_enabled?: boolean
  test_overrides_applied?: Array<{
    code: string
    original_qty: number | null
    override_qty: number
    feishu_had_record?: boolean
  }>
  diagnostics?: Record<string, unknown> & { message?: string }
  per_account: AccountProductBreakdown[]
}

export interface AccountDelistTask {
  account_id: string
  status: string
  run_id: string
  candidate_codes: string[]
  target_count: number
  deleted_mapping_ids: string[]
  warnings: string[]
  error: string
}

export interface InventoryDelistJob {
  job_id: string
  status: string
  trigger: string
  created_at: string
  started_at: string
  finished_at: string
  account_ids: string[]
  execution_mode: InventoryDelistExecutionMode
  common_on_sale_codes: string[]
  negative_inventory_codes: string[]
  per_account: AccountDelistTask[]
  message: string
  error: string
}

export interface InventoryDelistRecord {
  record_id: string
  job_id: string
  run_id: string
  account_id: string
  shop_display_name: string
  product_code: string
  merchant_code: string
  mapping_id: string
  pdd_product_id: string
  erp_available_qty: number | null
  erp_original_qty: number | null
  is_test_override: boolean
  is_common_on_sale: boolean
  trigger: string
  execution_mode: InventoryDelistExecutionMode
  dry_run: boolean
  delist_status: string
  message: string
  is_relisted: boolean
  delisted_at: string
}
