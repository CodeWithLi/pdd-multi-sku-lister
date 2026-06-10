import axios from 'axios'
import type {
  Account,
  AccountCreatePayload,
  AccountDetail,
  AccountUpdatePayload,
  BatchTaskResponse,
  ConfigSummary,
  HealthResponse,
  DelistTaskResponse,
  FailureListResponse,
  FailureRetryResponse,
  FailureSyncResponse,
  ListingTaskResponse,
  LoginBatchCheckResponse,
  LoginStatus,
  PlanResponse,
  PreflightResponse,
  PublishedProductListResponse,
  PublishedProductDetailResponse,
  ProductDetail,
  ProductSummary,
  QueueCancelResponse,
  QueueStatus,
  RunRecord,
  RunListResponse,
  RunInterpretResponse,
  RuntimeConfig,
} from '@/types'

const http = axios.create({
  baseURL: '/api',
  timeout: 120_000,
})

http.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg =
      err.response?.data?.detail ||
      err.response?.data?.error ||
      err.message ||
      '请求失败'
    return Promise.reject(new Error(typeof msg === 'string' ? msg : JSON.stringify(msg)))
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

  accountDetail: (accountId: string) =>
    http.get<AccountDetail>(`/config/accounts/${accountId}`).then((r) => r.data),

  createAccount: (body: AccountCreatePayload) =>
    http.post<AccountDetail>('/config/accounts', body).then((r) => r.data),

  updateAccount: (accountId: string, body: AccountUpdatePayload) =>
    http.put<AccountDetail>(`/config/accounts/${accountId}`, body).then((r) => r.data),

  deleteAccount: (accountId: string) =>
    http.delete(`/config/accounts/${accountId}`).then(() => undefined),

  products: () => http.get<ProductSummary[]>('/catalog/products').then((r) => r.data),

  productDetail: (productCode: string) =>
    http.get<ProductDetail>(`/catalog/products/${productCode}`).then((r) => r.data),

  preflight: (product_codes: string[]) =>
    http.post<PreflightResponse>('/catalog/preflight', { product_codes }).then((r) => r.data),

  plan: (message: string) =>
    http.post<PlanResponse>('/tasks/plan', { message }).then((r) => r.data),

  listing: (body: {
    account_id: string
    product_codes: string[]
    dry_run: boolean
    category_keyword: string
    background: boolean
  }) => http.post<ListingTaskResponse>('/tasks/listing', body).then((r) => r.data),

  listingBatch: (body: {
    account_ids: string[]
    product_codes: string[]
    dry_run: boolean
    category_keyword: string
    max_concurrent_stores?: number
    store_start_delay_min_seconds?: number
    store_start_delay_max_seconds?: number
  }) => http.post<BatchTaskResponse>('/tasks/listing/batch', body).then((r) => r.data),

  retryListingItem: (sourceRunId: string, body: {
    listing_label: string
    product_code?: string
    image_set?: string
    category_keyword?: string
  }) => http.post<ListingTaskResponse>(`/tasks/listing/retry-item/${sourceRunId}`, body).then((r) => r.data),

  delist: (body: {
    account_id: string
    dry_run?: boolean
    min_created_after?: string
    merchant_code_contains?: string
    max_delist_per_run?: number
    background?: boolean
  }) => http.post<DelistTaskResponse>('/tasks/delist', body).then((r) => r.data),

  delistBatch: (body: {
    account_ids: string[]
    dry_run?: boolean
    min_created_after?: string
    merchant_code_contains?: string
    max_delist_per_run?: number
    max_concurrent_stores?: number
    store_start_delay_min_seconds?: number
    store_start_delay_max_seconds?: number
  }) => http.post<BatchTaskResponse>('/tasks/delist/batch', body).then((r) => r.data),

  runs: (params: {
    page?: number
    page_size?: number
    account_id?: string
    agent?: string
    status?: string
    started_from?: string
    started_to?: string
    product_code?: string
  } = {}) => http.get<RunListResponse>('/runs', { params }).then((r) => r.data),

  run: (runId: string) => http.get<RunRecord>(`/runs/${runId}`).then((r) => r.data),

  interpretRun: (runId: string) =>
    http.post<RunInterpretResponse>(`/runs/${runId}/interpret`).then((r) => r.data),

  queueStatus: (params: {
    limit?: number
    status?: string
    account_id?: string
  } = {}) => http.get<QueueStatus>('/queue/status', { params }).then((r) => r.data),

  pauseQueue: (reason = '') =>
    http.post<QueueStatus>('/queue/pause', { reason }).then((r) => r.data),

  resumeQueue: (reason = '') =>
    http.post<QueueStatus>('/queue/resume', { reason }).then((r) => r.data),

  pauseAccountQueue: (accountId: string, reason = '') =>
    http.post<QueueStatus>(`/queue/accounts/${accountId}/pause`, { reason }).then((r) => r.data),

  resumeAccountQueue: (accountId: string, reason = '') =>
    http.post<QueueStatus>(`/queue/accounts/${accountId}/resume`, { reason }).then((r) => r.data),

  cancelQueuedTasks: (accountId = '') =>
    http.post<QueueCancelResponse>('/queue/cancel-queued', null, { params: { account_id: accountId || undefined } }).then((r) => r.data),

  failures: (params: {
    page?: number
    page_size?: number
    account_id?: string
    item_status?: string
    decision_status?: string
    product_code?: string
  } = {}) => http.get<FailureListResponse>('/failures', { params }).then((r) => r.data),

  syncFailures: (limitRuns = 1000) =>
    http.post<FailureSyncResponse>('/failures/sync', null, { params: { limit_runs: limitRuns } }).then((r) => r.data),

  markFailure: (itemId: string, body: { decision_status: string; decision_note?: string }) =>
    http.post(`/failures/${itemId}/mark`, body).then((r) => r.data),

  markFailuresBulk: (body: { item_ids: string[]; decision_status: string; decision_note?: string }) =>
    http.post('/failures/mark-bulk', body).then((r) => r.data),

  retryFailures: (body: { item_ids: string[]; category_keyword?: string }) =>
    http.post<FailureRetryResponse>('/failures/retry', body).then((r) => r.data),

  publishedProducts: (params: {
    page?: number
    page_size?: number
    account_id?: string
    product_code?: string
    pdd_product_id?: string
  } = {}) => http.get<PublishedProductListResponse>('/published-products', { params }).then((r) => r.data),

  publishedProductDetail: (mappingId: string) =>
    http.get<PublishedProductDetailResponse>(`/published-products/${mappingId}`).then((r) => r.data),

  loginStatuses: () =>
    http.get<LoginStatus[]>('/login/statuses').then((r) => r.data),

  checkLogin: (accountId: string) =>
    http.post<LoginStatus>(`/login/check/${accountId}`).then((r) => r.data),

  checkLoginBatch: (body: {
    account_ids?: string[]
    delay_min_seconds?: number
    delay_max_seconds?: number
  }) => http.post<LoginBatchCheckResponse>('/login/check-batch', body).then((r) => r.data),

  openLoginWindow: (accountId: string, keep_open_seconds = 300) =>
    http.post<LoginStatus>(`/login/open/${accountId}`, { keep_open_seconds }).then((r) => r.data),

  agents: () =>
    http.get<{ agents: { id: string; enabled: boolean; description: string }[] }>('/agents').then((r) => r.data),
}

export default http
