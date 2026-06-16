import axios from 'axios'

export interface FeishuConfigOut {
  config_path: string
  app_id: string
  app_secret_masked: string
  oauth_redirect_uri: string
  oauth_scope: string
  use_user_access_token: boolean
  user_token_ready: boolean
  bitable_app_token: string
  table_id: string
  table_name: string
  dedupe_field: string
  field_names: Record<string, string>
}

export interface FeishuCheckResult {
  ok: boolean
  message: string
  token_length?: number
  auth_mode?: string
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
  access_token_length: number
  expires_in: number
  refresh_token_present: boolean
}

export interface FeishuPreviewItem {
  mapping_id: string
  account_id: string
  product_code: string
  listing_label: string
  pdd_product_id: string
  published_at: string
}

export interface FeishuPreviewResult {
  date: string
  count: number
  items: FeishuPreviewItem[]
}

export interface FeishuSyncResult {
  date: string
  table_id: string
  candidates: number
  created?: number
  would_create?: number
  skipped_existing: number
  preview?: Record<string, unknown>[]
  record_ids?: string[]
}

const http = axios.create({
  baseURL: '/api/feishu',
  timeout: 120_000,
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg =
      err.response?.data?.detail ||
      err.response?.data?.message ||
      err.message ||
      '请求失败'
    return Promise.reject(new Error(typeof msg === 'string' ? msg : JSON.stringify(msg)))
  },
)

export const feishuApi = {
  health: () => http.get('/health').then((r) => r.data),
  config: () => http.get<FeishuConfigOut>('/config').then((r) => r.data),
  oauthAuthorizeUrl: () =>
    http.get<FeishuOAuthAuthorizeResult>('/oauth/authorize-url').then((r) => r.data),
  oauthExchangeCode: (body: { code: string; state?: string; redirect_uri?: string }) =>
    http.post<FeishuOAuthExchangeResult>('/oauth/exchange-code', body).then((r) => r.data),
  check: () => http.post<FeishuCheckResult>('/check').then((r) => r.data),
  initTable: () => http.post('/init-table').then((r) => r.data),
  preview: (date: string) =>
    http.get<FeishuPreviewResult>('/preview', { params: { date } }).then((r) => r.data),
  tables: () => http.get('/tables').then((r) => r.data),
  sync: (body: { date: string; dry_run: boolean; minimal_fields: boolean }) =>
    http.post<FeishuSyncResult>('/sync', body).then((r) => r.data),
}
