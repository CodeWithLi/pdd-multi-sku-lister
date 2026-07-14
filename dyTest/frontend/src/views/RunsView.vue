<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { agentLabel, listingStatusLabel, runStatusLabel, runStatusType } from '@/utils/labels'
import type { Account, RunRecord } from '@/types'

const route = useRoute()
const loading = ref(false)
const runs = ref<RunRecord[]>([])
const total = ref(0)
const selected = ref<RunRecord | null>(null)
const error = ref('')
const accounts = ref<Account[]>([])

const filters = reactive({
  account_id: '',
  status: '',
})

async function loadRuns() {
  loading.value = true
  error.value = ''
  try {
    const resp = await api.runs({
      limit: 100,
      account_id: filters.account_id || undefined,
      status: filters.status || undefined,
    })
    runs.value = resp.items
    total.value = resp.total
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function selectRun(runId: string) {
  loading.value = true
  try {
    selected.value = await api.run(runId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载详情失败'
  } finally {
    loading.value = false
  }
}

function formatTime(t: string | null | undefined) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function resultRows(record: RunRecord) {
  const results = record.result?.results
  if (!Array.isArray(results)) return []
  return results.filter((r) => r && typeof r === 'object')
}

function listingStatusType(status: string) {
  if (status === 'success' || status === 'step1_done' || status === 'step2_done' || status === 'step3_done' || status === 'step4_done' || status === 'step5_done') return 'success'
  if (status === 'failed') return 'danger'
  return 'info'
}

watch(
  () => route.query.id,
  (id) => {
    if (typeof id === 'string') selectRun(id)
  },
  { immediate: true },
)

onMounted(async () => {
  try {
    accounts.value = await api.accounts(true)
  } catch {
    /* ignore */
  }
  loadRuns()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="操作记录" desc="查看上架任务执行状态与结果。">
      <template #actions>
        <el-button @click="loadRuns">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 16px" @close="error = ''" />

    <el-card shadow="never" class="stat-card filter-card">
      <el-form inline>
        <el-form-item label="店铺">
          <el-select v-model="filters.account_id" clearable filterable style="width: 160px" @change="loadRuns">
            <el-option v-for="a in accounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable style="width: 140px" @change="loadRuns">
            <el-option label="进行中" value="running" />
            <el-option label="成功" value="success" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never" class="stat-card">
          <el-table :data="runs" stripe highlight-current-row @row-click="(row: RunRecord) => selectRun(row.run_id)">
            <el-table-column label="类型" width="100">
              <template #default="{ row }">{{ agentLabel[row.agent] || row.agent }}</template>
            </el-table-column>
            <el-table-column prop="account_id" label="店铺" width="110" />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag :type="(runStatusType[row.status] as any) || 'info'" size="small">
                  {{ runStatusLabel[row.status] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="开始时间" min-width="160">
              <template #default="{ row }">{{ formatTime(row.started_at) }}</template>
            </el-table-column>
            <el-table-column prop="message" label="说明" min-width="180" show-overflow-tooltip />
          </el-table>
          <el-empty v-if="!runs.length" description="暂无记录" />
          <div v-if="total" class="muted" style="margin-top: 12px">共 {{ total }} 条</div>
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card v-if="selected" shadow="never" class="stat-card">
          <template #header>记录详情</template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="类型">{{ agentLabel[selected.agent] || selected.agent }}</el-descriptions-item>
            <el-descriptions-item label="店铺">{{ selected.account_id }}</el-descriptions-item>
            <el-descriptions-item label="结果">
              <el-tag :type="(runStatusType[selected.status] as any) || 'info'" size="small">
                {{ runStatusLabel[selected.status] || selected.status }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="开始">{{ formatTime(selected.started_at) }}</el-descriptions-item>
            <el-descriptions-item label="结束">{{ formatTime(selected.finished_at) }}</el-descriptions-item>
            <el-descriptions-item label="说明">{{ selected.message || '-' }}</el-descriptions-item>
          </el-descriptions>

          <div v-if="selected.listing_labels.length" style="margin-top: 14px">
            <div class="section-label">涉及商品</div>
            <el-tag v-for="l in selected.listing_labels" :key="l" size="small" style="margin: 0 4px 4px 0">{{ l }}</el-tag>
          </div>

          <el-table v-if="resultRows(selected).length" :data="resultRows(selected)" size="small" stripe style="margin-top: 14px">
            <el-table-column prop="listing_label" label="商品" />
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="listingStatusType(row.status as string) as any" size="small">
                  {{ listingStatusLabel[row.status as string] || row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="说明" show-overflow-tooltip />
          </el-table>

          <el-collapse v-if="Object.keys(selected.result || {}).length" style="margin-top: 14px">
            <el-collapse-item title="技术详情" name="tech">
              <pre class="json-block">{{ JSON.stringify(selected.result, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </el-card>
        <el-empty v-else description="点击左侧记录查看详情" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.filter-card { margin-bottom: 16px; }
.section-label { font-size: 13px; font-weight: 600; margin-bottom: 6px; color: #475569; }
</style>
