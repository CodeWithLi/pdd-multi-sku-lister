import axios from 'axios'
import type {
  Account,
  AccountCreatePayload,
  AccountDetail,
  AccountUpdatePayload,
  AutoUploadConfig,
  BatchTaskResponse,
  CampaignTaskResponse,
  CommerceDispatchResult,
  CommerceIntentBatchCancelResult,
  CommerceIntentCancelResult,
  CommerceOverview,
  CommerceResetResult,
  CommerceAccountResetResult,
  TrafficTaskResponse,
  MarketingActivityListResponse,
  ConfigSummary,
  HealthResponse,
  IntegratedPipeline,
  IntegratedPipelineBatchProductStageListResponse,
  IntegratedPipelineBatchResponse,
  IntegratedPipelineBatchStartPayload,
  IntegratedPipelineListResponse,
  IntegratedPipelineStartPayload,
  PipelineSubmitAiTitleConfig,
  PipelineSubmitAiTitleTestPayload,
  PipelineSubmitAiTitleTestResult,
  PipelineLateRetryStartResponse,
  PipelineBatchLimitedTimeRetryStartResponse,
  PipelineIssueListResponse,
  PipelineIssueReport,
  PipelineIssueSummaryResponse,
  DelistTaskResponse,
  FailureListResponse,
  FailureRetryResponse,
  FailureSyncResponse,
  PddFailureLogListResponse,
  PddFailureCycleRelistWatch,
  PddFailureCycleRelistWatchUpdate,
  PddFailureCycleRelistDismissBlockerResult,
  FailureSequentialJobListResponse,
  FailureSequentialResetStuckResponse,
  FailureSequentialStuckListResponse,
  PddFailureCycleRelistCandidateListResponse,
  PddFailureCycleRelistPollResponse,
  PddFailureCycleRelistPollLogListResponse,
  DailyCycleRelistRecordListResponse,
  DailyCycleRelistSummaryResponse,
  DailyInventoryDelistRecordListResponse,
  DailyInventoryDelistSummaryResponse,
  DailyListingRecordListResponse,
  DailyListingSummaryResponse,
  DailyPipelineListingSkipRecordListResponse,
  DailyPipelineListingSkipSummaryResponse,
  PddFailureCycleRelistTriggerResult,
  PddFailureCycleRelistTriggerPayload,
  PddFailureCycleRelistClaimResult,
  PddFailureCycleRelistClaimPayload,
  PddFailureCycleRelistReleasePayload,
  ListingFailureDetailListResponse,
  ListingTaskResponse,
  ListingTargetOption,
  ListedAssetFolderListResponse,
  LoginBatchCheckResponse,
  LoginStatus,
  PlanResponse,
  MinioSyncJob,
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
  ListingProductAttributeBatchUpdatePayload,
  ListingProductAttributeListResponse,
  ProductDetail,
  ProductSummary,
  QueueCancelResponse,
  QueueStatus,
  RunRecord,
  RunListResponse,
  RunInterpretResponse,
  RunPlatformGuardResult,
  RuntimeConfig,
  FeishuBitableHealth,
  FeishuClearCacheResult,
  FeishuFailureLogSettings,
  FeishuInspectListingPricesResult,
  FeishuBagViewInspectResult,
  FeishuOAuthAuthorizeResult,
  FeishuOAuthExchangeResult,
  FeishuOAuthStatus,
  TrafficReportSchedule,
  TrafficReportScheduleUpdate,
  TrafficReportScheduleTriggerResult,
  WecomConfig,
  WecomConfigUpdatePayload,
  WecomDailyContent,
  WecomDailyContentUpdatePayload,
  WecomDailyPreviewSavePayload,
  WecomDailyReportPlatform,
  WecomDailyReportPreview,
  WecomStoreProgressPreview,
  WecomInProgressDraft,
  WecomDailyReportLogDetail,
  WecomDailyReportLogListResponse,
  WecomDailyReportTriggerPayload,
  WecomDailyReportTriggerResult,
  WecomHealth,
  WecomTestSendPayload,
  WecomTestSendResult,
} from '@/types'

