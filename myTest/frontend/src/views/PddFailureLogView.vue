<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { PddFailureLogListResponse, PddFailureLogRecord } from '@/types'

const loading = ref(false)
const error = ref('')
const data = ref<PddFailureLogListResponse | null>(null)
const showDebug = ref(false)
const selected = ref<PddFailureLogRecord | null>(null)
const limit = ref(100)

const items = computed(() => data.value?.items ?? [])

function processTagType(label: string, source: string) {
  if (source === 'empty') return 'info'
  if (!label || label === '未同步') return 'info'
  if (label.includes('完成') || label.includes('结束')) return 'success'
  if (label.includes('处理')) return 'warning'
  return 'primary'
}

function recordTypeTag(type: string) {
  if (type === '失败') return 'danger'
  if (type === '跳过') return 'warning'
  return 'info'
}

function sourceLabel(source: string) {
  const map: Record<string, string> = {
    mirror_text: '处理状态镜像',
    empty: '自动化尚未同步',
  }
  return map[source] || source
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.pddFailureLogs({ limit: limit.value })
    data.value = resp
    if (!resp.ok) {
      error.value = resp.error || '读取失败'
      return
    }
    if (!resp.items.length) {
      ElMessage.info('表内暂无记录')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取失败'
  } finally {
    loading.value = false
  }
}

function openDebug(row: PddFailureLogRecord) {
  selected.value = row
  showDebug.value = true
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page">
    <PageHeader
      title="发布失败日志"
      subtitle="从飞书多维表格读取失败记录，处理状态以「处理状态镜像」列为准"
    />

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      :closable="false"
      class="mb-16"
    />

    <el-card shadow="never" class="mb-16">
      <div class="toolbar">
        <div class="meta" v-if="data?.ok">
          <span>表：{{ data.table_name || '—' }}</span>
          <span>table_id：{{ data.table_id }}</span>
          <span v-if="data.mirror_field_name">状态列：{{ data.mirror_field_name }}</span>
          <span>共 {{ data.total }} 条</span>
        </div>
        <div class="actions">
          <el-input-number v-model="limit" :min="1" :max="500" :step="50" />
          <el-button type="primary" :loading="loading" @click="load">刷新</el-button>
        </div>
      </div>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="处理状态读取「处理状态镜像」列（由飞书自动化从流程字段同步）。若显示「未同步」，请在飞书里改一次流程或等待自动化执行。"
      />
    </el-card>

    <el-table v-loading="loading" :data="items" stripe border style="width: 100%">
      <el-table-column prop="date" label="日期" width="110" />
      <el-table-column prop="merchant_code" label="商品编码" width="140" show-overflow-tooltip />
      <el-table-column prop="report_platform" label="报错平台" width="90" />
      <el-table-column prop="account_name" label="店铺" width="120" show-overflow-tooltip />
      <el-table-column prop="record_type" label="记录类型" width="90">
        <template #default="{ row }">
          <el-tag :type="recordTypeTag(row.record_type)" size="small">{{ row.record_type || '—' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="failure_reason" label="失败原因" min-width="220" show-overflow-tooltip />
      <el-table-column label="处理状态" width="150">
        <template #default="{ row }">
          <el-tag :type="processTagType(row.process_completed.label, row.process_completed.source)" size="small">
            {{ row.process_completed.label || '—' }}
          </el-tag>
          <div class="sub">{{ sourceLabel(row.process_completed.source) }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="cycle_relist" label="是否循环上架" width="120" show-overflow-tooltip />
      <el-table-column prop="processor" label="人员" width="100" show-overflow-tooltip />
      <el-table-column prop="processed_at" label="处理时间" width="150" />
      <el-table-column prop="duration_seconds" label="耗时秒" width="90" />
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDebug(row)">原始数据</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-drawer v-model="showDebug" title="原始 fields 与处理状态" size="520px">
      <template v-if="selected">
        <h4>处理状态解析</h4>
        <pre class="json-block">{{ JSON.stringify(selected.process_completed, null, 2) }}</pre>
        <h4>飞书 fields 原始值</h4>
        <pre class="json-block">{{ JSON.stringify(selected.fields_raw, null, 2) }}</pre>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page {
  padding: 0 4px 24px;
}

.mb-16 {
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.json-block {
  background: #f6f8fa;
  border-radius: 6px;
  padding: 12px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
}

h4 {
  margin: 12px 0 8px;
  font-size: 14px;
}
</style>
