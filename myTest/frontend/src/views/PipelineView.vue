<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { useMinioSync } from '@/composables/useMinioSync'
import { useMinioMaterialRefresh } from '@/composables/useMinioMaterialRefresh'
import {
  formatMaterialGroupLabel,
  formatMaterialGroupMeta,
  groupListingTargetsByFamily,
} from '@/utils/listingTargets'
import { formatAutoPipelineFeedback } from '@/utils/autoPipeline'
import {
  loadListingBatchIntervalMinutes,
  loadListingBatchSetCount,
  loadRandomSelectCount,
  loadListingThrottleEnabled,
  loadListingPerBatchLimitedTimeEnabled,
  loadListingPerBatchCampaignEnabled,
  loadListingPerBatchLtTrafficActivityEnabled,
  loadListingPerBatchPromoteLtSuccessOnlyEnabled,
  loadDelistSpecCodeSearchEnabled,
  loadActivityLimitedTimeSuccessOnly,
  loadActivityTrafficBatchEnabled,
  loadActivityTrafficBatchSize,
  loadPerBatchLimitedTimeChunkSize,
  loadBatchLimitedTimeAutoRetryEnabled,
  loadBatchLimitedTimeAutoRetryMaxAttempts,
  loadPipelineRelistStrategy,
  loadSlotAlignmentTest,
  loadSpecFillVerifyTest,
  loadPrimaryStyleFirstTest,
  loadParenSizeAsProductType,
  loadCategoryNextBurstDemo,
  saveListingBatchIntervalMinutes,
  saveListingBatchSetCount,
  saveRandomSelectCount,
  saveListingThrottleEnabled,
  saveListingPerBatchLimitedTimeEnabled,
  saveListingPerBatchCampaignEnabled,
  saveListingPerBatchLtTrafficActivityEnabled,
  saveListingPerBatchPromoteLtSuccessOnlyEnabled,
  saveDelistSpecCodeSearchEnabled,
  saveActivityLimitedTimeSuccessOnly,
  saveActivityTrafficBatchEnabled,
  saveActivityTrafficBatchSize,
  savePerBatchLimitedTimeChunkSize,
  saveBatchLimitedTimeAutoRetryEnabled,
  saveBatchLimitedTimeAutoRetryMaxAttempts,
  savePipelineRelistStrategy,
  saveSlotAlignmentTest,
  saveSpecFillVerifyTest,
  savePrimaryStyleFirstTest,
  saveParenSizeAsProductType,
  saveCategoryNextBurstDemo,
} from '@/utils/pipelinePreferences'
import {
  failureReasonLabel,
  listingUnitStatusType,
} from '@/utils/labels'
import type {
  Account,
  AccountLifecycle,
  AutoUploadConfig,
  AutoUploadTriggerMode,
  CommerceOverview,
  FeishuInspectListingPricesResult,
  IntegratedPipeline,
  IntegratedPipelineBatchProductStageItem,
  ListingTargetOption,
  MarketingActivityOption,
  PreflightResponse,
  RelistStrategy,
} from '@/types'
import {
  commerceBlockReasonLabel,
  commerceLifecycleStatusLabel,
  commerceLifecycleTagType,
  commercePhaseLabel,
  commerceTriggerLabel,
  formatIntentProducts,
  formatWakeCountdown,
  intentPriorityLabel,
  summarizeLifecycle,
} from '@/utils/commerceLabels'

const router = useRouter()
const loading = ref(false)
const cancelingId = ref('')
const lateRetryLoading = ref(false)
const polling = ref(false)
const error = ref('')
const success = ref('')

const accounts = ref<Account[]>([])
const productOptions = ref<ListingTargetOption[]>([])
const materialSource = ref<'local' | 'minio'>('minio')
const minioHealth = ref<{ available?: boolean; error?: string; listing_poll_seconds?: number; refresh_mode?: 'poll' | 'rabbitmq' } | null>(null)
const showOnlyUnlistedGroups = ref(false)
const activities = ref<MarketingActivityOption[]>([])
const pipelines = ref<IntegratedPipeline[]>([])
const pipelinePage = ref(1)
const pipelinePageSize = ref(10)
const pipelineTotal = ref(0)
const activePipeline = ref<IntegratedPipeline | null>(null)
const commerceOverview = ref<CommerceOverview>({
  lifecycles: [],
  pending_intents: [],
  pending_total: 0,
  pending_by_account: {},
})
const commerceLoading = ref(false)
const commerceDispatchingAll = ref(false)
const commerceDispatchingAccount = ref('')
const commerceCancelingIntent = ref('')
const commerceResettingAccount = ref('')
const commerceResettingAll = ref(false)

const accountId = ref('')
const productCodes = ref<string[]>([])
const checkedProductsBySet = ref<Record<string, string[]>>({})
const selectedSetDrawerVisible = ref(false)
const activeProductDrawerSelector = ref<string>('')
const activityIds = ref<string[]>(['20981', '21365'])
const categoryKeyword = ref('笔袋')
const autoPromotion = ref(true)
const continueAfterLimitedTimeFailure = ref(false)
const continueAfterActivityFailure = ref(true)
const promoteAfterLimitedTimeFailure = ref(true)
const demoMode = ref(false)
const activityDelayHours = ref(24)
const slotAlignmentTest = ref(loadSlotAlignmentTest())
const specFillVerifyTest = ref(loadSpecFillVerifyTest())
const primaryStyleFirstTest = ref(loadPrimaryStyleFirstTest())
const parenSizeAsProductType = ref(loadParenSizeAsProductType())
const categoryNextBurstDemo = ref(loadCategoryNextBurstDemo())

watch(specFillVerifyTest, (enabled) => {
  if (enabled) slotAlignmentTest.value = false
  saveSpecFillVerifyTest(enabled)
})
watch(slotAlignmentTest, (enabled) => {
  if (enabled) specFillVerifyTest.value = false
  saveSlotAlignmentTest(enabled)
})
watch(primaryStyleFirstTest, (enabled) => {
  savePrimaryStyleFirstTest(enabled)
})
watch(parenSizeAsProductType, (enabled) => {
  saveParenSizeAsProductType(enabled)
})
watch(categoryNextBurstDemo, (enabled) => {
  saveCategoryNextBurstDemo(enabled)
})
const relistStrategy = ref<RelistStrategy>(loadPipelineRelistStrategy())
const listingThrottleEnabled = ref(loadListingThrottleEnabled())
const listingBatchSetCount = ref(loadListingBatchSetCount())
const randomSelectCount = ref(loadRandomSelectCount())
const listingBatchIntervalMinutes = ref(loadListingBatchIntervalMinutes())
const listingPerBatchLimitedTimeEnabled = ref(loadListingPerBatchLimitedTimeEnabled())
const listingPerBatchCampaignEnabled = ref(loadListingPerBatchCampaignEnabled())
const listingPerBatchLtTrafficActivityEnabled = ref(loadListingPerBatchLtTrafficActivityEnabled())
const listingPerBatchPromoteLtSuccessOnlyEnabled = ref(loadListingPerBatchPromoteLtSuccessOnlyEnabled())
const delistSpecCodeSearchEnabled = ref(loadDelistSpecCodeSearchEnabled())
const activityLimitedTimeSuccessOnly = ref(loadActivityLimitedTimeSuccessOnly())
const activityTrafficBatchEnabled = ref(loadActivityTrafficBatchEnabled())
const activityTrafficBatchSize = ref(loadActivityTrafficBatchSize())
const perBatchLimitedTimeChunkSize = ref(loadPerBatchLimitedTimeChunkSize())
const batchLimitedTimeAutoRetryEnabled = ref(loadBatchLimitedTimeAutoRetryEnabled())
const batchLimitedTimeAutoRetryMaxAttempts = ref(loadBatchLimitedTimeAutoRetryMaxAttempts())
const excelFallbackEnabled = ref(false)
const excelFallbackSaving = ref(false)
const logSpecSkuRowsEnabled = ref(true)
const logSpecSkuRowsSaving = ref(false)
const platformSkipDedupeEnabled = ref(true)
const platformSkipDedupeSaving = ref(false)
const platformSkipDedupeCodeCount = ref(0)
const platformSkipDedupeUpdatedAt = ref('')
const failureLogEnabled = ref(true)
const failureLogSaving = ref(false)
const failureLogTableName = ref('')
const accessoryCostPricingEnabled = ref(true)
const accessoryCostTieredFloatEnabled = ref(true)
const accessoryCostTieredFloatSaving = ref(false)
const originalSumPricingEnabled = ref(false)
const originalSumPricingSaving = ref(false)
const aiGenerateTitleLoading = ref(false)
const submitAiTitleEnabled = ref(false)
const accessoryCostPricingSaving = ref(false)
const accessoryCostPricingFloatMin = ref(0)
const accessoryCostPricingFloatMax = ref(5)
const pipelineBatchEnabled = ref(false)
const storeSequentialEnabled = ref(false)
const batchAccountIds = ref<string[]>([])
const startDelayMin = ref(30)
const startDelayMax = ref(180)
const preflightChecking = ref(false)
const preflightResult = ref<PreflightResponse | null>(null)
const autoUploadSaving = ref(false)
const autoUploadConfigVisible = ref(false)
const autoUploadEnabled = ref(false)
const autoUploadTriggerMode = ref<AutoUploadTriggerMode>('new_product_folder')
const deletingImageSets = ref(false)
const autoUploadConfig = ref<AutoUploadConfig>({
  enabled: false,
  trigger_mode: 'new_product_folder',
  account_id: '',
  account_ids: [],
  activity_ids: ['20981'],
  category_keyword: '玩偶',
  auto_promotion: true,
  auto_limited_time_setup: true,
  continue_after_limited_time_failure: false,
  continue_after_activity_failure: true,
  demo_mode: false,
  activity_delay_hours: 24,
  slot_alignment_test: false,
  material_source: 'minio',
  auto_sync_minio: true,
})
const { minioSyncJob, syncing, startSync, resumeActiveSync } = useMinioSync()

const {
  materialPolling,
  sseConnected,
  switchingMode,
  materialRefreshPaused,
  refreshMode,
  restart: restartMaterialRefresh,
  stop: stopMaterialRefresh,
  setMaterialRefreshPaused,
  setRefreshMode,
} = useMinioMaterialRefresh({
  materialSource,
  minioHealth,
  reloadHealth: loadMinioHealth,
  onRefresh: async () => {
    if (accountId.value) await loadListingTargets(accountId.value)
  },
  onUploadBatch: async (data) => {
    const autoHint = formatAutoPipelineFeedback(data.auto_pipeline)
    if (autoHint && data.auto_pipeline?.reason !== 'disabled') {
      if (data.auto_pipeline?.triggered) {
        ElMessage.success(autoHint || 'RabbitMQ 已自动启动整合链路')
        pipelinePage.value = 1
        await refreshPipelines()
        startPolling()
      } else if (data.auto_pipeline?.reason) {
        ElMessage.warning(autoHint)
      }
      return
    }
  },
})

let pollTimer: ReturnType<typeof setInterval> | null = null

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))

function accountDisplayName(accountId: string): string {
  const acc = accounts.value.find((item) => item.account_id === accountId)
  const shop = String(acc?.shop_display_name || acc?.display_name || '').trim()
  return shop ? `${accountId}（${shop}）` : accountId
}

function lifecycleForAccount(accountId: string): AccountLifecycle | null {
  const id = String(accountId || '').trim()
  if (!id) return null
  return commerceOverview.value.lifecycles.find((row) => row.account_id === id) || null
}

const commerceAccountRows = computed(() => {
  const map = new Map<
    string,
    { account_id: string; lifecycle: AccountLifecycle | null; pending_count: number }
  >()
  for (const row of commerceOverview.value.lifecycles) {
    map.set(row.account_id, {
      account_id: row.account_id,
      lifecycle: row,
      pending_count: commerceOverview.value.pending_by_account[row.account_id] || 0,
    })
  }
  for (const [accountId, count] of Object.entries(commerceOverview.value.pending_by_account || {})) {
    if (!map.has(accountId)) {
      map.set(accountId, { account_id: accountId, lifecycle: null, pending_count: count })
    }
  }
  return Array.from(map.values()).sort((a, b) => {
    const score = (row: { lifecycle: AccountLifecycle | null; pending_count: number }) =>
      (row.lifecycle ? 10 : 0) + (row.pending_count > 0 ? 5 : 0)
    return score(b) - score(a) || a.account_id.localeCompare(b.account_id)
  })
})

const selectedAccountLifecycle = computed(() =>
  pipelineBatchEnabled.value ? null : lifecycleForAccount(accountId.value),
)

const selectedAccountPendingCount = computed(() => {
  if (pipelineBatchEnabled.value || !accountId.value) return 0
  return commerceOverview.value.pending_by_account[accountId.value] || 0
})

const selectedAccountCommerceHint = computed(() => {
  if (pipelineBatchEnabled.value || !accountId.value) return ''
  const parts: string[] = []
  const lifecycle = selectedAccountLifecycle.value
  if (lifecycle && lifecycle.lifecycle_status && lifecycle.lifecycle_status !== 'none') {
    parts.push(summarizeLifecycle(lifecycle))
  }
  if (selectedAccountPendingCount.value > 0) {
    parts.push(`排队 ${selectedAccountPendingCount.value} 条`)
  }
  return parts.join('；')
})

const unlistedGroupCount = computed(
  () => productOptions.value.filter((item) => !item.is_fully_listed).length,
)

const visibleProductOptions = computed(() => {
  if (!showOnlyUnlistedGroups.value) return productOptions.value
  return productOptions.value.filter((item) => !item.is_fully_listed)
})

const groupedVisibleProductOptions = computed(() =>
  groupListingTargetsByFamily(visibleProductOptions.value),
)

const selectedSetGroups = computed(() =>
  productCodes.value
    .map((sel) => productOptions.value.find((item) => item.selector === sel))
    .filter((item): item is ListingTargetOption => !!item),
)

const activeProductDrawerGroup = computed(
  () =>
    selectedSetGroups.value.find((item) => item.selector === activeProductDrawerSelector.value) || null,
)

const selectedListingProductCount = computed(() =>
  selectedSetGroups.value.reduce((sum, group) => sum + selectedCountForGroup(group), 0),
)

const pendingSelectedSetCount = computed(
  () => selectedSetGroups.value.filter((group) => (group.unlisted_count ?? 0) > 0).length,
)

const resolvedListingSelectors = computed(() => {
  const result: string[] = []
  for (const group of selectedSetGroups.value) {
    const checked = checkedProductsBySet.value[group.selector] || []
    for (const code of checked) {
      if (group.product_codes.includes(code)) {
        result.push(`${group.selector}/${code}`)
      }
    }
  }
  return result
})

const allSelectedAreListed = computed(() => {
  if (!resolvedListingSelectors.value.length) return false
  return resolvedListingSelectors.value.every(isSelectorListed)
})

const listedSelectors = computed(() => resolvedListingSelectors.value.filter(isSelectorListed))

const preflightReadyLabels = computed(() => {
  if (!preflightResult.value) return new Set<string>()
  const errors = new Set(
    preflightResult.value.issues
      .filter((item) => item.level === 'error')
      .map((item) => item.listing_label)
      .filter(Boolean),
  )
  return new Set(
    preflightResult.value.units
      .map((unit) => unit.listing_label)
      .filter((label) => label && !errors.has(label)),
  )
})

const activeListingUnitStatuses = computed(() => activePipeline.value?.listing_unit_statuses || [])

const feishuInspectVisible = ref(false)
const feishuInspectLoading = ref(false)
const feishuInspectRefreshing = ref(false)
const feishuInspectData = ref<FeishuInspectListingPricesResult | null>(null)
const feishuInspectPipelineId = ref('')

const batchStageVisible = ref(false)
const batchStageLoading = ref(false)
const batchLtRetryLoadingBatch = ref<number | null>(null)
const batchLtRetryAllLoading = ref(false)
const batchStageItems = ref<IntegratedPipelineBatchProductStageItem[]>([])
const batchStagePipelineId = ref('')
const batchStageExpandedNames = ref<number[]>([])
const batchStageContextPipeline = ref<IntegratedPipeline | null>(null)
const batchLtChunkEnabled = ref(true)
const batchLtChunkSize = ref(10)
const batchLtChunkSaving = ref(false)

const showBatchLtChunkSettings = computed(
  () => Boolean(batchStageContextPipeline.value?.per_batch_lt_chunk_supported),
)

const batchLtChunkSettingsDisabled = computed(
  () =>
    Boolean(batchStageContextPipeline.value?.per_batch_lt_chunk_sequence_active)
    || batchLtChunkSaving.value,
)

function syncBatchLtChunkSettingsFromPipeline(pipeline: IntegratedPipeline | null | undefined) {
  batchLtChunkEnabled.value = pipeline?.per_batch_limited_time_chunk_enabled !== false
  batchLtChunkSize.value = Number(pipeline?.per_batch_limited_time_chunk_size || 10)
}

async function saveBatchLtChunkSettings() {
  const pipeline = batchStageContextPipeline.value
  if (!pipeline?.pipeline_id || !showBatchLtChunkSettings.value) return
  batchLtChunkSaving.value = true
  try {
    const result = await api.updatePerBatchLtChunkSettings(pipeline.pipeline_id, {
      enabled: batchLtChunkEnabled.value,
      chunk_size: Number(batchLtChunkSize.value) || 10,
    })
    batchStageContextPipeline.value = {
      ...pipeline,
      per_batch_limited_time_chunk_enabled: result.enabled,
      per_batch_limited_time_chunk_size: result.chunk_size,
      per_batch_limited_time_chunk_display: result.display,
      per_batch_lt_chunk_sequence_active: result.sequence_active,
    }
    if (activePipeline.value?.pipeline_id === pipeline.pipeline_id) {
      activePipeline.value = {
        ...activePipeline.value,
        per_batch_limited_time_chunk_enabled: result.enabled,
        per_batch_limited_time_chunk_size: result.chunk_size,
        per_batch_limited_time_chunk_display: result.display,
        per_batch_lt_chunk_sequence_active: result.sequence_active,
      }
    }
    ElMessage.success(result.enabled ? '已开启限时按趟拆分' : '已关闭限时按趟拆分')
  } catch (error: any) {
    syncBatchLtChunkSettingsFromPipeline(pipeline)
    ElMessage.error(error?.response?.data?.detail || error?.message || '保存限时拆分设置失败')
  } finally {
    batchLtChunkSaving.value = false
  }
}

const BATCH_STAGE_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  success: '成功',
  failed: '失败',
  skipped: '已跳过',
  running: '进行中',
}

function batchStageStatusLabel(status: string) {
  return BATCH_STAGE_STATUS_LABELS[status] || status || '—'
}

function batchStageTagType(status: string) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  if (status === 'skipped') return 'info'
  return 'info'
}

function summarizeBatchStageStatuses(statuses: string[]) {
  const valid = statuses.map((item) => String(item || '').trim()).filter(Boolean)
  if (!valid.length) return '—'
  const unique = [...new Set(valid)]
  if (unique.length === 1) return batchStageStatusLabel(unique[0])
  const parts: string[] = []
  for (const key of ['success', 'running', 'failed', 'pending', 'skipped']) {
    const count = valid.filter((item) => item === key).length
    if (count) parts.push(`${batchStageStatusLabel(key)} ${count}`)
  }
  return parts.join(' · ')
}

function canViewBatchStagesForPipeline(pipeline: IntegratedPipeline | null | undefined) {
  if (!pipeline) return false
  const listingStep = pipeline.steps?.find((step) => step.key === 'listing')
  if (listingStep?.detail?.includes('分批')) return true
  if ((pipeline.per_batch_lt_aggregate?.batch_log?.length || 0) > 0) return true
  if (String(pipeline.current_step || '').startsWith('waiting_listing_batch_')) return true
  if (String(pipeline.current_step || '').includes('per_batch')) return true
  return false
}

const canViewBatchStages = computed(() => canViewBatchStagesForPipeline(activePipeline.value))

const batchStageGroups = computed(() => {
  const grouped = new Map<number, IntegratedPipelineBatchProductStageItem[]>()
  for (const item of batchStageItems.value) {
    const index = Number(item.batch_index) || 0
    const bucket = grouped.get(index) || []
    bucket.push(item)
    grouped.set(index, bucket)
  }
  return [...grouped.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([batchIndex, products]) => ({
      batch_index: batchIndex,
      batch_label: `第 ${batchIndex + 1} 批`,
      products,
      listing_summary: summarizeBatchStageStatuses(products.map((row) => row.listing_status)),
      limited_time_summary: summarizeBatchStageStatuses(products.map((row) => row.limited_time_status)),
      activity_1_summary: summarizeBatchStageStatuses(products.map((row) => row.activity_1_status)),
      activity_2_summary: summarizeBatchStageStatuses(products.map((row) => row.activity_2_status)),
      promotion_summary: summarizeBatchStageStatuses(products.map((row) => row.promotion_status)),
    }))
})

