<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { issueLevelLabel } from '@/utils/labels'
import type { ListingTargetOption, PreflightResponse } from '@/types'

const router = useRouter()
const loading = ref(false)
const productOptions = ref<ListingTargetOption[]>([])
const selectedCodes = ref<string[]>([])
const preflight = ref<PreflightResponse | null>(null)
const error = ref('')
const materialSource = ref<'local' | 'minio'>('minio')
const minioHealth = ref<{ available?: boolean; error?: string } | null>(null)

async function loadMinioHealth() {
  try {
    minioHealth.value = await api.minioHealth()
  } catch (e) {
    minioHealth.value = { available: false, error: e instanceof Error ? e.message : 'MinIO 不可用' }
  }
}

async function loadTargets() {
  loading.value = true
  try {
    productOptions.value = await api.listingTargets(materialSource.value)
    selectedCodes.value = selectedCodes.value.filter((code) =>
      productOptions.value.some((item) => item.selector === code),
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

async function onMaterialSourceChange(source: 'local' | 'minio') {
  materialSource.value = source
  selectedCodes.value = []
  if (source === 'minio') {
    await loadMinioHealth()
    if (!minioHealth.value?.available) {
      ElMessage.warning(minioHealth.value?.error || 'MinIO 未就绪，请检查 config/minio.yaml')
    }
  }
  await loadTargets()
}

async function runPreflight() {
  if (!selectedCodes.value.length) {
    ElMessage.warning('请至少选择一个商品/套图')
    return
  }
  loading.value = true
  error.value = ''
  preflight.value = null
  try {
    preflight.value = await api.preflight(selectedCodes.value, materialSource.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '检查失败'
  } finally {
    loading.value = false
  }
}

function selectAll() {
  selectedCodes.value = productOptions.value.map((item) => item.selector)
}

onMounted(async () => {
  await loadMinioHealth()
  await loadTargets()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="素材检查" desc="上架前检查主图、详情图、SKU 预览图是否齐全。">
      <template #actions>
        <el-button @click="loadTargets">刷新目录</el-button>
        <el-button type="primary" @click="router.push('/tasks')">去上架</el-button>
      </template>
    </PageHeader>

    <div class="section-tip">
      选择要检查的套图；MinIO 模式下会先同步图片到本地缓存再检查。
    </div>

    <el-card shadow="never" class="stat-card" style="margin-bottom: 16px">
      <el-form label-position="top">
        <div class="material-source-bar">
          <span class="material-source-label">素材来源</span>
          <el-radio-group
            :model-value="materialSource"
            size="small"
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
        </div>

        <el-form-item label="检查对象">
          <div class="select-actions">
            <el-button link type="primary" @click="selectAll">全选</el-button>
            <el-button link @click="selectedCodes = []">清空</el-button>
          </div>
          <el-select v-model="selectedCodes" multiple filterable style="width: 100%" placeholder="选择套图或商品">
            <el-option
              v-for="item in productOptions"
              :key="item.selector"
              :label="`${item.selector}（${item.product_count}个商品）`"
              :value="item.selector"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <el-button type="primary" @click="runPreflight">开始检查</el-button>
    </el-card>

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 16px" @close="error = ''" />

    <el-card v-if="preflight" shadow="never" class="stat-card">
      <template #header>
        <div class="card-head">
          <span>检查结果</span>
          <el-tag :type="preflight.issues?.some((i) => i.level === 'error') ? 'danger' : 'success'" size="small">
            {{ preflight.issues?.length ? `${preflight.issues.length} 项问题` : '通过' }}
          </el-tag>
        </div>
      </template>

      <el-table v-if="preflight.issues?.length" :data="preflight.issues" stripe>
        <el-table-column label="级别" width="90">
          <template #default="{ row }">
            <el-tag :type="row.level === 'error' ? 'danger' : 'warning'" size="small">
              {{ issueLevelLabel[row.level] || row.level }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="listing_label" label="商品" width="160" />
        <el-table-column prop="message" label="说明" min-width="280" show-overflow-tooltip />
      </el-table>
      <el-empty v-else description="未发现素材问题" />

      <el-collapse v-if="preflight.units?.length" style="margin-top: 16px">
        <el-collapse-item title="检查单元详情" name="units">
          <pre class="json-block">{{ JSON.stringify(preflight.units, null, 2) }}</pre>
        </el-collapse-item>
      </el-collapse>
    </el-card>
  </div>
</template>

<style scoped>
.card-head { display: flex; justify-content: space-between; align-items: center; }
.select-actions { margin-bottom: 8px; }
.material-source-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.material-source-label {
  font-size: 14px;
  color: var(--el-text-color-regular);
}
</style>
