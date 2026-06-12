<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import ResultSummary from '@/components/ResultSummary.vue'
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
const success = ref('')
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
  result.value = {
    ...result.value,
    status: run.status,
    message: run.message || result.value.message,
    result: run.result,
  }
}

function syncMarketingResultFromRun(run: RunRecord) {
  activeMarketingRun.value = run
  if (!marketingResult.value || marketingResult.value.run_id !== run.run_id) return
  marketingResult.value = {
    ...marketingResult.value,
    status: run.status,
    message: run.message || marketingResult.value.message,
    result: run.result,
  }
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
        success.value = run.status === 'success' ? '营销活动任务已完成' : ''
        error.value = run.status === 'failed' ? (run.message || '营销活动搜索失败') : ''
      }
    } catch (e) {
      stopMarketingPolling()
      marketingTaskLoading.value = false
      error.value = e instanceof Error ? e.message : '查询营销活动任务状态失败'
    }
  }, 2000)
}

async function startMarketingActivityRegister() {
  if (isMarketingRunning.value || isCampaignRunning.value) {
    error.value = '当前已有活动任务正在执行，请等待完成后再启动'
    return
  }
  if (!accountId.value) {
    error.value = '请选择店铺'
    return
  }
  if (!marketingActivityId.value) {
    error.value = '请选择营销活动'
    return
  }
  if (!selectedPddProductIds.value.length) {
    error.value = '请先选择要报名的已发布商品'
    return
  }

  marketingTaskLoading.value = true
  error.value = ''
  success.value = ''
  marketingResult.value = null
  activeMarketingRun.value = null
  try {
    marketingResult.value = await api.campaignMarketingActivityRegister({
      account_id: accountId.value,
      activity_id: marketingActivityId.value,
      pdd_product_ids: selectedPddProductIds.value,
    })
    success.value = marketingResult.value.message || '营销活动报名任务已启动'
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
    error.value = e instanceof Error ? e.message : '启动营销活动报名失败'
    marketingTaskLoading.value = false
  }
}

async function startMarketingActivitySearch() {
  if (isMarketingRunning.value || isCampaignRunning.value) {
    error.value = '当前已有活动任务正在执行，请等待完成后再启动'
    return
  }
  if (!accountId.value) {
    error.value = '请选择店铺'
    return
  }
  if (!marketingActivityId.value) {
    error.value = '请选择营销活动'
    return
  }

  marketingTaskLoading.value = true
  error.value = ''
  success.value = ''
  marketingResult.value = null
  activeMarketingRun.value = null
  try {
    marketingResult.value = await api.campaignMarketingActivitySearch({
      account_id: accountId.value,
      activity_id: marketingActivityId.value,
    })
    success.value = marketingResult.value.message || '营销活动搜索任务已启动'
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
    error.value = e instanceof Error ? e.message : '启动营销活动搜索失败'
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
        success.value = run.status === 'success' ? '活动任务已完成' : ''
        error.value = run.status === 'failed' ? (run.message || '活动任务失败') : ''
      }
    } catch (e) {
      stopCampaignPolling()
      taskLoading.value = false
      error.value = e instanceof Error ? e.message : '查询活动任务状态失败'
    }
  }, 2000)
}

