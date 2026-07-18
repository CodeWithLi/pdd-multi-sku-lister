<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { EditPen, Minus, Remove, Search, Tickets } from '@element-plus/icons-vue'
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
  next_single_price: number | null
}

interface StorePriceResult {
  account_id: string
  shop_name: string
  run_id: string
  product_id: string
  title: string
  status: 'loading' | 'success' | 'failed' | 'updating'
  error: string
  rows: PriceSpecRow[]
}

interface ChangedPriceEntry {
  store: StorePriceResult
  row: PriceSpecRow
}

const router = useRouter()
const accounts = ref<Account[]>([])
const accountsLoading = ref(false)
const publishedOptionsLoading = ref(false)
const publishedOptions = ref<ProductOperationPublishedOption[]>([])
const delistSubmitting = ref(false)
const delistRuns = ref<ProductOperationDelistRun[]>([])
const priceLoading = ref(false)
const priceSubmitting = ref(false)
const priceStores = ref<StorePriceResult[]>([])
const MIN_SINGLE_PRICE_GAP = 1

const delistForm = reactive({
  product_code: '',
  dry_run: false,
})

const priceForm = reactive({
  account_ids: [] as string[],
  product_code: '',
})

const bulkPriceForm = reactive({
  group_decrease: 0,
  single_decrease: 0,
})

const commonPriceOptions = computed(() =>
  publishedOptions.value.filter(
    (option) =>
      priceForm.account_ids.length > 0 &&
      priceForm.account_ids.every((accountId) => option.account_ids.includes(accountId)),
  ),
)

const selectedPriceOption = computed(() =>
  publishedOptions.value.find((option) => option.product_code === priceForm.product_code),
)

const successfulPriceStores = computed(() =>
  priceStores.value.filter((store) => store.status === 'success' || store.status === 'updating'),
)

const changedEntries = computed<ChangedPriceEntry[]>(() =>
  successfulPriceStores.value.flatMap((store) =>
    store.rows.filter(rowPriceChanged).map((row) => ({ store, row })),
  ),
)

const invalidChangedEntries = computed(() =>
  changedEntries.value.filter(({ row }) => Boolean(priceRuleError(row))),
)

const changedStoreCount = computed(
  () => new Set(changedEntries.value.map(({ store }) => store.account_id)).size,
)

function roundPrice(value: number) {
  return Math.round(value * 100) / 100
}

function rowPriceChanged(row: PriceSpecRow) {
  if (
    row.next_group_price === null ||
    row.next_single_price === null ||
    !Number.isFinite(row.next_group_price) ||
    !Number.isFinite(row.next_single_price)
  ) {
    return false
  }
  return (
    Math.round(row.next_group_price * 100) !== Math.round(Number(row.group_price) * 100) ||
    Math.round(row.next_single_price * 100) !== Math.round(Number(row.single_price) * 100)
  )
}

function maxGroupPrice(row: PriceSpecRow): number | null {
  const singlePrice = row.next_single_price
  if (!Number.isFinite(singlePrice)) return null
  return roundPrice(Number(singlePrice) - MIN_SINGLE_PRICE_GAP)
}

function priceRuleError(row: PriceSpecRow): string {
  const nextGroupPrice = row.next_group_price
  const nextSinglePrice = row.next_single_price
  const maxPrice = maxGroupPrice(row)
  if (nextGroupPrice === null || !Number.isFinite(nextGroupPrice)) return '请输入有效拼单价'
  if (nextSinglePrice === null || !Number.isFinite(nextSinglePrice)) return '请输入有效单买价'
  if (nextGroupPrice <= 0 || nextSinglePrice <= 0) return '价格必须大于 0'
  if (maxPrice === null) return '单买价无效，无法校验'
  if (maxPrice < 0.01) return '单买价不足，无法设置合法拼单价'
  if (Math.round(nextGroupPrice * 100) > Math.round(maxPrice * 100)) {
    return `不能高于 ¥${maxPrice.toFixed(2)}`
  }
  return ''
}

function shopName(account: Account) {
  return account.shop_display_name || account.display_name || account.account_id
}

function shopNameById(accountId: string) {
  const account = accounts.value.find((item) => item.account_id === accountId)
  return account ? shopName(account) : accountId
}

function runStatusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: '等待中',
    loading: '读取中',
    running: '执行中',
    updating: '修改中',
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
  if (status === 'running' || status === 'loading' || status === 'updating') return 'warning'
  return 'info'
}

function openRun(runId: string) {
  router.push({ path: '/runs', query: { id: runId } })
}

async function loadAccounts() {
  accountsLoading.value = true
  try {
    accounts.value = await api.accounts(true)
    if (!priceForm.account_ids.length && accounts.value.length) {
      priceForm.account_ids = [accounts.value[0].account_id]
    }
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

function resetPriceResults() {
  priceStores.value = []
  bulkPriceForm.group_decrease = 0
  bulkPriceForm.single_decrease = 0
}

function handlePriceAccountsChange() {
  priceForm.product_code = ''
  resetPriceResults()
}

function handlePriceProductChange() {
  resetPriceResults()
}

function productOptionLabel(option: ProductOperationPublishedOption) {
  if (!option.listing_label || option.listing_label === option.product_code) {
    return option.product_code
  }
  return `${option.product_code} · ${option.listing_label}`
}

function priceProductIds(option: ProductOperationPublishedOption) {
  return priceForm.account_ids
    .map((accountId) => option.product_ids[accountId])
    .filter((productId): productId is string => Boolean(productId))
}

function priceProductOptionLabel(option: ProductOperationPublishedOption) {
  const base = productOptionLabel(option)
  return `${base} · ${priceProductIdLabel(option)}`
}

function priceProductIdLabel(option: ProductOperationPublishedOption) {
  const productIds = priceProductIds(option)
  return productIds.length === 1 ? `ID ${productIds[0]}` : `${productIds.length} 个商品ID`
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
  if (!priceForm.account_ids.length) {
    ElMessage.warning('请至少选择一家店铺')
    return
  }
  if (!productCode) {
    ElMessage.warning('请选择共同已发布商品')
    return
  }
  const selectedOption = selectedPriceOption.value
  if (!selectedOption) {
    ElMessage.error('未找到所选商品的精确商品ID，请重新选择')
    return
  }
  const missingAccount = priceForm.account_ids.find(
    (accountId) => !selectedOption.product_ids[accountId],
  )
  if (missingAccount) {
    ElMessage.error(`${shopNameById(missingAccount)} 缺少商品ID，无法安全读取价格`)
    return
  }

  priceLoading.value = true
  priceStores.value = priceForm.account_ids.map((accountId) => ({
    account_id: accountId,
    shop_name: shopNameById(accountId),
    run_id: '',
    product_id: '',
    title: '',
    status: 'loading',
    error: '',
    rows: [],
  }))

  await Promise.all(
    priceStores.value.map(async (store) => {
      try {
        const submitted = await api.previewProductPrices({
          account_id: store.account_id,
          product_code: productCode,
          pdd_product_id: selectedOption.product_ids[store.account_id],
        })
        store.run_id = submitted.run_id
        const run = await waitForRun(submitted.run_id)
        const rawRows = Array.isArray(run.result?.skus) ? run.result.skus : []
        store.product_id = String(run.result?.pdd_product_id || '')
        store.title = String(run.result?.title || '')
        store.rows = rawRows.map((raw) => {
          const row = raw as Record<string, unknown>
          const groupPrice = String(row.group_price || '')
          const singlePrice = String(row.single_price || '')
          return {
            style_name: String(row.style_name || ''),
            package_name: String(row.package_name || ''),
            inventory: String(row.inventory || ''),
            group_price: groupPrice,
            single_price: singlePrice,
            spec_code: String(row.spec_code || ''),
            status: String(row.status || ''),
            next_group_price: Number.isFinite(Number(groupPrice)) ? Number(groupPrice) : null,
            next_single_price: Number.isFinite(Number(singlePrice)) ? Number(singlePrice) : null,
          }
        })
        store.status = 'success'
      } catch (error) {
        store.status = 'failed'
        store.error = error instanceof Error ? error.message : '读取商品规格失败'
      }
    }),
  )

  priceLoading.value = false
  const successCount = priceStores.value.filter((store) => store.status === 'success').length
  if (successCount) {
    const skuCount = priceStores.value.reduce((total, store) => total + store.rows.length, 0)
    ElMessage.success(`已读取 ${successCount} 家店铺，共 ${skuCount} 个规格`)
  } else {
    ElMessage.error('所选店铺均未能读取规格')
  }
}

function applyBulkDecrease() {
  const groupDecrease = Number(bulkPriceForm.group_decrease || 0)
  const singleDecrease = Number(bulkPriceForm.single_decrease || 0)
  if (groupDecrease < 0 || singleDecrease < 0) {
    ElMessage.warning('减少金额不能为负数')
    return
  }
  if (groupDecrease === 0 && singleDecrease === 0) {
    ElMessage.warning('请填写至少一项减少金额')
    return
  }

  const drafts = successfulPriceStores.value.flatMap((store) =>
    store.rows.map((row) => ({
      row,
      groupPrice: roundPrice(Number(row.group_price) - groupDecrease),
      singlePrice: roundPrice(Number(row.single_price) - singleDecrease),
    })),
  )
  const invalid = drafts.find(
    ({ groupPrice, singlePrice }) =>
      !Number.isFinite(groupPrice) ||
      !Number.isFinite(singlePrice) ||
      groupPrice <= 0 ||
      singlePrice <= 0 ||
      Math.round(groupPrice * 100) >
        Math.round((singlePrice - MIN_SINGLE_PRICE_GAP) * 100),
  )
  if (invalid) {
    ElMessage.error(`${invalid.row.spec_code} 批量减价后不符合价格规则，未应用任何修改`)
    return
  }
  for (const draft of drafts) {
    draft.row.next_group_price = draft.groupPrice
    draft.row.next_single_price = draft.singlePrice
  }
  ElMessage.success(`已应用到 ${successfulPriceStores.value.length} 家店铺的 ${drafts.length} 个规格`)
}

function changedRowsForStore(store: StorePriceResult) {
  return store.rows.filter(rowPriceChanged)
}

async function submitPriceChanges() {
  if (invalidChangedEntries.value.length) {
    const { store, row } = invalidChangedEntries.value[0]
    ElMessage.error(`${store.shop_name} / ${row.spec_code}：${priceRuleError(row)}`)
    return
  }
  if (!changedEntries.value.length) {
    ElMessage.warning('没有需要提交的价格变化')
    return
  }
  const storesWithChanges = successfulPriceStores.value
    .map((store) => ({ store, rows: changedRowsForStore(store) }))
    .filter((item) => item.rows.length)
  try {
    await ElMessageBox.confirm(
      `确认同时修改 ${storesWithChanges.length} 家店铺、${changedEntries.value.length} 个规格的拼单价和单买价？`,
      '多店价格修改确认',
      {
        confirmButtonText: '确认同时修改',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  priceSubmitting.value = true
  const results = await Promise.all(
    storesWithChanges.map(async ({ store, rows }) => {
      store.status = 'updating'
      store.error = ''
      try {
        const submitted = await api.updateProductPrices({
          account_id: store.account_id,
          product_code: priceForm.product_code.trim(),
          pdd_product_id: store.product_id,
          updates: rows.map((row) => ({
            spec_code: row.spec_code,
            group_price: Number(row.next_group_price),
            ...(Math.round(Number(row.next_single_price) * 100) !==
            Math.round(Number(row.single_price) * 100)
              ? { single_price: Number(row.next_single_price) }
              : {}),
          })),
        })
        store.run_id = submitted.run_id
        await waitForRun(submitted.run_id)
        for (const row of rows) {
          row.group_price = Number(row.next_group_price).toFixed(2)
          row.single_price = Number(row.next_single_price).toFixed(2)
        }
        store.status = 'success'
        return true
      } catch (error) {
        store.status = 'failed'
        store.error = error instanceof Error ? error.message : '修改价格失败'
        return false
      }
    }),
  )
  priceSubmitting.value = false
  const successCount = results.filter(Boolean).length
  if (successCount === results.length) {
    ElMessage.success(`已完成 ${successCount} 家店铺的价格修改`)
  } else {
    ElMessage.warning(`成功 ${successCount} 家，失败 ${results.length - successCount} 家`)
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
        <el-table-column label="店铺" min-width="160">
          <template #default="{ row }">{{ shopNameById(row.account_id) }}</template>
        </el-table-column>
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
            <h2 id="price-title">多店规格价格调整</h2>
            <p>并行读取所选店铺的共同商品，同时调整拼单价与单买价。</p>
          </div>
        </div>
      </div>

      <div class="price-search">
        <label class="field-block field-block--stores">
          <span>店铺</span>
          <el-select
            v-model="priceForm.account_ids"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            :max-collapse-tags="2"
            :loading="accountsLoading"
            placeholder="选择一家或多家店铺"
            @change="handlePriceAccountsChange"
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
          <span>共同已发布商品</span>
          <el-select
            v-model="priceForm.product_code"
            filterable
            clearable
            :loading="publishedOptionsLoading"
            :disabled="!priceForm.account_ids.length"
            placeholder="选择所选店铺均已发布的商品"
            @change="handlePriceProductChange"
          >
            <el-option
              v-for="option in commonPriceOptions"
              :key="option.product_code"
              :label="priceProductOptionLabel(option)"
              :value="option.product_code"
            >
              <div class="product-option">
                <span class="product-option__code">{{ option.product_code }}</span>
                <span class="product-option__label">{{ option.listing_label }}</span>
                <span class="product-option__id">{{ priceProductIdLabel(option) }}</span>
              </div>
            </el-option>
          </el-select>
        </label>
        <el-button
          type="primary"
          :icon="Search"
          :loading="priceLoading"
          class="search-button"
          @click="loadPriceSpecs"
        >
          并行读取规格
        </el-button>
      </div>

      <div v-if="priceStores.length" class="spec-result">
        <div class="bulk-price-toolbar">
          <div class="bulk-price-fields">
            <label>
              <span>拼单价统一减</span>
              <el-input-number
                v-model="bulkPriceForm.group_decrease"
                :min="0"
                :max="999999.99"
                :precision="2"
                :step="0.1"
                controls-position="right"
                aria-label="拼单价统一减少金额"
              />
            </label>
            <label>
              <span>单买价统一减</span>
              <el-input-number
                v-model="bulkPriceForm.single_decrease"
                :min="0"
                :max="999999.99"
                :precision="2"
                :step="0.1"
                controls-position="right"
                aria-label="单买价统一减少金额"
              />
            </label>
          </div>
          <el-button :icon="Minus" :disabled="!successfulPriceStores.length" @click="applyBulkDecrease">
            应用到全部店铺规格
          </el-button>
        </div>

        <section
          v-for="store in priceStores"
          :key="store.account_id"
          class="store-price-block"
          :aria-label="`${store.shop_name}价格规格`"
        >
          <header class="store-price-header">
            <div>
              <strong>{{ store.shop_name }}</strong>
              <span v-if="store.product_id">ID {{ store.product_id }}</span>
              <span v-if="store.title">{{ store.title }}</span>
            </div>
            <div class="store-price-meta">
              <el-tag :type="runStatusType(store.status)" effect="plain" size="small">
                {{ runStatusLabel(store.status) }}
              </el-tag>
              <el-tag v-if="store.rows.length" effect="plain" size="small">
                {{ store.rows.length }} 个规格
              </el-tag>
              <el-button
                v-if="store.run_id"
                link
                type="primary"
                :icon="Tickets"
                @click="openRun(store.run_id)"
              >
                任务记录
              </el-button>
            </div>
          </header>

          <el-alert
            v-if="store.error"
            :title="store.error"
            type="error"
            :closable="false"
            show-icon
            class="store-price-error"
          />

          <el-table
            v-if="store.rows.length"
            :data="store.rows"
            size="small"
            border
            stripe
            class="spec-table"
          >
            <el-table-column prop="style_name" label="款式" min-width="120" show-overflow-tooltip />
            <el-table-column prop="package_name" label="套餐 / 尺寸" min-width="120" show-overflow-tooltip />
            <el-table-column prop="inventory" label="库存" width="90" align="right" />
            <el-table-column label="当前拼单价" width="105" align="right">
              <template #default="{ row }">¥ {{ row.group_price || '-' }}</template>
            </el-table-column>
            <el-table-column label="新拼单价" width="180">
              <template #default="{ row }">
                <div class="price-input-cell" :class="{ 'is-error': priceRuleError(row) }">
                  <el-input-number
                    v-model="row.next_group_price"
                    :min="0.01"
                    :max="Math.max(0.01, maxGroupPrice(row) ?? 999999.99)"
                    :precision="2"
                    :step="0.1"
                    controls-position="right"
                    :aria-label="`新拼单价，最高 ${maxGroupPrice(row)?.toFixed(2) ?? '未知'}`"
                  />
                  <span v-if="priceRuleError(row)" class="price-input-hint is-error" role="alert">
                    {{ priceRuleError(row) }}
                  </span>
                  <span v-else class="price-input-hint">
                    最高 ¥{{ maxGroupPrice(row)?.toFixed(2) ?? '-' }}
                  </span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="当前单买价" width="105" align="right">
              <template #default="{ row }">¥ {{ row.single_price || '-' }}</template>
            </el-table-column>
            <el-table-column label="新单买价" width="160">
              <template #default="{ row }">
                <el-input-number
                  v-model="row.next_single_price"
                  :min="0.01"
                  :max="999999.99"
                  :precision="2"
                  :step="0.1"
                  controls-position="right"
                  aria-label="新单买价"
                />
              </template>
            </el-table-column>
            <el-table-column prop="spec_code" label="规格编码" min-width="190" show-overflow-tooltip>
              <template #default="{ row }"><span class="spec-code">{{ row.spec_code }}</span></template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="80" align="center" />
          </el-table>
        </section>

        <div class="price-actions">
          <span v-if="invalidChangedEntries.length" class="price-summary-error">
            {{ invalidChangedEntries.length }} 项价格不符合规则
          </span>
          <span v-else>已修改 {{ changedStoreCount }} 家店铺、{{ changedEntries.length }} 个规格</span>
          <el-button
            type="primary"
            :icon="EditPen"
            :disabled="!changedEntries.length || Boolean(invalidChangedEntries.length)"
            :loading="priceSubmitting"
            @click="submitPriceChanges"
          >
            同时提交所选店铺
          </el-button>
        </div>
      </div>

      <el-empty
        v-else-if="!priceLoading"
        description="选择店铺和共同已发布商品"
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
  grid-template-columns: minmax(90px, auto) minmax(120px, 1fr) minmax(120px, auto);
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

.product-option__id {
  color: #334155;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
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

.field-block--stores {
  width: min(380px, 100%);
}

.field-block :deep(.el-select) {
  width: 100%;
}

.search-button {
  min-height: 40px;
}

.price-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.bulk-price-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}

.bulk-price-fields {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.bulk-price-fields label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: #334155;
  font-size: 13px;
  font-weight: 500;
}

.bulk-price-fields :deep(.el-input-number) {
  width: 160px;
}

.store-price-block {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid #e2e8f0;
}

.store-price-header,
.store-price-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.store-price-header {
  justify-content: space-between;
  margin-bottom: 10px;
}

.store-price-header > div:first-child {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.store-price-header strong {
  color: #0f172a;
  flex-shrink: 0;
}

.store-price-header span {
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.store-price-error {
  margin-bottom: 10px;
}

.spec-table :deep(.el-input-number) {
  width: 148px;
}

.price-input-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
}

.price-input-cell.is-error :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}

.price-input-hint {
  color: #64748b;
  font-size: 12px;
  line-height: 1.35;
}

.price-input-hint.is-error,
.price-summary-error {
  color: var(--el-color-danger);
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

  .delist-controls > .el-select {
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

  .field-block--stores {
    width: 100%;
  }
}

@media (max-width: 640px) {
  .operation-section {
    padding: 18px 16px;
  }

  .section-heading--row,
  .bulk-price-toolbar,
  .bulk-price-fields,
  .store-price-header,
  .store-price-header > div:first-child,
  .price-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .bulk-price-toolbar,
  .bulk-price-fields,
  .bulk-price-fields label,
  .bulk-price-toolbar .el-button {
    width: 100%;
  }

  .bulk-price-fields :deep(.el-input-number) {
    width: 100%;
  }

  .store-price-meta {
    flex-wrap: wrap;
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
