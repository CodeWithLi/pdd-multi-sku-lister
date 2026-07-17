<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, Remove, Search, Tickets } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type {
  Account,
  ProductOperationDelistRun,
  ProductOperationPublishedOption,
  RunRecord,
} from '@/types'

interface PriceSpecRow {
  style_name: string
  package_name: string
  inventory: string
  group_price: string
  single_price: string
  spec_code: string
  status: string
  next_group_price: number | null
}

const router = useRouter()
const accounts = ref<Account[]>([])
const accountsLoading = ref(false)
const publishedOptionsLoading = ref(false)
const priceOptionsLoading = ref(false)
const publishedOptions = ref<ProductOperationPublishedOption[]>([])
const pricePublishedOptions = ref<ProductOperationPublishedOption[]>([])
const delistSubmitting = ref(false)
const delistRuns = ref<ProductOperationDelistRun[]>([])
const priceLoading = ref(false)
const priceSubmitting = ref(false)
const priceRunId = ref('')
const priceProductId = ref('')
const priceTitle = ref('')
const priceRows = ref<PriceSpecRow[]>([])

const delistForm = reactive({
  product_code: '',
  dry_run: false,
})

const priceForm = reactive({
  account_id: '',
  product_code: '',
})

const changedRows = computed(() =>
  priceRows.value.filter((row) => {
    if (row.next_group_price === null || !Number.isFinite(row.next_group_price)) return false
    return Math.round(row.next_group_price * 100) !== Math.round(Number(row.group_price) * 100)
  }),
)

function shopName(account: Account) {
  return account.shop_display_name || account.display_name || account.account_id
}

function runStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: '等待中',
    running: '执行中',
    success: '成功',
    failed: '失败',
    canceled: '已取消',
    delisted: '已下架',
    not_found: '未上架，已跳过',
    dry_run: '试运行命中',
  }
  return labels[status] || status
}

function runStatusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'success') return 'success'
  if (status === 'delisted') return 'success'
  if (status === 'not_found' || status === 'dry_run') return 'info'
  if (status === 'failed' || status === 'canceled') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function openRun(runId: string) {
  router.push({ path: '/runs', query: { id: runId } })
}

async function loadAccounts() {
  accountsLoading.value = true
  try {
    accounts.value = await api.accounts(true)
    if (!priceForm.account_id && accounts.value.length) {
      priceForm.account_id = accounts.value[0].account_id
    }
    await loadPricePublishedOptions()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载店铺失败')
  } finally {
    accountsLoading.value = false
  }
}

async function loadPublishedOptions() {
  publishedOptionsLoading.value = true
  try {
    const result = await api.productOperationPublishedProducts()
    publishedOptions.value = result.items
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载已发布商品失败')
  } finally {
    publishedOptionsLoading.value = false
  }
}

async function loadPricePublishedOptions() {
  priceRows.value = []
  priceProductId.value = ''
  priceTitle.value = ''
  priceForm.product_code = ''
  if (!priceForm.account_id) {
    pricePublishedOptions.value = []
    return
  }
  priceOptionsLoading.value = true
  try {
    const result = await api.productOperationPublishedProducts(priceForm.account_id)
    pricePublishedOptions.value = result.items
  } catch (error) {
    pricePublishedOptions.value = []
    ElMessage.error(error instanceof Error ? error.message : '加载店铺已发布商品失败')
  } finally {
    priceOptionsLoading.value = false
  }
}

function productOptionLabel(option: ProductOperationPublishedOption) {
  if (!option.listing_label || option.listing_label === option.product_code) {
    return option.product_code
  }
  return `${option.product_code} · ${option.listing_label}`
}

async function waitForRun(runId: string): Promise<RunRecord> {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    const run = await api.run(runId)
    if (['success', 'failed', 'canceled', 'needs_human', 'skipped'].includes(run.status)) {
      if (run.status !== 'success') {
        const detail = String(run.result?.error || run.message || '任务执行失败')
        throw new Error(detail)
      }
      return run
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1500))
  }
  throw new Error('任务仍在执行，可到操作记录查看进度')
}

