<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import ResultSummary from '@/components/ResultSummary.vue'
import { summarizeRunError, extractActivitySpecLookupMeta, extractActivitySpecLookupRows, formatActivityRegistrationMessage, extractActivityRegistrationSummary } from '@/utils/runMessage'
import type {
  Account,
  CampaignTaskResponse,
  MarketingActivityOption,
  PublishedProduct,
  RunRecord,
} from '@/types'

type ProductTableRef = {
  clearSelection: () => void
}

const router = useRouter()

const taskLoading = ref(false)
const marketingTaskLoading = ref(false)
const productLoading = ref(false)
const error = ref('')
const taskError = ref('')
const taskSuccess = ref('')
const accounts = ref<Account[]>([])
const accountId = ref('')
const result = ref<CampaignTaskResponse | null>(null)
const marketingResult = ref<CampaignTaskResponse | null>(null)
const activeCampaignRun = ref<RunRecord | null>(null)
const activeMarketingRun = ref<RunRecord | null>(null)
const marketingActivities = ref<MarketingActivityOption[]>([])
const marketingActivityId = ref('')
const productTableRef = ref<ProductTableRef | null>(null)
const publishedProducts = ref<PublishedProduct[]>([])
const selectedProducts = ref<PublishedProduct[]>([])
const productTotal = ref(0)
const productPage = ref(1)
const productPageSize = ref(20)
const productFilters = reactive({
  pdd_product_id: '',
  product_code: '',
})

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))
const selectedPddProductIds = computed(() => {
  const ids = selectedProducts.value
    .map((item) => String(item.pdd_product_id || '').trim())
    .filter(Boolean)
  return Array.from(new Set(ids))
})
const selectedMappingIds = computed(() => {
  const ids = selectedProducts.value.map((item) => String(item.mapping_id || '').trim()).filter(Boolean)
  return Array.from(new Set(ids))
})
const canStart = computed(() => Boolean(accountId.value) && selectedPddProductIds.value.length > 0)
const isCampaignRunning = computed(() => {
  const status = activeCampaignRun.value?.status || result.value?.status
  return status === 'pending' || status === 'running'
})
const isMarketingRunning = computed(() => {
  const status = activeMarketingRun.value?.status || marketingResult.value?.status
  return status === 'pending' || status === 'running'
})
const selectedMarketingActivity = computed(() =>
  marketingActivities.value.find((item) => item.activity_id === marketingActivityId.value) || null,
)
const canSearchMarketingActivity = computed(
  () => Boolean(accountId.value) && Boolean(marketingActivityId.value),
)
const canRegisterMarketingActivity = computed(
  () =>
    Boolean(accountId.value) &&
    Boolean(marketingActivityId.value) &&
    selectedPddProductIds.value.length > 0,
)
const currentStep = computed(() => {
  if (!accountId.value || !marketingActivityId.value) return 0
  if (!selectedPddProductIds.value.length) return 1
  return 2
})

type ActivitySpecLookupRow = import('@/utils/runMessage').ActivitySpecLookupRow

function campaignResultPayload(): Record<string, unknown> | null {
  return (marketingResult.value?.result || activeMarketingRun.value?.result || null) as Record<
    string,
    unknown
  > | null
}

const marketingSpecLookupRows = computed(() => extractActivitySpecLookupRows(campaignResultPayload() ?? undefined))

const marketingSpecLookup = computed(() => extractActivitySpecLookupMeta(campaignResultPayload() ?? undefined))

const showSpecLookupPanel = computed(() => {
  if (!['20981', '21365'].includes(marketingActivityId.value)) return false
  if (marketingResult.value || result.value) return false
  return marketingSpecLookupRows.value.length > 0
})

const hasResultSummary = computed(() => Boolean(marketingResult.value || result.value))

const canExpandLeftPanel = computed(() => showSpecLookupPanel.value || hasResultSummary.value)

const leftPanelExpanded = ref(false)

const sideStackRef = ref<HTMLElement | null>(null)