const batchStageActivityIds = computed(() => {
  const pipeline = batchStageContextPipeline.value || activePipeline.value
  if (!pipeline) return [] as string[]
  if (pipeline.activity_ids?.length) return pipeline.activity_ids
  return pipeline.activity_id ? [pipeline.activity_id] : []
})

const batchStageHasActivity2 = computed(() => {
  if (batchStageActivityIds.value.length > 1) return true
  return batchStageItems.value.some((item) => Boolean(item.activity_2_id || item.activity_2_status !== 'pending'))
})

function countBatchLtRetryTargets(products: IntegratedPipelineBatchProductStageItem[]) {
  return products.filter(
    (row) =>
      row.listing_status === 'success'
      && row.limited_time_status === 'failed'
      && Boolean(String(row.pdd_product_id || '').trim()),
  ).length
}

function isPipelineListingBatchesComplete(pipeline: IntegratedPipeline | null | undefined) {
  if (!pipeline) return false
  if (pipeline.listing_batches_complete) return true
  const step = String(pipeline.current_step || '')
  if (step.startsWith('waiting_listing_batch_')) return false
  const listingStep = pipeline.steps?.find((item) => item.key === 'listing')
  const detail = String(listingStep?.detail || '')
  const batchProgress = detail.match(/分批上架\s*(\d+)\s*\/\s*(\d+)/)
  if (batchProgress && batchProgress[1] === batchProgress[2]) return true
  if (listingStep?.status === 'success' || listingStep?.status === 'skipped') return true
  return false
}

function isBatchInitialLimitedTimeRecorded(products: IntegratedPipelineBatchProductStageItem[]) {
  return products.some(
    (row) =>
      row.listing_status === 'success'
      && row.limited_time_status
      && row.limited_time_status !== 'pending',
  )
}

function batchLtRetryDisabledReason(batchIndex: number, products: IntegratedPipelineBatchProductStageItem[]) {
  const pipeline = batchStageContextPipeline.value
  if (!pipeline) return '链路信息未加载'
  if (!isPipelineListingBatchesComplete(pipeline)) return '全部分批上架完成后才可重跑限时'
  if (!isBatchInitialLimitedTimeRecorded(products)) return '本批首轮限时限量购尚未跑完'
  if (countBatchLtRetryTargets(products) <= 0) return '本批无可重跑商品'
  const retryState = pipeline.batch_limited_time_retry
  if (retryState?.phase === 'limited_time') {
    if (retryState.active_batch_index === batchIndex) return '本批限时重跑进行中'
    if ((retryState.pending_batch_indices || []).includes(batchIndex)) return '本批已加入重跑队列'
  }
  return ''
}

function canBatchLtRetryForGroup(batchIndex: number, products: IntegratedPipelineBatchProductStageItem[]) {
  return countBatchLtRetryTargets(products) > 0 && !batchLtRetryDisabledReason(batchIndex, products)
}

function shouldShowBatchLtRetryAction(batchIndex: number, products: IntegratedPipelineBatchProductStageItem[]) {
  return countBatchLtRetryTargets(products) > 0
}

const batchLtRetryAllTargetStats = computed(() => {
  let batchCount = 0
  let productCount = 0
  for (const group of batchStageGroups.value) {
    if (!shouldShowBatchLtRetryAction(group.batch_index, group.products)) continue
    if (!canBatchLtRetryForGroup(group.batch_index, group.products)) continue
    const n = countBatchLtRetryTargets(group.products)
    if (n <= 0) continue
    batchCount += 1
    productCount += n
  }
  return { batchCount, productCount }
})

const canStartAllBatchLtRetry = computed(() => {
  if (batchLtRetryAllLoading.value || batchLtRetryLoadingBatch.value !== null) return false
  return batchLtRetryAllTargetStats.value.batchCount > 0
})

const batchLtRetryAllDisabledReason = computed(() => {
  if (!isPipelineListingBatchesComplete(batchStageContextPipeline.value)) {
    return '全部分批上架完成后才可一键重跑限时'
  }
  if (batchLtRetryAllTargetStats.value.batchCount <= 0) {
    return '当前没有可重跑的批次'
  }
  if (batchLtRetryLoadingBatch.value !== null || batchLtRetryAllLoading.value) {
    return '重跑进行中'
  }
  return ''
})

const batchLtRetryPhaseLabel = (phase?: string) => {
  if (phase === 'limited_time') return '限时重跑中'
  if (phase === 'done') return '已完成'
  if (phase === 'partial_done') return '部分完成'
  return phase || ''
}

