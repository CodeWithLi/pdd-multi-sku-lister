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
  loadListingThrottleEnabled,
  loadPipelineRelistStrategy,
  saveListingBatchIntervalMinutes,
  saveListingBatchSetCount,
  saveListingThrottleEnabled,
  savePipelineRelistStrategy,
} from '@/utils/pipelinePreferences'
import {
  failureReasonLabel,
  listingUnitStatusType,
} from '@/utils/labels'
import type {
  Account,
  AutoUploadConfig,
  AutoUploadTriggerMode,
  FeishuInspectListingPricesResult,
  IntegratedPipeline,
  ListingTargetOption,
  MarketingActivityOption,
  PreflightResponse,
  RelistStrategy,
} from '@/types'

const router = useRouter()
const loading = ref(false)
const cancelingId = ref('')
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

const accountId = ref('')
const productCodes = ref<string[]>([])
const checkedProductsBySet = ref<Record<string, string[]>>({})
const activityIds = ref<string[]>(['20981'])
const categoryKeyword = ref('玩偶')
const autoPromotion = ref(true)
const continueAfterLimitedTimeFailure = ref(false)
const continueAfterActivityFailure = ref(false)
const demoMode = ref(true)
const activityDelayHours = ref(24)
const slotAlignmentTest = ref(true)
const relistStrategy = ref<RelistStrategy>(loadPipelineRelistStrategy())
const listingThrottleEnabled = ref(loadListingThrottleEnabled())
const listingBatchSetCount = ref(loadListingBatchSetCount())
const listingBatchIntervalMinutes = ref(loadListingBatchIntervalMinutes())
const excelFallbackEnabled = ref(false)
const excelFallbackSaving = ref(false)
const logSpecSkuRowsEnabled = ref(false)
const logSpecSkuRowsSaving = ref(false)
const pipelineBatchEnabled = ref(false)
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
  activity_ids: ['20981'],
  category_keyword: '玩偶',
  auto_promotion: true,
  auto_limited_time_setup: true,
  continue_after_limited_time_failure: false,
  continue_after_activity_failure: false,
  demo_mode: true,
  activity_delay_hours: 24,
  slot_alignment_test: true,
  material_source: 'minio',
  auto_sync_minio: true,
})
const { minioSyncJob, syncing, startSync, resumeActiveSync } = useMinioSync()

const {
  materialPolling,
  sseConnected,
  switchingMode,
  refreshMode,
  restart: restartMaterialRefresh,
  stop: stopMaterialRefresh,
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
      } else if (data.auto_pipeline?.reason !== 'append_only_batch') {
        ElMessage.warning(autoHint)
      }
      return
    }
  },
})

let pollTimer: ReturnType<typeof setInterval> | null = null

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))

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

function selectAllMaterialGroups() {
  productCodes.value = visibleProductOptions.value.map((item) => item.selector)
  syncCheckedProductsForSets(productCodes.value)
}