async function startLimitedTimeSetup() {
  if (isCampaignRunning.value || isMarketingRunning.value) {
    error.value = '当前已有活动任务正在执行，请等待完成后再启动'
    return
  }
  if (!accountId.value) {
    error.value = '请选择店铺'
    return
  }
  if (!selectedPddProductIds.value.length) {
    error.value = '请先选择要搜索的商品'
    return
  }

  taskLoading.value = true
  error.value = ''
  success.value = ''
  result.value = null
  activeCampaignRun.value = null
  try {
    result.value = await api.campaignLimitedTimeSetup({
      account_id: accountId.value,
      pdd_product_ids: selectedPddProductIds.value,
      published_mapping_ids: selectedMappingIds.value,
    })
    success.value = result.value.message || '限时限量购活动设置任务已启动'
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
    error.value = e instanceof Error ? e.message : '启动活动任务失败'
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
  <div v-loading="taskLoading || marketingTaskLoading">
    <PageHeader
      title="活动"
      desc="支持营销活动大厅搜索报名活动，以及限时限量购创建页设置。"
    />

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      style="margin-bottom: 12px"
      @close="error = ''"
    />
    <el-alert
      v-if="success"
      type="success"
      :title="success"
      show-icon
      closable
      style="margin-bottom: 12px"
      @close="success = ''"
    />

    <el-card shadow="never" class="stat-card campaign-card marketing-card">
      <template #header>
        <div class="card-head">
          <span>营销活动</span>
          <el-tag v-if="marketingActivityId" type="info" effect="plain">
            ID {{ marketingActivityId }}
          </el-tag>
        </div>
      </template>

      <div class="section-tip marketing-tip">
        流程：搜索活动 → 活动详情 → 立即报名 → 弹窗：查询 → 全选 → 确认 → 确认选择 → 取消流量保护。
        输入下方已选商品 ID（逗号分隔）→ 查询 → 确认。
      </div>

      <el-form label-position="top" class="campaign-form">
        <el-form-item label="选择店铺" required>
          <el-select v-model="accountId" filterable style="width: 100%" placeholder="请选择店铺">
            <el-option
              v-for="a in enabledAccounts"
              :key="a.account_id"
              :label="a.account_id"
              :value="a.account_id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="选择营销活动" required>
          <el-select
            v-model="marketingActivityId"
            filterable
            style="width: 100%"
            placeholder="请选择营销活动"
          >
            <el-option
              v-for="item in marketingActivities"
              :key="item.activity_id"
              :label="`${item.name}（ID ${item.activity_id}）`"
              :value="item.activity_id"
            />
          </el-select>
          <div v-if="selectedMarketingActivity" class="muted activity-desc">
            将搜索活动 {{ selectedMarketingActivity.activity_id }}，并完成去报名与选品确认。
          </div>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="stat-card campaign-card product-card">
      <template #header>
        <div class="card-head">
          <span>选择报名商品</span>
          <el-tag v-if="selectedPddProductIds.length" type="success" effect="plain">
            已选 {{ selectedPddProductIds.length }} 个
          </el-tag>
        </div>
      </template>

      <div class="product-section" v-loading="productLoading">
        <div class="product-head">
          <div>
            <div class="section-label">已发布商品</div>
            <div class="muted">从当前店铺选择要参加营销活动的商品，报名时会按拼多多商品 ID 搜索。</div>
          </div>
          <el-button @click="loadPublishedProducts">刷新</el-button>
        </div>

        <el-form label-position="top" class="product-filter-form">
          <el-row :gutter="12">
            <el-col :xs="24" :sm="10">
              <el-form-item label="拼多多商品ID">
                <el-input
                  v-model="productFilters.pdd_product_id"
                  clearable
                  placeholder="如 96442086670"
                  @keyup.enter="applyProductFilters"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="10">
              <el-form-item label="商品编码 / 套图 / 货号">
                <el-input
                  v-model="productFilters.product_code"
                  clearable
                  placeholder="如 BD046A"
                  @keyup.enter="applyProductFilters"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="4">
              <el-form-item label=" ">
                <div class="filter-actions">
                  <el-button @click="resetProductFilters">重置</el-button>
                  <el-button type="primary" @click="applyProductFilters">查询</el-button>
                </div>
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>

        <el-table
          ref="productTableRef"
          :data="publishedProducts"
          row-key="mapping_id"
          size="small"
          stripe
          @selection-change="onProductSelectionChange"
        >
          <el-table-column type="selection" width="44" :selectable="isSelectableProduct" reserve-selection />
          <el-table-column prop="pdd_product_id" label="商品ID" width="140" />
          <el-table-column label="商品/套图" min-width="180">
            <template #default="{ row }">
              <div class="strong">{{ row.listing_label }}</div>
              <div class="muted">{{ row.product_code }}<span v-if="row.image_set"> / {{ row.image_set }}</span></div>
              <div v-if="row.family_code" class="muted">母编码：{{ row.family_code }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="merchant_code" label="货号" min-width="150" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="96" />
          <el-table-column label="更新时间" width="160">
            <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!publishedProducts.length && !productLoading" description="当前店铺暂无已发布商品记录" />

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

        <div v-if="selectedPddProductIds.length" class="selected-bar">
          <span>已选商品ID</span>
          <el-tag v-for="id in selectedPddProductIds" :key="id" effect="plain">{{ id }}</el-tag>
        </div>
      </div>

      <div class="marketing-actions">
        <el-button
          type="primary"
          size="large"
          class="submit-btn marketing-register-btn"
          :disabled="!canRegisterMarketingActivity || isMarketingRunning || isCampaignRunning"
          :loading="isMarketingRunning"
          @click="startMarketingActivityRegister"
        >
          打开营销活动并报名
        </el-button>
        <el-button
          size="large"
          :disabled="!canSearchMarketingActivity || isMarketingRunning || isCampaignRunning"
          @click="startMarketingActivitySearch"
        >
          仅搜索活动
        </el-button>
      </div>

      <ResultSummary
        v-if="marketingResult"
        :status="marketingResult.status"
        :message="marketingResult.message"
        :run-id="marketingResult.run_id"
        :result="marketingResult.result"
        @view-detail="goRunDetail(marketingResult!.run_id)"
      />
    </el-card>

    <div class="section-tip limited-tip">
      限时限量购任务会依次进入营销工具、限时限量购、立即创建。
      到活动设置页后只处理“同步设置惊喜优惠”复选框，不会点击最终创建按钮。
    </div>

    <el-card shadow="never" class="stat-card campaign-card">
      <template #header>
        <div class="card-head">
          <span>限时限量购</span>
          <el-tag v-if="selectedPddProductIds.length" type="success" effect="plain">
            已选 {{ selectedPddProductIds.length }} 个
          </el-tag>
        </div>
      </template>

      <div class="muted limited-note">
        复用上方「选择报名商品」中已选的商品 ID。
      </div>

      <el-button
        type="primary"
        size="large"
        class="submit-btn"
        :disabled="!canStart || isCampaignRunning || isMarketingRunning"
        :loading="isCampaignRunning"
        @click="startLimitedTimeSetup"
      >
        打开限时限量购并取消惊喜优惠
      </el-button>

      <ResultSummary
        v-if="result"
        :status="result.status"
        :message="result.message"
        :run-id="result.run_id"
        :result="result.result"
        @view-detail="goRunDetail(result!.run_id)"
      />
    </el-card>
  </div>
</template>

<style scoped>
.campaign-card {
  max-width: 1120px;
}

.marketing-card {
  margin-bottom: 16px;
}

.product-card {
  margin-bottom: 16px;
}

.marketing-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
}

.marketing-register-btn {
  flex: 1 1 320px;
}

.limited-note {
  margin-bottom: 16px;
}

.section-tip {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid var(--border-color);
  color: #64748b;
  font-size: 12px;
  line-height: 1.6;
}

.limited-tip {
  max-width: 1120px;
}

.activity-desc {
  margin-top: 8px;
}

.campaign-form {
  max-width: 520px;
}

.card-head,
.product-head,
.filter-actions,
.selected-bar {
  display: flex;
  align-items: center;
}

.card-head {
  justify-content: space-between;
  gap: 12px;
}

.product-section {
  margin: 8px 0 18px;
}

.product-head {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.product-filter-form {
  margin-bottom: 4px;
}

.filter-actions {
  justify-content: flex-end;
  gap: 8px;
  width: 100%;
}

.strong {
  font-weight: 600;
  color: #0f172a;
}

.muted {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-secondary);
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
  color: #475569;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}

.selected-bar {
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #f8fafc;
  color: #475569;
  font-size: 12px;
}

.submit-btn {
  width: 100%;
  max-width: 520px;
}
</style>
