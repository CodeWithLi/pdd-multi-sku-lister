<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { issueLevelLabel } from '@/utils/labels'
import type { PreflightResponse, ProductSummary } from '@/types'

const router = useRouter()
const loading = ref(false)
const products = ref<ProductSummary[]>([])
const selectedCodes = ref<string[]>([])
const preflight = ref<PreflightResponse | null>(null)
const error = ref('')

const productOptions = computed(() => products.value.map((p) => p.product_code))
const allPassed = computed(() => preflight.value?.ok === true)

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
  try {
    preflight.value = await api.preflight(selectedCodes.value)
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

onMounted(loadProducts)
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="素材检查"
      desc="上架前检查图片、Excel、SKU 是否齐全。这一步不会打开浏览器，也不消耗拼多多账号。"
    />

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 16px" @close="error = ''" />

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="never" class="stat-card">
          <template #header>
            <div class="card-head">
              <span>选择要检查的商品</span>
              <el-button link type="primary" @click="selectAll">全选</el-button>
            </div>
          </template>

          <el-empty v-if="!products.length" description="素材文件夹里还没有商品">
            <div class="form-tip">请把商品素材放到 data/assets 目录下</div>
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

      <el-col :span="14">
        <el-card v-if="preflight" shadow="never" class="stat-card">
          <template #header>
            <div class="card-head">
              <span>检查结果</span>
              <el-tag :type="preflight.ok ? 'success' : 'danger'" effect="dark" size="large">
                {{ preflight.ok ? '✓ 可以上架' : '✗ 有问题需处理' }}
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
            <el-table :data="preflight.units" size="small" stripe max-height="320">
              <el-table-column prop="listing_label" label="商品/套图" width="180" />
              <el-table-column prop="sku_count" label="SKU数" width="72" />
              <el-table-column prop="carousel_count" label="主图" width="60" />
              <el-table-column prop="detail_count" label="详情图" width="72" />
              <el-table-column prop="merchant_code" label="货号" />
            </el-table>
          </div>
        </el-card>

        <el-empty v-else description="勾选商品后点击「开始检查」" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.code-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.code-row {
  border: 1px solid var(--border-color);
  border-radius: 10px;
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

.mini-stat {
  text-align: center;
  padding: 12px;
  background: #f8fafc;
  border-radius: 10px;
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
</style>
