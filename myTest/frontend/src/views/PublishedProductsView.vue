<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ElTable } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type {
  Account,
  ListingUnit,
  ProductDetail,
  PublishedProduct,
  PublishedProductDetailResponse,
  SkuCombo,
} from '@/types'

interface PreviewImage {
  label: string
  path: string
  meta: string
}

const router = useRouter()
const loading = ref(false)
const detailLoading = ref(false)
const delistingId = ref('')
const deletingId = ref('')
const batchWorking = ref(false)
const lookupId = ref('')
const items = ref<PublishedProduct[]>([])
const selectedRows = ref<PublishedProduct[]>([])
const tableRef = ref<InstanceType<typeof ElTable>>()
const accounts = ref<Account[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const error = ref('')

const filters = reactive({
  account_id: '',
  product_code: '',
  pdd_product_id: '',
})

const detailVisible = ref(false)
const detail = ref<PublishedProductDetailResponse | null>(null)
const activeUnit = ref<ListingUnit | null>(null)
const activeSku = ref<SkuCombo | null>(null)
const imagePanelTitle = ref('')
const previewImages = ref<PreviewImage[]>([])

const addVisible = ref(false)
const addSubmitting = ref(false)
const catalogLoading = ref(false)
const catalogHint = ref('')
const addMode = ref<'pdd_only' | 'with_local'>('pdd_only')
const addForm = reactive({
  account_id: '',
  pdd_product_id: '',
  product_code: '',
  listing_label: '',
  family_code: '',
  image_set: '',
  merchant_code: '',
  status: 'on_sale',
  note: '',
  import_catalog_skus: false,
})
const catalogImageSets = ref<string[]>([])

const activeSkuRows = computed(() => activeUnit.value?.skus ?? [])
const selectedCount = computed(() => selectedRows.value.length)
const selectedDelistable = computed(() =>
  selectedRows.value.filter((row) => row.pdd_product_id && row.status !== 'delisted'),
)

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function priceSyncLabel(status: string) {
  const map: Record<string, string> = {
    none: '未反查',
    specs_synced: '拼多多规格价',
    local_skus: '本地规格价',
    list_price: '已有列表价',
    detail_opened: '已打开详情',
    edit_opened: '已打开编辑',
    searched: '已搜索',
  }
  return map[status] || status || '未反查'
}

function priceSyncTagType(status: string): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'specs_synced' || status === 'local_skus' || status === 'list_price' || status === 'edit_opened' || status === 'detail_opened') {
    return 'success'
  }
  if (status === 'searched') return 'warning'
  return 'info'
}

function listPriceHint(row: PublishedProduct) {
  const lookup = row.spec_metadata?.pdd_goods_lookup as Record<string, unknown> | undefined
  const pddSkus = lookup?.pdd_skus
  if (Array.isArray(pddSkus) && pddSkus.length) {
    const first = pddSkus[0] as Record<string, unknown>
    const parts = [`${pddSkus.length} 个SKU`]
    if (first.group_price) parts.push(`拼单价 ${first.group_price}`)
    if (first.activity_price) parts.push(`活动价 ${first.activity_price}`)
    return parts.join(' · ')
  }
  const listRow = lookup?.list_row as Record<string, unknown> | undefined
  if (!listRow) return ''
  const parts: string[] = []
  if (listRow.group_price) parts.push(`拼单价 ${listRow.group_price}`)
  if (listRow.activity_price) parts.push(`活动价 ${listRow.activity_price}`)
  return parts.join(' · ')
}

const pddSkuRows = computed(() => {
  const lookup = detail.value?.published.spec_metadata?.pdd_goods_lookup as Record<string, unknown> | undefined
  const rows = lookup?.pdd_skus
  return Array.isArray(rows) ? rows : []
})

function assetUrl(path: string) {
  return `/api/catalog/asset?path=${encodeURIComponent(path)}`
}

function fileName(path: string) {
  return path.split(/[\\/]/).pop() || path
}

async function loadMeta() {
  try {
    accounts.value = await api.accounts(true)
  } catch {
    accounts.value = []
  }
}