const DEFAULT_TIMEOUT_MS = 120_000

const http = axios.create({
  baseURL: '/api',
  timeout: DEFAULT_TIMEOUT_MS,
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

  products: (materialSource: 'local' | 'minio' = 'local') =>
    http
      .get<ProductSummary[]>('/catalog/products', { params: { material_source: materialSource } })
      .then((r) => r.data),

  listingTargets: (accountId?: string, materialSource: 'local' | 'minio' = 'local') =>
    http
      .get<ListingTargetOption[]>('/catalog/listing-targets', {
        params: {
          ...(accountId ? { account_id: accountId } : {}),
          material_source: materialSource,
        },
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
        upload_categories?: string[]
        alist?: {
          configured?: boolean
          available?: boolean
          error?: string
        }
        cache_root?: string
        error?: string
        rabbitmq?: {
          enabled?: boolean
          running?: boolean
          refresh_mode?: string
          queue?: string
          host?: string
          last_error?: string
        }
      }>('/catalog/minio/health')
      .then((r) => r.data),

  updateMinioRefreshMode: (refresh_mode: 'poll' | 'rabbitmq') =>
    http
      .put<{
        refresh_mode: 'poll' | 'rabbitmq'
        listing_poll_seconds: number
        rabbitmq: Record<string, unknown>
      }>('/catalog/minio/refresh-mode', { refresh_mode })
      .then((r) => r.data),

  minioRabbitmqQueues: () =>
    http
      .get<{
        available: boolean
        method: string
        configured_queue?: string
        suggested_queue?: string
        management_error?: string
        amqp?: { available?: boolean; error?: string }
        queues: Array<{
          name: string
          messages?: number
          messages_ready?: number
          consumers?: number
        }>
      }>('/catalog/minio/rabbitmq/queues')
      .then((r) => r.data),

  saveMinioRabbitmqQueue: (queue: string) =>
    http
      .put<{ queue: string; rabbitmq: Record<string, unknown> }>('/catalog/minio/rabbitmq/queue', {
        queue,
      })
      .then((r) => r.data),

  minioRabbitmqRecent: (limit = 20) =>
    http
      .get<{
        batches?: Array<Record<string, unknown>>
        events?: Array<Record<string, unknown>>
        consumer?: Record<string, unknown>
      }>('/catalog/minio/rabbitmq/recent', { params: { limit } })
      .then((r) => r.data),

  peekMinioRabbitmq: (queue = '') =>
    http
      .post<{ queue: string; found: boolean; body_preview?: string; requeued?: boolean }>(
        '/catalog/minio/rabbitmq/peek',
        null,
        { params: queue ? { queue } : {} },
      )
      .then((r) => r.data),

  minioRabbitmqBindings: (queue = '') =>
    http
      .get<{
        queue: string
        available: boolean
        minio_events_bound?: boolean
        expected_exchange?: string
        expected_routing_key?: string
        bindings?: Array<{ exchange: string; routing_key: string; destination: string }>
        error?: string
      }>('/catalog/minio/rabbitmq/bindings', { params: queue ? { queue } : {} })
      .then((r) => r.data),

  ensureMinioRabbitmqBinding: (params?: { queue?: string; exchange?: string; routing_key?: string }) =>
    http
      .post<{
        queue: string
        exchange: string
        routing_key: string
        bound: boolean
        bindings?: {
          minio_events_bound?: boolean
          bindings?: Array<{ exchange: string; routing_key: string }>
        }
        rabbitmq?: Record<string, unknown>
      }>('/catalog/minio/rabbitmq/ensure-binding', null, { params: params || {} })
      .then((r) => r.data),

  uploadMinioFolder: (formData: FormData) =>
    http
      .post<{
        category: string
        folder_name: string
        bucket: string
        upload_count: number
        object_keys: string[]
        skipped: string[]
        upload_method: string
        flow?: string
        recent_events?: Array<Record<string, unknown>>
        consumer?: Record<string, unknown>
        local_process?: {
          indexed?: number
          auto_pipeline?: {
            triggered?: boolean
            reason?: string
            reason_label?: string
            product_codes?: string[]
            group_change_types?: string[]
          }
        }
      }>('/catalog/minio/upload-folder', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 600_000,
      })
      .then((r) => r.data),

  uploadMinioTestSet: (body: {
    family_code?: string
    image_set?: string
    product_code?: string
    category?: string
    image_numbers?: number[]
    upload_method?: 'alist' | 'minio'
    publish_rabbitmq?: boolean
    process_local?: boolean
  }) =>
    http
      .post<{
        bucket: string
        object_keys: string[]
        upload_count: number
        upload_method: 'alist' | 'minio'
        alist_paths?: string[]
        flow?: string
        rabbitmq_published: number
        rabbitmq_queue: string
        selector?: string
        recent_events?: Array<Record<string, unknown>>
        consumer?: Record<string, unknown>
      }>('/catalog/minio/test-upload', body)
      .then((r) => r.data),

  deleteMinioImageSet: (body: {
    selector?: string
    family_code?: string
    image_set?: string
    sync_alist?: boolean
    clear_local_cache?: boolean
  }) =>
    http
      .delete<{
        selector: string
        family_code: string
        image_set: string
        object_prefix: string
        deleted_object_count: number
        alist_deleted: boolean
        alist_virtual_path: string
        local_cache_cleared: boolean
        index_removed: boolean
        summary: string
      }>('/catalog/minio/image-set', { data: body })
      .then((r) => r.data),

  deleteMinioProductFolder: (body: {
    selector?: string
    family_code?: string
    image_set?: string
    product_code?: string
    sync_alist?: boolean
    clear_local_cache?: boolean
  }) =>
    http
      .delete<{
        selector: string
        family_code: string
        image_set: string
        product_code: string
        object_prefix: string
        deleted_object_count: number
        alist_deleted: boolean
        alist_virtual_path: string
        local_cache_cleared: boolean
        index_updated: boolean
        image_set_removed: boolean
        family_folder_removed: boolean
        summary: string
      }>('/catalog/minio/product-folder', { data: body })
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

  preflight: (product_codes: string[], materialSource: 'local' | 'minio' = 'local') =>
    http
      .post<PreflightResponse>('/catalog/preflight', {
        product_codes,
        material_source: materialSource,
      })
      .then((r) => r.data),

  startMinioSync: (product_codes: string[]) =>
    http.post<MinioSyncJob>('/catalog/minio/sync', { product_codes }).then((r) => r.data),

  getMinioSyncStatus: (jobId: string) =>
    http.get<MinioSyncJob>(`/catalog/minio/sync/${jobId}`).then((r) => r.data),

  getActiveMinioSync: () =>
    http.get<MinioSyncJob | null>('/catalog/minio/sync/active').then((r) => r.data),

  async waitMinioSync(
    jobId: string,
    onProgress?: (job: MinioSyncJob) => void,
    intervalMs = 1500,
  ): Promise<MinioSyncJob> {
    while (true) {
      const job = await this.getMinioSyncStatus(jobId)
      onProgress?.(job)
      if (job.status === 'success') return job
      if (job.status === 'failed') {
        throw new Error(job.error || 'MinIO 同步失败')
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs))
    }
  },

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
    material_source?: 'local' | 'minio'
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
    material_source?: 'local' | 'minio'
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

  runPlatformGuard: (runId: string) =>
    http.get<RunPlatformGuardResult>(`/runs/${runId}/platform-guard`).then((r) => r.data),

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

  listingProductAttributes: (params: { enabled_only?: boolean } = {}) =>
    http
      .get<ListingProductAttributeListResponse>('/listing-product-attributes', { params })
      .then((r) => r.data),

  updateListingProductAttributes: (body: ListingProductAttributeBatchUpdatePayload) =>
    http
      .put<ListingProductAttributeListResponse>('/listing-product-attributes/batch', body)
      .then((r) => r.data),

  loginStatuses: () =>
    http.get<LoginStatus[]>('/login/statuses').then((r) => r.data),

  checkLogin: (accountId: string) =>
    http.post<LoginStatus>(`/login/check/${accountId}`).then((r) => r.data),

  checkLoginBatch: (body: {
    account_ids?: string[]
    delay_min_seconds?: number
    delay_max_seconds?: number
  }) => http.post<LoginBatchCheckResponse>('/login/check-batch', body).then((r) => r.data),

  scrapeShopNamesBatch: (body: {
    account_ids?: string[]
    delay_min_seconds?: number
    delay_max_seconds?: number
  }) => http.post<LoginBatchCheckResponse>('/login/scrape-shop-names-batch', body).then((r) => r.data),

  scrapeShopName: (accountId: string) =>
    http.post<{ account_id: string; shop_display_name: string; ok: boolean; reason: string }>(
      `/login/scrape-shop-name/${accountId}`,
    ).then((r) => r.data),

  openLoginWindow: (accountId: string, keep_open_seconds = 300) =>
    http.post<LoginStatus>(`/login/open/${accountId}`, { keep_open_seconds }).then((r) => r.data),

  agents: () =>
    http.get<{ agents: { id: string; enabled: boolean; description: string }[] }>('/agents').then((r) => r.data),

  startIntegratedPipeline: (body: IntegratedPipelineStartPayload) =>
    http.post<IntegratedPipeline>('/pipelines/integrated', body).then((r) => r.data),

  startIntegratedPipelineBatch: (body: IntegratedPipelineBatchStartPayload) =>
    http.post<IntegratedPipelineBatchResponse>('/pipelines/integrated/batch', body).then((r) => r.data),

  listIntegratedPipelines: (params: { page?: number; page_size?: number; batch_id?: string } = {}) =>
    http
      .get<IntegratedPipelineListResponse>('/pipelines/integrated', {
        params: {
          page: params.page ?? 1,
          page_size: params.page_size ?? 10,
          batch_id: params.batch_id || undefined,
        },
      })
      .then((r) => r.data),

  getIntegratedPipeline: (pipelineId: string) =>
    http.get<IntegratedPipeline>(`/pipelines/integrated/${pipelineId}`).then((r) => r.data),

  getIntegratedPipelineBatchProductStages: (pipelineId: string, batchIndex?: number) =>
    http
      .get<IntegratedPipelineBatchProductStageListResponse>(
        `/pipelines/integrated/${pipelineId}/batch-product-stages`,
        { params: batchIndex != null ? { batch_index: batchIndex } : undefined },
      )
      .then((r) => r.data),

  cancelIntegratedPipeline: (pipelineId: string) =>
    http.post<IntegratedPipeline>(`/pipelines/integrated/${pipelineId}/cancel`).then((r) => r.data),

  lateRetryFailedPipeline: (
    pipelineId: string,
    body: { selectors?: string[]; deadline_buffer_minutes?: number } = {},
  ) =>
    http
      .post<PipelineLateRetryStartResponse>(`/pipelines/integrated/${pipelineId}/late-retry-failed`, body)
      .then((r) => r.data),

  startBatchLimitedTimeRetry: (pipelineId: string, batchIndex: number) =>
    http
      .post<PipelineBatchLimitedTimeRetryStartResponse>(
        `/pipelines/integrated/${pipelineId}/batch-limited-time-retry`,
        { batch_index: batchIndex },
      )
      .then((r) => r.data),

  updatePerBatchLtChunkSettings: (
    pipelineId: string,
    body: { enabled?: boolean; chunk_size?: number },
  ) =>
    http
      .put<{
        supported: boolean
        enabled: boolean
        chunk_size: number
        display: string
        sequence_active: boolean
      }>(`/pipelines/integrated/${pipelineId}/per-batch-lt-chunks`, body)
      .then((r) => r.data),

  getPipelineExcelFallback: () =>
    http.get<{ enabled: boolean }>('/pipelines/integrated/excel-fallback').then((r) => r.data),

  updatePipelineExcelFallback: (enabled: boolean) =>
    http
      .put<{ enabled: boolean }>('/pipelines/integrated/excel-fallback', { enabled })
      .then((r) => r.data),

  getPipelineAccessoryCostPricing: () =>
    http
      .get<{ enabled: boolean; float_min: number; float_max: number }>(
        '/pipelines/integrated/accessory-cost-pricing',
      )
      .then((r) => r.data),

  updatePipelineAccessoryCostPricing: (enabled: boolean) =>
    http
      .put<{ enabled: boolean; float_min: number; float_max: number }>(
        '/pipelines/integrated/accessory-cost-pricing',
        { enabled },
      )
      .then((r) => r.data),

  getPipelineAccessoryTieredFloat: () =>
    http.get<{ enabled: boolean }>('/pipelines/integrated/accessory-tiered-float').then((r) => r.data),

  updatePipelineAccessoryTieredFloat: (enabled: boolean) =>
    http
      .put<{ enabled: boolean }>('/pipelines/integrated/accessory-tiered-float', { enabled })
      .then((r) => r.data),

  getPipelineSubmitAiTitle: () =>
    http
      .get<PipelineSubmitAiTitleConfig>('/pipelines/integrated/submit-ai-title')
      .then((r) => r.data),

  updatePipelineSubmitAiTitle: (body: Partial<PipelineSubmitAiTitleConfig> & { api_key?: string }) =>
    http
      .put<PipelineSubmitAiTitleConfig>('/pipelines/integrated/submit-ai-title', body)
      .then((r) => r.data),

  testPipelineSubmitAiTitle: (body: PipelineSubmitAiTitleTestPayload) =>
    http
      .post<PipelineSubmitAiTitleTestResult>('/pipelines/integrated/submit-ai-title/test', body, {
        timeout: 300_000,
      })
      .then((r) => r.data),

  getPipelineLogSpecSkuRows: () =>
    http.get<{ enabled: boolean }>('/pipelines/integrated/log-spec-sku-rows').then((r) => r.data),

  updatePipelineLogSpecSkuRows: (enabled: boolean) =>
    http
      .put<{ enabled: boolean }>('/pipelines/integrated/log-spec-sku-rows', { enabled })
      .then((r) => r.data),

  getPipelinePlatformSkipDedupe: () =>
    http
      .get<{
        enabled: boolean
        sync_seconds: number
        code_count: number
        updated_at: string
        redis_available: boolean
        last_sync_at: string
        last_error: string
      }>('/pipelines/integrated/platform-skip-dedupe')
      .then((r) => r.data),

  updatePipelinePlatformSkipDedupe: (enabled: boolean) =>
    http
      .put<{
        enabled: boolean
        sync_seconds: number
        code_count: number
        updated_at: string
        redis_available: boolean
        last_sync_at: string
        last_error: string
      }>('/pipelines/integrated/platform-skip-dedupe', { enabled })
      .then((r) => r.data),

  syncPipelinePlatformSkipDedupe: () =>
    http
      .post<{
        enabled: boolean
        sync_seconds: number
        code_count: number
        updated_at: string
        redis_available: boolean
        last_sync_at: string
        last_error: string
      }>('/pipelines/integrated/platform-skip-dedupe/sync')
      .then((r) => r.data),

  getAutoUploadConfig: () =>
    http.get<AutoUploadConfig>('/pipelines/auto-upload-config').then((r) => r.data),

  updateAutoUploadConfig: (body: AutoUploadConfig) =>
    http.put<AutoUploadConfig>('/pipelines/auto-upload-config', body).then((r) => r.data),

  commerceOverview: () => http.get<CommerceOverview>('/commerce/overview').then((r) => r.data),

  dispatchCommerceAccount: (accountId: string) =>
    http.post<CommerceDispatchResult>(`/commerce/dispatch/${accountId}`).then((r) => r.data),

  dispatchCommerceAll: (limit = 20) =>
    http
      .post<{ count: number; items: CommerceDispatchResult[]; nudged?: number; synced?: number }>(
        '/commerce/dispatch',
        null,
        { params: { limit } },
      )
      .then((r) => r.data),

  cancelCommerceIntent: (intentId: string) =>
    http.post<CommerceIntentCancelResult>(`/commerce/intents/${intentId}/cancel`).then((r) => r.data),

  cancelCommerceIntents: (body: { intent_ids?: string[]; account_id?: string; all_pending?: boolean } = {}) =>
    http.post<CommerceIntentBatchCancelResult>('/commerce/intents/cancel', body).then((r) => r.data),

  resetCommerceAccount: (
    accountId: string,
    params: { cancel_pipelines?: boolean; cancel_intents?: boolean; clear_lifecycle?: boolean } = {},
  ) =>
    http
      .post<CommerceAccountResetResult>(`/commerce/reset/${accountId}`, null, { params })
      .then((r) => r.data),

  resetCommerceAll: (body: {
    account_ids?: string[]
    all_accounts?: boolean
    cancel_pipelines?: boolean
    cancel_intents?: boolean
    clear_lifecycle?: boolean
  } = {}) => http.post<CommerceResetResult>('/commerce/reset', body).then((r) => r.data),

  reconcileCommerce: (dispatchLimit = 30) =>
    http
      .post<{ nudged: number; synced: number; dispatched_count: number; dispatched: CommerceDispatchResult[] }>(
        '/commerce/reconcile',
        null,
        { params: { dispatch_limit: dispatchLimit } },
      )
      .then((r) => r.data),

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

  feishuClearCache: () =>
    http.post<FeishuClearCacheResult>('/feishu/clear-cache').then((r) => r.data),

  feishuFailureLogSettings: () =>
    http.get<FeishuFailureLogSettings>('/feishu/failure-log-settings').then((r) => r.data),

  updateFeishuFailureLogSettings: (body: { failure_log_enabled: boolean }) =>
    http.put<FeishuFailureLogSettings>('/feishu/failure-log-settings', body).then((r) => r.data),

  feishuInspectListingPrices: (codes: string[], forceRefresh = true, pipelineId = '') =>
    http
      .post<FeishuInspectListingPricesResult>('/feishu/inspect-listing-prices', {
        codes,
        force_refresh: forceRefresh,
        pipeline_id: pipelineId || undefined,
      })
      .then((r) => r.data),

  feishuInspectPriceCompareBagView: (limit = 30) =>
    http
      .get<FeishuBagViewInspectResult>('/feishu/inspect-price-compare-bag-view', { params: { limit } })
      .then((r) => r.data),

  getPipelineFeishuInspect: (pipelineId: string, refresh = false) =>
    http
      .get<FeishuInspectListingPricesResult>(`/pipelines/integrated/${pipelineId}/feishu-inspect`, {
        params: { refresh },
      })
      .then((r) => r.data),

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

  feishuOAuthStatus: () =>
    http.get<FeishuOAuthStatus>('/feishu/oauth/status').then((r) => r.data),

  feishuOAuthAuthorizeUrl: () =>
    http.get<FeishuOAuthAuthorizeResult>('/feishu/oauth/authorize-url').then((r) => r.data),

  feishuOAuthExchangeCode: (body: { code: string; state?: string; redirect_uri?: string }) =>
    http.post<FeishuOAuthExchangeResult>('/feishu/oauth/exchange-code', body).then((r) => r.data),

  trafficReportSchedule: () =>
    http.get<TrafficReportSchedule>('/traffic-report-schedule').then((r) => r.data),

  updateTrafficReportSchedule: (body: TrafficReportScheduleUpdate) =>
    http.put<TrafficReportSchedule>('/traffic-report-schedule', body).then((r) => r.data),

  triggerTrafficReportSchedule: () =>
    http
      .post<TrafficReportScheduleTriggerResult>('/traffic-report-schedule/trigger')
      .then((r) => r.data),

  pddFailureLogs: (params?: { limit?: number }) =>
    http
      .get<PddFailureLogListResponse>('/pdd-failure-logs', { params })
      .then((r) => r.data),

  pddFailureCycleRelistWatch: () =>
    http
      .get<PddFailureCycleRelistWatch>('/pdd-failure-logs/cycle-relist/watch')
      .then((r) => r.data),

  updatePddFailureCycleRelistWatch: (body: PddFailureCycleRelistWatchUpdate) =>
    http
      .put<PddFailureCycleRelistWatch>('/pdd-failure-logs/cycle-relist/watch', body)
      .then((r) => r.data),

  dismissPddFailureCycleRelistBlocker: (body: { pipeline_id?: string } = {}) =>
    http
      .post<PddFailureCycleRelistDismissBlockerResult>(
        '/pdd-failure-logs/cycle-relist/dismiss-blocker',
        body,
      )
      .then((r) => r.data),

  pddFailureSequentialJobs: (params?: { limit?: number }) =>
    http
      .get<FailureSequentialJobListResponse>('/pdd-failure-logs/cycle-relist/sequential/jobs', {
        params,
      })
      .then((r) => r.data),

  pddFailureSequentialStuckJobs: (params?: { limit?: number }) =>
    http
      .get<FailureSequentialStuckListResponse>('/pdd-failure-logs/cycle-relist/sequential/stuck', {
        params,
      })
      .then((r) => r.data),

  resetPddFailureSequentialStuckJobs: (params?: { limit?: number }) =>
    http
      .post<FailureSequentialResetStuckResponse>(
        '/pdd-failure-logs/cycle-relist/sequential/reset-stuck',
        null,
        { params },
      )
      .then((r) => r.data),

  pollPddFailureCycleRelist: () =>
    http
      .post<PddFailureCycleRelistPollResponse>('/pdd-failure-logs/cycle-relist/poll')
      .then((r) => r.data),

  pddFailureCycleRelistCandidates: (params?: { only_new?: boolean }) =>
    http
      .get<PddFailureCycleRelistCandidateListResponse>(
        '/pdd-failure-logs/cycle-relist/candidates',
        { params },
      )
      .then((r) => r.data),

  pddFailureCycleRelistPollLogs: (params?: { limit?: number }) =>
    http
      .get<PddFailureCycleRelistPollLogListResponse>(
        '/pdd-failure-logs/cycle-relist/poll-logs',
        { params },
      )
      .then((r) => r.data),

  claimPddFailureCycleRelist: (body: PddFailureCycleRelistClaimPayload) =>
    http
      .post<PddFailureCycleRelistClaimResult>('/pdd-failure-logs/cycle-relist/claim', body)
      .then((r) => r.data),

  releasePddFailureCycleRelist: (body: PddFailureCycleRelistReleasePayload) =>
    http
      .post<PddFailureCycleRelistClaimResult>('/pdd-failure-logs/cycle-relist/release', body)
      .then((r) => r.data),

  getPddFailureCycleRelistClaim: (recordId: string) =>
    http
      .get<PddFailureCycleRelistClaimResult>(`/pdd-failure-logs/cycle-relist/claim/${recordId}`)
      .then((r) => r.data),

  triggerPddFailureCycleRelist: (body: PddFailureCycleRelistTriggerPayload) =>
    http
      .post<PddFailureCycleRelistTriggerResult>('/pdd-failure-logs/cycle-relist/trigger', body)
      .then((r) => r.data),

  dailyCycleRelistSummary: (params?: { triggered_date?: string }) =>
    http
      .get<DailyCycleRelistSummaryResponse>('/daily-cycle-relists/summary', { params })
      .then((r) => r.data),

  dailyCycleRelistRecords: (params?: {
    triggered_date?: string
    account_id?: string
    limit?: number
  }) =>
    http
      .get<DailyCycleRelistRecordListResponse>('/daily-cycle-relists', { params })
      .then((r) => r.data),

  dailyInventoryDelistSummary: (params?: { stat_date?: string }) =>
    http
      .get<DailyInventoryDelistSummaryResponse>('/daily-inventory-delist/summary', { params })
      .then((r) => r.data),

  dailyInventoryDelistRecords: (params?: {
    stat_date?: string
    action?: 'delist' | 'relist'
    account_id?: string
    limit?: number
  }) =>
    http
      .get<DailyInventoryDelistRecordListResponse>('/daily-inventory-delist', { params })
      .then((r) => r.data),

  dailyListingSummary: (params?: { listed_date?: string; window_mode?: 'calendar' | 'report' }) =>
    http
      .get<DailyListingSummaryResponse>('/daily-listings/summary', { params })
      .then((r) => r.data),

  dailyListingRecords: (params?: {
    listed_date?: string
    window_mode?: 'calendar' | 'report'
    account_id?: string
    limit?: number
    active_only?: boolean
  }) =>
    http
      .get<DailyListingRecordListResponse>('/daily-listings', { params })
      .then((r) => r.data),

  dailyPipelineListingSkipSummary: (params?: { skip_date?: string; account_id?: string }) =>
    http
      .get<DailyPipelineListingSkipSummaryResponse>('/daily-pipeline-listing-skips/summary', {
        params,
      })
      .then((r) => r.data),

  dailyPipelineListingSkipRecords: (params?: {
    skip_date?: string
    account_id?: string
    skip_kind?: string
    limit?: number
  }) =>
    http
      .get<DailyPipelineListingSkipRecordListResponse>('/daily-pipeline-listing-skips', { params })
      .then((r) => r.data),

  wecomHealth: () => http.get<WecomHealth>('/wecom/health').then((r) => r.data),

  wecomConfig: () => http.get<WecomConfig>('/wecom/config').then((r) => r.data),

  updateWecomConfig: (body: WecomConfigUpdatePayload) =>
    http.put<WecomConfig>('/wecom/config', body).then((r) => r.data),

  wecomTestSend: (body: WecomTestSendPayload) =>
    http.post<WecomTestSendResult>('/wecom/test', body).then((r) => r.data),

  wecomDailyContent: () => http.get<WecomDailyContent>('/wecom/daily-content').then((r) => r.data),

  updateWecomDailyContent: (body: WecomDailyContentUpdatePayload) =>
    http.put<WecomDailyContent>('/wecom/daily-content', body).then((r) => r.data),

  saveWecomDailyPreview: (body: WecomDailyPreviewSavePayload) =>
    http.put<WecomDailyContent>('/wecom/daily-report/saved-preview', body).then((r) => r.data),

  wecomDailyReportPreview: (
    platform: WecomDailyReportPlatform,
    options?: {
      use_saved_preview?: boolean
      listing_window_start?: string
      listing_window_end?: string
    },
  ) =>
    http
      .get<WecomDailyReportPreview>('/wecom/daily-report/preview', {
        params: {
          platform,
          use_saved_preview: options?.use_saved_preview ?? true,
          listing_window_start: options?.listing_window_start || undefined,
          listing_window_end: options?.listing_window_end || undefined,
        },
      })
      .then((r) => r.data),

  wecomDailyReportStoreProgress: (params?: {
    listing_window_start?: string
    listing_window_end?: string
  }) =>
    http
      .get<WecomStoreProgressPreview>('/wecom/daily-report/store-progress', { params })
      .then((r) => r.data),

  wecomInProgressDraft: () =>
    http.get<WecomInProgressDraft>('/wecom/daily-report/in-progress-draft').then((r) => r.data),

  wecomDailyReportLogs: (params?: { platform?: string; page?: number; page_size?: number }) =>
    http
      .get<WecomDailyReportLogListResponse>('/wecom/daily-report/logs', { params })
      .then((r) => r.data),

  wecomDailyReportLog: (logId: string) =>
    http.get<WecomDailyReportLogDetail>(`/wecom/daily-report/logs/${logId}`).then((r) => r.data),

  wecomDailyReportTrigger: (body: WecomDailyReportTriggerPayload) =>
    http.post<WecomDailyReportTriggerResult>('/wecom/daily-report/trigger', body).then((r) => r.data),
}

export default http
