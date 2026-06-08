import axios from 'axios'
import type {
  Account,
  AccountCreatePayload,
  AccountDetail,
  AccountUpdatePayload,
  ConfigSummary,
  HealthResponse,
  DelistTaskResponse,
  ListingTaskResponse,
  PlanResponse,
  PreflightResponse,
  ProductSummary,
  RunRecord,
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

  delist: (body: {
    account_id: string
    dry_run?: boolean
    min_created_after?: string
    merchant_code_contains?: string
    max_delist_per_run?: number
    background?: boolean
  }) => http.post<DelistTaskResponse>('/tasks/delist', body).then((r) => r.data),

  runs: (limit = 30) =>
    http.get<RunRecord[]>('/runs', { params: { limit } }).then((r) => r.data),

  run: (runId: string) => http.get<RunRecord>(`/runs/${runId}`).then((r) => r.data),

  interpretRun: (runId: string) =>
    http.post<RunInterpretResponse>(`/runs/${runId}/interpret`).then((r) => r.data),

  agents: () =>
    http.get<{ agents: { id: string; enabled: boolean; description: string }[] }>('/agents').then((r) => r.data),
}

export default http