async function startBatchLimitedTimeRetry(batchIndex: number, products: IntegratedPipelineBatchProductStageItem[]) {
  const pipeline = batchStageContextPipeline.value
  if (!pipeline?.pipeline_id) return
  const count = countBatchLtRetryTargets(products)
  if (count <= 0) return
  const chunkEnabled = pipeline.per_batch_limited_time_chunk_enabled !== false
  const chunkSize = Number(pipeline.per_batch_limited_time_chunk_size || 10)
  const chunkHint = chunkEnabled && count > chunkSize
    ? `\n已开启按趟拆分：将按每趟最多 ${chunkSize} 个依次重跑（共约 ${Math.ceil(count / chunkSize)} 趟）。`
    : ''
  try {
    await ElMessageBox.confirm(
      `将重跑第 ${batchIndex + 1} 批中 ${count} 个「上架成功、限时失败」商品的限时限量购。${chunkHint}\n`
        + '若有成功，商品会追加进活动池；活动改期需等全部批次首轮限时跑完后，按最后一批重跑成功时刻 + 24h 执行。',
      '分批限时重跑',
      { type: 'warning', confirmButtonText: '开始重跑', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  batchLtRetryLoadingBatch.value = batchIndex
  try {
    const result = await api.startBatchLimitedTimeRetry(pipeline.pipeline_id, batchIndex)
    if (batchStageContextPipeline.value) {
      batchStageContextPipeline.value = {
        ...batchStageContextPipeline.value,
        batch_limited_time_retry: result.batch_limited_time_retry,
        status: result.queued ? batchStageContextPipeline.value.status : 'running',
        current_step: result.queued
          ? batchStageContextPipeline.value.current_step
          : 'batch_limited_time_retry',
      }
    }
    if (activePipeline.value?.pipeline_id === pipeline.pipeline_id) {
      activePipeline.value = await api.getIntegratedPipeline(pipeline.pipeline_id)
    }
    if (batchStageContextPipeline.value?.pipeline_id === pipeline.pipeline_id) {
      batchStageContextPipeline.value = await api.getIntegratedPipeline(pipeline.pipeline_id)
    }
    await refreshBatchStageDialog()
    ElMessage.success(
      result.queued
        ? `第 ${batchIndex + 1} 批已加入限时重跑队列`
        : `第 ${batchIndex + 1} 批限时重跑已启动（${result.retry_count} 个商品）`,
    )
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '分批限时重跑启动失败')
  } finally {
    batchLtRetryLoadingBatch.value = null
  }
}

async function startAllBatchLimitedTimeRetry() {
  const pipeline = batchStageContextPipeline.value
  if (!pipeline?.pipeline_id) return
  const { batchCount, productCount } = batchLtRetryAllTargetStats.value
  if (batchCount <= 0) return
  const disabled = batchLtRetryAllDisabledReason.value
  if (disabled && !canStartAllBatchLtRetry.value) {
    ElMessage.warning(disabled)
    return
  }
  try {
    await ElMessageBox.confirm(
      `将对全部 ${batchCount} 批共 ${productCount} 个「上架成功、限时失败」商品，按批次串行重跑限时限量购（第 1 批先跑，其余自动排队）。\n`
        + '流程与逐批点击「重跑限时失败」相同；若有成功会追加进活动池，活动改期规则不变。',
      '一键全部重跑限时失败',
      { type: 'warning', confirmButtonText: '开始全部重跑', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  batchLtRetryAllLoading.value = true
  try {
    const result = await api.startAllBatchLimitedTimeRetry(pipeline.pipeline_id)
    if (batchStageContextPipeline.value) {
      batchStageContextPipeline.value = {
        ...batchStageContextPipeline.value,
        batch_limited_time_retry: result.batch_limited_time_retry,
        status: 'running',
        current_step: 'batch_limited_time_retry',
      }
    }
    if (activePipeline.value?.pipeline_id === pipeline.pipeline_id) {
      activePipeline.value = await api.getIntegratedPipeline(pipeline.pipeline_id)
    }
    if (batchStageContextPipeline.value?.pipeline_id === pipeline.pipeline_id) {
      batchStageContextPipeline.value = await api.getIntegratedPipeline(pipeline.pipeline_id)
    }
    await refreshBatchStageDialog()
    const queuedN = result.queued_batches?.length || 0
    ElMessage.success(
      queuedN > 0
        ? `已启动全部重跑：${result.batch_count} 批 / ${result.retry_count} 个商品（含 ${queuedN} 批排队）`
        : `已启动全部重跑：${result.batch_count} 批 / ${result.retry_count} 个商品`,
    )
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '一键全部重跑启动失败')
  } finally {
    batchLtRetryAllLoading.value = false
  }
}

async function openBatchStageDialog(pipeline?: IntegratedPipeline | null) {
  const target = pipeline || activePipeline.value
  if (!target?.pipeline_id) return
  batchStageContextPipeline.value = target
  batchStagePipelineId.value = target.pipeline_id
  batchStageVisible.value = true
  batchStageLoading.value = true
  batchStageItems.value = []
  try {
    const [stageData, pipelineData] = await Promise.all([
      api.getIntegratedPipelineBatchProductStages(target.pipeline_id),
      api.getIntegratedPipeline(target.pipeline_id),
    ])
    batchStageItems.value = stageData.items || []
    batchStageContextPipeline.value = pipelineData
    syncBatchLtChunkSettingsFromPipeline(pipelineData)
    batchStageExpandedNames.value = [
      ...new Set(batchStageItems.value.map((item) => Number(item.batch_index) || 0)),
    ].sort((a, b) => a - b)
    if (!batchStageItems.value.length) {
      ElMessage.info('暂无分批记录，上架批次开始后会逐步写入')
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '读取每批状态失败')
    batchStageVisible.value = false
  } finally {
    batchStageLoading.value = false
  }
}

async function refreshBatchStageDialog() {
  if (!batchStagePipelineId.value) return
  batchStageLoading.value = true
  try {
    const [stageData, pipelineData] = await Promise.all([
      api.getIntegratedPipelineBatchProductStages(batchStagePipelineId.value),
      api.getIntegratedPipeline(batchStagePipelineId.value),
    ])
    batchStageItems.value = stageData.items || []
    batchStageContextPipeline.value = pipelineData
    syncBatchLtChunkSettingsFromPipeline(pipelineData)
    if (!batchStageExpandedNames.value.length) {
      batchStageExpandedNames.value = [
        ...new Set(batchStageItems.value.map((item) => Number(item.batch_index) || 0)),
      ].sort((a, b) => a - b)
    }
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || err?.message || '刷新每批状态失败')
  } finally {
    batchStageLoading.value = false
  }
}

function merchantCodeFromPipelineSelector(raw: string): string {
  const text = String(raw || '').trim()
  if (!text) return ''
  const parts = text.split('/').filter(Boolean)
  if (parts.length >= 3) return parts[parts.length - 1]
  return parts[0] || text
}

function feishuCodesFromPipeline(pipeline: IntegratedPipeline | null | undefined): string[] {
  if (!pipeline) return []
  const codes = new Set<string>()
  for (const row of pipeline.listing_unit_statuses || []) {
    const label = String(row.listing_label || '').trim()
    if (label) codes.add(label.split('/')[0])
  }
  for (const sel of pipeline.product_codes || []) {
    const code = merchantCodeFromPipelineSelector(sel)
    if (code) codes.add(code)
  }
  return [...codes]
}

async function loadFeishuInspectForPipeline(
  pipeline: IntegratedPipeline,
  options: { preferStored?: boolean; refresh?: boolean } = {},
) {
  const { preferStored = true, refresh = false } = options
  feishuInspectPipelineId.value = pipeline.pipeline_id
  feishuInspectVisible.value = true
  feishuInspectLoading.value = true
  feishuInspectData.value = null

  try {
    if (refresh) {
      feishuInspectData.value = await api.getPipelineFeishuInspect(pipeline.pipeline_id, true)
      return
    }

    if (preferStored) {
      try {
        feishuInspectData.value = await api.getPipelineFeishuInspect(pipeline.pipeline_id, false)
        return
      } catch (e: unknown) {
        const err = e as { response?: { status?: number } }
        if (err?.response?.status !== 404) throw e
      }
    }

    const codes = feishuCodesFromPipeline(pipeline)
    if (!codes.length) {
      ElMessage.warning('该链路没有可查询的商品编码')
      feishuInspectVisible.value = false
      return
    }
    feishuInspectData.value = await api.feishuInspectListingPrices(
      codes,
      true,
      pipeline.pipeline_id,
    )
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ElMessage.error(err?.response?.data?.detail || err?.message || '读取飞书数据失败')
  } finally {
    feishuInspectLoading.value = false
  }
}

async function openFeishuInspectDialog(pipeline?: IntegratedPipeline | null) {
  const target = pipeline || activePipeline.value
  if (!target) {
    ElMessage.warning('请先选择一条整合链路')
    return
  }
  await loadFeishuInspectForPipeline(target, { preferStored: true })
}

async function refreshFeishuInspectDialog() {
  const pipelineId = feishuInspectPipelineId.value
  if (!pipelineId) return
  feishuInspectRefreshing.value = true
  try {
    feishuInspectData.value = await api.getPipelineFeishuInspect(pipelineId, true)
    ElMessage.success('已重新读取飞书数据')
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ElMessage.error(err?.response?.data?.detail || err?.message || '重新读取失败')
  } finally {
    feishuInspectRefreshing.value = false
  }
}

const listingUnitStatusSummary = computed(() => {
  const rows = activeListingUnitStatuses.value
  if (!rows.length) return null
  const counts: Record<string, number> = {}
  for (const row of rows) {
    counts[row.status] = (counts[row.status] || 0) + 1
  }
  return counts
})

const lateRetryState = computed(() => activePipeline.value?.late_retry)
const batchLtRetryState = computed(() => activePipeline.value?.batch_limited_time_retry)
const batchLtAutoRetryState = computed(() => activePipeline.value?.batch_limited_time_auto_retry)
const lateRetryFailedCount = computed(() => listingUnitStatusSummary.value?.failed || 0)
const canLateRetryFailed = computed(() => {
  const pipeline = activePipeline.value
  if (!pipeline) return false
  const lr = pipeline.late_retry
  if (lr?.phase === 'listing' || lr?.phase === 'limited_time') return false
  return Boolean(lr?.eligibility?.eligible ?? lr?.eligible)
})

function lateRetryEligibilityHint() {
  const lr = lateRetryState.value
  const defer = lr?.activity_defer
  if (defer?.rescheduled && defer.reschedule_reason) {
    return defer.reschedule_reason
  }
  if (defer?.last_deferred_at && (lr?.phase === 'listing' || lr?.phase === 'limited_time')) {
    return '补跑进行中，活动已自动推迟'
  }
  const reason = lr?.eligibility?.reason || ''
  const map: Record<string, string> = {
    pipeline_not_waiting_activity: '链路未处于等活动状态',
    pipeline_not_in_waiting_activity_step: '当前步骤不允许补跑',
    activity_not_scheduled: '活动尚未预约',
    activity_deadline_passed: '活动预约时间已过',
    late_retry_in_progress: '补跑进行中',
    no_failed_selectors: '没有可补跑的失败套图',
    insufficient_time_before_activity: `距活动不足 ${lr?.eligibility?.required_buffer_minutes ?? 30} 分钟缓冲`,
  }
  if (map[reason]) return map[reason]
  if (lr?.outcome_detail) return lr.outcome_detail
  return reason || ''
}

function lateRetryPhaseLabel(phase?: string) {
  const map: Record<string, string> = {
    idle: '未开始',
    listing: '补跑上架中',
    limited_time: '补跑限时购中',
    done: '已并入活动池',
    partial_done: '部分完成',
    expired: '已超时未并入',
  }
  return map[String(phase || '')] || phase || ''
}

function listingUnitReasonText(reasonCode: string) {
  if (!reasonCode) return ''
  return failureReasonLabel[reasonCode] || reasonCode
}

async function syncSelectedFromMinio() {
  if (!resolvedListingSelectors.value.length) {
    ElMessage.warning('请先选择要上架的套图')
    return
  }
  await startSync(resolvedListingSelectors.value, (msg) => {
    ElMessage.error(msg)
  })
}

async function checkSelectedSets() {
  if (!resolvedListingSelectors.value.length) {
    ElMessage.warning('请先选择要上架的套图')
    return
  }
  if (materialSource.value === 'minio' && syncing.value) {
    ElMessage.warning('MinIO 仍在同步中，请稍候再检查')
    return
  }
  preflightChecking.value = true
  preflightResult.value = null
  try {
    preflightResult.value = await api.preflight(resolvedListingSelectors.value, materialSource.value)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    ElMessage.error(msg || '检查失败')
  } finally {
    preflightChecking.value = false
  }
}

const unlistedSelectors = computed(() =>
  resolvedListingSelectors.value.filter((selector) => !isSelectorListed(selector)),
)

function isSelectorListed(selector: string) {
  const slash = selector.lastIndexOf('/')
  if (slash <= 0) return false
  const setSelector = selector.slice(0, slash)
  const code = selector.slice(slash + 1)
  const group = productOptions.value.find((item) => item.selector === setSelector)
  return !!group && isProductListed(group, code)
}

interface ListingIntent {
  skipListing: boolean
  listingSkipSelectors: string[]
}

async function resolveListingIntent(): Promise<ListingIntent | null> {
  if (relistStrategy.value === 'delist_and_relist') {
    return { skipListing: false, listingSkipSelectors: [] }
  }
  if (relistStrategy.value === 'append_to_existing') {
    ElMessage.warning('「原 ID 链接补漏」功能尚未实现，请选择其他策略')
    return null
  }
  const listed = listedSelectors.value
  const unlisted = unlistedSelectors.value
  if (!listed.length) {
    return { skipListing: false, listingSkipSelectors: [] }
  }

  if (!unlisted.length) {
    const labels = resolvedListingSelectors.value.join('、')
    try {
      await ElMessageBox.confirm(
        `所选商品均已上架：\n${labels}\n\n是否跳过上架，直接进入活动报名？\n选择「重新上架」将照常执行上架步骤。`,
        '已上架商品',
        {
          type: 'info',
          confirmButtonText: '跳过上架',
          cancelButtonText: '重新上架',
          distinguishCancelAndClose: true,
        },
      )
      return { skipListing: true, listingSkipSelectors: [] }
    } catch (action) {
      if (action === 'cancel') return { skipListing: false, listingSkipSelectors: [] }
      return null
    }
  }

  const listedText = listed.join('\n')
  const unlistedText = unlisted.join('\n')
  try {
    await ElMessageBox.confirm(
      `所选同时包含已上架与未上架商品：\n\n已上架：\n${listedText}\n\n待上架：\n${unlistedText}\n\n请选择如何处理已上架商品。`,
      '含已上架商品',
      {
        type: 'warning',
        confirmButtonText: '仅上架未上架',
        cancelButtonText: '全部重新上架',
        distinguishCancelAndClose: true,
      },
    )
    return { skipListing: false, listingSkipSelectors: listed }
  } catch (action) {
    if (action === 'cancel') return { skipListing: false, listingSkipSelectors: [] }
    return null
  }
}

function syncCheckedProductsForSets(setSelectors: string[]) {
  const next: Record<string, string[]> = { ...checkedProductsBySet.value }
  for (const sel of setSelectors) {
    const opt = productOptions.value.find((item) => item.selector === sel)
    if (!opt) continue
    const prev = next[sel] || []
    const valid = prev.filter((code) => opt.product_codes.includes(code))
    next[sel] = valid.length ? valid : [...opt.product_codes]
  }
  for (const key of Object.keys(next)) {
    if (!setSelectors.includes(key)) delete next[key]
  }
  checkedProductsBySet.value = next
}

function updateCheckedProducts(selector: string, codes: string[]) {
  checkedProductsBySet.value = { ...checkedProductsBySet.value, [selector]: codes }
}

function openProductDrawer(selector: string) {
  activeProductDrawerSelector.value = selector
}

function closeProductDrawer() {
  activeProductDrawerSelector.value = ''
}

function openSelectedSetDrawer() {
  selectedSetDrawerVisible.value = true
}

function closeSelectedSetDrawer() {
  selectedSetDrawerVisible.value = false
}

function selectAllMaterialGroups() {
  productCodes.value = visibleProductOptions.value.map((item) => item.selector)
  syncCheckedProductsForSets(productCodes.value)
}

function shuffleArray<T>(items: T[]): T[] {
  const arr = [...items]
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

function randomSelectMaterialGroups() {
  const candidates = visibleProductOptions.value
  if (!candidates.length) {
    ElMessage.warning(showOnlyUnlistedGroups.value ? '当前没有待上架套图' : '暂无可选套图')
    return
  }
  const requested = Math.max(1, Math.floor(Number(randomSelectCount.value) || 1))
  const n = Math.min(requested, candidates.length)
  const picked = shuffleArray(candidates).slice(0, n)
  productCodes.value = picked.map((item) => item.selector)
  syncCheckedProductsForSets(productCodes.value)
  if (requested > candidates.length) {
    ElMessage.success(`可选 ${candidates.length} 套，已全部随机选中`)
  } else {
    ElMessage.success(`已随机选中 ${picked.length} 套图`)
  }
}

function clearAllMaterialGroups() {
  productCodes.value = []
  checkedProductsBySet.value = {}
  closeSelectedSetDrawer()
}

async function deleteSelectedProducts() {
  if (materialSource.value !== 'minio') {
    ElMessage.warning('仅 MinIO 素材模式支持删除商品素材')
    return
  }
  const selectors = [...resolvedListingSelectors.value]
  if (!selectors.length) {
    ElMessage.warning('请先在下方「上架商品」中勾选要删除的商品（如 BD713B）')
    return
  }
  const labels = selectors.join('、')
  try {
    await ElMessageBox.confirm(
      `将永久删除以下商品文件夹（MinIO + Alist），同级其他商品会保留；仅当套图/款号已空时才删除上级目录：\n\n${labels}`,
      '删除商品素材',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  deletingImageSets.value = true
  const deleted: string[] = []
  try {
    for (const selector of selectors) {
      const result = await api.deleteMinioProductFolder({
        selector,
        sync_alist: true,
        clear_local_cache: true,
      })
      deleted.push(result.summary || selector)
      const parts = selector.split('/')
      const setSelector = parts.length >= 2 ? `${parts[0]}/${parts[1]}` : selector
      const checked = checkedProductsBySet.value[setSelector] || []
      updateCheckedProducts(
        setSelector,
        checked.filter((code) => `${setSelector}/${code}` !== selector),
      )
      if (result.image_set_removed) {
        productCodes.value = productCodes.value.filter((sel) => sel !== setSelector)
      }
    }
    if (accountId.value) await loadListingTargets(accountId.value)
    ElMessage.success(`已删除 ${selectors.length} 个商品文件夹（MinIO + Alist 已同步）`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
    if (deleted.length && accountId.value) {
      await loadListingTargets(accountId.value).catch(() => undefined)
    }
  } finally {
    deletingImageSets.value = false
  }
}

function stepTagType(status: string) {
  if (['success', 'completed', 'skipped'].includes(status)) return 'success'
  if (['running', 'scheduled', 'pending'].includes(status)) return 'warning'
  if (['failed', 'canceled'].includes(status)) return 'danger'
  return 'info'
}

function pipelineTagType(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'canceled') return 'info'
  if (status === 'waiting_activity') return 'warning'
  return 'info'
}

const PIPELINE_TERMINAL_STATUSES = new Set(['completed', 'failed', 'canceled'])

function canCancelPipeline(pipeline: IntegratedPipeline) {
  return !PIPELINE_TERMINAL_STATUSES.has(pipeline.status)
}

async function cancelPipeline(pipeline: IntegratedPipeline) {
  if (!canCancelPipeline(pipeline)) return
  try {
    await ElMessageBox.confirm(
      `确定取消链路 ${pipeline.pipeline_id}？取消后不会再执行后续活动报名与推广。`,
      '取消整合链路',
      { type: 'warning', confirmButtonText: '确定取消', cancelButtonText: '保留' },
    )
  } catch {
    return
  }
  cancelingId.value = pipeline.pipeline_id
  try {
    const updated = await api.cancelIntegratedPipeline(pipeline.pipeline_id)
    if (activePipeline.value?.pipeline_id === pipeline.pipeline_id) {
      activePipeline.value = updated
    }
    await refreshPipelines()
    ElMessage.success('整合链路已取消')
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '取消失败'
    ElMessage.error(msg)
  } finally {
    cancelingId.value = ''
  }
}

async function startLateRetryFailed(pipeline: IntegratedPipeline) {
  const failedCount = lateRetryFailedCount.value
  if (!failedCount) {
    ElMessage.warning('当前没有失败的套图可补跑')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将补跑 ${failedCount} 个失败套图：上架 → 限时限量购 → 并入活动池。\n若活动原定时间到了补跑还没跑完，会自动推迟；全部补跑结束后，将按最后一次补跑上架完成时间重新计 ${pipeline.activity_delay_hours || 24} 小时再报活动。`,
      '补跑失败项',
      { type: 'warning', confirmButtonText: '开始补跑', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  lateRetryLoading.value = true
  try {
    const resp = await api.lateRetryFailedPipeline(pipeline.pipeline_id)
    ElMessage.success(`已提交补跑 ${resp.selector_count} 个套图`)
    if (activePipeline.value?.pipeline_id === pipeline.pipeline_id) {
      activePipeline.value = await api.getIntegratedPipeline(pipeline.pipeline_id)
    }
    await refreshPipelines()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ElMessage.error(err?.response?.data?.detail || err?.message || '补跑提交失败')
  } finally {
    lateRetryLoading.value = false
  }
}

function formatTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function formatActivityLabel(activityId: string) {
  const act = activities.value.find((item) => item.activity_id === activityId)
  if (!act) return activityId
  const name = act.name?.trim()
  return name ? `${activityId} · ${name}` : activityId
}

function formatActivityShortLabel(act: MarketingActivityOption) {
  const name = (act.name?.trim() || '活动').replace(/\s+/g, ' ')
  const short = name.length > 22 ? `${name.slice(0, 20)}…` : name
  return `${act.activity_id} · ${short}`
}

function selectAllListingProducts() {
  for (const group of selectedSetGroups.value) {
    updateCheckedProducts(group.selector, [...group.product_codes])
  }
}

function clearAllListingProducts() {
  for (const group of selectedSetGroups.value) {
    updateCheckedProducts(group.selector, [])
  }
}

function formatActivityList(activityIds: string[] | undefined) {
  if (!activityIds?.length) return '—'
  return activityIds.map((id) => formatActivityLabel(id)).join('；')
}

function campaignResultTagType(result: { success?: boolean; skipped?: boolean }) {
  if (result.skipped) return 'warning'
  if (result.success) return 'success'
  return 'danger'
}

function campaignResultLabel(result: { success?: boolean; skipped?: boolean }) {
  if (result.skipped) return '已跳过'
  if (result.success) return '成功'
  return '失败'
}

function pipelineActivitySummary(pipeline: IntegratedPipeline) {
  const ids = pipeline.activity_ids?.length
    ? pipeline.activity_ids
    : pipeline.activity_id
      ? [pipeline.activity_id]
      : []
  if (!ids.length) return '—'
  if (ids.length === 1) return ids[0]
  return `${ids.length} 个活动`
}

function isProductListed(group: ListingTargetOption, code: string) {
  return (group.listed_product_codes || []).includes(code)
}

function isProductChecked(group: ListingTargetOption, code: string) {
  return (checkedProductsBySet.value[group.selector] || []).includes(code)
}

function toggleProductChecked(group: ListingTargetOption, code: string, checked: boolean) {
  const current = checkedProductsBySet.value[group.selector] || []
  const next = checked ? Array.from(new Set([...current, code])) : current.filter((item) => item !== code)
  updateCheckedProducts(group.selector, next)
}

function selectedCountForGroup(group: ListingTargetOption) {
  return (checkedProductsBySet.value[group.selector] || []).length
}

function isGroupFullySelected(group: ListingTargetOption) {
  return !!group.product_codes.length && selectedCountForGroup(group) === group.product_codes.length
}

function toggleGroupSelection(group: ListingTargetOption, shouldSelect: boolean) {
  updateCheckedProducts(group.selector, shouldSelect ? [...group.product_codes] : [])
}

function toggleGroupSelectionQuick(group: ListingTargetOption) {
  toggleGroupSelection(group, selectedCountForGroup(group) <= 0)
}

function productStatusType(group: ListingTargetOption, code: string) {
  if (isProductListed(group, code)) return 'success'
  if (isProductChecked(group, code)) return 'primary'
  return 'info'
}

function productStatusText(group: ListingTargetOption, code: string) {
  if (isProductListed(group, code)) return '已上架'
  if (isProductChecked(group, code)) return '已选中'
  return '未选中'
}

function previewProductCodes(group: ListingTargetOption) {
  const checked = checkedProductsBySet.value[group.selector] || []
  return checked.slice(0, 4)
}

function remainingPreviewCount(group: ListingTargetOption) {
  return Math.max(selectedCountForGroup(group) - previewProductCodes(group).length, 0)
}

function groupSummaryText(group: ListingTargetOption) {
  const selected = selectedCountForGroup(group)
  const total = group.product_codes.length
  const listed = group.listed_count || 0
  if (!total) return '当前套图暂无可用商品'
  if (!selected) return `共 ${total} 个商品，当前未勾选`
  return `已选 ${selected}/${total} 个商品，已上架 ${listed} 个`
}

function onMaterialGroupDropdownVisible(visible: boolean) {
  if (!visible) return
  if (accountId.value) loadListingTargets(accountId.value).catch(() => undefined)
}

function onAccountChange() {
  productCodes.value = []
  checkedProductsBySet.value = {}
}

async function loadMinioHealth() {
  try {
    minioHealth.value = await api.minioHealth()
  } catch (e) {
    minioHealth.value = { available: false, error: e instanceof Error ? e.message : 'MinIO 不可用' }
  }
}

async function loadListingTargets(forAccountId = '') {
  productOptions.value = await api.listingTargets(forAccountId || undefined, materialSource.value)
}

async function onMaterialSourceChange(source: 'local' | 'minio') {
  materialSource.value = source
  productCodes.value = []
  checkedProductsBySet.value = {}
  if (source === 'minio') {
    await loadMinioHealth()
    if (!minioHealth.value?.available) {
      ElMessage.warning(minioHealth.value?.error || 'MinIO 未就绪，请检查 config/minio.yaml')
    }
  }
  stopMaterialRefresh()
  if (accountId.value) await loadListingTargets(accountId.value)
  restartMaterialRefresh()
}

async function loadBaseData() {
  const [acc, activityList, cfg] = await Promise.all([
    api.accounts(true),
    api.campaignMarketingActivities(),
    api.runtimeConfig(),
  ])
  accounts.value = acc
  activities.value = activityList.items || []
  startDelayMin.value = cfg.batch.store_start_delay_min_seconds ?? 30
  startDelayMax.value = cfg.batch.store_start_delay_max_seconds ?? 180
  if (!accountId.value && enabledAccounts.value.length) {
    accountId.value = enabledAccounts.value[0].account_id
  }
  if (!batchAccountIds.value.length && enabledAccounts.value.length) {
    batchAccountIds.value = enabledAccounts.value.map((a) => a.account_id)
  }
  if (!activityIds.value.length && activities.value.length) {
    activityIds.value = [activities.value[0].activity_id]
  }
  await loadListingTargets(accountId.value)
}

async function loadExcelFallbackSetting() {
  const data = await api.getPipelineExcelFallback()
  excelFallbackEnabled.value = !!data.enabled
}

function applyAutoUploadConfig(cfg: AutoUploadConfig) {
  const accountIds =
    cfg.account_ids?.length ? [...cfg.account_ids] : cfg.account_id ? [cfg.account_id] : []
  autoUploadConfig.value = {
    ...cfg,
    account_ids: accountIds,
    account_id: accountIds[0] || cfg.account_id || '',
  }
  autoUploadEnabled.value = !!cfg.enabled
  autoUploadTriggerMode.value = cfg.trigger_mode || 'new_product_folder'
}

async function loadAutoUploadConfig() {
  const data = await api.getAutoUploadConfig()
  applyAutoUploadConfig(data)
}

function buildAutoUploadPayload(overrides: Partial<AutoUploadConfig> = {}): AutoUploadConfig {
  const accountIds =
    autoUploadConfig.value.account_ids?.length
      ? [...autoUploadConfig.value.account_ids]
      : autoUploadConfig.value.account_id
        ? [autoUploadConfig.value.account_id]
        : []
  return {
    ...autoUploadConfig.value,
    enabled: autoUploadEnabled.value,
    trigger_mode: autoUploadTriggerMode.value,
    account_ids: accountIds,
    account_id: accountIds[0] || accountId.value,
    ...overrides,
  }
}

async function saveAutoUploadConfig(
  overrides: Partial<AutoUploadConfig> = {},
  options: { manageSaving?: boolean } = {},
) {
  const manageSaving = options.manageSaving !== false
  if (manageSaving) autoUploadSaving.value = true
  try {
    const payload = buildAutoUploadPayload(overrides)
    if (payload.enabled && !payload.account_ids.length) {
      throw new Error('开启自动上架时请选择至少一家店铺')
    }
    if (payload.enabled && !payload.activity_ids.length) {
      throw new Error('开启自动上架时请至少选择一个活动')
    }
    const saved = await api.updateAutoUploadConfig(payload)
    applyAutoUploadConfig(saved)
    return saved
  } finally {
    if (manageSaving) autoUploadSaving.value = false
  }
}

async function onAutoUploadToggle(enabled: boolean) {
  try {
    await saveAutoUploadConfig({ enabled })
    ElMessage.success(enabled ? '已开启 RabbitMQ 自动上架' : '已关闭 RabbitMQ 自动上架')
  } catch (e) {
    autoUploadEnabled.value = !enabled
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function onAutoUploadTriggerModeChange(mode: AutoUploadTriggerMode) {
  autoUploadTriggerMode.value = mode
  try {
    await saveAutoUploadConfig({ trigger_mode: mode })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function openAutoUploadConfigDialog() {
  autoUploadConfig.value.trigger_mode = autoUploadTriggerMode.value
  if (!autoUploadConfig.value.account_id && accountId.value) {
    autoUploadConfig.value.account_id = accountId.value
  }
  if (!autoUploadConfig.value.activity_ids.length && activityIds.value.length) {
    autoUploadConfig.value.activity_ids = [...activityIds.value]
  }
  try {
    await loadAccessoryCostPricingSetting()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '读取配件成本定价配置失败')
  }
  autoUploadConfigVisible.value = true
}

async function confirmAutoUploadConfig() {
  autoUploadSaving.value = true
  try {
    await saveAutoUploadConfig(
      {
      account_ids: autoUploadConfig.value.account_ids,
      account_id: autoUploadConfig.value.account_ids[0] || autoUploadConfig.value.account_id,
      trigger_mode: autoUploadConfig.value.trigger_mode,
      activity_ids: autoUploadConfig.value.activity_ids,
      category_keyword: autoUploadConfig.value.category_keyword,
      auto_promotion: autoUploadConfig.value.auto_promotion,
      continue_after_limited_time_failure: autoUploadConfig.value.continue_after_limited_time_failure,
      continue_after_activity_failure: autoUploadConfig.value.continue_after_activity_failure,
      demo_mode: autoUploadConfig.value.demo_mode,
      activity_delay_hours: autoUploadConfig.value.activity_delay_hours,
      slot_alignment_test: autoUploadConfig.value.slot_alignment_test,
      material_source: autoUploadConfig.value.material_source,
      auto_sync_minio: autoUploadConfig.value.auto_sync_minio,
      },
      { manageSaving: false },
    )
    const pricing = await api.updatePipelineAccessoryCostPricing(accessoryCostPricingEnabled.value)
    accessoryCostPricingEnabled.value = !!pricing.enabled
    accessoryCostPricingFloatMin.value = Number(pricing.float_min ?? 0)
    accessoryCostPricingFloatMax.value = Number(pricing.float_max ?? 5)
    const originalSum = await api.updatePipelineOriginalSumPricing(originalSumPricingEnabled.value)
    originalSumPricingEnabled.value = !!originalSum.enabled
    if (originalSumPricingEnabled.value) {
      accessoryCostPricingEnabled.value = false
      accessoryCostTieredFloatEnabled.value = false
    } else if (accessoryCostPricingEnabled.value) {
      const tiered = await api.updatePipelineAccessoryTieredFloat(accessoryCostTieredFloatEnabled.value)
      accessoryCostTieredFloatEnabled.value = !!tiered.enabled
    } else {
      accessoryCostTieredFloatEnabled.value = false
    }
    autoUploadConfigVisible.value = false
    ElMessage.success('自动上架配置已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    autoUploadSaving.value = false
  }
}

const autoUploadTriggerModeLabel = computed(() => {
  if (autoUploadTriggerMode.value === 'append_to_product') return '仅追加图片'
  if (autoUploadTriggerMode.value === 'all') return '都可以'
  return '新增文件夹'
})

async function onExcelFallbackChange(enabled: boolean) {
  excelFallbackSaving.value = true
  try {
    const data = await api.updatePipelineExcelFallback(enabled)
    excelFallbackEnabled.value = !!data.enabled
    ElMessage.success(enabled ? '已开启本地 Excel 回退' : '已关闭本地 Excel 回退')
  } catch (e) {
    excelFallbackEnabled.value = !enabled
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    excelFallbackSaving.value = false
  }
}

async function loadAccessoryCostPricingSetting() {
  const data = await api.getPipelineAccessoryCostPricing()
  accessoryCostPricingEnabled.value = !!data.enabled
  accessoryCostPricingFloatMin.value = Number(data.float_min ?? 0)
  accessoryCostPricingFloatMax.value = Number(data.float_max ?? 5)
  try {
    const tiered = await api.getPipelineAccessoryTieredFloat()
    accessoryCostTieredFloatEnabled.value = !!tiered.enabled
  } catch {
    accessoryCostTieredFloatEnabled.value = false
  }
  try {
    const originalSum = await api.getPipelineOriginalSumPricing()
    originalSumPricingEnabled.value = !!originalSum.enabled
  } catch {
    originalSumPricingEnabled.value = false
  }
}

async function onAccessoryCostPricingChange(enabled: boolean) {
  if (enabled && originalSumPricingEnabled.value) {
    accessoryCostPricingEnabled.value = false
    ElMessage.warning('已开启原价相加，无法同时开启配件成本定价')
    return
  }
  accessoryCostPricingSaving.value = true
  try {
    const data = await api.updatePipelineAccessoryCostPricing(enabled)
    accessoryCostPricingEnabled.value = !!data.enabled
    accessoryCostPricingFloatMin.value = Number(data.float_min ?? 0)
    accessoryCostPricingFloatMax.value = Number(data.float_max ?? 5)
    if (enabled) {
      originalSumPricingEnabled.value = false
    } else {
      accessoryCostTieredFloatEnabled.value = false
    }
    ElMessage.success(enabled ? '已开启配件成本定价' : '已关闭配件成本定价')
  } catch (e) {
    accessoryCostPricingEnabled.value = !enabled
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    accessoryCostPricingSaving.value = false
  }
}

async function onAccessoryCostTieredFloatChange(enabled: boolean) {
  if (originalSumPricingEnabled.value) {
    accessoryCostTieredFloatEnabled.value = false
    ElMessage.warning('已开启原价相加，无法同时开启子商品档位浮动')
    return
  }
  if (!accessoryCostPricingEnabled.value) {
    accessoryCostTieredFloatEnabled.value = false
    ElMessage.warning('请先开启配件成本定价')
    return
  }
  accessoryCostTieredFloatSaving.value = true
  try {
    const data = await api.updatePipelineAccessoryTieredFloat(enabled)
    accessoryCostTieredFloatEnabled.value = !!data.enabled
    ElMessage.success(enabled ? '已开启子商品档位浮动' : '已关闭子商品档位浮动')
  } catch (e) {
    accessoryCostTieredFloatEnabled.value = !enabled
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    accessoryCostTieredFloatSaving.value = false
  }
}

async function onOriginalSumPricingChange(enabled: boolean) {
  if (enabled && (accessoryCostPricingEnabled.value || accessoryCostTieredFloatEnabled.value)) {
    // 允许开启：后端会关闭冲突开关
  }
  originalSumPricingSaving.value = true
  try {
    const data = await api.updatePipelineOriginalSumPricing(enabled)
    originalSumPricingEnabled.value = !!data.enabled
    if (enabled) {
      accessoryCostPricingEnabled.value = false
      accessoryCostTieredFloatEnabled.value = false
    }
    ElMessage.success(enabled ? '已开启原价相加' : '已关闭原价相加')
  } catch (e) {
    originalSumPricingEnabled.value = !enabled
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    originalSumPricingSaving.value = false
  }
}

function onAiGenerateTitleClick() {
  onSubmitAiTitleToggle()
}

async function loadSubmitAiTitleSetting() {
  const data = await api.getPipelineSubmitAiTitle()
  submitAiTitleEnabled.value = !!data.enabled
}

async function onSubmitAiTitleToggle() {
  aiGenerateTitleLoading.value = true
  const next = !submitAiTitleEnabled.value
  try {
    const data = await api.updatePipelineSubmitAiTitle({ enabled: next })
    submitAiTitleEnabled.value = !!data.enabled
    ElMessage.success(data.enabled ? '已开启提交前 AI 标题' : '已关闭提交前 AI 标题')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    aiGenerateTitleLoading.value = false
  }
}

async function loadLogSpecSkuRowsSetting() {
  const data = await api.getPipelineLogSpecSkuRows()
  logSpecSkuRowsEnabled.value = !!data.enabled
}

async function loadPlatformSkipDedupeSetting() {
  const data = await api.getPipelinePlatformSkipDedupe()
  platformSkipDedupeEnabled.value = !!data.enabled
  platformSkipDedupeCodeCount.value = Number(data.code_count || 0)
  platformSkipDedupeUpdatedAt.value = String(data.updated_at || data.last_sync_at || '')
}

async function onPlatformSkipDedupeChange(enabled: boolean) {
  platformSkipDedupeSaving.value = true
  try {
    const data = await api.updatePipelinePlatformSkipDedupe(enabled)
    platformSkipDedupeEnabled.value = !!data.enabled
    platformSkipDedupeCodeCount.value = Number(data.code_count || 0)
    platformSkipDedupeUpdatedAt.value = String(data.updated_at || data.last_sync_at || '')
    ElMessage.success(
      enabled
        ? `已开启平台跳过去重，Redis 缓存 ${data.code_count} 个编码`
        : '已关闭平台跳过去重',
    )
  } catch (e) {
    platformSkipDedupeEnabled.value = !enabled
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    platformSkipDedupeSaving.value = false
  }
}

async function onLogSpecSkuRowsChange(enabled: boolean) {
  logSpecSkuRowsSaving.value = true
  try {
    const data = await api.updatePipelineLogSpecSkuRows(enabled)
    logSpecSkuRowsEnabled.value = !!data.enabled
    ElMessage.success(
      enabled ? '已开启按规格编码展开写发布日志' : '已关闭按规格编码展开（仅写商品摘要行）',
    )
  } catch (e) {
    logSpecSkuRowsEnabled.value = !enabled
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    logSpecSkuRowsSaving.value = false
  }
}

async function loadFailureLogSetting() {
  const data = await api.feishuFailureLogSettings()
  failureLogEnabled.value = !!data.failure_log_enabled
  failureLogTableName.value = String(data.failure_table_name || '')
}

async function onFailureLogChange(enabled: boolean) {
  failureLogSaving.value = true
  try {
    const data = await api.updateFeishuFailureLogSettings({ failure_log_enabled: enabled })
    failureLogEnabled.value = !!data.failure_log_enabled
    failureLogTableName.value = String(data.failure_table_name || '')
    ElMessage.success(
      enabled
        ? '已开启：上架失败/跳过会写入飞书失败表'
        : '已关闭：本次及后续发布不再写入飞书失败表（本地任务记录仍保留）',
    )
  } catch (e) {
    failureLogEnabled.value = !enabled
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    failureLogSaving.value = false
  }
}

async function refreshCommerceOverview() {
  commerceLoading.value = true
  try {
    commerceOverview.value = await api.commerceOverview()
  } catch {
    commerceOverview.value = {
      lifecycles: [],
      pending_intents: [],
      pending_total: 0,
      pending_by_account: {},
    }
  } finally {
    commerceLoading.value = false
  }
}

async function dispatchCommerceForAccount(targetAccountId: string) {
  const id = String(targetAccountId || '').trim()
  if (!id) return
  commerceDispatchingAccount.value = id
  try {
    const result = await api.dispatchCommerceAccount(id)
    if (result.dispatched && result.pipeline_id) {
      ElMessage.success(`已派发排队任务，链路 ${result.pipeline_id}`)
      pipelinePage.value = 1
      await refreshPipelines()
      startPolling()
    } else if (result.queued_again) {
      ElMessage.warning('店铺仍被占用，任务继续排队')
      await refreshCommerceOverview()
    } else {
      ElMessage.info(result.message || '当前没有可派发的排队任务')
      await refreshCommerceOverview()
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    commerceDispatchingAccount.value = ''
  }
}

async function dispatchAllCommerce() {
  commerceDispatchingAll.value = true
  try {
    const result = await api.dispatchCommerceAll()
    if (result.count > 0) {
      const extra =
        result.nudged || result.synced
          ? `（推进 ${result.nudged || 0} 条等待活动，同步 ${result.synced || 0} 条周期）`
          : ''
      ElMessage.success(`已尝试派发 ${result.count} 条排队任务${extra}`)
      pipelinePage.value = 1
      await refreshPipelines()
      startPolling()
    } else {
      const extra =
        result.nudged || result.synced
          ? `已推进 ${result.nudged || 0} 条等待活动，同步 ${result.synced || 0} 条周期`
          : '暂无排队任务可派发'
      ElMessage.info(extra)
      await refreshCommerceOverview()
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    commerceDispatchingAll.value = false
  }
}

async function cancelCommerceIntentRow(intentId: string) {
  const id = String(intentId || '').trim()
  if (!id) return
  commerceCancelingIntent.value = id
  try {
    await api.cancelCommerceIntent(id)
    ElMessage.success('已取消排队任务')
    await refreshCommerceOverview()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    commerceCancelingIntent.value = ''
  }
}

async function resetCommerceAccountRow(targetAccountId: string) {
  const id = String(targetAccountId || '').trim()
  if (!id) return
  try {
    await ElMessageBox.confirm(
      `将重置店铺 ${accountDisplayName(id)}：\n· 取消该店所有进行中的整合链路\n· 清空排队任务\n· 清除「执行中/等活动」状态\n\n浏览器里正在跑的上架任务也会停止。`,
      '重置店铺运营状态',
      { type: 'warning', confirmButtonText: '确定重置', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  commerceResettingAccount.value = id
  try {
    const result = await api.resetCommerceAccount(id)
    const parts: string[] = []
    if (result.canceled_pipelines?.length) parts.push(`取消 ${result.canceled_pipelines.length} 条链路`)
    if (result.canceled_intents) parts.push(`清空 ${result.canceled_intents} 条排队`)
    if (result.lifecycle_cleared) parts.push('已清除运营状态')
    ElMessage.success(parts.length ? parts.join('，') : '店铺已重置')
    await Promise.all([refreshCommerceOverview(), refreshPipelines()])
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    commerceResettingAccount.value = ''
  }
}

async function resetAllCommerce() {
  const count = commerceAccountRows.value.length
  if (!count && !commerceOverview.value.pending_total) {
    ElMessage.info('当前没有需要重置的店铺')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将重置全部 ${count} 个活跃店铺及所有排队：\n· 取消各店进行中的整合链路\n· 清空全部排队\n· 清除运营状态\n\n此操作不可撤销。`,
      '重置全部店铺',
      { type: 'warning', confirmButtonText: '确定重置全部', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  commerceResettingAll.value = true
  try {
    const result = await api.resetCommerceAll({ all_accounts: true })
    const parts: string[] = []
    if (result.canceled_pipelines_total) parts.push(`取消 ${result.canceled_pipelines_total} 条链路`)
    if (result.canceled_intents_total) parts.push(`清空 ${result.canceled_intents_total} 条排队`)
    if (result.lifecycle_cleared_total) parts.push(`清除 ${result.lifecycle_cleared_total} 店状态`)
    if (result.stale_cleared) parts.push(`清理 ${result.stale_cleared} 条残留`)
    ElMessage.success(parts.length ? parts.join('，') : result.message || '已重置')
    await Promise.all([refreshCommerceOverview(), refreshPipelines()])
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  } finally {
    commerceResettingAll.value = false
  }
}

async function clearAllPendingIntents() {
  if (!commerceOverview.value.pending_total) {
    ElMessage.info('当前没有排队任务')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定清空全部 ${commerceOverview.value.pending_total} 条排队任务？\n不会取消已在执行的整合链路。`,
      '清空排队',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    const result = await api.cancelCommerceIntents({ all_pending: true })
    ElMessage.success(`已清空 ${result.canceled_count} 条排队`)
    await refreshCommerceOverview()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
  }
}

async function refreshPipelines() {
  const page = pipelinePage.value
  const pageSize = pipelinePageSize.value
  const data = await api.listIntegratedPipelines({ page, page_size: pageSize })
  const resolvedPageSize = data.page_size ?? pageSize
  const items = data.items || []
  // 兼容旧后端一次返回全量的情况，避免表格行数超过每页条数
  pipelines.value = items.length > resolvedPageSize ? items.slice(0, resolvedPageSize) : items
  pipelineTotal.value = data.total ?? items.length
  if (typeof data.page === 'number' && data.page > 0) {
    pipelinePage.value = data.page
  }
  if (activePipeline.value) {
    const latest = pipelines.value.find((p) => p.pipeline_id === activePipeline.value?.pipeline_id)
    if (latest) {
      activePipeline.value = latest
    } else {
      try {
        activePipeline.value = await api.getIntegratedPipeline(activePipeline.value.pipeline_id)
      } catch {
        // 当前页未包含该链路时仍保留详情
      }
    }
  }
  await refreshCommerceOverview()
}

function onPipelinePageChange(page: number) {
  pipelinePage.value = page
  refreshPipelines().catch(() => undefined)
}

function onPipelinePageSizeChange(size: number) {
  pipelinePageSize.value = size
  pipelinePage.value = 1
  refreshPipelines().catch(() => undefined)
}

async function startPipeline() {
  error.value = ''
  success.value = ''
  const accountIds = pipelineBatchEnabled.value ? batchAccountIds.value.filter(Boolean) : [accountId.value]
  if (!accountIds.length) {
    error.value = pipelineBatchEnabled.value ? '请至少选择一家店铺' : '请选择店铺'
    return
  }
  if (!resolvedListingSelectors.value.length) {
    error.value = '请至少选择一套图里的一个商品'
    return
  }
  if (pipelineBatchEnabled.value && storeSequentialEnabled.value && accountIds.length < 2) {
    error.value = '店铺串行模式至少需要选择 2 家店铺'
    return
  }
  const listingIntent = await resolveListingIntent()
  if (!listingIntent) return
  const { skipListing, listingSkipSelectors } = listingIntent
  loading.value = true
  try {
    if (pipelineBatchEnabled.value) {
      const result = await api.startIntegratedPipelineBatch({
        account_ids: accountIds,
        product_codes: resolvedListingSelectors.value,
        activity_ids: activityIds.value,
        activity_id: activityIds.value[0],
        category_keyword: categoryKeyword.value,
        auto_promotion: autoPromotion.value,
        continue_after_limited_time_failure: continueAfterLimitedTimeFailure.value,
        continue_after_activity_failure: continueAfterActivityFailure.value,
        promote_after_limited_time_failure: promoteAfterLimitedTimeFailure.value,
        activity_delay_hours: demoMode.value ? 0 : activityDelayHours.value,
        demo_mode: demoMode.value,
        slot_alignment_test: slotAlignmentTest.value,
        spec_fill_verify_test: specFillVerifyTest.value,
        primary_style_first_test: primaryStyleFirstTest.value,
        paren_size_as_product_type: parenSizeAsProductType.value,
        category_next_burst_demo: categoryNextBurstDemo.value,
        store_start_delay_min_seconds: startDelayMin.value,
        store_start_delay_max_seconds: startDelayMax.value,
        skip_listing: skipListing,
        listing_skip_selectors: listingSkipSelectors,
        material_source: materialSource.value,
        relist_strategy: relistStrategy.value,
        listing_throttle_enabled: listingThrottleEnabled.value,
        listing_batch_set_count: listingBatchSetCount.value,
        listing_batch_interval_minutes: listingBatchIntervalMinutes.value,
        listing_per_batch_limited_time_enabled: listingPerBatchLimitedTimeEnabled.value,
        listing_per_batch_campaign_enabled: listingPerBatchCampaignEnabled.value,
        listing_per_batch_lt_traffic_activity_enabled: listingPerBatchLtTrafficActivityEnabled.value,
        listing_per_batch_promote_lt_success_only_enabled: listingPerBatchPromoteLtSuccessOnlyEnabled.value,
        store_sequential_enabled: storeSequentialEnabled.value,
        delist_spec_code_search_enabled: delistSpecCodeSearchEnabled.value,
        activity_limited_time_success_only: activityLimitedTimeSuccessOnly.value,
        activity_traffic_batch_enabled: activityTrafficBatchEnabled.value,
        activity_traffic_batch_size: activityTrafficBatchSize.value,
        per_batch_limited_time_chunk_size: perBatchLimitedTimeChunkSize.value,
        batch_limited_time_auto_retry_enabled: batchLimitedTimeAutoRetryEnabled.value,
        batch_limited_time_auto_retry_max_attempts: batchLimitedTimeAutoRetryMaxAttempts.value,
      })
      success.value = `批量整合链路已提交：${result.total} 家店铺${
        result.store_sequential_enabled
          ? `（串行：第 1 家已启动，其余 ${result.pending_stores ?? 0} 家待前店上架+限时限量购完成后自动启动；店间间隔 ${result.store_start_delay_min_seconds}-${result.store_start_delay_max_seconds} 秒；活动次日执行）`
          : `，批次 ${result.batch_id}，启动间隔 ${result.store_start_delay_min_seconds}-${result.store_start_delay_max_seconds} 秒`
      }，活动 ${activityIds.value.length} 个${
        listingThrottleEnabled.value
          ? `；分批上架 ${listingBatchSetCount.value} 套/批，间隔 ${listingBatchIntervalMinutes.value} 分钟${
              listingPerBatchLimitedTimeEnabled.value ? '，每批限时限量购' : ''
            }${listingPerBatchCampaignEnabled.value ? '，每批活动/推广' : ''}`
          : ''
      }`
      pipelinePage.value = 1
      if (result.pipelines.length) {
        const first = await api.getIntegratedPipeline(result.pipelines[0].pipeline_id)
        activePipeline.value = first
      }
    } else {
      const result = await api.startIntegratedPipeline({
        account_id: accountId.value,
        product_codes: resolvedListingSelectors.value,
        activity_ids: activityIds.value,
        activity_id: activityIds.value[0],
        category_keyword: categoryKeyword.value,
        auto_promotion: autoPromotion.value,
        continue_after_limited_time_failure: continueAfterLimitedTimeFailure.value,
        continue_after_activity_failure: continueAfterActivityFailure.value,
        promote_after_limited_time_failure: promoteAfterLimitedTimeFailure.value,
        activity_delay_hours: demoMode.value ? 0 : activityDelayHours.value,
        demo_mode: demoMode.value,
        slot_alignment_test: slotAlignmentTest.value,
        spec_fill_verify_test: specFillVerifyTest.value,
        primary_style_first_test: primaryStyleFirstTest.value,
        paren_size_as_product_type: parenSizeAsProductType.value,
        category_next_burst_demo: categoryNextBurstDemo.value,
        skip_listing: skipListing,
        listing_skip_selectors: listingSkipSelectors,
        material_source: materialSource.value,
        relist_strategy: relistStrategy.value,
        listing_throttle_enabled: listingThrottleEnabled.value,
        listing_batch_set_count: listingBatchSetCount.value,
        listing_batch_interval_minutes: listingBatchIntervalMinutes.value,
        listing_per_batch_limited_time_enabled: listingPerBatchLimitedTimeEnabled.value,
        listing_per_batch_campaign_enabled: listingPerBatchCampaignEnabled.value,
        listing_per_batch_lt_traffic_activity_enabled: listingPerBatchLtTrafficActivityEnabled.value,
        listing_per_batch_promote_lt_success_only_enabled: listingPerBatchPromoteLtSuccessOnlyEnabled.value,
        delist_spec_code_search_enabled: delistSpecCodeSearchEnabled.value,
        activity_limited_time_success_only: activityLimitedTimeSuccessOnly.value,
        activity_traffic_batch_enabled: activityTrafficBatchEnabled.value,
        activity_traffic_batch_size: activityTrafficBatchSize.value,
        per_batch_limited_time_chunk_size: perBatchLimitedTimeChunkSize.value,
        batch_limited_time_auto_retry_enabled: batchLimitedTimeAutoRetryEnabled.value,
        batch_limited_time_auto_retry_max_attempts: batchLimitedTimeAutoRetryMaxAttempts.value,
      })
      pipelinePage.value = 1
      if (result.commerce_queued) {
        const mergedHint = result.is_merged ? '（已合并到现有排队）' : ''
        success.value =
          (result.block_reason_label ||
            `任务已排队（${result.intent_id || '—'}），当前店铺有进行中的运营周期`) + mergedHint
        await refreshCommerceOverview()
        return
      }
      activePipeline.value = result
      const activityCount = activityIds.value.length
      const activityHint = activityCount > 1 ? `，${activityCount} 个活动将依次报名` : ''
      const partialHint = listingSkipSelectors.length
        ? `（已上架 ${listingSkipSelectors.length} 个跳过上架）`
        : ''
      const relistHint =
        relistStrategy.value === 'delist_and_relist'
          ? '（将先下架原商品并删除已发布记录）'
          : ''
      const throttleHint = listingThrottleEnabled.value
        ? `（分批上架：${selectedSetCount.value} 套分 ${listingBatchPlanCount.value} 批，每批 ${listingBatchSetCount.value} 套，间隔 ${listingBatchIntervalMinutes.value} 分钟${
            listingPerBatchLimitedTimeEnabled.value ? '，每批限时限量购' : ''
          }${listingPerBatchCampaignEnabled.value ? '，每批活动/推广' : ''}）`
        : ''
      success.value = skipListing
        ? demoMode.value
          ? `整合链路已启动（跳过上架，先限时限量购再约 2 分钟后报活动${activityHint}）`
          : `整合链路已启动（跳过上架，先限时限量购再 ${activityDelayHours.value} 小时后报活动${activityHint}）`
        : demoMode.value
          ? `整合链路已启动（演示：上架后限时限量购 → 约 2 分钟后报活动${activityHint}${partialHint}${relistHint}${throttleHint}）`
          : `整合链路已启动（上架 → 限时限量购 → ${activityDelayHours.value} 小时后报活动${activityHint}${partialHint}${relistHint}${throttleHint}）`
    }
    await refreshPipelines()
    startPolling()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function startPolling() {
  if (pollTimer) return
  polling.value = true
  pollTimer = setInterval(() => {
    refreshPipelines().catch(() => undefined)
  }, 5000)
}

function stopPolling() {
  polling.value = false
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function openRun(runId: string) {
  if (!runId) return
  router.push({ path: '/runs', query: { run_id: runId } })
}

watch(productCodes, (codes) => syncCheckedProductsForSets(codes), { deep: true })
const selectedSetCount = computed(() => productCodes.value.length)

const listingBatchPlanCount = computed(() => {
  if (!listingThrottleEnabled.value || selectedSetCount.value <= 0) return 1
  return Math.ceil(selectedSetCount.value / Math.max(1, listingBatchSetCount.value))
})

const activityTrafficBatchDisabled = computed(
  () =>
    listingPerBatchLtTrafficActivityEnabled.value
    || listingPerBatchCampaignEnabled.value
    || !autoPromotion.value,
)

watch(relistStrategy, (value) => {
  savePipelineRelistStrategy(value)
})

watch(listingThrottleEnabled, (value) => {
  saveListingThrottleEnabled(value)
  if (!value) {
    listingPerBatchLimitedTimeEnabled.value = false
    listingPerBatchCampaignEnabled.value = false
  }
})

watch(listingBatchSetCount, (value) => {
  saveListingBatchSetCount(Number(value) || 5)
})

watch(randomSelectCount, (value) => {
  saveRandomSelectCount(Number(value) || 3)
})

watch(listingBatchIntervalMinutes, (value) => {
  saveListingBatchIntervalMinutes(Number(value) || 30)
})

watch(listingPerBatchLimitedTimeEnabled, (value) => {
  saveListingPerBatchLimitedTimeEnabled(value)
  if (!value) {
    batchLimitedTimeAutoRetryEnabled.value = false
  }
})

watch(listingPerBatchCampaignEnabled, (value) => {
  saveListingPerBatchCampaignEnabled(value)
  if (value) {
    listingPerBatchLtTrafficActivityEnabled.value = false
    activityTrafficBatchEnabled.value = false
    batchLimitedTimeAutoRetryEnabled.value = false
  }
})

watch(listingPerBatchLtTrafficActivityEnabled, (value) => {
  saveListingPerBatchLtTrafficActivityEnabled(value)
  if (value) {
    listingPerBatchCampaignEnabled.value = false
    activityTrafficBatchEnabled.value = false
    listingPerBatchLimitedTimeEnabled.value = true
    listingThrottleEnabled.value = true
    batchLimitedTimeAutoRetryEnabled.value = false
  }
})

watch(listingPerBatchPromoteLtSuccessOnlyEnabled, (value) => {
  saveListingPerBatchPromoteLtSuccessOnlyEnabled(value)
})

watch(delistSpecCodeSearchEnabled, (value) => {
  saveDelistSpecCodeSearchEnabled(value)
})

watch(activityLimitedTimeSuccessOnly, (value) => {
  saveActivityLimitedTimeSuccessOnly(value)
  if (value) {
    continueAfterLimitedTimeFailure.value = false
  }
})

watch(activityTrafficBatchEnabled, (value) => {
  saveActivityTrafficBatchEnabled(value)
})

watch(activityTrafficBatchSize, (value) => {
  saveActivityTrafficBatchSize(Number(value) || 10)
})

watch(perBatchLimitedTimeChunkSize, (value) => {
  savePerBatchLimitedTimeChunkSize(Number(value) || 10)
})

watch(batchLimitedTimeAutoRetryEnabled, (value) => {
  saveBatchLimitedTimeAutoRetryEnabled(value)
})

watch(batchLimitedTimeAutoRetryMaxAttempts, (value) => {
  saveBatchLimitedTimeAutoRetryMaxAttempts(Number(value) || 1)
})

watch(autoPromotion, (value) => {
  if (!value) {
    activityTrafficBatchEnabled.value = false
  }
})

watch(resolvedListingSelectors, () => {
  preflightResult.value = null
})
watch(accountId, (id) => {
  if (id) loadListingTargets(id).catch(() => undefined)
})

onMounted(async () => {
  try {
    await loadMinioHealth()
    await loadBaseData()
    await loadExcelFallbackSetting()
    await loadAccessoryCostPricingSetting()
    await loadSubmitAiTitleSetting()
    await loadLogSpecSkuRowsSetting()
    await loadPlatformSkipDedupeSetting()
    await loadFailureLogSetting()
    await loadAutoUploadConfig()
    await refreshPipelines()
    if (materialSource.value === 'minio') {
      await resumeActiveSync((msg) => {
        ElMessage.error(msg)
      })
    }
    startPolling()
    restartMaterialRefresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="page">
    <PageHeader
      title="整合链路"
      subtitle="一套图走完：上架 → 隔日自动报活动 → 活动成功后自动推广（Demo）"
    />

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="tip"
      title="链路说明"
      description="选好店铺、一套图、一个或多个活动后点一次即可。上架完成后系统会按设定时间自动报活动；多个活动将按顺序依次报名，全部完成后再自动创建推广。拼多多要求新上架商品通常隔 1 天才能报活动，正式使用请关闭演示模式并设 24 小时。"
    />

    <el-row :gutter="16" class="pipeline-layout">
      <el-col :span="13" :xs="24">
        <el-card shadow="never" class="stat-card task-card">
          <template #header>新建整合任务</template>

          <el-form label-position="top" class="pipeline-form">
            <div class="form-section">
              <div class="form-section-title">店铺</div>
              <el-form-item label="批量店铺">
                <div class="batch-toggle-row">
                  <el-switch v-model="pipelineBatchEnabled" active-text="开启" inactive-text="关闭" />
                </div>
                <div v-if="pipelineBatchEnabled" class="form-tip">
                  {{
                    storeSequentialEnabled
                      ? '串行模式：每家店「上架 + 限时限量购（含全部分批）」全部完成后立即启动下一家；活动次日按预约执行，推广在活动之后，均不阻塞下一家'
                      : '多店共用下方素材选择，各店按启动间隔错开入队（可并行）'
                  }}
                </div>
              </el-form-item>

              <el-form-item v-if="pipelineBatchEnabled" label="店铺串行">
                <div class="batch-toggle-row">
                  <el-switch
                    v-model="storeSequentialEnabled"
                    active-text="一家跑完再跑下一家"
                    inactive-text="错开并行"
                  />
                </div>
                <div v-if="storeSequentialEnabled" class="form-tip">
                  推荐开启：同一时刻仅一家店在跑，风控更安全。分批上架仍在单店内按批执行，不会跨店穿插。
                </div>
              </el-form-item>

              <el-form-item v-if="pipelineBatchEnabled" label="选择店铺" required>
                <el-select
                  v-model="batchAccountIds"
                  multiple
                  filterable
                  collapse-tags
                  collapse-tags-tooltip
                  placeholder="选择要执行的店铺"
                  style="width: 100%"
                >
                  <el-option
                    v-for="acc in enabledAccounts"
                    :key="acc.account_id"
                    :label="acc.account_id"
                    :value="acc.account_id"
                  />
                </el-select>
              </el-form-item>

              <el-form-item v-else label="选择店铺" required>
                <el-select
                  v-model="accountId"
                  placeholder="请选择店铺"
                  style="width: 100%"
                  @change="onAccountChange"
                >
                  <el-option
                    v-for="acc in enabledAccounts"
                    :key="acc.account_id"
                    :label="acc.account_id"
                    :value="acc.account_id"
                  />
                </el-select>
              </el-form-item>

              <el-alert
                v-if="selectedAccountCommerceHint"
                type="warning"
                :closable="false"
                show-icon
                class="commerce-account-hint"
                :title="`当前店铺：${selectedAccountCommerceHint}`"
                description="若此时启动整合链路，任务会自动进入排队；当前周期结束后系统会尝试自动派发。"
              />

              <el-row v-if="pipelineBatchEnabled" :gutter="16">
                <el-col :span="12">
                  <el-form-item :label="storeSequentialEnabled ? '店间间隔最小秒数' : '启动间隔最小秒数'">
                    <el-input-number v-model="startDelayMin" :min="0" :max="3600" style="width: 100%" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item :label="storeSequentialEnabled ? '店间间隔最大秒数' : '启动间隔最大秒数'">
                    <el-input-number
                      v-model="startDelayMax"
                      :min="startDelayMin"
                      :max="3600"
                      style="width: 100%"
                    />
                  </el-form-item>
                </el-col>
              </el-row>
            </div>

            <div class="form-section form-section-material">
              <div class="form-section-title">素材与商品</div>

              <el-form-item required class="material-form-item">
                <div class="material-panel">
                  <div class="material-panel-toolbar">
                    <div class="material-source-row">
                      <el-radio-group
                        :model-value="materialSource"
                        size="small"
                        class="source-segment"
                        @change="onMaterialSourceChange($event as 'local' | 'minio')"
                      >
                        <el-radio-button label="local">本地文件夹</el-radio-button>
                        <el-radio-button label="minio">MinIO</el-radio-button>
                      </el-radio-group>
                      <el-tag
                        v-if="materialSource === 'minio'"
                        size="small"
                        :type="minioHealth?.available ? 'success' : 'danger'"
                      >
                        {{ minioHealth?.available ? 'MinIO 已连接' : (minioHealth?.error || 'MinIO 未连接') }}
                      </el-tag>
                      <el-tag v-if="materialSource === 'minio' && materialRefreshPaused" size="small" type="warning">
                        已暂停拉取
                      </el-tag>
                      <el-tag v-else-if="materialSource === 'minio' && refreshMode === 'poll' && materialPolling" size="small" type="info">
                        自动刷新
                      </el-tag>
                      <template v-if="materialSource === 'minio'">
                        <el-radio-group
                          :model-value="refreshMode"
                          size="small"
                          :disabled="switchingMode"
                          @change="setRefreshMode($event as 'poll' | 'rabbitmq')"
                        >
                          <el-radio-button label="poll">定时 {{ minioHealth?.listing_poll_seconds ?? 30 }}s</el-radio-button>
                          <el-radio-button label="rabbitmq">RabbitMQ 推送</el-radio-button>
                        </el-radio-group>
                        <el-switch
                          :model-value="!materialRefreshPaused"
                          inline-prompt
                          active-text="自动拉取"
                          inactive-text="已关闭"
                          @change="setMaterialRefreshPaused(!$event)"
                        />
                        <el-tag v-if="!materialRefreshPaused && refreshMode === 'rabbitmq' && sseConnected" size="small" type="success">实时监听</el-tag>
                        <el-tag v-else-if="!materialRefreshPaused && refreshMode === 'rabbitmq'" size="small" type="warning">推送未连接</el-tag>
                      </template>
                    </div>
                    <el-radio-group v-model="showOnlyUnlistedGroups" size="small" class="filter-segment">
                      <el-radio-button :label="true">
                        仅未上架{{ unlistedGroupCount ? ` (${unlistedGroupCount})` : '' }}
                      </el-radio-button>
                      <el-radio-button :label="false">全部套图</el-radio-button>
                    </el-radio-group>
                    <div class="random-select-actions">
                      <span class="random-select-label">随机</span>
                      <el-input-number
                        v-model="randomSelectCount"
                        size="small"
                        :min="1"
                        :max="100"
                        controls-position="right"
                        class="random-select-input"
                      />
                      <span class="random-select-label">套</span>
                      <el-button size="small" type="warning" plain @click="randomSelectMaterialGroups">
                        随机选
                      </el-button>
                    </div>
                    <div class="toolbar-actions">
                      <el-button size="small" type="primary" plain @click="selectAllMaterialGroups">全选</el-button>
                      <el-button size="small" @click="clearAllMaterialGroups">清空</el-button>
                      <el-button
                        v-if="materialSource === 'minio'"
                        size="small"
                        type="danger"
                        plain
                        :disabled="!resolvedListingSelectors.length"
                        :loading="deletingImageSets"
                        @click="deleteSelectedProducts"
                      >
                        删除商品
                      </el-button>
                      <el-button
                        size="small"
                        link
                        type="primary"
                        :disabled="!accountId"
                        @click="loadListingTargets(accountId)"
                      >
                        刷新
                      </el-button>
                    </div>
                    <div v-if="materialSource === 'minio'" class="auto-upload-row">
                      <el-switch
                        v-model="autoUploadEnabled"
                        inline-prompt
                        active-text="自动上架"
                        inactive-text="手动"
                        :loading="autoUploadSaving"
                        :disabled="refreshMode !== 'rabbitmq'"
                        @change="onAutoUploadToggle"
                      />
                      <el-select
                        v-model="autoUploadTriggerMode"
                        size="small"
                        class="auto-upload-mode-select"
                        :disabled="!autoUploadEnabled || autoUploadSaving"
                        @change="onAutoUploadTriggerModeChange($event as AutoUploadTriggerMode)"
                      >
                        <el-option label="新增文件夹（不含追加图片）" value="new_product_folder" />
                        <el-option label="仅追加图片" value="append_to_product" />
                        <el-option label="都可以" value="all" />
                      </el-select>
                      <el-button size="small" plain @click="openAutoUploadConfigDialog">自动化配置</el-button>
                      <el-tag v-if="autoUploadEnabled" size="small" type="success">
                        监听中 · {{ autoUploadTriggerModeLabel }}
                      </el-tag>
                      <el-tag v-else-if="refreshMode !== 'rabbitmq'" size="small" type="info">
                        需切换 RabbitMQ 推送
                      </el-tag>
                    </div>
                  </div>
                  <el-select
                    v-model="productCodes"
                    multiple
                    filterable
                    class="material-group-select"
                    popper-class="material-group-select-popper"
                    :placeholder="showOnlyUnlistedGroups ? '仅显示仍有待上架商品的套图' : '选择套图（如 BD720 · 第一套图）'"
                    style="width: 100%"
                    @visible-change="onMaterialGroupDropdownVisible"
                  >
                    <el-option-group
                      v-for="group in groupedVisibleProductOptions"
                      :key="group.family_code"
                      :label="`${group.family_code}（${group.options.length} 套）`"
                    >
                      <el-option
                        v-for="opt in group.options"
                        :key="opt.selector"
                        :label="formatMaterialGroupLabel(opt)"
                        :value="opt.selector"
                      >
                        <div class="material-option">
                          <div class="material-option-main">
                            <span class="material-option-set">{{ opt.image_set }}</span>
                            <span class="material-option-meta">{{ formatMaterialGroupMeta(opt) }}</span>
                          </div>
                          <div class="material-option-tags">
                            <el-tag v-if="opt.is_fully_listed" size="small" type="success" class="listed-tag">已全部上架</el-tag>
                            <el-tag v-else-if="opt.has_pending_listing" size="small" type="warning" class="listed-tag">
                              待上架 {{ opt.unlisted_count ?? 0 }}
                            </el-tag>
                            <el-tag
                              v-else-if="opt.is_material_ready === false && !(opt.product_count || opt.product_codes.length)"
                              size="small"
                              type="info"
                              class="listed-tag"
                            >
                              素材未就绪
                            </el-tag>
                          </div>
                        </div>
                      </el-option>
                    </el-option-group>
                  </el-select>
                  <div v-if="showOnlyUnlistedGroups && !visibleProductOptions.length" class="form-tip">
                    当前店铺暂无未上架套图
                  </div>
                  <div v-else-if="productCodes.length" class="selection-summary">
                    已选 {{ productCodes.length }} 套图
                  </div>
                </div>
              </el-form-item>

              <el-form-item v-if="selectedSetGroups.length" required>
                <template #label>
                  <span class="form-label-with-actions">
                    <span>上架商品</span>
                    <span class="label-actions">
                      <el-button link type="primary" size="small" @click="selectAllListingProducts">全选</el-button>
                      <el-button link size="small" @click="clearAllListingProducts">清空</el-button>
                    </span>
                  </span>
                </template>
                <div class="product-pick-panel">
                  <div class="selection-overview-card">
                    <div class="selection-overview-metrics">
                      <div class="selection-metric">
                        <span class="selection-metric-value">{{ selectedSetGroups.length }}</span>
                        <span class="selection-metric-label">已选套图</span>
                      </div>
                      <div class="selection-metric">
                        <span class="selection-metric-value">{{ selectedListingProductCount }}</span>
                        <span class="selection-metric-label">已选商品</span>
                      </div>
                      <div class="selection-metric">
                        <span class="selection-metric-value">{{ pendingSelectedSetCount }}</span>
                        <span class="selection-metric-label">待上架套图</span>
                      </div>
                    </div>
                    <div class="selection-overview-actions">
                      <el-button type="primary" plain size="small" @click="openSelectedSetDrawer">查看已选套图</el-button>
                      <el-button size="small" @click="selectAllListingProducts">全选商品</el-button>
                      <el-button size="small" @click="clearAllListingProducts">清空商品</el-button>
                    </div>
                    <div class="selection-overview-preview">
                      <el-tag v-for="group in selectedSetGroups.slice(0, 3)" :key="group.selector" effect="plain" round>
                        {{ group.family_code }} · {{ group.image_set }}
                      </el-tag>
                      <span v-if="selectedSetGroups.length > 3" class="selection-overview-more">
                        还有 {{ selectedSetGroups.length - 3 }} 套图
                      </span>
                    </div>
                  </div>
                </div>
              </el-form-item>

              <el-drawer
                v-model="selectedSetDrawerVisible"
                title="已选套图"
                size="860px"
                append-to-body
                class="selected-set-drawer"
                @close="closeSelectedSetDrawer"
              >
                <div class="product-pick-panel">
                  <div v-for="group in selectedSetGroups" :key="group.selector" class="product-pick-group">
                    <div class="product-pick-group-head">
                      <div class="product-pick-group-title">
                        <span class="pick-family">{{ group.family_code }}</span>
                        <span class="pick-set-badge">{{ group.image_set }}</span>
                        <el-tag v-if="group.is_fully_listed" size="small" type="success" class="listed-tag">套图已全部上架</el-tag>
                        <el-tag v-else-if="group.has_pending_listing" size="small" type="warning" class="listed-tag">
                          待上架 {{ group.unlisted_count ?? 0 }} 个
                        </el-tag>
                        <el-tag v-else-if="(group.listed_count || 0) > 0" size="small" type="info" class="listed-tag">
                          已上架 {{ group.listed_count }}/{{ group.product_codes.length }}
                        </el-tag>
                        <el-tag v-if="!selectedCountForGroup(group)" size="small" type="info" effect="plain">暂不上架</el-tag>
                        <el-tag
                          class="group-toggle-tag"
                          size="small"
                          :type="selectedCountForGroup(group) > 0 ? 'success' : 'info'"
                          effect="light"
                          @click="toggleGroupSelectionQuick(group)"
                        >
                          {{ selectedCountForGroup(group) > 0 ? '上架中（点设不上架）' : '不上架（点设上架）' }}
                        </el-tag>
                      </div>
                      <div class="product-pick-group-actions">
                        <el-button link type="primary" size="small" @click="openProductDrawer(group.selector)">查看商品</el-button>
                      </div>
                    </div>
                    <div class="product-pick-group-summary">{{ groupSummaryText(group) }}</div>
                    <div v-if="group.product_codes.length" class="product-pick-preview">
                      <el-tag
                        v-for="code in previewProductCodes(group)"
                        :key="code"
                        :type="productStatusType(group, code) as any"
                        effect="plain"
                        round
                      >
                        {{ code }}
                      </el-tag>
                      <span v-if="remainingPreviewCount(group)" class="product-pick-more">
                        +{{ remainingPreviewCount(group) }} 个
                      </span>
                    </div>
                    <div v-else class="empty-set-tip">
                      套图目录已存在，但暂无可用商品（需在套图下放入带 1.jpg/1.png 等编号主图的商品文件夹）
                    </div>
                  </div>
                </div>
              </el-drawer>

              <el-drawer
                :model-value="!!activeProductDrawerGroup"
                size="760px"
                destroy-on-close
                append-to-body
                class="product-detail-drawer"
                @close="closeProductDrawer"
              >
                <template #header>
                  <div v-if="activeProductDrawerGroup" class="product-drawer-header">
                    <div class="product-drawer-title-row">
                      <span class="pick-family">{{ activeProductDrawerGroup.family_code }}</span>
                      <span class="pick-set-badge">{{ activeProductDrawerGroup.image_set }}</span>
                    </div>
                    <div class="product-drawer-meta">{{ groupSummaryText(activeProductDrawerGroup) }}</div>
                  </div>
                </template>

                <div v-if="activeProductDrawerGroup" class="product-drawer-body">
                  <div class="product-drawer-actions">
                    <el-button size="small" @click="updateCheckedProducts(activeProductDrawerGroup.selector, [])">清空当前套图</el-button>
                    <el-button
                      size="small"
                      type="primary"
                      plain
                      @click="updateCheckedProducts(activeProductDrawerGroup.selector, [...activeProductDrawerGroup.product_codes])"
                    >
                      全选当前套图
                    </el-button>
                  </div>

                  <div v-if="activeProductDrawerGroup.product_codes.length" class="product-grid">
                    <div
                      v-for="code in activeProductDrawerGroup.product_codes"
                      :key="code"
                      class="product-card"
                      :class="{
                        'is-checked': isProductChecked(activeProductDrawerGroup, code),
                        'is-listed': isProductListed(activeProductDrawerGroup, code),
                      }"
                      @click="toggleProductChecked(activeProductDrawerGroup!, code, !isProductChecked(activeProductDrawerGroup, code))"
                    >
                      <div class="product-card-head">
                        <el-checkbox
                          :model-value="isProductChecked(activeProductDrawerGroup, code)"
                          @update:model-value="(val) => toggleProductChecked(activeProductDrawerGroup!, code, Boolean(val))"
                          @click.stop
                        />
                        <el-tag
                          :type="productStatusType(activeProductDrawerGroup, code) as any"
                          size="small"
                          effect="light"
                        >
                          {{ productStatusText(activeProductDrawerGroup, code) }}
                        </el-tag>
                      </div>
                      <div class="product-card-code">{{ code }}</div>
                      <div class="product-card-foot">点击卡片可快速切换勾选</div>
                    </div>
                  </div>

                  <div v-else class="empty-set-tip">
                    套图目录已存在，但暂无可用商品（需在套图下放入带 1.jpg/1.png 等编号主图的商品文件夹）
                  </div>
                </div>
              </el-drawer>

              <el-form-item label="已上架处理">
                <el-radio-group v-model="relistStrategy" class="relist-strategy-group">
                  <el-radio label="ignore">不管（沿用跳过上架/重新上架提示）</el-radio>
                  <el-radio label="append_to_existing" disabled>原 ID 链接补漏（开发中）</el-radio>
                  <el-radio label="delist_and_relist">下架原商品并重新上架</el-radio>
                </el-radio-group>
                <div v-if="relistStrategy === 'ignore'" class="form-tip">
                  若所选商品已在售，启动时会询问是否跳过上架或重新上架；可能产生重复链路。
                </div>
                <div v-else-if="relistStrategy === 'delist_and_relist'" class="form-tip form-tip-highlight">
                  上架前一次性将全部商品编码原样填入搜索框，逐页勾选校验后批量下架；全部完成后才进入上架（不是每个商品上架前单独下架）。
                </div>
                <div
                  v-if="relistStrategy === 'delist_and_relist'"
                  class="option-row delist-spec-search-row"
                >
                  <div class="switch-row">
                    <span class="switch-label">商品编码未命中时尝试规格编码搜索</span>
                    <el-switch v-model="delistSpecCodeSearchEnabled" />
                  </div>
                  <div class="form-tip">
                    默认关闭：仅按商品编码搜索，可节省每批约 20–40 秒。开启后商品编码无结果时会再搜规格编码。
                  </div>
                </div>
              </el-form-item>

              <el-form-item label="分批上架">
                <div class="option-row listing-throttle-row">
                  <div class="switch-row">
                    <span class="switch-label">启用分批（防风控）</span>
                    <el-switch v-model="listingThrottleEnabled" />
                  </div>
                  <template v-if="listingThrottleEnabled">
                    <span class="throttle-inline-label">每批</span>
                    <el-input-number
                      v-model="listingBatchSetCount"
                      :min="1"
                      :max="100"
                      controls-position="right"
                      size="small"
                    />
                    <span class="throttle-inline-label">套，间隔</span>
                    <el-input-number
                      v-model="listingBatchIntervalMinutes"
                      :min="1"
                      :max="1440"
                      controls-position="right"
                      size="small"
                    />
                    <span class="throttle-inline-label">分钟</span>
                  </template>
                </div>
                <div v-if="listingThrottleEnabled" class="form-tip">
                  已选 {{ selectedSetCount }} 套图，将分 {{ listingBatchPlanCount }} 批上架{{
                    listingPerBatchLimitedTimeEnabled || listingPerBatchCampaignEnabled
                      ? '；每批完成后'
                      : '；全部批次完成后才进入限时限量购 / 活动 / 推广'
                  }}<template v-if="listingPerBatchLimitedTimeEnabled || listingPerBatchCampaignEnabled">
                    <template v-if="listingPerBatchLimitedTimeEnabled">先跑限时限量购</template><template v-if="listingPerBatchLimitedTimeEnabled && listingPerBatchCampaignEnabled">，</template><template v-if="listingPerBatchCampaignEnabled">再跑活动{{ autoPromotion ? '/推广' : '' }}</template>（仅本批商品），再按间隔进入下一批
                  </template>。
                </div>
                <div v-if="listingThrottleEnabled" class="option-row listing-throttle-row per-batch-lt-row">
                  <div class="switch-row">
                    <span class="switch-label">每批完成后跑限时限量购</span>
                    <el-switch v-model="listingPerBatchLimitedTimeEnabled" />
                  </div>
                  <template
                    v-if="
                      listingPerBatchLimitedTimeEnabled &&
                      !listingPerBatchLtTrafficActivityEnabled
                    "
                  >
                    <span class="throttle-inline-label">每趟最多</span>
                    <el-input-number
                      v-model="perBatchLimitedTimeChunkSize"
                      :min="1"
                      :max="500"
                      controls-position="right"
                      size="small"
                    />
                    <span class="throttle-inline-label">个商品</span>
                  </template>
                </div>
                <div
                  v-if="
                    listingThrottleEnabled &&
                    listingPerBatchLimitedTimeEnabled &&
                    !listingPerBatchLtTrafficActivityEnabled
                  "
                  class="form-tip"
                >
                  每批上架成功后，限时限量购按商品数再拆成多趟（默认紧接着跑）；某一趟失败记失败并继续下一趟。
                </div>
                <div
                  v-if="
                    listingThrottleEnabled &&
                    listingPerBatchLimitedTimeEnabled &&
                    !listingPerBatchLtTrafficActivityEnabled &&
                    !listingPerBatchCampaignEnabled
                  "
                  class="option-row listing-throttle-row per-batch-lt-row"
                >
                  <div class="switch-row">
                    <span class="switch-label">限时失败自动重跑</span>
                    <el-switch v-model="batchLimitedTimeAutoRetryEnabled" />
                  </div>
                  <template v-if="batchLimitedTimeAutoRetryEnabled">
                    <span class="throttle-inline-label">最多</span>
                    <el-input-number
                      v-model="batchLimitedTimeAutoRetryMaxAttempts"
                      :min="1"
                      :max="10"
                      controls-position="right"
                      size="small"
                    />
                    <span class="throttle-inline-label">次</span>
                  </template>
                </div>
                <div
                  v-if="
                    listingThrottleEnabled &&
                    listingPerBatchLimitedTimeEnabled &&
                    !listingPerBatchLtTrafficActivityEnabled &&
                    !listingPerBatchCampaignEnabled &&
                    batchLimitedTimeAutoRetryEnabled
                  "
                  class="form-tip"
                >
                  全部分批上架完成后，自动对「上架成功、限时失败」商品按现有分批限时重跑流程执行；仍失败时按配置次数继续自动重跑。活动改期规则与手动重跑一致。
                </div>
                <div v-if="listingThrottleEnabled" class="option-row listing-throttle-row per-batch-lt-row">
                  <div class="switch-row">
                    <span class="switch-label">每批完成后跑活动{{ autoPromotion ? '/推广' : '' }}</span>
                    <el-switch
                      v-model="listingPerBatchCampaignEnabled"
                      :disabled="listingPerBatchLtTrafficActivityEnabled"
                    />
                  </div>
                </div>
                <div v-if="listingThrottleEnabled" class="option-row listing-throttle-row per-batch-lt-row">
                  <div class="switch-row">
                    <span class="switch-label">分批：限时→推广→全部批次结束后报活动</span>
                    <el-switch
                      v-model="listingPerBatchLtTrafficActivityEnabled"
                      :disabled="listingPerBatchCampaignEnabled || !listingPerBatchLimitedTimeEnabled"
                    />
                  </div>
                  <div v-if="listingPerBatchLtTrafficActivityEnabled" class="form-tip option-tip">
                    每批限时完成后先推广，全部批次跑完后用各批累计的限时成功商品统一报活动。推广失败不阻断。
                  </div>
                </div>
                <div
                  v-if="listingThrottleEnabled && listingPerBatchLtTrafficActivityEnabled"
                  class="option-row listing-throttle-row per-batch-lt-row"
                >
                  <div class="switch-row">
                    <span class="switch-label">仅限时成功报推广</span>
                    <el-switch
                      v-model="listingPerBatchPromoteLtSuccessOnlyEnabled"
                      :disabled="!autoPromotion"
                    />
                  </div>
                  <div v-if="listingPerBatchPromoteLtSuccessOnlyEnabled" class="form-tip option-tip">
                    开启：仅推广本批限时限量购成功的商品；限时失败记 fail、跳过推广、继续下一批。
                  </div>
                  <div v-else class="form-tip option-tip">
                    关闭：推广本批全部上架成功商品（不受限时结果影响）。
                  </div>
                </div>
                <div v-else class="form-tip">
                  关闭时一次上架所选全部套图；新店铺大量上架建议开启分批。
                </div>
              </el-form-item>
            </div>

            <div class="form-section">
              <div class="form-section-head">
                <div class="form-section-title">活动与推广</div>
                <div class="limited-time-inline">
                  <span class="limited-time-label">限时限量购</span>
                  <el-tag size="small" type="warning" effect="plain">必选</el-tag>
                  <span class="limited-time-hint muted">先于活动报名</span>
                </div>
              </div>
              <p class="form-tip limited-time-tip">
                链路顺序：上架 → 限时限量购 → 活动报名 → 推广。已选活动时，限时限量购会在浏览器中先于活动报名自动执行。
              </p>

              <el-form-item label="营销活动" required>
                <el-select
                  v-model="activityIds"
                  multiple
                  filterable
                  collapse-tags
                  collapse-tags-tooltip
                  :max-collapse-tags="2"
                  placeholder="选择一个或多个活动"
                  style="width: 100%"
                >
                  <el-option
                    v-for="act in activities"
                    :key="act.activity_id"
                    :label="formatActivityShortLabel(act)"
                    :value="act.activity_id"
                  />
                </el-select>
                <div v-if="activityIds.length > 1" class="form-tip">
                  已选 {{ activityIds.length }} 个活动，限时限量购完成后将按顺序依次报名，全部完成后再推广
                </div>
              </el-form-item>

              <el-form-item label="活动/推广分批">
                <div class="option-row listing-throttle-row">
                  <div class="switch-row">
                    <span class="switch-label">按商品数分批报名活动并推广</span>
                    <el-switch
                      v-model="activityTrafficBatchEnabled"
                      :disabled="activityTrafficBatchDisabled"
                    />
                  </div>
                  <template v-if="activityTrafficBatchEnabled">
                    <span class="throttle-inline-label">每批</span>
                    <el-input-number
                      v-model="activityTrafficBatchSize"
                      :min="1"
                      :max="500"
                      controls-position="right"
                      size="small"
                    />
                    <span class="throttle-inline-label">个商品</span>
                  </template>
                </div>
                <div v-if="activityTrafficBatchEnabled" class="form-tip">
                  限时全部完成后：每批依次报名全部活动 → 推广 → 下一批。首批仍遵守活动延迟；后续批次在上批推广完成后立即执行。
                </div>
                <div v-else-if="activityTrafficBatchDisabled" class="form-tip muted">
                  与「每批活动/推广」「分批：限时→推广→活动」互斥；须开启自动推广。
                </div>
              </el-form-item>

              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="类目关键词">
                    <el-input v-model="categoryKeyword" placeholder="上架类目，默认笔袋" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="活动延迟" v-if="!demoMode">
                    <el-input-number v-model="activityDelayHours" :min="1" :max="168" style="width: 100%" />
                    <div class="form-tip">建议 24 小时，到期会随机抖动</div>
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item label="高级选项">
                <div class="option-row">
                  <el-checkbox v-model="slotAlignmentTest" class="slot-align-test" :disabled="specFillVerifyTest">
                    槽位对齐（试验）
                  </el-checkbox>
                  <el-checkbox v-model="specFillVerifyTest" class="spec-fill-verify-test" :disabled="slotAlignmentTest">
                    规格校验填表（试验）
                  </el-checkbox>
                  <el-checkbox v-model="primaryStyleFirstTest" class="primary-style-first-test">
                    主款款式优先（试验）
                  </el-checkbox>
                  <el-checkbox v-model="parenSizeAsProductType" class="paren-size-as-type">
                    挂件(公仔)→公仔（试验）
                  </el-checkbox>
                  <el-checkbox v-model="categoryNextBurstDemo" class="category-burst-demo">
                    分类页下一步连点（演示）
                  </el-checkbox>
                  <div class="switch-row">
                    <span class="switch-label">自动推广</span>
                    <el-switch v-model="autoPromotion" />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">限时失败仍继续</span>
                    <el-switch
                      v-model="continueAfterLimitedTimeFailure"
                      :disabled="activityLimitedTimeSuccessOnly"
                    />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">仅限时成功报活动</span>
                    <el-switch v-model="activityLimitedTimeSuccessOnly" />
                  </div>
                  <div v-if="activityLimitedTimeSuccessOnly" class="form-tip option-tip">
                    开启后：活动/推广只使用限时限量购提交成功的商品 ID；限时整单失败但无成功商品时不报活动。
                    与「限时失败仍继续（全量 ID）」互斥。
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">活动失败仍继续</span>
                    <el-switch v-model="continueAfterActivityFailure" />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">限时失败仍推广</span>
                    <el-switch v-model="promoteAfterLimitedTimeFailure" :disabled="!autoPromotion" />
                  </div>
                  <div v-if="promoteAfterLimitedTimeFailure" class="form-tip option-tip">
                    限时限量购失败导致活动不跑时，跳过活动并立即创建推广；推广商品 ID 来源见系统设置。
                    限时成功时仍按原流程：先活动、后推广。分批模式下须等全部批次限时跑完再决策。
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">演示模式</span>
                    <el-switch v-model="demoMode" />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">本地 Excel 回退</span>
                    <el-switch
                      v-model="excelFallbackEnabled"
                      :loading="excelFallbackSaving"
                      @change="onExcelFallbackChange"
                    />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">规格编码展开日志</span>
                    <el-switch
                      v-model="logSpecSkuRowsEnabled"
                      :loading="logSpecSkuRowsSaving"
                      @change="onLogSpecSkuRowsChange"
                    />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">平台跳过去重</span>
                    <el-switch
                      v-model="platformSkipDedupeEnabled"
                      :loading="platformSkipDedupeSaving"
                      @change="onPlatformSkipDedupeChange"
                    />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">写入飞书失败日志</span>
                    <el-switch
                      v-model="failureLogEnabled"
                      :loading="failureLogSaving"
                      @change="onFailureLogChange"
                    />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">配件成本定价</span>
                    <el-switch
                      v-model="accessoryCostPricingEnabled"
                      :disabled="originalSumPricingEnabled"
                      :loading="accessoryCostPricingSaving"
                      @change="onAccessoryCostPricingChange"
                    />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">子商品档位浮动</span>
                    <el-switch
                      v-model="accessoryCostTieredFloatEnabled"
                      :disabled="!accessoryCostPricingEnabled || originalSumPricingEnabled"
                      :loading="accessoryCostTieredFloatSaving"
                      @change="onAccessoryCostTieredFloatChange"
                    />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">原价相加</span>
                    <el-switch
                      v-model="originalSumPricingEnabled"
                      :loading="originalSumPricingSaving"
                      @change="onOriginalSumPricingChange"
                    />
                  </div>
                  <div class="switch-row">
                    <el-button
                      :type="submitAiTitleEnabled ? 'success' : 'primary'"
                      :plain="!submitAiTitleEnabled"
                      :loading="aiGenerateTitleLoading"
                      @click="onAiGenerateTitleClick"
                    >
                      AI 生成标题{{ submitAiTitleEnabled ? '（已开启）' : '（未开启）' }}
                    </el-button>
                    <el-button link type="primary" @click="router.push('/submit-ai-title-config')">
                      配置
                    </el-button>
                  </div>
                </div>
                <div v-if="categoryNextBurstDemo" class="form-tip">
                  演示拼多多分类页渲染延迟：随机等待 20–45 秒（5 秒步长）后点击「下一步」；未跳转则随机连点 3–5 次并监听 30 秒。关闭后仅单次点击（便于对比复现 bug）。
                </div>
                <div v-if="continueAfterLimitedTimeFailure" class="form-tip">
                  限时限量购失败时仍继续活动报名；若同时开启自动推广，活动全部处理完后仍会创建推广。
                </div>
                <div v-if="continueAfterActivityFailure" class="form-tip">
                  某个活动报名失败（非「需等待1天」等可跳过类）时，仍继续下一个活动；全部活动处理完后，若开启自动推广仍会创建推广。
                </div>
                <div
                  v-if="autoPromotion && continueAfterLimitedTimeFailure && continueAfterActivityFailure"
                  class="form-tip form-tip-highlight"
                >
                  容错模式：上架 → 限时限量购 → 各活动 → 推广 将逐步执行；中间步骤失败不阻断后续（上架失败除外）。
                </div>
                <div v-if="slotAlignmentTest" class="form-tip">
                  开启后：主款预览图顺序定尺寸名，兄弟款跟槽位不走尺寸并集。
                </div>
                <div v-if="specFillVerifyTest" class="form-tip">
                  开启后：按尺寸语义（笔袋+挂件、笔袋+套尺等）对齐兄弟款槽位（YKL 子编码可不同）→ 按「款式/尺寸」逐格填写 → 回读校验 → 通过后再传预览图。与「槽位对齐」互斥；语义槽位与商品表仍不一致时将判失败。
                </div>
                <div v-if="primaryStyleFirstTest" class="form-tip">
                  开启后：本套图主上架编码（如 BD068Q）对应的款式颜色排在拼多多「款式」列第 1 位，不再按兄弟款文件夹 A-Z 顺序。可与槽位对齐 / 规格校验填表叠加。
                </div>
                <div v-if="parenSizeAsProductType" class="form-tip">
                  开启后：现有识别不变；定稿后再把撞名的「笔袋+挂件(公仔)」简写为「笔袋+公仔」（仅改带括号的那一个）。
                </div>
                <div v-if="demoMode" class="form-tip">
                  演示模式：限时限量购上架后立即执行，活动约 2 分钟后执行，便于测试整条链路。
                </div>
                <div v-if="excelFallbackEnabled" class="form-tip">
                  已开启：飞书商品表/定价表读不到数据时，会回退读取本地 Excel（拼多多所有商品、pdd.xls、拼多多定价、拼多多控价）。
                </div>
                <div v-else class="form-tip">
                  默认关闭：一律只读飞书，不回退本地 Excel；飞书缺数据将直接报错。
                </div>
                <div v-if="logSpecSkuRowsEnabled" class="form-tip">
                  已开启：上架成功后在 PDD 发布日志表写入 1 条商品摘要 + 每条规格编码 1 行（组合商品条码、标题含飞书颜色规格）。
                </div>
                <div v-else class="form-tip">
                  默认关闭：上架成功仅写 1 条商品摘要行到 PDD 发布日志表。
                </div>
                <div v-if="platformSkipDedupeEnabled" class="form-tip">
                  已开启：从飞书失败日志同步「平台不适用跳过」的拼多多商品编码到 Redis（全店铺共用，每 5 分钟刷新）。上架时编码命中则静默跳过，不打开拼多多页面、不写失败日志。
                  <span v-if="platformSkipDedupeCodeCount > 0">
                    当前缓存 {{ platformSkipDedupeCodeCount }} 个编码
                    <template v-if="platformSkipDedupeUpdatedAt">（更新于 {{ platformSkipDedupeUpdatedAt }}）</template>。
                  </span>
                </div>
                <div v-else class="form-tip">
                  默认关闭：每次上架仍会走笔袋视图校验，不适用商品会写入失败日志表。
                </div>
                <div v-if="failureLogEnabled" class="form-tip">
                  已开启：上架失败、跳过、校验不通过等会写入飞书
                  「{{ failureLogTableName || '全平台发布日志表（失败）' }}」；仅影响该表，成功日志与活动日志不受影响。
                </div>
                <div v-else class="form-tip">
                  已关闭：发布过程中<strong>不会</strong>往飞书失败表写任何记录；本地任务记录与报错详情仍保留。发布前关掉、跑完再开即可。
                </div>
                <div v-if="originalSumPricingEnabled" class="form-tip">
                  已开启原价相加：拼单价 = 主商品「拼多多定价」+ 子商品「组合装定价」，不加浮动。
                  与配件成本定价 / 子商品档位浮动互斥。
                </div>
                <div v-else-if="accessoryCostPricingEnabled" class="form-tip">
                  已开启：拼单价 = 主商品拼多多定价 + 主商品浮动（{{ accessoryCostPricingFloatMin }}~{{ accessoryCostPricingFloatMax }}）+ 所有子商品组合装定价 + 子商品浮动。
                  <template v-if="accessoryCostTieredFloatEnabled">
                    子商品档位浮动：≤0.5 元 +1~1.5；0.5~1 元 +1.5~2.5；1~2 元 +3~4；&gt;2 元 +5~7。
                  </template>
                  <template v-else>
                    子商品统一浮动 {{ accessoryCostPricingFloatMin }}~{{ accessoryCostPricingFloatMax }} 元。
                  </template>
                </div>
                <div v-else class="form-tip">
                  默认关闭：拼单价按飞书「拼多多比价定价」各组件定价相加，并分别加浮动。
                </div>
              </el-form-item>
            </div>

            <div
              v-if="materialSource === 'minio' && minioSyncJob"
              class="minio-sync-progress"
            >
              <div class="minio-sync-progress-head">
                <span>MinIO 同步</span>
                <el-tag
                  size="small"
                  :type="
                    minioSyncJob.status === 'success'
                      ? 'success'
                      : minioSyncJob.status === 'failed'
                        ? 'danger'
                        : 'warning'
                  "
                >
                  {{
                    minioSyncJob.status === 'success'
                      ? '已完成'
                      : minioSyncJob.status === 'failed'
                        ? '失败'
                        : '进行中'
                  }}
                </el-tag>
              </div>
              <el-progress
                :percentage="minioSyncJob.progress_percent"
                :status="
                  minioSyncJob.status === 'success'
                    ? 'success'
                    : minioSyncJob.status === 'failed'
                      ? 'exception'
                      : undefined
                "
                :stroke-width="10"
              />
              <div class="form-tip">
                {{ minioSyncJob.completed_sets }}/{{ minioSyncJob.total_sets }} 套图
                <template v-if="minioSyncJob.current_label">
                  · {{ minioSyncJob.current_label }}
                </template>
              </div>
            </div>

            <div class="submit-actions">
              <el-button
                v-if="materialSource === 'minio'"
                size="large"
                :loading="syncing"
                :disabled="!resolvedListingSelectors.length"
                @click="syncSelectedFromMinio"
              >
                {{ syncing ? 'MinIO 同步中…' : '同步 MinIO 素材' }}
              </el-button>
              <el-button
                size="large"
                :loading="preflightChecking"
                :disabled="!resolvedListingSelectors.length || syncing"
                @click="checkSelectedSets"
              >
                检查所选套图
              </el-button>
              <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="startPipeline">
                {{ pipelineBatchEnabled ? '批量启动整合链路' : '一键启动整合链路' }}
              </el-button>
            </div>

            <el-card v-if="preflightResult" shadow="never" class="preflight-card">
              <template #header>
                <div class="card-head">
                  <span>上架前检查</span>
                  <el-tag :type="preflightReadyLabels.size ? 'success' : 'danger'" size="small">
                    可上架 {{ preflightReadyLabels.size }} / {{ preflightResult.unit_count }}
                  </el-tag>
                </div>
              </template>
              <el-table
                :data="preflightResult.units"
                size="small"
                stripe
                max-height="240"
                class="preflight-table"
              >
                <el-table-column prop="listing_label" label="套图" min-width="140" />
                <el-table-column label="状态" width="108">
                  <template #default="{ row }">
                    <el-tag
                      size="small"
                      :type="preflightReadyLabels.has(row.listing_label) ? 'success' : 'danger'"
                    >
                      {{ preflightReadyLabels.has(row.listing_label) ? '可上架' : '有问题' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="SKU" width="72" align="center">
                  <template #default="{ row }">{{ row.sku_count }}</template>
                </el-table-column>
              </el-table>
              <p v-if="preflightResult.error_count" class="form-tip">
                有问题的套图不会上架，其余套图仍会正常执行。
              </p>
            </el-card>
          </el-form>

          <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="msg" />
          <el-alert v-if="success" type="success" :title="success" show-icon :closable="false" class="msg" />
        </el-card>
      </el-col>

      <el-col :span="11" :xs="24" class="pipeline-side-col">
        <el-card v-if="activePipeline" shadow="never" class="stat-card side-card">
          <template #header>
            <div class="card-head">
              <span>当前链路</span>
              <div class="card-head-actions">
                <el-button
                  v-if="canViewBatchStages"
                  link
                  type="primary"
                  size="small"
                  :loading="batchStageLoading && batchStageVisible"
                  @click="openBatchStageDialog(activePipeline)"
                >
                  每批状态
                </el-button>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :loading="feishuInspectLoading"
                  @click="openFeishuInspectDialog(activePipeline)"
                >
                  飞书定价数据
                </el-button>
                <el-button
                  v-if="canLateRetryFailed && lateRetryFailedCount > 0"
                  link
                  type="warning"
                  size="small"
                  :loading="lateRetryLoading"
                  @click="startLateRetryFailed(activePipeline)"
                >
                  补跑失败 ({{ lateRetryFailedCount }})
                </el-button>
                <el-button
                  v-if="canCancelPipeline(activePipeline)"
                  link
                  type="danger"
                  size="small"
                  :loading="cancelingId === activePipeline.pipeline_id"
                  @click="cancelPipeline(activePipeline)"
                >
                  取消
                </el-button>
                <el-tag :type="pipelineTagType(activePipeline.status)">{{ activePipeline.status }}</el-tag>
              </div>
            </div>
          </template>
          <p class="meta">ID：{{ activePipeline.pipeline_id }}</p>
          <p v-if="activePipeline.batch_id" class="meta">批次：{{ activePipeline.batch_id }}</p>
          <p v-if="activePipeline.activity_ids?.length || activePipeline.activity_id" class="meta">
            活动：{{ formatActivityList(activePipeline.activity_ids?.length ? activePipeline.activity_ids : [activePipeline.activity_id]) }}
          </p>
          <p v-if="activePipeline.scheduled_activity_at" class="meta">
            活动计划时间：{{ formatTime(activePipeline.scheduled_activity_at) }}
            <template v-if="lateRetryState?.activity_defer?.rescheduled || batchLtRetryState?.activity_defer?.rescheduled">
              （已因补跑/限时重跑延期）
            </template>
          </p>
          <p v-if="lateRetryState?.activity_defer?.reschedule_reason" class="warn-text">
            {{ lateRetryState.activity_defer.reschedule_reason }}
          </p>
          <p v-if="batchLtRetryState?.activity_defer?.reschedule_reason" class="warn-text">
            {{ batchLtRetryState.activity_defer.reschedule_reason }}
          </p>
          <p v-if="lateRetryState?.phase && lateRetryState.phase !== 'idle'" class="warn-text">
            补跑：{{ lateRetryPhaseLabel(lateRetryState.phase) }}
            <template v-if="lateRetryState.outcome_detail"> — {{ lateRetryState.outcome_detail }}</template>
          </p>
          <p
            v-if="batchLtRetryState?.phase && batchLtRetryState.phase !== 'idle'"
            class="warn-text"
          >
            分批限时重跑：{{ batchLtRetryPhaseLabel(batchLtRetryState.phase) }}
            <template v-if="batchLtRetryState.outcome_detail"> — {{ batchLtRetryState.outcome_detail }}</template>
          </p>
          <p v-if="batchLtAutoRetryState?.enabled" class="meta">
            限时失败自动重跑已开启（最多 {{ batchLtAutoRetryState.max_attempts || 1 }} 次）
            <template v-if="batchLtAutoRetryState.last_started_batches?.length">
              · 最近自动启动批次：{{
                batchLtAutoRetryState.last_started_batches.map((i: number) => i + 1).join('、')
              }}
            </template>
          </p>
          <p v-else-if="lateRetryFailedCount > 0 && activePipeline.current_step === 'waiting_activity'" class="meta">
            等活动期间可补跑失败套图（{{ lateRetryFailedCount }} 个）
            <template v-if="!canLateRetryFailed && lateRetryEligibilityHint()">
              · {{ lateRetryEligibilityHint() }}
            </template>
          </p>
          <p v-if="activePipeline.pdd_product_ids.length" class="meta">
            拼多多商品：{{ activePipeline.pdd_product_ids.join(', ') }}
          </p>
          <p v-if="activePipeline.error" class="error-text">{{ activePipeline.error }}</p>
          <p v-if="activePipeline.listing_skip_reason" class="warn-text">
            上架：{{ activePipeline.listing_skip_reason }}
          </p>

          <div v-if="activeListingUnitStatuses.length" class="listing-unit-panel">
            <div class="listing-unit-head">
              <span>套图进度</span>
              <span v-if="listingUnitStatusSummary" class="listing-unit-summary">
                <template v-if="listingUnitStatusSummary.success">
                  已上架 {{ listingUnitStatusSummary.success }}
                </template>
                <template v-if="listingUnitStatusSummary.listing">
                  · 进行中 {{ listingUnitStatusSummary.listing }}
                </template>
                <template v-if="listingUnitStatusSummary.ready">
                  · 待上架 {{ listingUnitStatusSummary.ready }}
                </template>
                <template v-if="listingUnitStatusSummary.preflight_failed">
                  · 有问题 {{ listingUnitStatusSummary.preflight_failed }}
                </template>
                <template v-if="listingUnitStatusSummary.failed">
                  · 失败 {{ listingUnitStatusSummary.failed }}
                </template>
              </span>
            </div>
            <el-table
              :data="activeListingUnitStatuses"
              size="small"
              stripe
              max-height="280"
              class="listing-unit-table"
            >
              <el-table-column prop="listing_label" label="套图" min-width="132" show-overflow-tooltip />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="(listingUnitStatusType[row.status] || 'info') as any">
                    {{ row.status_label || row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="说明" min-width="120" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ listingUnitReasonText(row.reason_code) }}
                </template>
              </el-table-column>
            </el-table>
          </div>

          <p v-if="activePipeline.campaign_skip_reason" class="warn-text">
            活动：{{ activePipeline.campaign_skip_reason }}
          </p>

          <p v-if="canViewBatchStages" class="meta steps-overall-hint">
            下方四步为<strong>整条链路总体进度</strong>；各批明细请点右上角「每批状态」。
          </p>

          <el-steps direction="vertical" :active="activePipeline.steps.length" class="steps">
            <el-step v-for="step in activePipeline.steps" :key="step.key" :title="step.label">
              <template #description>
                <div class="step-desc">
                  <el-tag size="small" :type="stepTagType(step.status)">{{ step.status }}</el-tag>
                  <span class="step-detail-text">{{ step.detail }}</span>
                  <el-button
                    v-if="step.run_id"
                    link
                    type="primary"
                    size="small"
                    @click="openRun(step.run_id)"
                  >
                    查看记录
                  </el-button>
                </div>
                <div
                  v-if="step.key === 'activity' && (activePipeline.campaign_results?.length || 0) > 1"
                  class="campaign-results"
                >
                  <div
                    v-for="item in activePipeline.campaign_results"
                    :key="`${item.activity_id}-${item.run_id || ''}`"
                    class="campaign-result-row"
                  >
                    <span class="campaign-result-id">{{ formatActivityLabel(item.activity_id) }}</span>
                    <el-tag size="small" :type="campaignResultTagType(item)">
                      {{ campaignResultLabel(item) }}
                    </el-tag>
                    <el-button
                      v-if="item.run_id"
                      link
                      type="primary"
                      size="small"
                      @click="openRun(item.run_id)"
                    >
                      记录
                    </el-button>
                    <span v-if="item.summary || item.error" class="campaign-result-summary">
                      {{ item.summary || item.error }}
                    </span>
                  </div>
                </div>
              </template>
            </el-step>
          </el-steps>
        </el-card>

        <el-card shadow="never" class="stat-card side-card commerce-card">
          <template #header>
            <div class="card-head">
              <span>店铺运营状态</span>
              <div class="card-head-actions">
                <el-tag v-if="commerceOverview.pending_total" size="small" type="warning">
                  排队 {{ commerceOverview.pending_total }}
                </el-tag>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :loading="commerceLoading"
                  @click="refreshCommerceOverview().catch(() => undefined)"
                >
                  刷新
                </el-button>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :loading="commerceDispatchingAll"
                  :disabled="!commerceOverview.pending_total"
                  @click="dispatchAllCommerce"
                >
                  派发全部
                </el-button>
                <el-button
                  v-if="commerceOverview.pending_total"
                  link
                  type="warning"
                  size="small"
                  @click="clearAllPendingIntents"
                >
                  清空排队
                </el-button>
                <el-button
                  v-if="commerceAccountRows.length || commerceOverview.pending_total"
                  link
                  type="danger"
                  size="small"
                  :loading="commerceResettingAll"
                  @click="resetAllCommerce"
                >
                  重置全部
                </el-button>
              </div>
            </div>
          </template>

          <el-empty
            v-if="!commerceAccountRows.length && !commerceOverview.pending_total"
            description="各店铺空闲，无排队任务"
            :image-size="56"
          />

          <el-table
            v-if="commerceAccountRows.length"
            :data="commerceAccountRows"
            size="small"
            class="commerce-status-table"
            empty-text="暂无活跃周期"
          >
            <el-table-column label="店铺" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">
                {{ accountDisplayName(row.account_id) }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="88">
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="commerceLifecycleTagType(row.lifecycle?.lifecycle_status || 'none')"
                >
                  {{ commerceLifecycleStatusLabel(row.lifecycle?.lifecycle_status || 'none') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="阶段" width="88">
              <template #default="{ row }">
                {{ row.lifecycle ? commercePhaseLabel(row.lifecycle.phase || '') : '—' }}
              </template>
            </el-table-column>
            <el-table-column label="等待" min-width="96" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.lifecycle?.lifecycle_status === 'scheduled'">
                  {{ formatWakeCountdown(row.lifecycle.wake_at) }}
                </span>
                <span v-else-if="row.lifecycle?.wake_at">
                  {{ formatTime(row.lifecycle.wake_at) }}
                </span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="排队" width="56" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.pending_count" size="small" type="warning">{{ row.pending_count }}</el-tag>
                <span v-else>0</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120" align="center">
              <template #default="{ row }">
                <el-button
                  v-if="row.pending_count"
                  link
                  type="primary"
                  size="small"
                  :loading="commerceDispatchingAccount === row.account_id"
                  @click="dispatchCommerceForAccount(row.account_id)"
                >
                  派发
                </el-button>
                <el-button
                  v-if="row.lifecycle || row.pending_count"
                  link
                  type="danger"
                  size="small"
                  :loading="commerceResettingAccount === row.account_id"
                  @click="resetCommerceAccountRow(row.account_id)"
                >
                  重置
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="commerceOverview.pending_intents.length" class="commerce-intents-panel">
            <div class="commerce-intents-head">排队明细</div>
            <el-table
              :data="commerceOverview.pending_intents"
              size="small"
              class="commerce-intents-table"
              max-height="220"
            >
              <el-table-column prop="account_id" label="店铺" width="88" show-overflow-tooltip />
              <el-table-column label="来源" width="108">
                <template #default="{ row }">
                  <span>{{ intentPriorityLabel(row) }}</span>
                  <el-tag v-if="row.is_merged" size="small" type="info" class="commerce-merged-tag">
                    已合并
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="商品" min-width="140" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ formatIntentProducts(row.product_selectors) }}
                </template>
              </el-table-column>
              <el-table-column label="原因" min-width="120" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ row.block_reason_label || commerceBlockReasonLabel(row.block_reason) }}
                </template>
              </el-table-column>
              <el-table-column prop="created_at" label="入队" width="96" show-overflow-tooltip />
              <el-table-column label="操作" width="72" fixed="right" align="center">
                <template #default="{ row }">
                  <el-button
                    link
                    type="danger"
                    size="small"
                    :loading="commerceCancelingIntent === row.intent_id"
                    @click="cancelCommerceIntentRow(row.intent_id)"
                  >
                    取消
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-card>

        <el-card shadow="never" class="stat-card side-card recent-pipelines-card">
          <template #header>
            <div class="card-head">
              <span>最近链路</span>
              <el-tag v-if="polling" size="small" type="info">自动刷新</el-tag>
            </div>
          </template>
          <el-table
            :data="pipelines"
            size="small"
            empty-text="暂无整合链路"
            class="recent-pipelines-table"
          >
            <el-table-column prop="pipeline_id" label="ID" min-width="108" show-overflow-tooltip />
            <el-table-column prop="account_id" label="店铺" width="72" show-overflow-tooltip />
            <el-table-column prop="batch_id" label="批次" min-width="88" show-overflow-tooltip />
            <el-table-column label="活动" width="72" show-overflow-tooltip>
              <template #default="{ row }">
                {{ pipelineActivitySummary(row) }}
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="88">
              <template #default="{ row }">
                <el-tag size="small" :type="pipelineTagType(row.status)">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="196" fixed="right" align="center">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="activePipeline = row">查看</el-button>
                <el-button
                  v-if="canViewBatchStagesForPipeline(row)"
                  link
                  type="primary"
                  size="small"
                  @click.stop="openBatchStageDialog(row)"
                >
                  每批
                </el-button>
                <el-button
                  link
                  type="primary"
                  size="small"
                  @click.stop="openFeishuInspectDialog(row)"
                >
                  飞书
                </el-button>
                <el-button
                  v-if="canCancelPipeline(row)"
                  link
                  type="danger"
                  size="small"
                  :loading="cancelingId === row.pipeline_id"
                  @click="cancelPipeline(row)"
                >
                  取消
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="recent-pipelines-pagination">
            <el-pagination
              :current-page="pipelinePage"
              :page-size="pipelinePageSize"
              :total="pipelineTotal"
              :page-sizes="[10, 20, 30]"
              layout="total, sizes, prev, pager, next"
              small
              background
              @current-change="onPipelinePageChange"
              @size-change="onPipelinePageSizeChange"
            />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog
      v-model="feishuInspectVisible"
      title="飞书定价读取结果"
      width="92%"
      top="4vh"
      destroy-on-close
      class="feishu-inspect-dialog"
    >
      <div v-loading="feishuInspectLoading" class="feishu-inspect-body">
        <template v-if="feishuInspectData">
          <p class="feishu-inspect-meta">
            表：{{ feishuInspectData.table_name || '拼多多比价定价' }}
            · 快照来源：{{ feishuInspectData.snapshot_source || '—' }}
            · 全表区间来源：{{ feishuInspectData.range_catalog_source || '—' }}
            · 查询编码 {{ feishuInspectData.codes.length }} 个
            <template v-if="feishuInspectData.saved_at">
              · 记录时间 {{ feishuInspectData.saved_at }}
            </template>
            <el-tag v-if="feishuInspectData.from_cache" size="small" type="info" class="feishu-inspect-tag">
              已保存
            </el-tag>
          </p>
          <el-table :data="feishuInspectData.items" stripe size="small" max-height="62vh">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="feishu-inspect-expand">
                  <p><strong>飞书匹配行数：</strong>{{ row.feishu_row_count }}</p>
                  <p v-if="row.snapshot_matched_key">
                    <strong>快照命中 key：</strong>{{ row.snapshot_matched_key }}
                  </p>
                  <p v-if="row.diagnose_messages?.length">
                    <strong>系统诊断：</strong>{{ row.diagnose_messages.join('；') }}
                  </p>
                  <p v-if="row.feishu_rows?.length > 1" class="warn-text">
                    飞书存在多行匹配，可能导致读错行
                  </p>
                  <el-table
                    v-if="row.feishu_rows?.length"
                    :data="row.feishu_rows"
                    size="small"
                    border
                    class="feishu-inspect-subtable"
                  >
                    <el-table-column prop="商品编码" label="商品编码" min-width="140" />
                    <el-table-column prop="颜色规格" label="颜色规格" width="100" />
                    <el-table-column prop="零售综合成本" label="零售综合成本" width="108" />
                    <el-table-column prop="拼多多定价" label="拼多多定价" width="96" />
                    <el-table-column prop="PDD控价" label="PDD控价" width="96" />
                  </el-table>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="query_code" label="查询编码" min-width="148" show-overflow-tooltip />
            <el-table-column label="零售综合成本" width="108">
              <template #default="{ row }">
                <span :class="{ 'feishu-cell-empty': !row.parsed?.['零售综合成本'] && !row.catalog_retail_cost }">
                  {{ row.parsed?.['零售综合成本'] || row.catalog_retail_cost || '—' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="拼多多定价" width="96">
              <template #default="{ row }">{{ row.parsed?.拼多多定价 || '—' }}</template>
            </el-table-column>
            <el-table-column label="PDD控价" width="96">
              <template #default="{ row }">{{ row.parsed?.PDD控价 || '—' }}</template>
            </el-table-column>
            <el-table-column label="快照零售成本" width="108">
              <template #default="{ row }">{{ row.snapshot_retail_cost || '—' }}</template>
            </el-table-column>
            <el-table-column label="区间诊断" min-width="120" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.range_aspect || row.snapshot_range_aspect || '正常' }}
              </template>
            </el-table-column>
            <el-table-column label="飞书行数" width="72" align="center">
              <template #default="{ row }">{{ row.feishu_row_count }}</template>
            </el-table-column>
          </el-table>
        </template>
        <el-empty v-else-if="!feishuInspectLoading" description="暂无数据" />
      </div>
      <template #footer>
        <el-button @click="feishuInspectVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :loading="feishuInspectRefreshing"
          :disabled="!feishuInspectPipelineId"
          @click="refreshFeishuInspectDialog"
        >
          重新读取飞书
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="batchStageVisible"
      title="分批状态明细"
      width="92%"
      top="4vh"
      destroy-on-close
      class="batch-stage-dialog"
    >
      <div v-loading="batchStageLoading" class="batch-stage-body">
        <p v-if="batchStageContextPipeline?.per_batch_lt_aggregate?.accumulated_success_count" class="batch-stage-meta">
          限时累计成功 {{ batchStageContextPipeline.per_batch_lt_aggregate.accumulated_success_count }} 个商品
          <template v-if="batchStageContextPipeline.per_batch_lt_aggregate.finalized">
            · 限时阶段已汇总
          </template>
          <template v-else-if="batchStageContextPipeline.per_batch_lt_aggregate.in_progress">
            · 分批进行中
          </template>
        </p>
        <p v-if="batchStageContextPipeline?.batch_limited_time_retry?.phase && batchStageContextPipeline.batch_limited_time_retry.phase !== 'idle'" class="warn-text">
          分批限时重跑：{{ batchLtRetryPhaseLabel(batchStageContextPipeline.batch_limited_time_retry.phase) }}
          <template v-if="batchStageContextPipeline.batch_limited_time_retry.outcome_detail">
            — {{ batchStageContextPipeline.batch_limited_time_retry.outcome_detail }}
          </template>
          <template v-if="batchStageContextPipeline.batch_limited_time_retry.activity_defer?.reschedule_reason">
            · {{ batchStageContextPipeline.batch_limited_time_retry.activity_defer.reschedule_reason }}
          </template>
        </p>
        <p v-if="batchStageContextPipeline?.batch_limited_time_auto_retry?.enabled" class="batch-stage-meta">
          限时失败自动重跑已开启（最多 {{ batchStageContextPipeline.batch_limited_time_auto_retry.max_attempts || 1 }} 次）
          <template v-if="batchStageContextPipeline.batch_limited_time_auto_retry.last_started_batches?.length">
            · 最近自动启动批次：{{
              batchStageContextPipeline.batch_limited_time_auto_retry.last_started_batches
                .map((i: number) => i + 1)
                .join('、')
            }}
          </template>
        </p>
        <div
          v-if="batchStageGroups.some((g) => shouldShowBatchLtRetryAction(g.batch_index, g.products))"
          class="batch-lt-retry-all-bar"
        >
          <el-tooltip
            :content="batchLtRetryAllDisabledReason || '对所有可重跑批次串行执行限时重跑'"
            placement="top"
          >
            <el-button
              type="warning"
              :disabled="!canStartAllBatchLtRetry"
              :loading="batchLtRetryAllLoading"
              @click="startAllBatchLimitedTimeRetry"
            >
              全部重跑限时失败
              <template v-if="batchLtRetryAllTargetStats.batchCount">
                （{{ batchLtRetryAllTargetStats.batchCount }} 批 / {{ batchLtRetryAllTargetStats.productCount }} 个）
              </template>
            </el-button>
          </el-tooltip>
          <span class="form-tip muted">点一次后按批排队执行，无需再逐批点击</span>
        </div>
        <p class="batch-stage-meta">
          按<strong>每一批</strong>展示商品的上架 / 限时限量购 / 活动 / 推广状态；活动与推广在全部批次完成后统一执行。
        </p>

        <div
          v-if="showBatchLtChunkSettings"
          class="batch-lt-chunk-settings"
        >
          <div class="batch-lt-chunk-settings-row">
            <span class="batch-lt-chunk-label">限时按趟拆分</span>
            <el-switch
              v-model="batchLtChunkEnabled"
              :disabled="batchLtChunkSettingsDisabled"
              :loading="batchLtChunkSaving"
              @change="saveBatchLtChunkSettings"
            />
            <template v-if="batchLtChunkEnabled">
              <span class="throttle-inline-label">每趟最多</span>
              <el-input-number
                v-model="batchLtChunkSize"
                :min="1"
                :max="500"
                :disabled="batchLtChunkSettingsDisabled"
                controls-position="right"
                size="small"
                @change="saveBatchLtChunkSettings"
              />
              <span class="throttle-inline-label">个商品</span>
            </template>
          </div>
          <p v-if="batchStageContextPipeline?.per_batch_limited_time_chunk_display" class="form-tip">
            当前进度：{{ batchStageContextPipeline.per_batch_limited_time_chunk_display }}
          </p>
          <p v-else-if="batchLtChunkEnabled" class="form-tip">
            开启后，每批限时限量购与「重跑限时失败」都会按每趟上限拆分；某一趟失败记失败并继续下一趟。
          </p>
          <p v-else class="form-tip muted">
            关闭后，每批限时限量购一次跑完全部商品；重跑也同样一次跑完。
          </p>
          <p v-if="batchStageContextPipeline?.per_batch_lt_chunk_sequence_active" class="warn-text">
            限时子趟进行中，暂不可修改拆分设置。
          </p>
        </div>

        <el-empty v-if="!batchStageLoading && !batchStageGroups.length" description="暂无分批记录" />

        <el-collapse v-else v-model="batchStageExpandedNames" class="batch-stage-collapse">
          <el-collapse-item
            v-for="group in batchStageGroups"
            :key="group.batch_index"
            :name="group.batch_index"
          >
            <template #title>
              <div class="batch-stage-collapse-title">
                <div class="batch-stage-collapse-head">
                  <span class="batch-stage-collapse-label">{{ group.batch_label }}</span>
                  <el-tooltip
                    v-if="shouldShowBatchLtRetryAction(group.batch_index, group.products)"
                    :content="batchLtRetryDisabledReason(group.batch_index, group.products) || '重跑本批上架成功但限时失败的商品'"
                    placement="top"
                  >
                    <el-button
                      type="warning"
                      size="small"
                      plain
                      class="batch-stage-retry-btn"
                      :disabled="!canBatchLtRetryForGroup(group.batch_index, group.products)"
                      :loading="batchLtRetryLoadingBatch === group.batch_index"
                      @click.stop="startBatchLimitedTimeRetry(group.batch_index, group.products)"
                    >
                      重跑限时失败 ({{ countBatchLtRetryTargets(group.products) }})
                    </el-button>
                  </el-tooltip>
                </div>
                <span class="batch-stage-collapse-summary">
                  上架 {{ group.listing_summary }}
                  · 限时 {{ group.limited_time_summary }}
                  · 活动1 {{ group.activity_1_summary }}
                  <template v-if="batchStageHasActivity2"> · 活动2 {{ group.activity_2_summary }}</template>
                  · 推广 {{ group.promotion_summary }}
                </span>
              </div>
            </template>

            <el-table :data="group.products" stripe size="small" class="batch-stage-product-table">
              <el-table-column prop="listing_label" label="套图" min-width="140" show-overflow-tooltip />
              <el-table-column prop="pdd_product_id" label="拼多多 ID" min-width="110" show-overflow-tooltip />
              <el-table-column label="上架" width="88">
                <template #default="{ row }">
                  <el-tag size="small" :type="batchStageTagType(row.listing_status)">
                    {{ batchStageStatusLabel(row.listing_status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="限时限量购" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="batchStageTagType(row.limited_time_status)">
                    {{ batchStageStatusLabel(row.limited_time_status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column
                :label="batchStageActivityIds[0] ? `活动 ${batchStageActivityIds[0]}` : '活动1'"
                width="96"
              >
                <template #default="{ row }">
                  <el-tag size="small" :type="batchStageTagType(row.activity_1_status)">
                    {{ batchStageStatusLabel(row.activity_1_status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column
                v-if="batchStageHasActivity2"
                :label="batchStageActivityIds[1] ? `活动 ${batchStageActivityIds[1]}` : '活动2'"
                width="96"
              >
                <template #default="{ row }">
                  <el-tag size="small" :type="batchStageTagType(row.activity_2_status)">
                    {{ batchStageStatusLabel(row.activity_2_status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="推广" width="88">
                <template #default="{ row }">
                  <el-tag size="small" :type="batchStageTagType(row.promotion_status)">
                    {{ batchStageStatusLabel(row.promotion_status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="错误说明" min-width="160" show-overflow-tooltip>
                <template #default="{ row }">
                  {{
                    [
                      row.listing_error,
                      row.limited_time_error,
                      row.activity_1_error,
                      row.activity_2_error,
                      row.promotion_error,
                    ]
                      .filter(Boolean)
                      .join('；') || '—'
                  }}
                </template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </div>
      <template #footer>
        <el-button @click="batchStageVisible = false">关闭</el-button>
        <el-button type="primary" :loading="batchStageLoading" @click="refreshBatchStageDialog">
          刷新
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="autoUploadConfigVisible"
      title="RabbitMQ 自动化上架配置"
      width="560px"
      destroy-on-close
    >
      <p class="form-tip">
        开启后，RabbitMQ 收到新上传批次时会按触发范围自动启动整合链路：上架 → 限时限量购 → 活动报名 → 推流。
      </p>
      <el-form label-width="110px" class="auto-upload-config-form">
        <el-form-item label="店铺" required>
          <el-select
            v-model="autoUploadConfig.account_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择一家或多家店铺（串行执行）"
            style="width: 100%"
          >
            <el-option
              v-for="acc in enabledAccounts"
              :key="acc.account_id"
              :label="acc.account_id"
              :value="acc.account_id"
            />
          </el-select>
          <div class="form-tip">多家店铺时按顺序串行：先跑完上架与限时限量购，到期后再串行跑活动/推广。</div>
        </el-form-item>
        <el-form-item label="触发范围">
          <el-select v-model="autoUploadConfig.trigger_mode" style="width: 100%">
            <el-option label="新增文件夹（不含追加图片）" value="new_product_folder" />
            <el-option label="仅追加图片" value="append_to_product" />
            <el-option label="都可以" value="all" />
          </el-select>
          <div class="form-tip">
            「新增文件夹」含首次上传整套（如 BD713719/第一套图/商品）和在已有套图下新增商品子文件夹；不含往已有商品里补图。
          </div>
        </el-form-item>
        <el-form-item label="营销活动" required>
          <el-select
            v-model="autoUploadConfig.activity_ids"
            multiple
            filterable
            collapse-tags
            placeholder="选择一个或多个活动"
            style="width: 100%"
          >
            <el-option
              v-for="act in activities"
              :key="act.activity_id"
              :label="formatActivityShortLabel(act)"
              :value="act.activity_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="类目关键词">
          <el-input v-model="autoUploadConfig.category_keyword" placeholder="上架类目，默认玩偶" />
        </el-form-item>
        <el-form-item label="活动延迟" v-if="!autoUploadConfig.demo_mode">
          <el-input-number v-model="autoUploadConfig.activity_delay_hours" :min="1" :max="168" style="width: 100%" />
        </el-form-item>
        <el-form-item label="链路选项">
          <div class="option-row">
            <div class="switch-row">
              <span class="switch-label">限时限量购</span>
              <el-tag size="small" type="warning" effect="plain">必选</el-tag>
            </div>
            <div class="switch-row">
              <span class="switch-label">自动推广（推流）</span>
              <el-switch v-model="autoUploadConfig.auto_promotion" />
            </div>
            <div class="switch-row">
              <span class="switch-label">限时失败仍继续</span>
              <el-switch v-model="autoUploadConfig.continue_after_limited_time_failure" />
            </div>
            <div class="switch-row">
              <span class="switch-label">活动失败仍继续</span>
              <el-switch v-model="autoUploadConfig.continue_after_activity_failure" />
            </div>
            <div class="switch-row">
              <span class="switch-label">演示模式</span>
              <el-switch v-model="autoUploadConfig.demo_mode" />
            </div>
            <div class="switch-row">
              <span class="switch-label">槽位对齐（试验）</span>
              <el-switch v-model="autoUploadConfig.slot_alignment_test" />
            </div>
            <div class="switch-row">
              <span class="switch-label">上架前同步 MinIO</span>
              <el-switch v-model="autoUploadConfig.auto_sync_minio" />
            </div>
            <div class="switch-row">
              <span class="switch-label">配件成本定价</span>
              <el-switch
                v-model="accessoryCostPricingEnabled"
                :disabled="originalSumPricingEnabled"
              />
            </div>
            <div class="switch-row">
              <span class="switch-label">子商品档位浮动</span>
              <el-switch
                v-model="accessoryCostTieredFloatEnabled"
                :disabled="!accessoryCostPricingEnabled || originalSumPricingEnabled"
              />
            </div>
            <div class="switch-row">
              <span class="switch-label">原价相加</span>
              <el-switch v-model="originalSumPricingEnabled" />
            </div>
          </div>
          <div v-if="originalSumPricingEnabled" class="form-tip">
            原价相加：拼单价 = 主商品「拼多多定价」+ 子商品「组合装定价」，不加浮动。
            与「活动与推广」共用开关，RabbitMQ 自动上架同样生效。
          </div>
          <div v-else-if="accessoryCostPricingEnabled" class="form-tip">
            拼单价 = 主商品拼多多定价 + 主商品浮动（{{ accessoryCostPricingFloatMin }}~{{ accessoryCostPricingFloatMax }}）+ 子商品组合装定价 + 子商品浮动。
            <template v-if="accessoryCostTieredFloatEnabled">
              子商品按定价档位：≤0.5 +1~1.5；0.5~1 +1.5~2.5；1~2 +3~4；&gt;2 +5~7。
            </template>
            <template v-else>
              子商品统一浮动 {{ accessoryCostPricingFloatMin }}~{{ accessoryCostPricingFloatMax }} 元。
            </template>
            与「活动与推广」共用开关，RabbitMQ 自动上架同样生效。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="autoUploadConfigVisible = false">取消</el-button>
        <el-button type="primary" :loading="autoUploadSaving" @click="confirmAutoUploadConfig">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tip {
  margin-bottom: 4px;
}

.task-card {
  margin-bottom: 0;
}

.side-card {
  margin-bottom: 16px;
}

.side-card:last-child {
  margin-bottom: 0;
}

.feishu-inspect-meta {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.feishu-inspect-expand {
  padding: 8px 12px 4px;
  font-size: 13px;
}

.feishu-inspect-subtable {
  margin-top: 8px;
}

.feishu-cell-empty {
  color: var(--el-color-danger);
  font-weight: 600;
}

.pipeline-layout {
  align-items: flex-start;
}

.pipeline-side-col {
  min-width: 0;
}

.recent-pipelines-card :deep(.el-card__body) {
  padding-bottom: 12px;
}

.commerce-card :deep(.el-card__body) {
  padding-top: 8px;
  padding-bottom: 12px;
}

.commerce-account-hint {
  margin-bottom: 12px;
}

.commerce-status-table {
  margin-bottom: 8px;
}

.commerce-intents-panel {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.commerce-intents-head {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 8px;
}

.commerce-merged-tag {
  margin-left: 4px;
  vertical-align: middle;
}

.recent-pipelines-table {
  width: 100%;
}

.recent-pipelines-table :deep(.el-table__body-wrapper) {
  max-height: 420px;
  overflow-y: auto;
}

.recent-pipelines-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
  overflow-x: auto;
}

.recent-pipelines-pagination :deep(.el-pagination) {
  flex-wrap: wrap;
  justify-content: flex-end;
  row-gap: 8px;
}

.pipeline-form {
  max-width: 100%;
}

.form-section {
  padding: 16px 18px;
  margin-bottom: 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: #fafbfd;
}

.form-section-material {
  background: #fff;
  border-color: #e2e8f0;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}

.form-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.form-section-title {
  margin: 0;
  font-size: 13px;
  font-weight: 700;
  color: #475569;
  letter-spacing: 0.02em;
  text-transform: none;
}

.limited-time-inline {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  border: 1px solid #fcd34d;
  border-radius: 8px;
  background: #fffbeb;
}

.limited-time-label {
  font-size: 13px;
  font-weight: 600;
  color: #b45309;
  white-space: nowrap;
}

.limited-time-hint {
  font-size: 12px;
  white-space: nowrap;
}

.limited-time-tip {
  margin: -6px 0 12px;
}

.form-section :deep(.el-form-item:last-child) {
  margin-bottom: 0;
}

.batch-toggle-row {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.material-form-item :deep(.el-form-item__label) {
  display: none;
}

.material-panel {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: linear-gradient(180deg, #f8fafc 0%, #fff 100%);
}

.material-panel-toolbar {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 10px 12px;
  align-items: center;
}

.material-source-row {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-segment :deep(.el-radio-button__inner) {
  padding: 7px 14px;
  font-size: 13px;
}

.random-select-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.random-select-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.random-select-input {
  width: 88px;
}

.toolbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.auto-upload-row {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding-top: 8px;
  margin-top: 2px;
  border-top: 1px dashed var(--border-color);
}

.auto-upload-mode-select {
  width: 140px;
}

.auto-upload-config-form {
  margin-top: 8px;
}

.selection-summary {
  font-size: 12px;
  color: var(--text-secondary);
}

.material-group-select :deep(.el-select__wrapper) {
  min-height: 40px;
  align-items: flex-start;
  padding-top: 6px;
  padding-bottom: 6px;
}

.material-group-select :deep(.el-select__selection) {
  flex-wrap: wrap;
  gap: 4px;
  max-height: 84px;
  overflow-y: auto;
}

.material-group-select :deep(.el-select__selected-item .el-tag) {
  max-width: 180px;
}

.material-group-select :deep(.el-select__selected-item .el-tag__content) {
  overflow: hidden;
  text-overflow: ellipsis;
}

.option-main {
  font-weight: 500;
  margin-right: 8px;
}

.option-meta {
  font-size: 12px;
  color: var(--text-muted);
  margin-right: 8px;
}

.material-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.material-option-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1 1 auto;
}

.material-option-set {
  font-weight: 600;
  color: #1e293b;
}

.material-option-meta {
  font-size: 12px;
  color: var(--text-muted);
}

.material-option-tags {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.material-option-tags .listed-tag {
  margin-left: 0;
}

.pick-family {
  font-weight: 700;
  color: #0f172a;
}

.pick-set-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 12px;
  font-weight: 600;
}

.empty-set-tip {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-muted);
  padding: 4px 0;
}

.product-pick-panel {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
}

.selection-overview-card {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.selection-overview-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
}

.selection-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 88px;
}

.selection-metric-value {
  font-size: 20px;
  line-height: 1.1;
  font-weight: 700;
  color: #0f172a;
}

.selection-metric-label {
  font-size: 12px;
  color: #64748b;
}

.selection-overview-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.selection-overview-preview {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.selection-overview-more {
  font-size: 12px;
  color: var(--text-muted);
}

.product-pick-group {
  padding: 14px 16px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: #fafbfd;
  min-height: 136px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.product-pick-group-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.product-pick-group-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.group-toggle-tag {
  cursor: pointer;
  user-select: none;
}

.product-pick-group-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.product-pick-group-summary {
  font-size: 13px;
  color: #475569;
  line-height: 1.5;
}

.product-pick-preview {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-height: 32px;
}

.product-pick-more {
  font-size: 12px;
  color: var(--text-muted);
}

.listed-tag {
  margin-left: 6px;
}

.product-drawer-header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.product-drawer-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.product-drawer-meta {
  font-size: 13px;
  color: #64748b;
}

.product-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.product-drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.product-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 12px;
}

.product-card {
  border: 1px solid #dbe4f0;
  border-radius: 12px;
  background: #fff;
  padding: 12px;
  min-height: 116px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.product-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 8px 24px rgba(37, 99, 235, 0.08);
  transform: translateY(-1px);
}

.product-card.is-checked {
  border-color: #60a5fa;
  background: #f8fbff;
}

.product-card.is-listed {
  background: #f0fdf4;
  border-color: #86efac;
}

.product-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.product-card-code {
  font-size: 15px;
  line-height: 1.4;
  font-weight: 700;
  color: #0f172a;
  word-break: break-all;
}

.product-card-foot {
  margin-top: auto;
  font-size: 12px;
  color: #94a3b8;
}

.form-label-with-actions {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.label-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.label-actions :deep(.el-button) {
  padding: 0 4px;
  height: auto;
  font-size: 13px;
}

.form-tip {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.option-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px 28px;
  width: 100%;
}

.listing-throttle-row {
  gap: 12px 16px;
}

.throttle-inline-label {
  color: var(--text-secondary);
  font-size: 13px;
}

.switch-row {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.switch-label {
  font-size: 13px;
  color: #475569;
}

.slot-align-test {
  margin: 0;
}

.submit-btn {
  flex: 1;
  margin-top: 4px;
}

.minio-sync-progress {
  margin: 12px 0 4px;
  padding: 12px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.minio-sync-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.submit-actions {
  display: flex;
  gap: 12px;
  align-items: stretch;
  margin-top: 4px;
}

.preflight-card {
  margin-top: 16px;
}

.preflight-table {
  width: 100%;
}

.listing-unit-panel {
  margin: 12px 0 16px;
}

.listing-unit-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
}

.listing-unit-summary {
  font-weight: 400;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.listing-unit-table {
  width: 100%;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-head-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.msg {
  margin-top: 12px;
}

.meta {
  margin: 0 0 8px;
  color: var(--text-secondary);
  font-size: 13px;
}

.error-text {
  color: var(--el-color-danger);
  margin-bottom: 12px;
}

.warn-text {
  color: var(--el-color-warning);
  margin-bottom: 12px;
  font-size: 13px;
}

.steps {
  margin-top: 8px;
}

.steps-overall-hint {
  margin: 0 0 10px;
}

.batch-stage-body {
  min-height: 120px;
}

.batch-stage-meta {
  margin: 0 0 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.batch-lt-chunk-settings {
  margin: 0 0 12px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}

.batch-lt-retry-all-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin: 0 0 12px;
  padding: 10px 12px;
  border: 1px dashed var(--el-color-warning-light-5);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
}

.batch-lt-chunk-settings-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.batch-lt-chunk-label {
  font-size: 13px;
  font-weight: 500;
}

.batch-stage-collapse {
  border: none;
}

.batch-stage-collapse-title {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
  width: 100%;
  padding-right: 12px;
}

.batch-stage-collapse-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.batch-stage-collapse-label {
  font-weight: 600;
  color: var(--el-text-color-primary);
  flex-shrink: 0;
}

.batch-stage-collapse-summary {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  word-break: break-word;
}

.batch-stage-retry-btn {
  flex-shrink: 0;
}

:deep(.batch-stage-collapse .el-collapse-item__header) {
  height: auto;
  min-height: 48px;
  line-height: 1.4;
  padding-top: 8px;
  padding-bottom: 8px;
}

:deep(.batch-stage-collapse .el-collapse-item__arrow) {
  align-self: flex-start;
  margin-top: 10px;
}

.batch-stage-product-table {
  width: 100%;
}

.step-desc {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.step-detail-text {
  flex: 1 1 100%;
  line-height: 1.5;
}

.campaign-results {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.campaign-result-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
}

.campaign-result-id {
  font-size: 12px;
  color: var(--el-text-color-primary);
}

.campaign-result-summary {
  flex: 1 1 100%;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}
</style>

<style>
.material-group-select-popper {
  min-width: 520px !important;
}

.material-group-select-popper .el-select-dropdown__item {
  height: auto;
  min-height: 44px;
  padding-top: 8px;
  padding-bottom: 8px;
  line-height: 1.4;
}

.material-group-select-popper .el-select-group__title {
  font-size: 12px;
  font-weight: 700;
  color: #64748b;
}
</style>