async function submitDelist() {
  const productCode = delistForm.product_code.trim()
  if (!productCode) {
    ElMessage.warning('请选择已发布商品')
    return
  }
  if (!delistForm.dry_run) {
    try {
      await ElMessageBox.confirm(
        `确认扫描全部启用店铺并下架商品编码 ${productCode}？未找到该编码的店铺会自动跳过。`,
        '全店下架确认',
        {
          confirmButtonText: '确认下架',
          cancelButtonText: '取消',
          type: 'warning',
        },
      )
    } catch {
      return
    }
  }

  delistSubmitting.value = true
  try {
    const result = await api.delistProductAllStores({
      product_code: productCode,
      dry_run: delistForm.dry_run,
    })
    delistRuns.value = result.runs
    ElMessage.success(result.message)
    void pollDelistRuns()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '提交全店下架失败')
  } finally {
    delistSubmitting.value = false
  }
}

async function pollDelistRuns() {
  for (let attempt = 0; attempt < 180; attempt += 1) {
    let hasActive = false
    await Promise.all(
      delistRuns.value.map(async (row) => {
        if (['delisted', 'not_found', 'dry_run', 'failed', 'canceled'].includes(row.status)) return
        try {
          const run = await api.run(row.run_id)
          if (['pending', 'running'].includes(run.status)) {
            row.status = run.status
            hasActive = true
            return
          }
          if (run.status !== 'success') {
            row.status = run.status
            row.message = String(run.result?.error || run.message || '执行失败')
            return
          }
          const results = Array.isArray(run.result?.results) ? run.result.results : []
          const item = (results[0] || {}) as Record<string, unknown>
          row.status = String(item.status || 'success')
          row.message = String(item.message || '')
        } catch (error) {
          row.status = 'failed'
          row.message = error instanceof Error ? error.message : '读取任务状态失败'
        }
      }),
    )
    if (!hasActive) return
    await new Promise((resolve) => window.setTimeout(resolve, 2000))
  }
}

async function loadPriceSpecs() {
  const productCode = priceForm.product_code.trim()
  if (!priceForm.account_id) {
    ElMessage.warning('请选择店铺')
    return
  }
  if (!productCode) {
    ElMessage.warning('请输入商品编码')
    return
  }

  priceLoading.value = true
  priceRows.value = []
  priceProductId.value = ''
  priceTitle.value = ''
  try {
    const submitted = await api.previewProductPrices({
      account_id: priceForm.account_id,
      product_code: productCode,
    })
    priceRunId.value = submitted.run_id
    const run = await waitForRun(submitted.run_id)
    const rawRows = Array.isArray(run.result?.skus) ? run.result.skus : []
    priceProductId.value = String(run.result?.pdd_product_id || '')
    priceTitle.value = String(run.result?.title || '')
    priceRows.value = rawRows.map((raw) => {
      const row = raw as Record<string, unknown>
      const groupPrice = String(row.group_price || '')
      return {
        style_name: String(row.style_name || ''),
        package_name: String(row.package_name || ''),
        inventory: String(row.inventory || ''),
        group_price: groupPrice,
        single_price: String(row.single_price || ''),
        spec_code: String(row.spec_code || ''),
        status: String(row.status || ''),
        next_group_price: Number.isFinite(Number(groupPrice)) ? Number(groupPrice) : null,
      }
    })
    ElMessage.success(`已读取 ${priceRows.value.length} 个规格`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '读取商品规格失败')
  } finally {
    priceLoading.value = false
  }
}