function clearAllMaterialGroups() {
  productCodes.value = []
  checkedProductsBySet.value = {}
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

async function loadLogSpecSkuRowsSetting() {
  const data = await api.getPipelineLogSpecSkuRows()
  logSpecSkuRowsEnabled.value = !!data.enabled
}

function applyAutoUploadConfig(cfg: AutoUploadConfig) {
  autoUploadConfig.value = { ...cfg }
  autoUploadEnabled.value = !!cfg.enabled
  autoUploadTriggerMode.value = cfg.trigger_mode || 'new_product_folder'
}

async function loadAutoUploadConfig() {
  const data = await api.getAutoUploadConfig()
  applyAutoUploadConfig(data)
}

function buildAutoUploadPayload(overrides: Partial<AutoUploadConfig> = {}): AutoUploadConfig {
  return {
    ...autoUploadConfig.value,
    enabled: autoUploadEnabled.value,
    trigger_mode: autoUploadTriggerMode.value,
    account_id: autoUploadConfig.value.account_id || accountId.value,
    ...overrides,
  }
}

async function saveAutoUploadConfig(overrides: Partial<AutoUploadConfig> = {}) {
  autoUploadSaving.value = true
  try {
    const payload = buildAutoUploadPayload(overrides)
    if (payload.enabled && !payload.account_id) {
      throw new Error('开启自动上架时请选择店铺')
    }
    if (payload.enabled && !payload.activity_ids.length) {
      throw new Error('开启自动上架时请至少选择一个活动')
    }
    const saved = await api.updateAutoUploadConfig(payload)
    applyAutoUploadConfig(saved)
    return saved
  } finally {
    autoUploadSaving.value = false
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
  autoUploadConfigVisible.value = true
}

async function confirmAutoUploadConfig() {
  try {
    await saveAutoUploadConfig({
      account_id: autoUploadConfig.value.account_id,
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
    })
    autoUploadConfigVisible.value = false
    ElMessage.success('自动上架配置已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : String(e))
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
  if (!activityIds.value.length) {
    error.value = '请至少选择一个活动'
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
        activity_delay_hours: demoMode.value ? 0 : activityDelayHours.value,
        demo_mode: demoMode.value,
        slot_alignment_test: slotAlignmentTest.value,
        store_start_delay_min_seconds: startDelayMin.value,
        store_start_delay_max_seconds: startDelayMax.value,
        skip_listing: skipListing,
        listing_skip_selectors: listingSkipSelectors,
        material_source: materialSource.value,
        relist_strategy: relistStrategy.value,
        listing_throttle_enabled: listingThrottleEnabled.value,
        listing_batch_set_count: listingBatchSetCount.value,
        listing_batch_interval_minutes: listingBatchIntervalMinutes.value,
      })
      success.value = `批量整合链路已提交：${result.total} 条，批次 ${result.batch_id}，活动 ${activityIds.value.length} 个，启动间隔 ${result.store_start_delay_min_seconds}-${result.store_start_delay_max_seconds} 秒${
        listingThrottleEnabled.value
          ? `；分批上架 ${listingBatchSetCount.value} 套/批，间隔 ${listingBatchIntervalMinutes.value} 分钟`
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
        activity_delay_hours: demoMode.value ? 0 : activityDelayHours.value,
        demo_mode: demoMode.value,
        slot_alignment_test: slotAlignmentTest.value,
        skip_listing: skipListing,
        listing_skip_selectors: listingSkipSelectors,
        material_source: materialSource.value,
        relist_strategy: relistStrategy.value,
        listing_throttle_enabled: listingThrottleEnabled.value,
        listing_batch_set_count: listingBatchSetCount.value,
        listing_batch_interval_minutes: listingBatchIntervalMinutes.value,
      })
      pipelinePage.value = 1
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
        ? `（分批上架：${selectedSetCount.value} 套分 ${listingBatchPlanCount.value} 批，每批 ${listingBatchSetCount.value} 套，间隔 ${listingBatchIntervalMinutes.value} 分钟）`
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

watch(relistStrategy, (value) => {
  savePipelineRelistStrategy(value)
})

watch(listingThrottleEnabled, (value) => {
  saveListingThrottleEnabled(value)
})

watch(listingBatchSetCount, (value) => {
  saveListingBatchSetCount(Number(value) || 5)
})

watch(listingBatchIntervalMinutes, (value) => {
  saveListingBatchIntervalMinutes(Number(value) || 30)
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
    await loadLogSpecSkuRowsSetting()
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
                  多店共用下方素材选择，各店按启动间隔错开入队
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

              <el-row v-if="pipelineBatchEnabled" :gutter="16">
                <el-col :span="12">
                  <el-form-item label="启动间隔最小秒数">
                    <el-input-number v-model="startDelayMin" :min="0" :max="3600" style="width: 100%" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="启动间隔最大秒数">
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
                      <el-tag v-if="materialSource === 'minio' && refreshMode === 'poll' && materialPolling" size="small" type="info">
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
                        <el-tag v-if="refreshMode === 'rabbitmq' && sseConnected" size="small" type="success">实时监听</el-tag>
                        <el-tag v-else-if="refreshMode === 'rabbitmq'" size="small" type="warning">推送未连接</el-tag>
                      </template>
                    </div>
                    <el-radio-group v-model="showOnlyUnlistedGroups" size="small" class="filter-segment">
                      <el-radio-button :label="true">
                        仅未上架{{ unlistedGroupCount ? ` (${unlistedGroupCount})` : '' }}
                      </el-radio-button>
                      <el-radio-button :label="false">全部套图</el-radio-button>
                    </el-radio-group>
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
                  <div v-for="group in selectedSetGroups" :key="group.selector" class="product-pick-group">
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
                    </div>
                    <el-checkbox-group
                      v-if="group.product_codes.length"
                      :model-value="checkedProductsBySet[group.selector] || []"
                      @update:model-value="(v) => updateCheckedProducts(group.selector, v as string[])"
                    >
                      <el-checkbox v-for="code in group.product_codes" :key="code" :label="code" :value="code">
                        {{ code }}
                        <el-tag v-if="isProductListed(group, code)" size="small" type="success" class="listed-tag">
                          已上架
                        </el-tag>
                      </el-checkbox>
                    </el-checkbox-group>
                    <div v-else class="empty-set-tip">
                      套图目录已存在，但暂无可用商品（需在套图下放入带 1.jpg/1.png 等编号主图的商品文件夹）
                    </div>
                  </div>
                </div>
              </el-form-item>

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
                  会先按「商品编码」扫在售列表，<strong>同一编码下的全部重复链接都会下架</strong>，并删除系统「已发布商品」记录，再重新上架 1 条；适用于 MinIO 补图后重跑整合链路。
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
                  已选 {{ selectedSetCount }} 套图，将分 {{ listingBatchPlanCount }} 批上架；全部批次完成后才进入限时限量购 / 活动 / 推广。
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

              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="类目关键词">
                    <el-input v-model="categoryKeyword" placeholder="上架类目，默认玩偶" />
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
                  <el-checkbox v-model="slotAlignmentTest" class="slot-align-test">
                    槽位对齐（试验）
                  </el-checkbox>
                  <div class="switch-row">
                    <span class="switch-label">自动推广</span>
                    <el-switch v-model="autoPromotion" />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">限时失败仍继续</span>
                    <el-switch v-model="continueAfterLimitedTimeFailure" />
                  </div>
                  <div class="switch-row">
                    <span class="switch-label">活动失败仍继续</span>
                    <el-switch v-model="continueAfterActivityFailure" />
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
                  link
                  type="primary"
                  size="small"
                  :loading="feishuInspectLoading"
                  @click="openFeishuInspectDialog(activePipeline)"
                >
                  飞书定价数据
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
            <el-table-column label="操作" width="148" fixed="right" align="center">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="activePipeline = row">查看</el-button>
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
                    <el-table-column prop="综合零售成本" label="综合零售成本" width="108" />
                    <el-table-column prop="拼多多定价" label="拼多多定价" width="96" />
                    <el-table-column prop="拼多多控价" label="拼多多控价" width="96" />
                    <el-table-column prop="PDD控价下限价格" label="下限" width="88" />
                    <el-table-column prop="PDD控价上限价格" label="上限" width="88" />
                  </el-table>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="query_code" label="查询编码" min-width="148" show-overflow-tooltip />
            <el-table-column label="综合零售成本" width="108">
              <template #default="{ row }">
                <span :class="{ 'feishu-cell-empty': !row.parsed?.['综合零售成本'] && !row.catalog_retail_cost }">
                  {{ row.parsed?.['综合零售成本'] || row.catalog_retail_cost || '—' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="拼多多定价" width="96">
              <template #default="{ row }">{{ row.parsed?.拼多多定价 || '—' }}</template>
            </el-table-column>
            <el-table-column label="拼多多控价" width="96">
              <template #default="{ row }">{{ row.parsed?.拼多多控价 || '—' }}</template>
            </el-table-column>
            <el-table-column label="下限" width="80">
              <template #default="{ row }">{{ row.parsed?.PDD控价下限价格 || '—' }}</template>
            </el-table-column>
            <el-table-column label="上限" width="80">
              <template #default="{ row }">
                <span :class="{ 'feishu-cell-empty': !row.parsed?.PDD控价上限价格 }">
                  {{ row.parsed?.PDD控价上限价格 || '空' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="全表上限" width="88">
              <template #default="{ row }">{{ row.catalog_range_max || '—' }}</template>
            </el-table-column>
            <el-table-column label="快照上限" width="88">
              <template #default="{ row }">{{ row.snapshot_range_max || '—' }}</template>
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
          <el-select v-model="autoUploadConfig.account_id" placeholder="选择店铺" style="width: 100%">
            <el-option
              v-for="acc in enabledAccounts"
              :key="acc.account_id"
              :label="acc.account_id"
              :value="acc.account_id"
            />
          </el-select>
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
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.product-pick-group {
  padding: 12px 14px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #fff;
}

.product-pick-group-title {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.product-pick-group :deep(.el-checkbox) {
  margin-right: 18px;
}

.listed-tag {
  margin-left: 6px;
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
