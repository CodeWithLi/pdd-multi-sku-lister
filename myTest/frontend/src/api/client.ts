import axios from 'axios'
import type {
  Account,
  AccountCreatePayload,
  AccountDetail,
  AccountUpdatePayload,
  BatchTaskResponse,
  CampaignTaskResponse,
  TrafficTaskResponse,
  MarketingActivityListResponse,
  ConfigSummary,
  HealthResponse,
  IntegratedPipeline,
  IntegratedPipelineBatchResponse,
  IntegratedPipelineBatchStartPayload,
  IntegratedPipelineListResponse,
  IntegratedPipelineStartPayload,
  PipelineIssueListResponse,
  PipelineIssueReport,
  PipelineIssueSummaryResponse,
  DelistTaskResponse,
  FailureListResponse,
  FailureRetryResponse,
  FailureSyncResponse,
  ListingFailureDetailListResponse,
  ListingTaskResponse,
  ListingTargetOption,
  ListedAssetFolderListResponse,
  LoginBatchCheckResponse,
  LoginStatus,
  PlanResponse,
  PreflightResponse,
  PublishedProductListResponse,
  PublishedProductDetailResponse,
  PublishedProductDelistResponse,
  PublishedProductLookupResponse,
  PublishedProductDeleteResponse,
  PublishedProductCreateResponse,
  PublishedProductManualCreatePayload,
  StyleColor,
  StyleColorCreatePayload,
  StyleColorListResponse,
  StyleColorUpdatePayload,
  ProductDetail,
  ProductSummary,
  QueueCancelResponse,
  QueueStatus,
  RunRecord,
  RunListResponse,
  RunInterpretResponse,
  RuntimeConfig,
  FeishuBitableHealth,
  TrafficReportSchedule,
  TrafficReportScheduleUpdate,
  TrafficReportScheduleTriggerResult,
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

  listingTargets: (accountId?: string) =>
    http
      .get<ListingTargetOption[]>('/catalog/listing-targets', {
        params: accountId ? { account_id: accountId } : undefined,
      })
      .then((r) => r.data),

  listedFolders: (params?: {
    account_id?: string
    family_code?: string
    image_set?: string
    product_code?: string
    source_kind?: string
    limit?: number
  }) =>
    http.get<ListedAssetFolderListResponse>('/listed-folders', { params }).then((r) => r.data),

  productDetail: (productCode: string) =>
    http.get<ProductDetail>(`/catalog/products/${productCode}`).then((r) => r.data),

  preflight: (product_codes: string[]) =>
    http.post<PreflightResponse>('/catalog/preflight', { product_codes }).then((r) => r.data),

  plan: (message: string) =>
    http.post<PlanResponse>('/tasks/plan', { message }).then((r) => r.data),

  listing: (body: {
    account_id: string
    product_codes: string[]
    platform_listing_code?: string
    dry_run: boolean
    category_keyword: string
    background: boolean
    slot_alignment_test?: boolean
  }) => http.post<ListingTaskResponse>('/tasks/listing', body).then((r) => r.data),

  listingBatch: (body: {
    account_ids: string[]
    product_codes: string[]
    platform_listing_code?: string
    dry_run: boolean
    category_keyword: string
    max_concurrent_stores?: number
    store_start_delay_min_seconds?: number
    store_start_delay_max_seconds?: number
    slot_alignment_test?: boolean
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

  campaignMarketingActivities: () =>
    http.get<MarketingActivityListResponse>('/tasks/campaign/marketing-activities').then((r) => r.data),

  campaignMarketingActivitySearch: (body: {
    account_id: string
    activity_id: string
  }) =>
    http.post<CampaignTaskResponse>('/tasks/campaign/marketing-activity-search', body).then((r) => r.data),

  campaignMarketingActivityRegister: (body: {
    account_id: string
    activity_id: string
    pdd_product_ids: string[]
  }) =>
    http.post<CampaignTaskResponse>('/tasks/campaign/marketing-activity-register', body).then((r) => r.data),

  campaignLimitedTimeSetup: (body: {
    account_id: string
    pdd_product_ids?: string[]
    published_mapping_ids?: string[]
  }) =>
    http.post<CampaignTaskResponse>('/tasks/campaign/limited-time-setup', body).then((r) => r.data),

  trafficPromotionCreate: (body: {
    account_id: string
    pdd_product_ids: string[]
    published_mapping_ids?: string[]
  }) =>
    http.post<TrafficTaskResponse>('/tasks/traffic/promotion-create', body).then((r) => r.data),

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

  cancelRunningTasks: (accountId = '') =>
    http.post<QueueCancelResponse>('/queue/cancel-running', null, { params: { account_id: accountId || undefined } }).then((r) => r.data),

  cancelPendingTasks: (accountId = '') =>
    http.post<QueueCancelResponse>('/queue/cancel-pending', null, { params: { account_id: accountId || undefined } }).then((r) => r.data),

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

  failureDetails: (itemId: string, limit = 200) =>
    http
      .get<ListingFailureDetailListResponse>(`/failures/${itemId}/details`, { params: { limit } })
      .then((r) => r.data),

  failureDetailsByRun: (runId: string, limit = 500) =>
    http
      .get<ListingFailureDetailListResponse>(`/failures/details/by-run/${runId}`, { params: { limit } })
      .then((r) => r.data),

  publishedProducts: (params: {
    page?: number
    page_size?: number
    account_id?: string
    product_code?: string
    pdd_product_id?: string
  } = {}) => http.get<PublishedProductListResponse>('/published-products', { params }).then((r) => r.data),

  publishedProductDetail: (mappingId: string) =>
    http.get<PublishedProductDetailResponse>(`/published-products/${mappingId}`).then((r) => r.data),

  delistPublishedProduct: (mappingId: string) =>
    http.post<PublishedProductDelistResponse>(`/published-products/${mappingId}/delist`).then((r) => r.data),

  lookupPublishedProductGoods: (mappingId: string) =>
    http.post<PublishedProductLookupResponse>(`/published-products/${mappingId}/lookup-pdd-goods`).then((r) => r.data),

  deletePublishedProduct: (mappingId: string) =>
    http.delete<PublishedProductDeleteResponse>(`/published-products/${mappingId}`).then((r) => r.data),

  createManualPublishedProduct: (body: PublishedProductManualCreatePayload) =>
    http.post<PublishedProductCreateResponse>('/published-products/manual', body).then((r) => r.data),

  styleColors: (params: {
    page?: number
    page_size?: number
    product_code?: string
    color_label?: string
    source?: string
  } = {}) => http.get<StyleColorListResponse>('/style-colors', { params }).then((r) => r.data),

  styleColorDetail: (productCode: string) =>
    http.get<StyleColor>(`/style-colors/${encodeURIComponent(productCode)}`).then((r) => r.data),

  createStyleColor: (body: StyleColorCreatePayload) =>
    http.post<StyleColor>('/style-colors', body).then((r) => r.data),

  updateStyleColor: (productCode: string, body: StyleColorUpdatePayload) =>
    http.put<StyleColor>(`/style-colors/${encodeURIComponent(productCode)}`, body).then((r) => r.data),

  deleteStyleColor: (productCode: string) =>
    http.delete(`/style-colors/${encodeURIComponent(productCode)}`).then(() => undefined),

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

  startIntegratedPipeline: (body: IntegratedPipelineStartPayload) =>
    http.post<IntegratedPipeline>('/pipelines/integrated', body).then((r) => r.data),

  startIntegratedPipelineBatch: (body: IntegratedPipelineBatchStartPayload) =>
    http.post<IntegratedPipelineBatchResponse>('/pipelines/integrated/batch', body).then((r) => r.data),

  listIntegratedPipelines: (limit = 20, batchId = '') =>
    http
      .get<IntegratedPipelineListResponse>('/pipelines/integrated', {
        params: { limit, batch_id: batchId || undefined },
      })
      .then((r) => r.data),

  getIntegratedPipeline: (pipelineId: string) =>
    http.get<IntegratedPipeline>(`/pipelines/integrated/${pipelineId}`).then((r) => r.data),

  cancelIntegratedPipeline: (pipelineId: string) =>
    http.post<IntegratedPipeline>(`/pipelines/integrated/${pipelineId}/cancel`).then((r) => r.data),

  pipelineIssues: (params: {
    page?: number
    page_size?: number
    pipeline_id?: string
    batch_id?: string
    account_id?: string
    stage?: string
    severity?: string
    keyword?: string
  } = {}) => http.get<PipelineIssueListResponse>('/pipeline-issues', { params }).then((r) => r.data),

  getPipelineIssue: (issueId: string) =>
    http.get<PipelineIssueReport>(`/pipeline-issues/${issueId}`).then((r) => r.data),

  pipelineIssueSummary: (pipelineId: string) =>
    http.get<PipelineIssueSummaryResponse>(`/pipeline-issues/summary/${pipelineId}`).then((r) => r.data),

  feishuBitableHealth: () =>
    http.get<FeishuBitableHealth>('/feishu-bitable/health').then((r) => r.data),

  feishuBitableCreateApp: (body: { name: string; folder_token?: string; time_zone?: string }) =>
    http.post('/feishu-bitable/apps', body).then((r) => r.data),

  feishuBitableListTables: (appToken = '') =>
    http
      .get('/feishu-bitable/tables', {
        params: { app_token: appToken || undefined },
      })
      .then((r) => r.data),

  feishuBitableCreateTable: (body: { app_token?: string; name: string }) =>
    http.post('/feishu-bitable/tables', body).then((r) => r.data),

  feishuBitableUpdateTable: (tableId: string, body: { app_token?: string; name: string }) =>
    http.patch(`/feishu-bitable/tables/${tableId}`, body).then((r) => r.data),

  feishuBitableDeleteTable: (tableId: string, appToken = '') =>
    http
      .delete(`/feishu-bitable/tables/${tableId}`, {
        params: { app_token: appToken || undefined },
      })
      .then((r) => r.data),

  feishuBitableListFields: (tableId: string, appToken = '') =>
    http
      .get(`/feishu-bitable/tables/${tableId}/fields`, {
        params: { app_token: appToken || undefined },
      })
      .then((r) => r.data),

  feishuBitableCreateField: (body: {
    app_token?: string
    table_id: string
    field_name: string
    type: number
    property?: Record<string, unknown> | null
  }) =>
    http.post('/feishu-bitable/fields', body).then((r) => r.data),

  feishuBitableDeleteField: (fieldId: string, tableId: string, appToken = '') =>
    http
      .delete(`/feishu-bitable/fields/${fieldId}`, {
        params: { table_id: tableId, app_token: appToken || undefined },
      })
      .then((r) => r.data),

  feishuBitableListRecords: (
    tableId: string,
    params: { app_token?: string; page_size?: number; page_token?: string },
  ) => http.get(`/feishu-bitable/tables/${tableId}/records`, { params }).then((r) => r.data),

  feishuBitableBatchCreateRecords: (body: {
    app_token?: string
    table_id: string
    records: Record<string, unknown>[]
  }) => http.post('/feishu-bitable/records/batch-create', body).then((r) => r.data),

  feishuBitableBatchDeleteRecords: (body: {
    app_token?: string
    table_id: string
    record_ids: string[]
  }) => http.post('/feishu-bitable/records/batch-delete', body).then((r) => r.data),

  trafficReportSchedule: () =>
    http.get<TrafficReportSchedule>('/traffic-report-schedule').then((r) => r.data),

  updateTrafficReportSchedule: (body: TrafficReportScheduleUpdate) =>
    http.put<TrafficReportSchedule>('/traffic-report-schedule', body).then((r) => r.data),

  triggerTrafficReportSchedule: () =>
    http
      .post<TrafficReportScheduleTriggerResult>('/traffic-report-schedule/trigger')
      .then((r) => r.data),
}

export default http