async function loadPublishedProducts() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.publishedProducts({
      page: page.value,
      page_size: pageSize.value,
      account_id: filters.account_id || undefined,
      product_code: filters.product_code || undefined,
      pdd_product_id: filters.pdd_product_id || undefined,
    })
    items.value = resp.items
    total.value = resp.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载已发布商品失败'
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  loadPublishedProducts()
}

function resetFilters() {
  filters.account_id = ''
  filters.product_code = ''
  filters.pdd_product_id = ''
  applyFilters()
}

function onPageChange(next: number) {
  page.value = next
  loadPublishedProducts()
}

function onPageSizeChange(next: number) {
  pageSize.value = next
  page.value = 1
  loadPublishedProducts()
}

function openRun(row: PublishedProduct) {
  if (!row.source_run_id) return
  router.push({ path: '/runs', query: { id: row.source_run_id } })
}

async function lookupPublishedGoods(row: PublishedProduct) {
  if (!row.mapping_id || !row.pdd_product_id) return
  lookupId.value = row.mapping_id
  try {
    const resp = await api.lookupPublishedProductGoods(row.mapping_id)
    ElMessage.success(`反查任务已提交：${resp.run_id}`)
    router.push({ path: '/runs', query: { id: resp.run_id } })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交反查任务失败')
  } finally {
    lookupId.value = ''
  }
}

function onSelectionChange(rows: PublishedProduct[]) {
  selectedRows.value = rows
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selectedRows.value = []
}

