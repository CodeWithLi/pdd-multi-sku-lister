<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { StyleColor } from '@/types'

const loading = ref(false)
const saving = ref(false)
const items = ref<StyleColor[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const error = ref('')

const filters = reactive({
  product_code: '',
  color_label: '',
  source: '',
})

const dialogVisible = ref(false)
const isEdit = ref(false)
const form = reactive({
  product_code: '',
  color_label: '',
  image_path: '',
})

const sourceOptions = [
  { label: '全部来源', value: '' },
  { label: 'AI识别', value: 'ai' },
  { label: '商品表', value: 'catalog' },
  { label: '人工维护', value: 'manual' },
]

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function sourceLabel(source: string) {
  const map: Record<string, string> = {
    ai: 'AI识别',
    catalog: '商品表',
    manual: '人工维护',
  }
  return map[source] || source || '-'
}

function sourceTagType(source: string) {
  if (source === 'manual') return 'success'
  if (source === 'ai') return 'primary'
  if (source === 'catalog') return 'info'
  return 'info'
}

function assetUrl(path: string) {
  if (!path) return ''
  return `/api/catalog/asset?path=${encodeURIComponent(path)}`
}

function fileName(path: string) {
  return path.split(/[\\/]/).pop() || path
}

function resetForm() {
  form.product_code = ''
  form.color_label = ''
  form.image_path = ''
}

async function loadStyleColors() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.styleColors({
      page: page.value,
      page_size: pageSize.value,
      product_code: filters.product_code || undefined,
      color_label: filters.color_label || undefined,
      source: filters.source || undefined,
    })
    items.value = resp.items
    total.value = resp.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载款式颜色失败'
  } finally {
    loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  loadStyleColors()
}

function resetFilters() {
  filters.product_code = ''
  filters.color_label = ''
  filters.source = ''
  applyFilters()
}

function onPageChange(next: number) {
  page.value = next
  loadStyleColors()
}

function onPageSizeChange(next: number) {
  pageSize.value = next
  page.value = 1
  loadStyleColors()
}

function openCreate() {
  isEdit.value = false
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: StyleColor) {
  isEdit.value = true
  form.product_code = row.product_code
  form.color_label = row.color_label
  form.image_path = row.image_path || ''
  dialogVisible.value = true
}

async function save() {
  const code = form.product_code.trim().toUpperCase()
  const label = form.color_label.trim()
  if (!code || !label) {
    ElMessage.warning('请填写商品编码和颜色')
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await api.updateStyleColor(code, {
        color_label: label,
        image_path: form.image_path.trim() || null,
      })
      ElMessage.success('已更新')
    } else {
      await api.createStyleColor({
        product_code: code,
        color_label: label,
        image_path: form.image_path.trim() || undefined,
      })
      ElMessage.success('已添加')
    }
    dialogVisible.value = false
    await loadStyleColors()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row: StyleColor) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.product_code} → ${row.color_label}」吗？删除后下次上架会重新 AI 识色。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await api.deleteStyleColor(row.product_code)
    ElMessage.success('已删除')
    if (items.value.length === 1 && page.value > 1) {
      page.value -= 1
    }
    await loadStyleColors()
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') {
      ElMessage.error(e instanceof Error ? e.message : '删除失败')
    }
  }
}

onMounted(loadStyleColors)
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="款式颜色"
      desc="管理商品编码对应的颜色缓存。上架时优先读取此处数据，可节省 AI Token；人工修改后不会被规格图变更覆盖。"
    >
      <template #actions>
        <el-button @click="loadStyleColors">刷新</el-button>
        <el-button type="primary" @click="openCreate">+ 新增颜色</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      style="margin-bottom: 16px"
      @close="error = ''"
    />

    <el-card shadow="never" class="stat-card filter-card">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :span="7">
            <el-form-item label="商品编码">
              <el-input
                v-model="filters.product_code"
                clearable
                placeholder="如 BD716A"
                @keyup.enter="applyFilters"
              />
            </el-form-item>
          </el-col>
          <el-col :span="7">
            <el-form-item label="颜色">
              <el-input
                v-model="filters.color_label"
                clearable
                placeholder="如 黑色、灰色"
                @keyup.enter="applyFilters"
              />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="来源">
              <el-select v-model="filters.source" clearable style="width: 100%">
                <el-option
                  v-for="opt in sourceOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
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
        <el-table-column prop="product_code" label="商品编码" width="120" />
        <el-table-column label="颜色" width="120">
          <template #default="{ row }">
            <el-tag effect="plain" size="small">{{ row.color_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <el-tag :type="sourceTagType(row.source)" size="small">
              {{ sourceLabel(row.source) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="规格图" min-width="220">
          <template #default="{ row }">
            <div v-if="row.image_path" class="image-cell">
              <div class="thumb-box">
                <img :src="assetUrl(row.image_path)" :alt="row.product_code" loading="lazy" />
              </div>
              <span class="muted path-text" :title="row.image_path">{{ fileName(row.image_path) }}</span>
            </div>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!items.length" description="暂无款式颜色记录" />

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

    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? `编辑颜色 · ${form.product_code}` : '新增款式颜色'"
      width="480px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item v-if="!isEdit" label="商品编码" required>
          <el-input v-model="form.product_code" placeholder="如 BD716A" />
        </el-form-item>
        <el-form-item label="颜色名称" required>
          <el-input v-model="form.color_label" placeholder="如 黑色、灰色、绿色" />
        </el-form-item>
        <el-form-item label="规格图路径（可选）">
          <el-input
            v-model="form.image_path"
            placeholder="本地图片绝对路径，留空则不关联图片"
          />
        </el-form-item>
        <div v-if="form.image_path" class="preview-box">
          <img :src="assetUrl(form.image_path)" alt="preview" loading="lazy" />
        </div>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
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

.pager {
  margin-top: 14px;
  justify-content: flex-end;
}

.muted {
  color: var(--text-secondary);
  font-size: 12px;
}

.image-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.thumb-box {
  width: 44px;
  height: 44px;
  flex-shrink: 0;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
  background: #f8fafc;
}

.thumb-box img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.path-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-box {
  width: 120px;
  height: 120px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
  background: #f8fafc;
}

.preview-box img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
</style>
