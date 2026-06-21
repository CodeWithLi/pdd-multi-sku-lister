<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import {
  formatMaterialGroupLabel,
  formatMaterialGroupMeta,
  groupListingTargetsByFamily,
} from '@/utils/listingTargets'
import type {
  Account,
  IntegratedPipeline,
  ListingTargetOption,
  MarketingActivityOption,
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
const minioHealth = ref<{ available?: boolean; error?: string; listing_poll_seconds?: number } | null>(null)
const materialPolling = ref(false)
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
const pipelineBatchEnabled = ref(false)
const batchAccountIds = ref<string[]>([])
const startDelayMin = ref(30)
const startDelayMax = ref(180)

let pollTimer: ReturnType<typeof setInterval> | null = null
let materialPollTimer: ReturnType<typeof setInterval> | null = null

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

function stopMaterialPolling() {
  materialPolling.value = false
  if (materialPollTimer) {
    clearInterval(materialPollTimer)
    materialPollTimer = null
  }
}

function startMaterialPolling() {
  stopMaterialPolling()
  if (materialSource.value !== 'minio') return
  const seconds = minioHealth.value?.listing_poll_seconds ?? 30
  if (!seconds || seconds <= 0) return
  materialPolling.value = true
  materialPollTimer = setInterval(() => {
    if (accountId.value) loadListingTargets(accountId.value).catch(() => undefined)
  }, seconds * 1000)
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
  stopMaterialPolling()
  if (accountId.value) await loadListingTargets(accountId.value)
  startMaterialPolling()
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
      })
      success.value = `批量整合链路已提交：${result.total} 条，批次 ${result.batch_id}，活动 ${activityIds.value.length} 个，启动间隔 ${result.store_start_delay_min_seconds}-${result.store_start_delay_max_seconds} 秒`
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
      })
      pipelinePage.value = 1
      activePipeline.value = result
      const activityCount = activityIds.value.length
      const activityHint = activityCount > 1 ? `，${activityCount} 个活动将依次报名` : ''
      const partialHint = listingSkipSelectors.length
        ? `（已上架 ${listingSkipSelectors.length} 个跳过上架）`
        : ''
      success.value = skipListing
        ? demoMode.value
          ? `整合链路已启动（跳过上架，先限时限量购再约 2 分钟后报活动${activityHint}）`
          : `整合链路已启动（跳过上架，先限时限量购再 ${activityDelayHours.value} 小时后报活动${activityHint}）`
        : demoMode.value
          ? `整合链路已启动（演示：上架后限时限量购 → 约 2 分钟后报活动${activityHint}${partialHint}）`
          : `整合链路已启动（上架 → 限时限量购 → ${activityDelayHours.value} 小时后报活动${activityHint}${partialHint}）`
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
watch(accountId, (id) => {
  if (id) loadListingTargets(id).catch(() => undefined)
})

onMounted(async () => {
  try {
    await loadMinioHealth()
    await loadBaseData()
    await refreshPipelines()
    startPolling()
    startMaterialPolling()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

onUnmounted(() => {
  stopPolling()
  stopMaterialPolling()
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
                      <el-tag v-if="materialSource === 'minio' && materialPolling" size="small" type="info">
                        自动刷新
                      </el-tag>
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
                        size="small"
                        link
                        type="primary"
                        :disabled="!accountId"
                        @click="loadListingTargets(accountId)"
                      >
                        刷新
                      </el-button>
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
              </el-form-item>
            </div>

            <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="startPipeline">
              {{ pipelineBatchEnabled ? '批量启动整合链路' : '一键启动整合链路' }}
            </el-button>
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
            <el-table-column label="操作" width="96" fixed="right" align="center">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="activePipeline = row">查看</el-button>
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
  width: 100%;
  margin-top: 4px;
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
