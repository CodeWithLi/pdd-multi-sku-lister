<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { issueLevelLabel } from '@/utils/labels'
import type { ListingUnit, PreflightResponse, ProductSummary, SkuCombo } from '@/types'

interface PreviewImage {
  label: string
  path: string
  meta: string
}

const router = useRouter()
const loading = ref(false)
const products = ref<ProductSummary[]>([])
const selectedCodes = ref<string[]>([])
const preflight = ref<PreflightResponse | null>(null)
const error = ref('')

const imagePanelTitle = ref('')
const previewImages = ref<PreviewImage[]>([])

const skuDrawerVisible = ref(false)
const activeUnit = ref<ListingUnit | null>(null)
const activeSku = ref<SkuCombo | null>(null)

const productOptions = computed(() => products.value.map((p) => p.product_code))
const allPassed = computed(() => preflight.value?.ok === true)
const activeSkuRows = computed(() => activeUnit.value?.skus ?? [])

function assetUrl(path: string) {
  return `/api/catalog/asset?path=${encodeURIComponent(path)}`
}

function fileName(path: string) {
  return path.split(/[\\/]/).pop() || path
}

async function loadProducts() {
  loading.value = true
  error.value = ''
  try {
    products.value = await api.products()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function runPreflight() {
  if (!selectedCodes.value.length) {
    error.value = '请至少勾选一个商品'
    return
  }
  loading.value = true
  error.value = ''
  preflight.value = null
  imagePanelTitle.value = ''
  previewImages.value = []
  try {
    const result = await api.preflight(selectedCodes.value)
    preflight.value = result
    const firstUnit = result.units[0]
    if (firstUnit) {
      showAllUnitImages(firstUnit)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '检查失败'
  } finally {
    loading.value = false
  }
}

function selectAll() {
  selectedCodes.value = [...productOptions.value]
}

function goListing() {
  router.push('/tasks')
}

function openImages(title: string, images: PreviewImage[]) {
  if (!images.length) {
    ElMessage.warning('当前没有可查看的图片')
    return
  }
  imagePanelTitle.value = title
  previewImages.value = images
}

function openUnitImages(unit: ListingUnit, kind: 'carousel' | 'detail') {
  const source = kind === 'carousel' ? unit.carousel_images : unit.detail_images
  const label = kind === 'carousel' ? '主图' : '详情图'
  openImages(
    `${unit.listing_label} · ${label}`,
    source.map((path, index) => ({
      label: `${label}${index + 1}`,
      path,
      meta: fileName(path),
    })),
  )
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

function showAllUnitImages(unit: ListingUnit) {
  imagePanelTitle.value = `${unit.listing_label} · 全部图片`
  previewImages.value = unitAllImages(unit)
}

function openAllUnitImages(unit: ListingUnit) {
  openImages(`${unit.listing_label} · 全部图片`, unitAllImages(unit))
}

function openSkuDrawer(unit: ListingUnit) {
  activeUnit.value = unit
  activeSku.value = unit.skus[0] ?? null
  skuDrawerVisible.value = true
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

onMounted(loadProducts)
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="素材检查"
      desc="上架前检查图片、Excel、SKU 是否齐全。这一步不会打开浏览器，也不消耗拼多多账号。"
    />

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      style="margin-bottom: 16px"
      @close="error = ''"
    />

    <el-row :gutter="16">
      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="stat-card">
          <template #header>
            <div class="card-head">
              <span>选择要检查的商品</span>
              <el-button link type="primary" @click="selectAll">全选</el-button>
            </div>
          </template>

          <el-empty v-if="!products.length" description="素材文件夹里还没有商品">
            <div class="form-tip">请把商品素材放到 data/assets 目录中</div>
          </el-empty>

          <el-checkbox-group v-else v-model="selectedCodes" class="code-list">
            <div v-for="p in products" :key="p.product_code" class="code-row">
              <el-checkbox :value="p.product_code">
                <span class="code-name">{{ p.product_code }}</span>
                <span class="code-meta">
                  共 {{ p.listing_unit_count }} 套图
                  <template v-if="p.image_sets.length"> · {{ p.image_sets.join('、') }}</template>
                </span>
              </el-checkbox>
            </div>
          </el-checkbox-group>

          <el-button
            type="primary"
            size="large"
            style="width: 100%; margin-top: 16px"
            :disabled="!selectedCodes.length"
            @click="runPreflight"
          >
            开始检查
          </el-button>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="14">
        <el-card v-if="preflight" shadow="never" class="stat-card result-card">
          <template #header>
            <div class="card-head">
              <span>检查结果</span>
              <el-tag :type="preflight.ok ? 'success' : 'danger'" effect="dark" size="large">
                {{ preflight.ok ? '可以上架' : '有问题需处理' }}
              </el-tag>
            </div>
          </template>

          <el-row :gutter="12" style="margin-bottom: 16px">
            <el-col :span="8">
              <div class="mini-stat">
                <div class="mini-val">{{ preflight.unit_count }}</div>
                <div class="mini-label">套图数量</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="mini-stat error">
                <div class="mini-val">{{ preflight.error_count }}</div>
                <div class="mini-label">错误</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="mini-stat warn">
                <div class="mini-val">{{ preflight.warning_count }}</div>
                <div class="mini-label">警告</div>
              </div>
            </el-col>
          </el-row>

          <el-button
            v-if="allPassed"
            type="success"
            size="large"
            style="width: 100%; margin-bottom: 16px"
            @click="goListing"
          >
            检查通过，去上架 →
          </el-button>

          <el-table v-if="preflight.issues.length" :data="preflight.issues" size="small" stripe style="margin-bottom: 16px">
            <el-table-column label="级别" width="72">
              <template #default="{ row }">
                <el-tag :type="row.level === 'error' ? 'danger' : 'warning'" size="small">
                  {{ issueLevelLabel[row.level] || row.level }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="listing_label" label="套图" width="160" />
            <el-table-column prop="message" label="问题说明" show-overflow-tooltip />
          </el-table>

          <div v-if="preflight.units.length">
            <div class="section-label">检查明细</div>
            <el-table :data="preflight.units" size="small" stripe max-height="360" @row-dblclick="openAllUnitImages">
              <el-table-column label="商品/套图" min-width="180">
                <template #default="{ row }">
                  <el-button link type="primary" class="unit-link" @click="openAllUnitImages(row)">
                    {{ row.listing_label }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column label="SKU数" width="80">
                <template #default="{ row }">
                  <el-button link type="primary" :disabled="!row.sku_count" @click="openSkuDrawer(row)">
                    {{ row.sku_count }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column label="图片" width="168">
                <template #default="{ row }">
                  <div class="image-actions">
                    <el-button size="small" :disabled="!row.carousel_count" @click="openUnitImages(row, 'carousel')">
                      主图 {{ row.carousel_count }}
                    </el-button>
                    <el-button size="small" :disabled="!row.detail_count" @click="openUnitImages(row, 'detail')">
                      详情 {{ row.detail_count }}
                    </el-button>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="merchant_code" label="货号" min-width="140" show-overflow-tooltip />
            </el-table>
          </div>
        </el-card>

        <section v-if="preflight" class="inline-image-panel">
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
          <el-empty v-else description="点击上方主图、详情或商品/套图后，在这里显示图片" />
        </section>

        <el-empty v-else description="勾选商品后点击“开始检查”" />
      </el-col>
    </el-row>

    <el-drawer v-model="skuDrawerVisible" :title="activeUnit ? `${activeUnit.listing_label} · SKU数据` : 'SKU数据'" size="760px">
      <div v-if="activeUnit" class="sku-panel">
        <el-descriptions :column="3" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="商品">{{ activeUnit.product_code }}</el-descriptions-item>
          <el-descriptions-item label="套图">{{ activeUnit.image_set || '默认' }}</el-descriptions-item>
          <el-descriptions-item label="货号">{{ activeUnit.merchant_code }}</el-descriptions-item>
        </el-descriptions>

        <el-table :data="activeSkuRows" size="small" stripe height="360" highlight-current-row @row-click="selectSku">
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
    </el-drawer>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.result-card {
  min-height: 348px;
}

.code-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.code-row {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  background: #fafbfc;
}

.code-row :deep(.el-checkbox) {
  height: auto;
  align-items: flex-start;
  width: 100%;
}

.code-name {
  font-weight: 600;
  margin-right: 8px;
}

.code-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #475569;
}

.unit-link {
  padding: 0;
  font-weight: 600;
}

.image-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}

.image-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.mini-stat {
  text-align: center;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.mini-stat.error .mini-val {
  color: #dc2626;
}

.mini-stat.warn .mini-val {
  color: #d97706;
}

.mini-val {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
}

.mini-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.inline-image-panel {
  margin-top: 16px;
  min-height: 420px;
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

.sku-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sku-detail {
  margin-top: 4px;
}

@media (max-width: 900px) {
  .inline-image-panel {
    min-height: 280px;
  }

  .inline-image-grid {
    grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  }
}
</style>
