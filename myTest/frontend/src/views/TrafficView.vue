<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import ResultSummary from '@/components/ResultSummary.vue'
import { summarizeRunError } from '@/utils/runMessage'
import type { Account, PublishedProduct, RunRecord, TrafficTaskResponse } from '@/types'

type ProductTableRef = {
  clearSelection: () => void
}

const router = useRouter()

const taskLoading = ref(false)
const productLoading = ref(false)
const error = ref('')
const taskError = ref('')
const taskSuccess = ref('')
const accounts = ref<Account[]>([])
const accountId = ref('')
const result = ref<TrafficTaskResponse | null>(null)
const activeRun = ref<RunRecord | null>(null)
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
const isRunning = computed(() => {
  const status = activeRun.value?.status || result.value?.status
  return status === 'pending' || status === 'running'
})
const currentStep = computed(() => {
  if (!accountId.value) return 0
  if (!selectedPddProductIds.value.length) return 1
  return 2
})

let pollTimer: number | undefined

async function loadMeta() {
  try {
    accounts.value = await api.accounts(true)
    if (accounts.value.length && !accountId.value) {
      accountId.value = accounts.value[0].account_id
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

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function syncResultFromRun(run: RunRecord) {
  activeRun.value = run
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

function startPolling(runId: string) {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    try {
      const run = await api.run(runId)
      syncResultFromRun(run)
      if (!['pending', 'running'].includes(run.status)) {
        stopPolling()
        taskLoading.value = false
        if (run.status === 'success') {
          showTaskSuccess('推广任务已完成')
        } else if (run.status === 'failed') {
          showTaskError(summarizeRunError(run))
        }
      }
    } catch (e) {
      stopPolling()
      taskLoading.value = false
      showTaskError(e instanceof Error ? e.message : '查询推广任务状态失败')
    }
  }, 2000)
}

async function startPromotionCreate() {
  if (isRunning.value) {
    showFormError('当前已有推广任务正在执行，请等待完成后再启动')
    return
  }
  if (!accountId.value) {
    showFormError('请选择店铺')
    return
  }
  if (!selectedPddProductIds.value.length) {
    showFormError('请先选择要推广的已发布商品')
    return
  }

  taskLoading.value = true
  taskError.value = ''
  taskSuccess.value = ''
  result.value = null
  activeRun.value = null
  try {
    result.value = await api.trafficPromotionCreate({
      account_id: accountId.value,
      pdd_product_ids: selectedPddProductIds.value,
      published_mapping_ids: selectedMappingIds.value,
    })
    if (result.value.status === 'failed') {
      showTaskError(result.value.message || '推广任务启动失败')
    } else {
      showTaskSuccess(result.value.message || '推广新建任务已启动')
    }
    activeRun.value = {
      run_id: result.value.run_id,
      agent: 'traffic',
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
      startPolling(result.value.run_id)
    } else {
      taskLoading.value = false
    }
  } catch (e) {
    showTaskError(e instanceof Error ? e.message : '启动推广任务失败')
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
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="traffic-page" v-loading="taskLoading">
    <PageHeader
      title="推广"
      desc="推广平台 → 推广概况 → 商品推广 → 新建推广。左侧配置、右侧选品。"
    />

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
      <el-step title="选店铺" description="左侧配置" />
      <el-step title="勾选商品" description="右侧表格" />
      <el-step title="启动任务" description="查询商品 ID" />
    </el-steps>

    <el-row :gutter="16" class="traffic-layout">
      <el-col :xs="24" :lg="8" :xl="7">
        <div class="side-stack">
          <el-card shadow="never" class="stat-card side-card">
            <template #header>
              <div class="card-head">
                <span>推广配置</span>
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
            </el-form>

            <el-collapse class="tip-collapse">
              <el-collapse-item title="当前自动化步骤" name="flow">
                <ol class="tip-list">
                  <li>进入 yingxiao 推广平台「商品推广」，点击「+ 新建推广」</li>
                  <li>在「添加推广商品」输入 ID 并查询；无结果会报错</li>
                  <li>有结果则依次点击每行「推广设置」小笔，打开净目标投产比弹层</li>
                  <li>探测出价（10→20→30…）获取建议价，填入后点「确定」</li>
                  <li>取消勾选底部「全局/全店优选起量」并点「确定关闭」</li>
                  <li>点击底部蓝色「开启推广」按钮提交</li>
                </ol>
              </el-collapse-item>
            </el-collapse>
          </el-card>

          <el-card shadow="never" class="stat-card side-card action-card">
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

            <el-button
              type="primary"
              class="action-btn"
              :disabled="!canStart || isRunning"
              :loading="isRunning"
              @click="startPromotionCreate"
            >
              打开推广概况并查询商品
            </el-button>
          </el-card>

          <div v-if="taskError || taskSuccess" class="task-feedback">
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

          <ResultSummary
            v-if="result"
            :status="result.status"
            :message="result.message"
            :run-id="result.run_id"
            :result="result.result"
            @view-detail="goRunDetail(result!.run_id)"
          />
        </div>
      </el-col>

      <el-col :xs="24" :lg="16" :xl="17">
        <el-card shadow="never" class="stat-card product-panel" v-loading="productLoading">
          <template #header>
            <div class="card-head">
              <div>
                <div class="panel-title">选择推广商品</div>
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
.traffic-page {
  max-width: 1400px;
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

.traffic-layout {
  align-items: stretch;
}

.side-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: sticky;
  top: 16px;
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

.action-btn {
  width: 100%;
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

.task-feedback-body {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
  font-size: 13px;
}

@media (max-width: 992px) {
  .side-stack {
    position: static;
    margin-bottom: 16px;
  }
}
</style>