async function submitPriceChanges() {
  if (!changedRows.value.length) {
    ElMessage.warning('没有需要提交的价格变化')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认修改商品 ${priceForm.product_code.trim()} 的 ${changedRows.value.length} 个规格拼单价？`,
      '价格修改确认',
      {
        confirmButtonText: '确认修改',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  priceSubmitting.value = true
  try {
    const submitted = await api.updateProductPrices({
      account_id: priceForm.account_id,
      product_code: priceForm.product_code.trim(),
      pdd_product_id: priceProductId.value,
      updates: changedRows.value.map((row) => ({
        spec_code: row.spec_code,
        group_price: Number(row.next_group_price),
      })),
    })
    priceRunId.value = submitted.run_id
    await waitForRun(submitted.run_id)
    for (const row of changedRows.value) {
      row.group_price = Number(row.next_group_price).toFixed(2)
    }
    ElMessage.success(`已修改 ${changedRows.value.length} 个规格的拼单价`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '修改拼单价失败')
  } finally {
    priceSubmitting.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadAccounts(), loadPublishedOptions()])
})
</script>

<template>
  <div class="product-operations-page">
    <PageHeader title="商品操作" description="跨店商品下架与规格拼单价调整" />

    <section class="operation-section delist-section" aria-labelledby="delist-title">
      <div class="section-heading">
        <div class="section-icon section-icon--danger"><el-icon><Remove /></el-icon></div>
        <div>
          <h2 id="delist-title">全店商品编码下架</h2>
          <p>从已发布商品中选择编码，逐店搜索并下架；未上架店铺自动跳过。</p>
        </div>
      </div>

      <div class="delist-controls">
        <el-select
          v-model="delistForm.product_code"
          filterable
          clearable
          :loading="publishedOptionsLoading"
          placeholder="选择已发布商品"
          aria-label="已发布商品"
        >
          <el-option
            v-for="option in publishedOptions"
            :key="option.product_code"
            :label="productOptionLabel(option)"
            :value="option.product_code"
          >
            <div class="product-option">
              <span class="product-option__code">{{ option.product_code }}</span>
              <span class="product-option__label">{{ option.listing_label }}</span>
              <el-tag size="small" effect="plain">{{ option.shop_count }} 家</el-tag>
            </div>
          </el-option>
        </el-select>
        <div class="dry-run-control">
          <el-switch v-model="delistForm.dry_run" />
          <span>试运行</span>
        </div>
        <el-button
          type="danger"
          :icon="Remove"
          :loading="delistSubmitting"
          @click="submitDelist"
        >
          按编码扫描全部店铺并下架
        </el-button>
      </div>

      <el-table
        v-if="delistRuns.length"
        :data="delistRuns"
        size="small"
        border
        class="result-table"
      >
        <el-table-column prop="account_id" label="店铺" min-width="160" />
        <el-table-column prop="run_id" label="任务 ID" min-width="240" show-overflow-tooltip />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="runStatusType(row.status)" effect="plain" size="small">
              {{ runStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="结果说明" min-width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button link type="primary" :icon="Tickets" @click="openRun(row.run_id)">记录</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="operation-section price-section" aria-labelledby="price-title">
      <div class="section-heading section-heading--row">
        <div class="section-heading__main">
          <div class="section-icon section-icon--primary"><el-icon><EditPen /></el-icon></div>
          <div>
            <h2 id="price-title">规格拼单价调整</h2>
            <p>按商品编码读取完整规格，以规格编码精确修改拼单价。</p>
          </div>
        </div>
        <el-button v-if="priceRunId" link type="primary" :icon="Tickets" @click="openRun(priceRunId)">
          当前任务
        </el-button>
      </div>

      <div class="price-search">
        <label class="field-block">
          <span>店铺</span>
          <el-select
            v-model="priceForm.account_id"
            filterable
            :loading="accountsLoading"
            placeholder="选择店铺"
            @change="loadPricePublishedOptions"
          >
            <el-option
              v-for="account in accounts"
              :key="account.account_id"
              :label="shopName(account)"
              :value="account.account_id"
            />
          </el-select>
        </label>
        <label class="field-block field-block--grow">
          <span>商品编码</span>
          <el-select
            v-model="priceForm.product_code"
            filterable
            clearable
            :loading="priceOptionsLoading"
            placeholder="选择该店已发布商品"
          >
            <el-option
              v-for="option in pricePublishedOptions"
              :key="option.product_code"
              :label="productOptionLabel(option)"
              :value="option.product_code"
            />
          </el-select>
        </label>
        <el-button
          type="primary"
          :icon="Search"
          :loading="priceLoading"
          class="search-button"
          @click="loadPriceSpecs"
        >
          读取全部规格
        </el-button>
      </div>

      <div v-if="priceRows.length" class="spec-result">
        <div class="product-summary">
          <div>
            <strong>{{ priceForm.product_code }}</strong>
            <span v-if="priceProductId">ID {{ priceProductId }}</span>
            <span v-if="priceTitle">{{ priceTitle }}</span>
          </div>
          <el-tag effect="plain">{{ priceRows.length }} 个规格</el-tag>
        </div>

        <el-table :data="priceRows" size="small" border stripe class="spec-table">
          <el-table-column prop="style_name" label="款式" min-width="150" show-overflow-tooltip />
          <el-table-column prop="package_name" label="套餐 / 尺寸" min-width="140" show-overflow-tooltip />
          <el-table-column prop="inventory" label="当前库存" width="110" align="right" />
          <el-table-column label="当前拼单价" width="120" align="right">
            <template #default="{ row }">¥ {{ row.group_price || '-' }}</template>
          </el-table-column>
          <el-table-column label="新拼单价" width="180">
            <template #default="{ row }">
              <el-input-number
                v-model="row.next_group_price"
                :min="0.01"
                :max="999999.99"
                :precision="2"
                :step="0.1"
                controls-position="right"
                aria-label="新拼单价"
              />
            </template>
          </el-table-column>
          <el-table-column prop="single_price" label="单买价" width="100" align="right" />
          <el-table-column prop="spec_code" label="规格编码" min-width="210" show-overflow-tooltip>
            <template #default="{ row }"><span class="spec-code">{{ row.spec_code }}</span></template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="90" align="center" />
        </el-table>

        <div class="price-actions">
          <span>已修改 {{ changedRows.length }} 项</span>
          <el-button
            type="primary"
            :icon="EditPen"
            :disabled="!changedRows.length"
            :loading="priceSubmitting"
            @click="submitPriceChanges"
          >
            提交价格修改
          </el-button>
        </div>
      </div>

      <el-empty
        v-else-if="!priceLoading"
        description="选择店铺和已发布商品"
        :image-size="72"
      />
    </section>
  </div>
</template>

<style scoped>
.product-operations-page {
  max-width: 1240px;
  padding-bottom: 32px;
}

.operation-section {
  margin-top: 20px;
  padding: 22px 24px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.section-heading,
.section-heading__main {
  display: flex;
  align-items: center;
  gap: 12px;
}

.section-heading--row {
  justify-content: space-between;
}

.section-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 8px;
  font-size: 20px;
  flex-shrink: 0;
}

.section-icon--danger {
  color: #dc2626;
  background: #fef2f2;
}

.section-icon--primary {
  color: #2563eb;
  background: #eff6ff;
}

.section-heading h2 {
  margin: 0;
  font-size: 17px;
  line-height: 1.4;
  letter-spacing: 0;
}

.section-heading p {
  margin: 2px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.45;
}

.delist-controls {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  margin-top: 20px;
  max-width: 820px;
}

.delist-controls > .el-select {
  width: 100%;
}

.product-option {
  display: grid;
  grid-template-columns: minmax(90px, auto) minmax(120px, 1fr) auto;
  align-items: center;
  gap: 10px;
}

.product-option__code {
  font-family: ui-monospace, Consolas, monospace;
  font-weight: 600;
  color: #1e293b;
}

.product-option__label {
  overflow: hidden;
  color: #64748b;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dry-run-control {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  color: #475569;
  font-size: 13px;
  white-space: nowrap;
}

.result-table,
.spec-result {
  margin-top: 18px;
}

.price-search {
  display: flex;
  align-items: flex-end;
  gap: 12px;
  margin-top: 20px;
}

.field-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 260px;
  color: #334155;
  font-size: 13px;
  font-weight: 500;
}

.field-block--grow {
  width: min(420px, 100%);
}

.field-block :deep(.el-select) {
  width: 100%;
}

.search-button {
  min-height: 40px;
}

.product-summary,
.price-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.product-summary {
  padding: 12px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-bottom: none;
  border-radius: 6px 6px 0 0;
}

.product-summary > div {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.product-summary strong {
  color: #0f172a;
}

.product-summary span {
  color: #64748b;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.spec-table :deep(.el-input-number) {
  width: 148px;
}

.spec-code {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
  color: #334155;
}

.price-actions {
  margin-top: 14px;
  color: #64748b;
  font-size: 13px;
}

@media (max-width: 900px) {
  .delist-controls {
    grid-template-columns: 1fr auto;
  }

  .delist-controls > .el-input {
    grid-column: 1 / -1;
  }

  .price-search {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .field-block,
  .field-block--grow {
    width: 100%;
  }
}

@media (max-width: 640px) {
  .operation-section {
    padding: 18px 16px;
  }

  .section-heading--row,
  .product-summary,
  .product-summary > div,
  .price-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .delist-controls,
  .price-search {
    display: flex;
    flex-direction: column;
    align-items: stretch;
  }

  .dry-run-control {
    min-height: 32px;
  }

  .price-actions .el-button {
    width: 100%;
  }
}
</style>