function toggleLeftPanelExpanded() {
  leftPanelExpanded.value = !leftPanelExpanded.value
}

watch(canExpandLeftPanel, (visible) => {
  if (!visible) leftPanelExpanded.value = false
})

watch(hasResultSummary, (visible) => {
  if (!visible) return
  nextTick(() => {
    sideStackRef.value?.scrollTo({ top: 0 })
    sideStackRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
})
let campaignPollTimer: number | undefined
let marketingPollTimer: number | undefined

async function loadMeta() {
  try {
    const [accountList, activityList] = await Promise.all([
      api.accounts(true),
      api.campaignMarketingActivities(),
    ])
    accounts.value = accountList
    marketingActivities.value = activityList.items
    if (accounts.value.length && !accountId.value) {
      accountId.value = accounts.value[0].account_id
    }
    if (marketingActivities.value.length && !marketingActivityId.value) {
      marketingActivityId.value = marketingActivities.value[0].activity_id
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载店铺失败，请确认后台已启动'
  }
}

async function loadPublishedProducts() {
  if (!accountId.value) {
    publishedProducts.value = []
    productTotal.value = 0
    clearProductSelection()
    return
  }

  productLoading.value = true
  error.value = ''
  try {
    const resp = await api.publishedProducts({
      page: productPage.value,
      page_size: productPageSize.value,
      account_id: accountId.value,
      product_code: productFilters.product_code || undefined,
      pdd_product_id: productFilters.pdd_product_id || undefined,
    })
    publishedProducts.value = resp.items
    productTotal.value = resp.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载已发布商品失败'
    publishedProducts.value = []
    productTotal.value = 0
  } finally {
    productLoading.value = false
  }
}

function clearProductSelection() {
  selectedProducts.value = []
  productTableRef.value?.clearSelection()
}

function applyProductFilters() {
  productPage.value = 1
  clearProductSelection()
  loadPublishedProducts()
}

function resetProductFilters() {
  productFilters.pdd_product_id = ''
  productFilters.product_code = ''
  applyProductFilters()
}

function onProductPageChange(next: number) {
  productPage.value = next
  loadPublishedProducts()
}

function onProductPageSizeChange(next: number) {
  productPageSize.value = next
  productPage.value = 1
  loadPublishedProducts()
}

function isSelectableProduct(row: PublishedProduct) {
  return Boolean(row.pdd_product_id) && row.status !== 'delisted'
}

function onProductSelectionChange(rows: PublishedProduct[]) {
  selectedProducts.value = rows.filter(isSelectableProduct)
}

function showTaskError(text: string) {
  taskSuccess.value = ''
  taskError.value = text
}

function showTaskSuccess(text: string) {
  taskError.value = ''
  taskSuccess.value = text
  ElMessage.success(text)
}

function showFormError(text: string) {
  ElMessage.warning(text)
}

function summarizeTaskFailure(resp: Pick<CampaignTaskResponse, 'message' | 'result'>): string {
  return summarizeRunError({ message: resp.message, result: resp.result })
}

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function stopCampaignPolling() {
  if (campaignPollTimer) {
    window.clearInterval(campaignPollTimer)
    campaignPollTimer = undefined
  }
}

function stopMarketingPolling() {
  if (marketingPollTimer) {
    window.clearInterval(marketingPollTimer)
    marketingPollTimer = undefined
  }
}

function syncResultFromRun(run: RunRecord) {
  activeCampaignRun.value = run
  if (!result.value || result.value.run_id !== run.run_id) return
  const shortMsg =
    run.status === 'failed' ? summarizeRunError(run) : run.message || result.value.message
  result.value = {
    ...result.value,
    status: run.status,
    message: shortMsg,
    result: run.result,
  }
}

function syncMarketingResultFromRun(run: RunRecord) {
  activeMarketingRun.value = run
  if (!marketingResult.value || marketingResult.value.run_id !== run.run_id) return
  const shortMsg =
    run.status === 'failed' ? summarizeRunError(run) : run.message || marketingResult.value.message
  marketingResult.value = {
    ...marketingResult.value,
    status: run.status,
    message: shortMsg,
    result: run.result,
  }
}

function campaignCompletionMessage(run: RunRecord): string {
  const summary = extractActivityRegistrationSummary(run.result as Record<string, unknown> | undefined)
  const formatted = formatActivityRegistrationMessage(summary)
  if (formatted) return formatted
  return run.message || '营销活动任务已完成'
}

function startMarketingPolling(runId: string) {
  stopMarketingPolling()
  marketingPollTimer = window.setInterval(async () => {
    try {
      const run = await api.run(runId)
      syncMarketingResultFromRun(run)
      if (!['pending', 'running'].includes(run.status)) {
        stopMarketingPolling()
        marketingTaskLoading.value = false
        if (run.status === 'success') {
          showTaskSuccess(campaignCompletionMessage(run))
        } else if (run.status === 'failed') {
          showTaskError(summarizeRunError(run))
        }
      }
    } catch (e) {
      stopMarketingPolling()
      marketingTaskLoading.value = false
      showTaskError(e instanceof Error ? e.message : '查询营销活动任务状态失败')
    }
  }, 2000)
}

async function startMarketingActivityRegister() {
  if (isMarketingRunning.value || isCampaignRunning.value) {
    showFormError('当前已有活动任务正在执行，请等待完成后再启动')
    return
  }
  if (!accountId.value) {
    showFormError('请选择店铺')
    return
  }
  if (!marketingActivityId.value) {
    showFormError('请选择营销活动')
    return
  }
  if (!selectedPddProductIds.value.length) {
    showFormError('请先选择要报名的已发布商品')
    return
  }

  marketingTaskLoading.value = true
  taskError.value = ''
  taskSuccess.value = ''
  marketingResult.value = null
  activeMarketingRun.value = null
  try {
    marketingResult.value = await api.campaignMarketingActivityRegister({
      account_id: accountId.value,
      activity_id: marketingActivityId.value,
      pdd_product_ids: selectedPddProductIds.value,
    })
    if (marketingResult.value.status === 'failed') {
      marketingResult.value = {
        ...marketingResult.value,
        message: summarizeTaskFailure(marketingResult.value),
      }
      showTaskError(marketingResult.value.message)
    } else {
      showTaskSuccess(marketingResult.value.message || '营销活动报名任务已启动')
    }
    activeMarketingRun.value = {
      run_id: marketingResult.value.run_id,
      agent: 'campaign',
      account_id: accountId.value,
      status: marketingResult.value.status,
      phase: '',
      started_at: new Date().toISOString(),
      finished_at: null,
      message: marketingResult.value.message || '',
      listing_labels: [],
      result: marketingResult.value.result || {},
    }
    if (['pending', 'running'].includes(marketingResult.value.status)) {
      startMarketingPolling(marketingResult.value.run_id)
    } else {
      marketingTaskLoading.value = false
    }
  } catch (e) {
    showTaskError(e instanceof Error ? e.message : '启动营销活动报名失败')
    marketingTaskLoading.value = false
  }
}

async function startMarketingActivitySearch() {
  if (isMarketingRunning.value || isCampaignRunning.value) {
    showFormError('当前已有活动任务正在执行，请等待完成后再启动')
    return
  }
  if (!accountId.value) {
    showFormError('请选择店铺')
    return
  }
  if (!marketingActivityId.value) {
    showFormError('请选择营销活动')
    return
  }

  marketingTaskLoading.value = true
  taskError.value = ''
  taskSuccess.value = ''
  marketingResult.value = null
  activeMarketingRun.value = null
  try {
    marketingResult.value = await api.campaignMarketingActivitySearch({
      account_id: accountId.value,
      activity_id: marketingActivityId.value,
    })
    if (marketingResult.value.status === 'failed') {
      marketingResult.value = {
        ...marketingResult.value,
        message: summarizeTaskFailure(marketingResult.value),
      }
      showTaskError(marketingResult.value.message)
    } else {
      showTaskSuccess(marketingResult.value.message || '营销活动搜索任务已启动')
    }
    activeMarketingRun.value = {
      run_id: marketingResult.value.run_id,
      agent: 'campaign',
      account_id: accountId.value,
      status: marketingResult.value.status,
      phase: '',
      started_at: new Date().toISOString(),
      finished_at: null,
      message: marketingResult.value.message || '',
      listing_labels: [],
      result: marketingResult.value.result || {},
    }
    if (['pending', 'running'].includes(marketingResult.value.status)) {
      startMarketingPolling(marketingResult.value.run_id)
    } else {
      marketingTaskLoading.value = false
    }
  } catch (e) {
    showTaskError(e instanceof Error ? e.message : '启动营销活动搜索失败')
    marketingTaskLoading.value = false
  }
}

function startCampaignPolling(runId: string) {
  stopCampaignPolling()
  campaignPollTimer = window.setInterval(async () => {
    try {
      const run = await api.run(runId)
      syncResultFromRun(run)
      if (!['pending', 'running'].includes(run.status)) {
        stopCampaignPolling()
        taskLoading.value = false
        if (run.status === 'success') {
          showTaskSuccess('活动任务已完成')
        } else if (run.status === 'failed') {
          showTaskError(summarizeRunError(run))
        }
      }
    } catch (e) {
      stopCampaignPolling()
      taskLoading.value = false
      showTaskError(e instanceof Error ? e.message : '查询活动任务状态失败')
    }
  }, 2000)
}

async function startLimitedTimeSetup() {
  if (isCampaignRunning.value || isMarketingRunning.value) {
    showFormError('当前已有活动任务正在执行，请等待完成后再启动')
    return
  }
  if (!accountId.value) {
    showFormError('请选择店铺')
    return
  }
  if (!selectedPddProductIds.value.length) {
    showFormError('请先选择要搜索的商品')
    return
  }

  taskLoading.value = true
  taskError.value = ''
  taskSuccess.value = ''
  result.value = null
  activeCampaignRun.value = null
  try {
    result.value = await api.campaignLimitedTimeSetup({
      account_id: accountId.value,
      pdd_product_ids: selectedPddProductIds.value,
      published_mapping_ids: selectedMappingIds.value,
    })
    if (result.value.status === 'failed') {
      const shortMsg = summarizeTaskFailure(result.value)
      result.value = { ...result.value, message: shortMsg }
      showTaskError(shortMsg)
    } else {
      showTaskSuccess(result.value.message || '限时限量购活动设置任务已启动')
    }
    activeCampaignRun.value = {
      run_id: result.value.run_id,
      agent: 'campaign',
      account_id: accountId.value,
      status: result.value.status,
      phase: '',
      started_at: new Date().toISOString(),
      finished_at: null,
      message: result.value.message || '',
      listing_labels: [],
      result: result.value.result || {},
    }
    if (['pending', 'running'].includes(result.value.status)) {
      startCampaignPolling(result.value.run_id)
    } else {
      taskLoading.value = false
    }
  } catch (e) {
    showTaskError(e instanceof Error ? e.message : '启动活动任务失败')
    taskLoading.value = false
  }
}

function goRunDetail(runId: string) {
  router.push({ path: '/runs', query: { id: runId } })
}

watch(accountId, () => {
  productPage.value = 1
  clearProductSelection()
  loadPublishedProducts()
})

onMounted(loadMeta)
onBeforeUnmount(() => {
  stopCampaignPolling()
  stopMarketingPolling()
})
</script>

<template>
  <div
    class="campaign-page"
    :class="{ 'campaign-page--expanded': leftPanelExpanded }"
    v-loading="taskLoading || marketingTaskLoading"
  >
    <PageHeader title="活动" desc="营销活动报名 + 限时限量购设置，左侧配置、右侧选品。" />

    <el-alert
      v-if="error"
      type="error"
      title="页面加载失败"
      :description="error"
      show-icon
      closable
      class="page-alert"
      @close="error = ''"
    />

    <el-steps :active="currentStep" align-center class="flow-steps" finish-status="success">
      <el-step title="选店铺与活动" description="左侧配置" />
      <el-step title="勾选商品" description="右侧表格" />
      <el-step title="启动任务" description="左侧按钮" />
    </el-steps>

    <el-row :gutter="16" class="campaign-layout">
      <!-- 左侧：配置 + 操作 -->
      <el-col :xs="24" :lg="leftPanelExpanded ? 24 : 8" :xl="leftPanelExpanded ? 24 : 7">
        <div
          ref="sideStackRef"
          class="side-stack"
          :class="{
            'side-stack--expanded': leftPanelExpanded || hasResultSummary,
            'side-stack--results-first': hasResultSummary,
          }"
        >
          <el-card shadow="never" class="stat-card side-card side-card-config">
            <template #header>
              <div class="card-head">
                <span>活动配置</span>
                <el-tag v-if="marketingActivityId" size="small" type="info" effect="plain">
                  ID {{ marketingActivityId }}
                </el-tag>
              </div>
            </template>

            <el-form label-position="top" class="compact-form">
              <el-form-item label="店铺" required>
                <el-select v-model="accountId" filterable style="width: 100%" placeholder="选择店铺">
                  <el-option
                    v-for="a in enabledAccounts"
                    :key="a.account_id"
                    :label="a.account_id"
                    :value="a.account_id"
                  />
                </el-select>
              </el-form-item>

              <el-form-item label="营销活动" required>
                <el-select
                  v-model="marketingActivityId"
                  filterable
                  style="width: 100%"
                  placeholder="选择活动"
                >
                  <el-option
                    v-for="item in marketingActivities"
                    :key="item.activity_id"
                    :label="`${item.name}（${item.activity_id}）`"
                    :value="item.activity_id"
                  />
                </el-select>
              </el-form-item>
            </el-form>

            <div v-if="selectedMarketingActivity" class="activity-brief">
              <div class="activity-brief-title">{{ selectedMarketingActivity.name }}</div>
              <div class="muted">活动 ID：{{ selectedMarketingActivity.activity_id }}</div>
            </div>

            <el-collapse class="tip-collapse">
              <el-collapse-item title="营销活动报名流程" name="marketing">
                <ol class="tip-list">
                  <li>搜索活动 → 进入详情 → 立即报名</li>
                  <li>弹窗内：查询 → 全选 → 确认 → 确认选择</li>
                  <li>21365：展开更多规格 → 取消「开启流量保护」等勾选（全店报名无则跳过，暂不提交）</li>
                  <li>取消流量保护 → 填入已选商品 ID → 确认</li>
                </ol>
              </el-collapse-item>
              <el-collapse-item title="限时限量购说明" name="limited">
                <p class="tip-text">
                  进入营销工具 → 限时限量购 → 立即创建。到设置页后只处理「同步设置惊喜优惠」复选框，不会点击最终创建。
                </p>
              </el-collapse-item>
            </el-collapse>
          </el-card>

          <el-card shadow="never" class="stat-card side-card side-card-action action-card">
            <template #header>
              <div class="card-head">
                <span>已选商品</span>
                <el-tag
                  :type="selectedPddProductIds.length ? 'success' : 'info'"
                  size="small"
                  effect="plain"
                >
                  {{ selectedPddProductIds.length }} 个
                </el-tag>
              </div>
            </template>

            <div v-if="selectedPddProductIds.length" class="selected-chips">
              <el-tag
                v-for="id in selectedPddProductIds"
                :key="id"
                size="small"
                effect="plain"
                class="id-chip"
              >
                {{ id }}
              </el-tag>
            </div>
            <el-empty v-else description="请在右侧表格勾选商品" :image-size="56" />

            <div class="action-group">
              <div class="action-group-label">营销活动</div>
              <el-button
                type="primary"
                class="action-btn"
                :disabled="!canRegisterMarketingActivity || isMarketingRunning || isCampaignRunning"
                :loading="isMarketingRunning"
                @click="startMarketingActivityRegister"
              >
                打开活动并报名
              </el-button>
              <el-button
                class="action-btn"
                :disabled="!canSearchMarketingActivity || isMarketingRunning || isCampaignRunning"
                @click="startMarketingActivitySearch"
              >
                仅搜索活动（不选品）
              </el-button>
            </div>

            <el-divider />

            <div class="action-group">
              <div class="action-group-label">限时限量购</div>
              <el-button
                type="warning"
                plain
                class="action-btn"
                :disabled="!canStart || isCampaignRunning || isMarketingRunning"
                :loading="isCampaignRunning"
                @click="startLimitedTimeSetup"
              >
                取消惊喜优惠设置
              </el-button>
            </div>
          </el-card>

          <div v-if="canExpandLeftPanel" class="left-panel-toolbar">
            <span v-if="leftPanelExpanded" class="toolbar-hint muted">
              表格已放大，右侧选品已隐藏
            </span>
            <el-button size="small" @click="toggleLeftPanelExpanded">
              <el-icon class="toolbar-icon">
                <FullScreen v-if="!leftPanelExpanded" />
                <Fold v-else />
              </el-icon>
              {{ leftPanelExpanded ? '恢复选品面板' : '放大表格' }}
            </el-button>
          </div>

          <el-card
            v-if="showSpecLookupPanel"
            shadow="never"
            class="stat-card side-card spec-lookup-card"
            :class="{ 'spec-lookup-card--expanded': leftPanelExpanded }"
          >
            <template #header>
              <div class="card-head">
                <span>价格确认页规格（完整名称）</span>
                <el-tag
                  :type="marketingSpecLookupRows.length ? 'success' : 'warning'"
                  size="small"
                  effect="plain"
                >
                  {{ marketingSpecLookup?.matched_count ?? 0 }}/{{ marketingSpecLookup?.spec_count ?? 0 }} 已匹配
                </el-tag>
              </div>
            </template>

            <el-table
              v-if="marketingSpecLookupRows.length"
              :data="marketingSpecLookupRows"
              size="small"
              stripe
              class="spec-lookup-table spec-full-table"
            >
              <el-table-column type="index" label="#" width="40" align="center" />
              <el-table-column label="完整规格名称" min-width="200">
                <template #default="{ row }">
                  <div class="spec-name-full">{{ row.spec_name || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column prop="activity_price" label="活动价" width="72" align="right" />
              <el-table-column
                v-if="marketingSpecLookupRows.some((row) => row.floor_price != null)"
                label="底价"
                width="72"
                align="right"
              >
                <template #default="{ row }">
                  {{ row.floor_price != null ? row.floor_price : '—' }}
                </template>
              </el-table-column>
              <el-table-column prop="spec_code" label="规格编码" width="130">
                <template #default="{ row }">
                  <span :class="row.spec_code ? 'strong' : 'muted'">{{ row.spec_code || '未匹配' }}</span>
                </template>
              </el-table-column>
              <el-table-column label="匹配" width="72" align="center">
                <template #default="{ row }">
                  <el-tag
                    size="small"
                    :type="row.spec_code ? 'success' : 'danger'"
                    effect="plain"
                  >
                    {{ row.spec_code ? 'OK' : '—' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
            <el-empty
              v-else
              description="活动页未抓到规格行，请确认已展开更多规格并停留在价格确认页"
              :image-size="48"
            />
          </el-card>

          <div v-if="(taskError || taskSuccess) && !hasResultSummary" class="task-feedback">
            <el-alert
              v-if="taskError"
              type="error"
              title="任务失败"
              show-icon
              closable
              @close="taskError = ''"
            >
              <div class="task-feedback-body">{{ taskError }}</div>
            </el-alert>
            <el-alert
              v-else-if="taskSuccess"
              type="success"
              :title="taskSuccess"
              show-icon
              closable
              @close="taskSuccess = ''"
            />
          </div>

          <div
            v-if="hasResultSummary"
            class="result-panel-wrap"
            :class="{ 'result-panel-wrap--expanded': leftPanelExpanded }"
          >
            <ResultSummary
              v-if="marketingResult"
              :expanded="leftPanelExpanded"
              :status="marketingResult.status"
              :message="marketingResult.message"
              :run-id="marketingResult.run_id"
              :result="marketingResult.result"
              @view-detail="goRunDetail(marketingResult!.run_id)"
            />
            <ResultSummary
              v-if="result"
              :expanded="leftPanelExpanded"
              :status="result.status"
              :message="result.message"
              :run-id="result.run_id"
              :result="result.result"
              @view-detail="goRunDetail(result!.run_id)"
            />
          </div>
        </div>
      </el-col>

      <!-- 右侧：商品选择 -->
      <el-col v-show="!leftPanelExpanded" :xs="24" :lg="16" :xl="17">
        <el-card shadow="never" class="stat-card product-panel" v-loading="productLoading">
          <template #header>
            <div class="card-head">
              <div>
                <div class="panel-title">选择报名商品</div>
                <div class="muted panel-sub">
                  店铺 {{ accountId || '—' }} · 共 {{ productTotal }} 条 · 仅可选有商品 ID 且未下架
                </div>
              </div>
              <el-button @click="loadPublishedProducts">刷新</el-button>
            </div>
          </template>

          <div class="filter-bar">
            <el-input
              v-model="productFilters.pdd_product_id"
              clearable
              placeholder="拼多多商品 ID"
              class="filter-input"
              @keyup.enter="applyProductFilters"
            />
            <el-input
              v-model="productFilters.product_code"
              clearable
              placeholder="商品编码 / 套图 / 货号"
              class="filter-input"
              @keyup.enter="applyProductFilters"
            />
            <el-button @click="resetProductFilters">重置</el-button>
            <el-button type="primary" @click="applyProductFilters">查询</el-button>
          </div>

          <el-table
            ref="productTableRef"
            :data="publishedProducts"
            row-key="mapping_id"
            stripe
            height="520"
            @selection-change="onProductSelectionChange"
          >
            <el-table-column type="selection" width="48" :selectable="isSelectableProduct" reserve-selection />
            <el-table-column prop="pdd_product_id" label="商品 ID" width="130" />
            <el-table-column label="商品 / 套图" min-width="200">
              <template #default="{ row }">
                <div class="strong">{{ row.listing_label }}</div>
                <div class="muted">
                  {{ row.product_code }}<span v-if="row.image_set"> / {{ row.image_set }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="merchant_code" label="货号" width="120" show-overflow-tooltip />
            <el-table-column label="状态" width="88">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'on_sale' ? 'success' : 'info'">
                  {{ row.status || '-' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="更新时间" width="158">
              <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
            </el-table-column>
          </el-table>

          <el-empty
            v-if="!publishedProducts.length && !productLoading"
            description="当前店铺暂无已发布商品，请先到「已发布商品」确认"
          />

          <el-pagination
            class="pager"
            background
            layout="total, sizes, prev, pager, next"
            :total="productTotal"
            :current-page="productPage"
            :page-size="productPageSize"
            :page-sizes="[10, 20, 50, 100]"
            @current-change="onProductPageChange"
            @size-change="onProductPageSizeChange"
          />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.campaign-page {
  max-width: 1400px;
}

.campaign-page--expanded {
  max-width: none;
}

.page-alert {
  margin-bottom: 12px;
}

.flow-steps {
  margin-bottom: 20px;
  padding: 16px 20px;
  background: rgba(255, 255, 255, 0.75);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.campaign-layout {
  align-items: stretch;
}

.side-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 32px);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: rgba(15, 23, 42, 0.2) transparent;
}

.side-stack--expanded {
  position: static;
  max-height: none;
  overflow: visible;
}

.side-stack--results-first .left-panel-toolbar {
  order: 1;
}

.side-stack--results-first .result-panel-wrap {
  order: 2;
}

.side-stack--results-first .side-card-config,
.side-stack--results-first .side-card-action {
  order: 10;
}

.side-stack--results-first .task-feedback {
  order: 3;
}

.side-stack::-webkit-scrollbar {
  width: 5px;
}

.side-stack::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.18);
  border-radius: 4px;
}

.task-feedback {
  margin-top: 2px;
}

.task-feedback-body {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
  font-size: 13px;
}

.task-feedback :deep(.el-alert__content) {
  min-width: 0;
}

.result-panel-wrap {
  margin-top: 0;
}

.left-panel-toolbar,
.result-panel-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  margin-bottom: 8px;
}

.left-panel-toolbar {
  margin-top: 4px;
}

.toolbar-hint {
  margin-right: auto;
  font-size: 12px;
}

.toolbar-icon {
  margin-right: 4px;
}

.result-panel-wrap :deep(.result-summary) {
  margin-top: 0;
}

.spec-lookup-card :deep(.el-card__body) {
  padding-top: 8px;
}

.spec-lookup-table {
  width: 100%;
}

.spec-lookup-card--expanded .spec-lookup-table {
  font-size: 14px;
}

.spec-lookup-card--expanded .spec-name-full {
  font-size: 14px;
  line-height: 1.5;
}

.spec-lookup-card--expanded :deep(.el-table__header th) {
  font-size: 13px;
}

.spec-lookup-table :deep(.cell) {
  font-size: 12px;
  line-height: 1.35;
}

.spec-full-table :deep(.el-table__cell) {
  vertical-align: top;
}

.spec-name-full {
  white-space: normal;
  word-break: break-word;
  line-height: 1.45;
}

.task-feedback :deep(.el-alert) {
  border-radius: 10px;
}

.side-card :deep(.el-card__header) {
  padding: 14px 18px;
}

.side-card :deep(.el-card__body) {
  padding: 16px 18px 18px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.compact-form :deep(.el-form-item) {
  margin-bottom: 14px;
}

.compact-form :deep(.el-form-item__label) {
  padding-bottom: 4px;
  font-size: 12px;
  color: #64748b;
}

.activity-brief {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: linear-gradient(135deg, #fff7ed 0%, #fff 100%);
  border: 1px solid #fed7aa;
}

.activity-brief-title {
  font-size: 13px;
  font-weight: 600;
  color: #9a3412;
  line-height: 1.4;
}

.tip-collapse {
  border: none;
}

.tip-collapse :deep(.el-collapse-item__header) {
  height: 36px;
  font-size: 12px;
  color: #64748b;
  border: none;
  background: transparent;
}

.tip-collapse :deep(.el-collapse-item__wrap) {
  border: none;
}

.tip-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.7;
}

.tip-text {
  margin: 0;
  font-size: 12px;
  color: #64748b;
  line-height: 1.7;
}

.action-card :deep(.el-card__body) {
  padding-top: 12px;
}

.selected-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 120px;
  overflow-y: auto;
  margin-bottom: 14px;
}

.id-chip {
  font-family: ui-monospace, monospace;
}

.action-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.action-group-label {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 2px;
}

.action-btn {
  width: 100%;
  margin: 0;
}

.product-panel :deep(.el-card__header) {
  padding: 14px 18px;
}

.product-panel :deep(.el-card__body) {
  padding: 16px 18px 18px;
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.panel-sub {
  margin-top: 2px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 14px;
  align-items: center;
}

.filter-input {
  flex: 1 1 180px;
  max-width: 280px;
}

.strong {
  font-weight: 600;
  color: #0f172a;
}

.muted {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-secondary);
}

.pager {
  margin-top: 14px;
  justify-content: flex-end;
}

@media (max-width: 992px) {
  .side-stack {
    position: static;
    margin-bottom: 16px;
  }

  .flow-steps :deep(.el-step__description) {
    display: none;
  }
}
</style>
