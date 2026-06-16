<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { Account, PipelineIssueReport } from '@/types'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const error = ref('')
const items = ref<PipelineIssueReport[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(25)
const accounts = ref<Account[]>([])
const detailVisible = ref(false)
const detailRow = ref<PipelineIssueReport | null>(null)

const filters = reactive({
  account_id: '',
  pipeline_id: '',
  batch_id: '',
  stage: '',
  severity: '',
  keyword: '',
})

const stageOptions = [
  { value: '', label: '全部阶段' },
  { value: 'listing', label: '上架' },
  { value: 'campaign', label: '活动报名' },
  { value: 'traffic', label: '推广' },
  { value: 'orchestration', label: '链路编排' },
  { value: 'scheduling', label: '任务调度' },
]

const severityOptions = [
  { value: '', label: '全部级别' },
  { value: 'critical', label: '严重' },
  { value: 'error', label: '错误' },
  { value: 'warning', label: '警告' },
]

const errorCount = computed(() => items.value.filter((i) => i.severity === 'error' || i.severity === 'critical').length)

function severityType(severity: string) {
  if (severity === 'critical') return 'danger'
  if (severity === 'error') return 'danger'
  if (severity === 'warning') return 'warning'
  return 'info'
}

function severityLabel(severity: string) {
  const map: Record<string, string> = {
    critical: '严重',
    error: '错误',
    warning: '警告',
  }
  return map[severity] || severity
}

function formatTime(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN')
}

function openDetail(row: PipelineIssueReport) {
  detailRow.value = row
  detailVisible.value = true
}

function goPipeline(pipelineId: string) {
  router.push({ path: '/pipeline', query: { pipeline_id: pipelineId } })
}

function goRun(runId: string) {
  if (!runId) return
  router.push({ path: '/runs', query: { run_id: runId } })
}

async function loadAccounts() {
  try {
    accounts.value = await api.accounts(true)
  } catch {
    accounts.value = []
  }
}

async function loadIssues() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.pipelineIssues({
      page: page.value,
      page_size: pageSize.value,
      account_id: filters.account_id || undefined,
      pipeline_id: filters.pipeline_id || undefined,
      batch_id: filters.batch_id || undefined,
      stage: filters.stage || undefined,
      severity: filters.severity || undefined,
      keyword: filters.keyword || undefined,
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  loadIssues()
}

function onPageChange(p: number) {
  page.value = p
  loadIssues()
}

onMounted(async () => {
  const q = route.query
  if (typeof q.pipeline_id === 'string') filters.pipeline_id = q.pipeline_id
  if (typeof q.batch_id === 'string') filters.batch_id = q.batch_id
  await loadAccounts()
  await loadIssues()
})
</script>

<template>
  <div class="page">
    <PageHeader
      title="链路报错"
      subtitle="整合链路专用报错监控：上架 / 活动 / 推广 / 编排全链路问题一目了然（独立于操作记录与失败项工作台）"
    />

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="tip"
      title="说明"
      description="此处只记录整合链路运行中的异常与阻断点，例如 SKU 编码找不到、预览图异常、浏览器断开、活动报名失败等。与普通任务日志、上架失败工作台完全分离。"
    />

    <el-card shadow="never" class="stat-card filter-card">
      <el-form :inline="true" class="filter-form" @submit.prevent="onSearch">
        <el-form-item label="店铺">
          <el-select v-model="filters.account_id" clearable placeholder="全部" style="width: 140px">
            <el-option v-for="a in accounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="链路 ID">
          <el-input v-model="filters.pipeline_id" clearable placeholder="pipeline_id" style="width: 200px" />
        </el-form-item>
        <el-form-item label="批次">
          <el-input v-model="filters.batch_id" clearable placeholder="batch_id" style="width: 180px" />
        </el-form-item>
        <el-form-item label="阶段">
          <el-select v-model="filters.stage" style="width: 130px">
            <el-option v-for="opt in stageOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="级别">
          <el-select v-model="filters.severity" style="width: 120px">
            <el-option v-for="opt in severityOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词">
          <el-input v-model="filters.keyword" clearable placeholder="标题/错误/商品" style="width: 180px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="onSearch">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="msg" />

    <el-card shadow="never" class="stat-card" v-loading="loading">
      <template #header>
        <div class="card-head">
          <span>报错列表（{{ total }}）</span>
          <el-tag v-if="errorCount" type="danger" size="small">本页严重/错误 {{ errorCount }}</el-tag>
        </div>
      </template>

      <el-table :data="items" stripe empty-text="暂无整合链路报错">
        <el-table-column prop="created_at" label="时间" width="168">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="severity" label="级别" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="severityType(row.severity)">{{ severityLabel(row.severity) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="stage_label" label="阶段" width="96" />
        <el-table-column prop="title" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="message" label="说明" min-width="260" show-overflow-tooltip />
        <el-table-column prop="account_id" label="店铺" width="100" />
        <el-table-column prop="product_selector" label="商品/套图" min-width="160" show-overflow-tooltip />
        <el-table-column prop="pipeline_id" label="链路" min-width="150" show-overflow-tooltip />
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            <el-button link type="primary" size="small" @click="goPipeline(row.pipeline_id)">链路</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="onPageChange"
        />
      </div>
    </el-card>

    <el-drawer v-model="detailVisible" title="报错详情" size="520px">
      <template v-if="detailRow">
        <div class="detail-block">
          <el-tag :type="severityType(detailRow.severity)" size="large">{{ severityLabel(detailRow.severity) }}</el-tag>
          <h3 class="detail-title">{{ detailRow.title }}</h3>
          <p class="detail-message">{{ detailRow.message }}</p>
        </div>

        <el-descriptions :column="1" border size="small" class="detail-desc">
          <el-descriptions-item label="阶段">{{ detailRow.stage_label || detailRow.stage }}</el-descriptions-item>
          <el-descriptions-item label="链路步骤">{{ detailRow.chain_step || '—' }}</el-descriptions-item>
          <el-descriptions-item label="原因码">{{ detailRow.reason_code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="店铺">{{ detailRow.account_id }}</el-descriptions-item>
          <el-descriptions-item label="商品/套图">{{ detailRow.product_selector || '—' }}</el-descriptions-item>
          <el-descriptions-item label="活动 ID">{{ detailRow.activity_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="链路 ID">{{ detailRow.pipeline_id }}</el-descriptions-item>
          <el-descriptions-item label="批次">{{ detailRow.batch_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="任务 run_id">
            <el-button v-if="detailRow.run_id" link type="primary" @click="goRun(detailRow.run_id)">
              {{ detailRow.run_id }}
            </el-button>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="记录位置">{{ detailRow.source_location || '—' }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ formatTime(detailRow.created_at) }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="detailRow.error_text" class="detail-section">
          <div class="section-label">完整错误</div>
          <pre class="error-pre">{{ detailRow.error_text }}</pre>
        </div>

        <div v-if="Object.keys(detailRow.context || {}).length" class="detail-section">
          <div class="section-label">上下文</div>
          <pre class="context-pre">{{ JSON.stringify(detailRow.context, null, 2) }}</pre>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.tip {
  margin-bottom: 0;
}

.filter-card :deep(.el-card__body) {
  padding-bottom: 4px;
}

.filter-form {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 0;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.msg {
  margin: 0;
}

.detail-block {
  margin-bottom: 20px;
}

.detail-title {
  margin: 12px 0 8px;
  font-size: 18px;
  color: #0f172a;
}

.detail-message {
  margin: 0;
  color: #475569;
  line-height: 1.6;
  font-size: 14px;
}

.detail-desc {
  margin-bottom: 16px;
}

.detail-section {
  margin-top: 16px;
}

.section-label {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #64748b;
}

.error-pre,
.context-pre {
  margin: 0;
  padding: 12px 14px;
  border-radius: 8px;
  background: #fff5f5;
  border: 1px solid #fecaca;
  color: #991b1b;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
}

.context-pre {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #334155;
}
</style>
