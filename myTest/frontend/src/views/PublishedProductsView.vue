<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type {
  Account,
  ListingUnit,
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
const items = ref<PublishedProduct[]>([])
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

const activeSkuRows = computed(() => activeUnit.value?.skus ?? [])

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

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
  const skuPreviews = unit.skus.map((sku) => ({
    label: `${sku.style_name}/${sku.model_name}`,
    path: sku.preview_image,
    meta: sku.combo_folder,
  }))
  return [...carousel, ...detail, ...skuPreviews]
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
    <PageHeader title="已发布商品" desc="查看 published_products 映射表，按店铺筛选已发布商品与拼多多商品ID。">
      <template #actions>
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
      <el-table :data="items" stripe>
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
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column label="发布时间" width="170">
          <template #default="{ row }">{{ formatTime(row.published_at) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="来源任务" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ row.source_run_id || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看详情</el-button>
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
</style>