async function batchDelistPublished() {
  const rows = selectedDelistable.value
  if (!rows.length) {
    ElMessage.warning('所选商品均不可下架（已下架或无拼多多商品ID）')
    return
  }
  const skipped = selectedCount.value - rows.length
  const skipHint = skipped > 0 ? `\n\n另有 ${skipped} 条已下架或无商品ID，将跳过。` : ''
  try {
    await ElMessageBox.confirm(
      `确认批量下架 ${rows.length} 个商品？\n\n系统会按各条记录的拼多多商品ID精准检索，ID不一致不会下架。${skipHint}`,
      '批量精准下架确认',
      {
        confirmButtonText: '确认下架',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  batchWorking.value = true
  let ok = 0
  let fail = 0
  const runIds: string[] = []
  for (const row of rows) {
    try {
      const resp = await api.delistPublishedProduct(row.mapping_id)
      ok += 1
      if (resp.run_id) runIds.push(resp.run_id)
    } catch {
      fail += 1
    }
  }
  batchWorking.value = false
  clearSelection()
  if (fail) {
    ElMessage.warning(`已提交 ${ok} 个下架任务，${fail} 个失败`)
  } else {
    ElMessage.success(`已提交 ${ok} 个精准下架任务`)
  }
  if (runIds.length === 1) {
    router.push({ path: '/runs', query: { id: runIds[0] } })
  } else if (runIds.length > 1) {
    router.push({ path: '/runs' })
  }
}

async function batchRemovePublished() {
  const rows = selectedRows.value
  if (!rows.length) return
  try {
    await ElMessageBox.confirm(
      `确认删除 ${rows.length} 条映射记录？\n\n仅删除数据库 published_products 表中的记录，不会在拼多多后台下架商品。`,
      '批量删除映射确认',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  batchWorking.value = true
  let ok = 0
  let fail = 0
  const deletingIds = new Set(rows.map((row) => row.mapping_id))
  for (const row of rows) {
    try {
      await api.deletePublishedProduct(row.mapping_id)
      ok += 1
    } catch {
      fail += 1
    }
  }
  batchWorking.value = false
  if (detail.value?.published.mapping_id && deletingIds.has(detail.value.published.mapping_id)) {
    detailVisible.value = false
    detail.value = null
  }
  clearSelection()
  if (items.value.length <= rows.length && page.value > 1) {
    page.value -= 1
  }
  await loadPublishedProducts()
  if (fail) {
    ElMessage.warning(`成功删除 ${ok} 条，失败 ${fail} 条`)
  } else {
    ElMessage.success(`已删除 ${ok} 条映射记录`)
  }
}

async function delistPublished(row: PublishedProduct) {
  if (!row.mapping_id || !row.pdd_product_id) return
  try {
    await ElMessageBox.confirm(
      `确认下架店铺 ${row.account_id} 的拼多多商品ID：${row.pdd_product_id}？系统会按商品ID精准检索，ID不一致不会下架。`,
      '精准下架确认',
      {
        confirmButtonText: '确认下架',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  delistingId.value = row.mapping_id
  try {
    const resp = await api.delistPublishedProduct(row.mapping_id)
    ElMessage.success(`精准下架任务已提交：${resp.run_id}`)
    router.push({ path: '/runs', query: { id: resp.run_id } })
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '提交下架任务失败')
  } finally {
    delistingId.value = ''
  }
}

async function removePublished(row: PublishedProduct) {
  if (!row.mapping_id) return
  try {
    await ElMessageBox.confirm(
      `确认删除映射记录「${row.listing_label}」？\n\n仅删除数据库 published_products 表中的记录，不会在拼多多后台下架商品。`,
      '删除映射确认',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }

  deletingId.value = row.mapping_id
  try {
    await api.deletePublishedProduct(row.mapping_id)
    ElMessage.success('已删除映射记录')
    if (detail.value?.published.mapping_id === row.mapping_id) {
      detailVisible.value = false
      detail.value = null
    }
    if (items.value.length === 1 && page.value > 1) {
      page.value -= 1
    }
    await loadPublishedProducts()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '删除失败')
  } finally {
    deletingId.value = ''
  }
}

function unitAllImages(unit: ListingUnit) {
  const carousel = unit.carousel_images.map((path, index) => ({
    label: `主图${index + 1}`,
    path,
    meta: fileName(path),
  }))
  const detail = unit.detail_images.map((path, index) => ({
    label: `详情${index + 1}`,
    path,
    meta: fileName(path),
  }))
  const material = unit.material_image
    ? [
        {
          label: '商品素材',
          path: unit.material_image,
          meta: fileName(unit.material_image),
        },
      ]
    : []
  const skuPreviews = unit.skus.map((sku) => ({
    label: `${sku.style_name}/${sku.model_name}`,
    path: sku.preview_image,
    meta: sku.combo_folder,
  }))
  return [...carousel, ...detail, ...material, ...skuPreviews]
}

function openImages(title: string, images: PreviewImage[]) {
  if (!images.length) {
    ElMessage.warning('当前没有可查看的图片')
    return
  }
  imagePanelTitle.value = title
  previewImages.value = images
}

function openAllUnitImages(unit: ListingUnit | null) {
  if (!unit) return
  openImages(`${unit.listing_label} · 全部图片`, unitAllImages(unit))
}

function selectSku(row: SkuCombo) {
  activeSku.value = row
}

function openSkuPreview(sku: SkuCombo) {
  openImages(`${sku.style_name}/${sku.model_name} · SKU预览图`, [
    {
      label: `${sku.style_code}+${sku.model_code}`,
      path: sku.preview_image,
      meta: sku.combo_folder,
    },
  ])
}

function resetAddForm() {
  addMode.value = 'pdd_only'
  addForm.account_id = filters.account_id || accounts.value[0]?.account_id || ''
  addForm.pdd_product_id = ''
  addForm.product_code = ''
  addForm.listing_label = ''
  addForm.family_code = ''
  addForm.image_set = ''
  addForm.merchant_code = ''
  addForm.status = 'on_sale'
  addForm.note = ''
  addForm.import_catalog_skus = false
  catalogHint.value = ''
  catalogImageSets.value = []
}

function onAddModeChange(mode: string | number | boolean | undefined) {
  if (mode !== 'pdd_only' && mode !== 'with_local') return
  if (mode === 'pdd_only') {
    addForm.import_catalog_skus = false
    addForm.family_code = ''
    addForm.image_set = ''
    catalogHint.value = ''
    catalogImageSets.value = []
    return
  }
  addForm.import_catalog_skus = true
}

function openAddDialog() {
  resetAddForm()
  addVisible.value = true
}

async function loadCatalogHint() {
  if (addMode.value === 'pdd_only') return
  const code = addForm.product_code.trim().toUpperCase()
  if (!code) {
    catalogHint.value = ''
    catalogImageSets.value = []
    return
  }
  catalogLoading.value = true
  catalogHint.value = ''
  try {
    const detail: ProductDetail = await api.productDetail(code)
    catalogImageSets.value = detail.image_sets || []
    const imageSet = addForm.image_set.trim()
    let unit: ListingUnit | undefined
    if (imageSet) {
      unit = detail.units.find((u) => u.image_set === imageSet)
    }
    if (!unit) {
      unit = detail.units[0]
    }
    if (unit) {
      if (!addForm.family_code) addForm.family_code = unit.family_code || ''
      if (!addForm.image_set) addForm.image_set = unit.image_set || ''
      if (!addForm.merchant_code) addForm.merchant_code = unit.merchant_code || code
      if (!addForm.listing_label) {
        addForm.listing_label = unit.listing_label || `${code}${unit.image_set ? ` / ${unit.image_set}` : ''}`
      }
      catalogHint.value = `素材目录已找到：${unit.sku_count} 个 SKU，${unit.style_codes?.length || 0} 个款式`
    } else {
      catalogHint.value = '素材目录有该编码，但未解析到套图/SKU'
    }
  } catch {
    catalogHint.value = '素材目录未找到该编码；仍可保存，但活动价格校验可能缺少 SKU'
    catalogImageSets.value = []
  } finally {
    catalogLoading.value = false
  }
}

async function submitManualAdd() {
  if (!addForm.account_id) {
    ElMessage.warning('请选择店铺')
    return
  }
  if (!/^\d+$/.test(addForm.pdd_product_id.trim())) {
    ElMessage.warning('拼多多商品 ID 必须是纯数字')
    return
  }
  if (!addForm.product_code.trim()) {
    ElMessage.warning('请填写商品编码')
    return
  }
  if (!addForm.listing_label.trim()) {
    ElMessage.warning('请填写显示名称')
    return
  }

  addSubmitting.value = true
  try {
    const resp = await api.createManualPublishedProduct({
      account_id: addForm.account_id.trim(),
      pdd_product_id: addForm.pdd_product_id.trim(),
      product_code: addForm.product_code.trim().toUpperCase(),
      listing_label: addForm.listing_label.trim(),
      family_code: addForm.family_code.trim().toUpperCase(),
      image_set: addForm.image_set.trim(),
      merchant_code: (addForm.merchant_code.trim() || addForm.product_code.trim()).toUpperCase(),
      status: addForm.status,
      note: addForm.note.trim(),
      import_catalog_skus: addMode.value === 'with_local' && addForm.import_catalog_skus,
    })
    addVisible.value = false
    ElMessage.success(resp.message || '已添加')
    if (resp.catalog_hints?.length) {
      ElMessage.info(resp.catalog_hints.join('；'))
    }
    filters.account_id = resp.published.account_id
    await loadPublishedProducts()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '添加失败')
  } finally {
    addSubmitting.value = false
  }
}

async function openDetail(row: PublishedProduct) {
  detailLoading.value = true
  detailVisible.value = true
  imagePanelTitle.value = ''
  previewImages.value = []
  try {
    const resp = await api.publishedProductDetail(row.mapping_id)
    detail.value = resp
    activeUnit.value = resp.unit_detail
    activeSku.value = resp.unit_detail?.skus?.[0] ?? null
    if (resp.unit_detail) {
      openAllUnitImages(resp.unit_detail)
    }
  } catch (e) {
    detail.value = null
    activeUnit.value = null
    activeSku.value = null
    error.value = e instanceof Error ? e.message : '加载商品详情失败'
  } finally {
    detailLoading.value = false
  }
}

onMounted(async () => {
  await loadMeta()
  await loadPublishedProducts()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="已发布商品"
      desc="本系统已上架 + 手动录入的拼多多商品映射。手动添加后可在「活动」页勾选报名。"
    >
      <template #actions>
        <el-button type="primary" @click="openAddDialog">手动添加已有商品</el-button>
        <el-button @click="loadPublishedProducts">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 16px" @close="error = ''" />

    <el-card shadow="never" class="stat-card filter-card">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :span="6">
            <el-form-item label="店铺">
              <el-select v-model="filters.account_id" clearable filterable style="width: 100%">
                <el-option v-for="a in accounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="商品编码 / 套图 / 货号">
              <el-input v-model="filters.product_code" clearable placeholder="如 BD046A" @keyup.enter="applyFilters" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="拼多多商品ID">
              <el-input v-model="filters.pdd_product_id" clearable placeholder="如 96442086670" @keyup.enter="applyFilters" />
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label=" ">
              <div class="filter-actions">
                <el-button @click="resetFilters">重置</el-button>
                <el-button type="primary" @click="applyFilters">查询</el-button>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never" class="stat-card">
      <div class="batch-bar">
        <span>已选 {{ selectedCount }} 条</span>
        <div class="batch-actions">
          <el-button
            :disabled="!selectedDelistable.length"
            :loading="batchWorking"
            type="danger"
            plain
            @click="batchDelistPublished"
          >
            批量下架{{ selectedDelistable.length ? ` (${selectedDelistable.length})` : '' }}
          </el-button>
          <el-button
            :disabled="!selectedCount"
            :loading="batchWorking"
            type="danger"
            @click="batchRemovePublished"
          >
            批量删除{{ selectedCount ? ` (${selectedCount})` : '' }}
          </el-button>
          <el-button :disabled="!selectedCount" @click="clearSelection">取消选择</el-button>
        </div>
      </div>

      <el-table
        ref="tableRef"
        :data="items"
        stripe
        row-key="mapping_id"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="44" reserve-selection />
        <el-table-column prop="account_id" label="店铺" width="110" />
        <el-table-column prop="pdd_product_id" label="商品ID" width="130" />
        <el-table-column label="商品/套图" min-width="180">
          <template #default="{ row }">
            <div class="strong">{{ row.listing_label }}</div>
            <div class="muted">{{ row.product_code }}<span v-if="row.image_set"> / {{ row.image_set }}</span></div>
            <div v-if="row.family_code" class="muted">母编码：{{ row.family_code }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="merchant_code" label="货号" min-width="150" show-overflow-tooltip />
        <el-table-column label="拼多多价格" width="150">
          <template #default="{ row }">
            <el-tag size="small" :type="priceSyncTagType(row.price_sync_status)" effect="plain">
              {{ priceSyncLabel(row.price_sync_status) }}
            </el-tag>
            <div v-if="listPriceHint(row)" class="muted">{{ listPriceHint(row) }}</div>
            <div v-else-if="row.price_sync_at" class="muted">{{ formatTime(row.price_sync_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column label="发布时间" width="170">
          <template #default="{ row }">{{ formatTime(row.published_at) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="来源任务" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag v-if="row.source_run_id === 'manual'" size="small" type="info" effect="plain">手动录入</el-tag>
            <span v-else>{{ row.source_run_id || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="360" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看详情</el-button>
            <el-button
              link
              type="primary"
              :loading="lookupId === row.mapping_id"
              :disabled="!row.pdd_product_id || row.status === 'delisted'"
              @click="lookupPublishedGoods(row)"
            >
              反查规格价格
            </el-button>
            <el-button link type="primary" :disabled="!row.source_run_id" @click="openRun(row)">查看记录</el-button>
            <el-button
              link
              type="danger"
              :loading="delistingId === row.mapping_id"
              :disabled="row.status === 'delisted' || !row.pdd_product_id"
              @click="delistPublished(row)"
            >
              下架
            </el-button>
            <el-button
              link
              type="danger"
              :loading="deletingId === row.mapping_id"
              @click="removePublished(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!items.length" description="暂无已发布商品记录" />

      <el-pagination
        class="pager"
        background
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="onPageChange"
        @size-change="onPageSizeChange"
      />
    </el-card>

    <el-drawer v-model="detailVisible" title="已发布商品详情" size="1100px" destroy-on-close>
      <div v-loading="detailLoading">
        <template v-if="detail">
          <el-descriptions :column="3" border size="small" style="margin-bottom: 16px">
            <el-descriptions-item label="店铺">{{ detail.published.account_id }}</el-descriptions-item>
            <el-descriptions-item label="拼多多商品ID">{{ detail.published.pdd_product_id }}</el-descriptions-item>
            <el-descriptions-item label="状态">{{ detail.published.status }}</el-descriptions-item>
            <el-descriptions-item label="商品编码">{{ detail.published.product_code }}</el-descriptions-item>
            <el-descriptions-item label="母文件编码">{{ detail.published.family_code || '-' }}</el-descriptions-item>
            <el-descriptions-item label="套图">{{ detail.published.image_set || '默认' }}</el-descriptions-item>
            <el-descriptions-item label="货号">{{ detail.published.merchant_code || '-' }}</el-descriptions-item>
            <el-descriptions-item label="商品标签">{{ detail.published.listing_label }}</el-descriptions-item>
            <el-descriptions-item label="发布时间">{{ formatTime(detail.published.published_at) }}</el-descriptions-item>
            <el-descriptions-item label="来源任务">{{ detail.published.source_run_id || '-' }}</el-descriptions-item>
          </el-descriptions>

          <el-row :gutter="16">
            <el-col :span="12">
              <div class="section-label">发布结果快照</div>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="结果状态">{{ detail.run_result_item.status || '-' }}</el-descriptions-item>
                <el-descriptions-item label="抓ID状态">{{ detail.run_result_item.pdd_product_id_capture_status || '-' }}</el-descriptions-item>
                <el-descriptions-item label="发布标题">{{ detail.run_result_item.title || '-' }}</el-descriptions-item>
                <el-descriptions-item label="原因">{{ detail.run_result_item.reason || '-' }}</el-descriptions-item>
                <el-descriptions-item label="报错">{{ detail.run_result_item.error || '-' }}</el-descriptions-item>
              </el-descriptions>
            </el-col>
            <el-col :span="12">
              <div class="section-label">素材明细</div>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="主图数量">{{ detail.unit_detail?.carousel_count ?? 0 }}</el-descriptions-item>
                <el-descriptions-item label="详情图数量">{{ detail.unit_detail?.detail_count ?? 0 }}</el-descriptions-item>
                <el-descriptions-item label="SKU数量">{{ detail.unit_detail?.sku_count ?? 0 }}</el-descriptions-item>
                <el-descriptions-item label="款式编码">{{ detail.unit_detail?.style_codes?.join('、') || '-' }}</el-descriptions-item>
                <el-descriptions-item label="型号编码">{{ detail.unit_detail?.model_codes?.join('、') || '-' }}</el-descriptions-item>
              </el-descriptions>
            </el-col>
          </el-row>

          <section v-if="detail.unit_detail" class="inline-image-panel">
            <div class="inline-image-head">
              <span>{{ imagePanelTitle || '图片预览' }}</span>
              <el-tag v-if="previewImages.length" size="small">{{ previewImages.length }} 张</el-tag>
            </div>
            <div v-if="previewImages.length" class="inline-image-grid">
              <div v-for="img in previewImages" :key="img.path" class="inline-image-item">
                <div class="inline-image-box">
                  <img :src="assetUrl(img.path)" :alt="img.label" loading="lazy" />
                </div>
                <div class="inline-image-info">
                  <strong>{{ img.label }}</strong>
                  <span>{{ img.meta }}</span>
                </div>
              </div>
            </div>
          </section>

          <div v-if="pddSkuRows.length" style="margin-top: 16px">
            <div class="section-label">拼多多反查 SKU（规格与库存）</div>
            <el-table :data="pddSkuRows" size="small" stripe max-height="360">
              <el-table-column prop="style_name" label="款式" min-width="120" show-overflow-tooltip />
              <el-table-column prop="package_name" label="套餐/尺寸" min-width="160" show-overflow-tooltip />
              <el-table-column prop="group_price" label="拼单价" width="82" />
              <el-table-column prop="single_price" label="单买价" width="82" />
              <el-table-column prop="spec_code" label="规格编码" min-width="140" show-overflow-tooltip />
            </el-table>
          </div>

          <div v-if="detail.unit_detail" style="margin-top: 16px">
            <div class="section-label">SKU数据</div>
            <el-table :data="activeSkuRows" size="small" stripe max-height="320" @row-click="selectSku">
              <el-table-column prop="style_code" label="款式编码" width="92" />
              <el-table-column prop="style_name" label="款式名称" min-width="120" show-overflow-tooltip />
              <el-table-column prop="model_code" label="型号编码" width="92" />
              <el-table-column prop="model_name" label="型号名称" min-width="120" show-overflow-tooltip />
              <el-table-column prop="inventory" label="库存" width="72" />
              <el-table-column prop="group_price" label="拼单价" width="82" />
              <el-table-column prop="single_price" label="单买价" width="82" />
              <el-table-column label="图片" width="72">
                <template #default="{ row }">
                  <el-button link type="primary" @click.stop="openSkuPreview(row)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>

            <div v-if="activeSku" class="sku-detail">
              <div class="section-label">当前SKU</div>
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="组合文件夹">{{ activeSku.combo_folder }}</el-descriptions-item>
                <el-descriptions-item label="预览图">{{ fileName(activeSku.preview_image) }}</el-descriptions-item>
                <el-descriptions-item label="款式">{{ activeSku.style_code }} · {{ activeSku.style_name }}</el-descriptions-item>
                <el-descriptions-item label="型号">{{ activeSku.model_code }} · {{ activeSku.model_name }}</el-descriptions-item>
                <el-descriptions-item label="库存">{{ activeSku.inventory }}</el-descriptions-item>
                <el-descriptions-item label="价格">{{ activeSku.group_price }} / {{ activeSku.single_price }}</el-descriptions-item>
              </el-descriptions>
            </div>
          </div>

          <el-collapse style="margin-top: 16px">
            <el-collapse-item title="来源任务原始结果（开发用）" name="raw">
              <pre class="json-block">{{ JSON.stringify(detail.source_run_result, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </template>
      </div>
    </el-drawer>

    <el-dialog
      v-model="addVisible"
      title="手动添加拼多多已有商品"
      width="720px"
      destroy-on-close
      class="manual-add-dialog"
    >
      <el-alert type="info" :closable="false" show-icon class="guide-alert">
        <template #title>添加方式</template>
        <el-radio-group v-model="addMode" class="mode-radio" @change="onAddModeChange">
          <el-radio value="pdd_only">拼多多已有商品（无本地图片/素材）</el-radio>
          <el-radio value="with_local">本地也有素材目录（可导入 SKU）</el-radio>
        </el-radio-group>
        <p v-if="addMode === 'pdd_only'" class="guide-text">
          商品和图片都在拼多多后台，本地没有素材文件夹。<strong>只需填 4 项</strong>：店铺、商品 ID、识别编码、显示名称。
          母文件编码、套图、SKU 导入<strong>全部可不填</strong>，保存后可直接去「活动」页勾选报名（如 21365）。
        </p>
        <p v-else class="guide-text">
          本地 <code>data/assets</code> 下有对应商品文件夹时，可自动导入 SKU，用于 20981 价格校验、限时限量购。
        </p>
      </el-alert>

      <el-form label-position="top" class="manual-add-form" @submit.prevent="submitManualAdd">
        <div class="form-section-title">必填 · 基础信息</div>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="店铺" required>
              <el-select v-model="addForm.account_id" filterable placeholder="选择店铺，如 store_A" style="width: 100%">
                <el-option v-for="a in accounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
              <div class="field-hint">与「店铺设置」里的 account_id 一致，活动任务会用它打开对应浏览器 Profile</div>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="拼多多商品 ID" required>
              <el-input v-model="addForm.pdd_product_id" placeholder="如 965836045952" maxlength="20" />
              <div class="field-hint">
                拼多多商家后台 → 商品管理 → 商品列表 → 复制数字 ID（不是货号）
              </div>
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="识别编码" required>
              <el-input
                v-model="addForm.product_code"
                :placeholder="addMode === 'pdd_only' ? '填拼多多货号或任意识别码' : '如 BD716A'"
                @blur="loadCatalogHint"
              />
              <div class="field-hint">
                <template v-if="addMode === 'pdd_only'">
                  仅在本系统里标识这条记录，可填拼多多「货号」或你记得的编码；<strong>不需要</strong>对应本地文件夹
                </template>
                <template v-else>
                  用于匹配「拼多多定价.xls / 控价.xls」；填完失焦可自动查素材目录
                </template>
              </div>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="显示名称" required>
              <el-input
                v-model="addForm.listing_label"
                :placeholder="addMode === 'pdd_only' ? '如 笔袋黑色款' : '如 BD716A / 第一套图'"
              />
              <div class="field-hint">在活动页、本页表格中展示，写你在拼多多看到的商品名即可</div>
            </el-form-item>
          </el-col>
        </el-row>

        <template v-if="addMode === 'with_local'">
          <div class="form-section-title">选填 · 编码与定价（参与价格校验时建议填写）</div>
          <el-row :gutter="12">
            <el-col :span="8">
              <el-form-item label="母文件编码">
                <el-input v-model="addForm.family_code" placeholder="如 BD716" />
                <div class="field-hint">商品文件夹名，定价表模糊匹配用</div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="套图">
                <el-select
                  v-model="addForm.image_set"
                  clearable
                  filterable
                  allow-create
                  default-first-option
                  placeholder="如 第一套图"
                  style="width: 100%"
                  @change="loadCatalogHint"
                >
                  <el-option v-for="s in catalogImageSets" :key="s" :label="s" :value="s" />
                </el-select>
                <div class="field-hint">多套图商品建议填写</div>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="货号">
                <el-input v-model="addForm.merchant_code" placeholder="通常同商品编码" />
                <div class="field-hint">拼多多后台「货号」，默认可与识别编码相同</div>
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <div v-else class="skip-hint">
          当前为「无本地素材」模式：母文件编码、套图、SKU 导入已跳过，不影响 21365 等活动选品报名。
        </div>

        <div class="form-section-title">其他</div>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="状态">
              <el-select v-model="addForm.status" style="width: 100%">
                <el-option label="在售 on_sale" value="on_sale" />
                <el-option label="已下架 delisted" value="delisted" />
              </el-select>
              <div class="field-hint">仅本系统标记；不会改动拼多多后台状态</div>
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="备注">
              <el-input v-model="addForm.note" placeholder="如：2024年手工上架的老款" />
            </el-form-item>
          </el-col>
        </el-row>

        <template v-if="addMode === 'with_local'">
          <el-form-item>
            <el-checkbox v-model="addForm.import_catalog_skus">
              从本地素材目录导入 SKU 规格（20981 价格校验 / 限时限量购需要）
            </el-checkbox>
            <el-button
              link
              type="primary"
              :loading="catalogLoading"
              :disabled="!addForm.product_code.trim()"
              @click="loadCatalogHint"
            >
              重新检测素材目录
            </el-button>
            <div v-if="catalogHint" class="catalog-hint">{{ catalogHint }}</div>
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="addSubmitting" @click="submitManualAdd">保存映射</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.filter-card {
  margin-bottom: 16px;
}

.filter-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  width: 100%;
}

.batch-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.batch-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
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

.pager {
  margin-top: 14px;
  justify-content: flex-end;
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #475569;
}

.inline-image-panel {
  margin-top: 16px;
  min-height: 280px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
}

.inline-image-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.inline-image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 12px;
}

.inline-image-item {
  min-width: 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.inline-image-box {
  width: 100%;
  aspect-ratio: 1 / 1;
  background: #f8fafc;
}

.inline-image-box img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.inline-image-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px;
}

.inline-image-info strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: #334155;
}

.inline-image-info span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--text-secondary);
}

.sku-detail {
  margin-top: 12px;
}

.guide-alert {
  margin-bottom: 16px;
}

.guide-text {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.55;
}

.mode-radio {
  margin-top: 8px;
}

.skip-hint {
  margin: 0 0 14px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.5;
  color: #64748b;
  background: #f8fafc;
  border: 1px dashed var(--border-color);
  border-radius: 8px;
}

.guide-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.65;
  color: #475569;
}

.form-section-title {
  margin: 4px 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.field-hint {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-secondary);
}

.catalog-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #059669;
}

.manual-add-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
</style>
