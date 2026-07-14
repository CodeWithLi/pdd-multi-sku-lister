import axios from 'axios'
import type {
  Account,
  AccountCreatePayload,
  AccountDetail,
  AccountUpdatePayload,
  ConfigSummary,
  FeishuClearCacheResult,
  FeishuOAuthAuthorizeResult,
  FeishuOAuthExchangeResult,
  FeishuOAuthStatus,
  HealthResponse,
  ListingTargetOption,
  ListingTaskResponse,
  LoginBatchResponse,
  LoginStatus,
  PreflightResponse,
  RunListResponse,
  RunRecord,
  RuntimeConfig,
  ShopNameScrapeResult,
} from '@/types'

const http = axios.create({ baseURL: '/api', timeout: 120_000 })

http.interceptors.response.use(
  (resp) => resp,
  (err) => {
    const detail = err?.response?.data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg).join('; ')
          : err.message
    return Promise.reject(new Error(message || '请求失败'))
  },
)

export const api = {
  health: () => http.get<HealthResponse>('/health').then((r) => r.data),
  configSummary: () => http.get<ConfigSummary>('/config/summary').then((r) => r.data),
  runtimeConfig: () => http.get<RuntimeConfig>('/config/runtime').then((r) => r.data),
  updateRuntimeConfig: (body: RuntimeConfig) =>
    http.put<RuntimeConfig>('/config/runtime', body).then((r) => r.data),
  accounts: (enabledOnly = false) =>
    http
      .get<Account[]>('/config/accounts', { params: { enabled_only: enabledOnly } })
      .then((r) => r.data),
  accountDetail: (id: string) =>
    http.get<AccountDetail>(`/config/accounts/${id}`).then((r) => r.data),
  createAccount: (body: AccountCreatePayload) =>
    http.post<AccountDetail>('/config/accounts', body).then((r) => r.data),
  updateAccount: (id: string, body: AccountUpdatePayload) =>
    http.put<AccountDetail>(`/config/accounts/${id}`, body).then((r) => r.data),
  deleteAccount: (id: string) => http.delete(`/config/accounts/${id}`),
  listingTargets: (materialSource: 'local' | 'minio' = 'local') =>
    http
      .get<ListingTargetOption[]>('/catalog/listing-targets', {
        params: { material_source: materialSource },
      })
      .then((r) => r.data),
  minioHealth: () =>
    http
      .get<{
        configured: boolean
        available: boolean
        endpoint?: string
        bucket?: string
        categories?: string[]
        prefix?: string
        refresh_mode?: 'poll' | 'rabbitmq'
        listing_poll_seconds?: number
        object_sample_found?: boolean
        alist_url?: string
        console_url?: string
        error?: string
      }>('/catalog/minio/health')
      .then((r) => r.data),
  preflight: (product_codes: string[], material_source: 'local' | 'minio' = 'local') =>
    http
      .post<PreflightResponse>('/catalog/preflight', { product_codes, material_source })
      .then((r) => r.data),
  createListing: (body: Record<string, unknown>) =>
    http.post<ListingTaskResponse>('/tasks/listing', body).then((r) => r.data),
  runs: (params?: Record<string, unknown>) =>
    http.get<RunListResponse>('/runs', { params }).then((r) => r.data),
  run: (runId: string) => http.get<RunRecord>(`/runs/${runId}`).then((r) => r.data),
  loginStatuses: (enabledOnly = true) =>
    http.get<LoginStatus[]>('/login/statuses', { params: { enabled_only: enabledOnly } }).then((r) => r.data),
  checkLogin: (accountId: string) =>
    http.post<LoginStatus>(`/login/check/${accountId}`).then((r) => r.data),
  checkLoginBatch: (body: Record<string, unknown>) =>
    http.post<LoginBatchResponse>('/login/check-batch', body).then((r) => r.data),
  scrapeShopName: (accountId: string) =>
    http.post<ShopNameScrapeResult>(`/login/scrape-shop-name/${accountId}`).then((r) => r.data),
  scrapeShopNamesBatch: (body: Record<string, unknown>) =>
    http.post<LoginBatchResponse>('/login/scrape-shop-names-batch', body).then((r) => r.data),
  openLoginWindow: (accountId: string, keepOpenSeconds = 300) =>
    http.post<LoginStatus>(`/login/open/${accountId}`, { keep_open_seconds: keepOpenSeconds }).then((r) => r.data),

  feishuClearCache: () =>
    http.post<FeishuClearCacheResult>('/feishu/clear-cache').then((r) => r.data),

  feishuOAuthStatus: () =>
    http.get<FeishuOAuthStatus>('/feishu/oauth/status').then((r) => r.data),

  feishuOAuthAuthorizeUrl: () =>
    http.get<FeishuOAuthAuthorizeResult>('/feishu/oauth/authorize-url').then((r) => r.data),

  feishuOAuthExchangeCode: (body: { code: string; state?: string; redirect_uri?: string }) =>
    http.post<FeishuOAuthExchangeResult>('/feishu/oauth/exchange-code', body).then((r) => r.data),
}
