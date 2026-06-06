<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { MagicStick } from '@element-plus/icons-vue'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { agentLabel, runStatusLabel, runStatusType } from '@/utils/labels'
import type { RunRecord } from '@/types'

const route = useRoute()
const loading = ref(false)
const runs = ref<RunRecord[]>([])
const selected = ref<RunRecord | null>(null)
const error = ref('')

const llmConfigured = ref(false)
const interpreting = ref(false)
const interpretError = ref('')
const interpretation = ref('')
const interpretRunId = ref('')

interface InterpretSection {
  title: string
  body: string
}

const interpretSections = computed<InterpretSection[]>(() => {
  if (!interpretation.value) return []
  return interpretation.value
    .split(/^## /m)
    .filter(Boolean)
    .map((block) => {
      const lines = block.trim().split('\n')
      const title = lines[0]?.trim() || '解读'
      const body = lines.slice(1).join('\n').trim()
      return { title, body }
    })
})

const severitySection = computed(() =>
  interpretSections.value.find((s) => s.title.includes('严重程度')),
)

const severityLevel = computed(() => {
  const body = severitySection.value?.body || ''
  if (body.includes('需联系技术')) return 'danger'
  if (body.includes('需重试')) return 'warning'
  if (body.includes('可自行处理')) return 'warning'
  return 'success'
})

async function loadRuns() {
  loading.value = true
  error.value = ''
  try {
    runs.value = await api.runs(50)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  try {
    const summary = await api.configSummary()
    llmConfigured.value = summary.llm_configured
  } catch {
    llmConfigured.value = false
  }
}

async function selectRun(runId: string) {
  loading.value = true
  interpretError.value = ''
  if (interpretRunId.value !== runId) {
    interpretation.value = ''
    interpretRunId.value = ''
  }
  try {
    selected.value = await api.run(runId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载详情失败'
  } finally {
    loading.value = false
  }
}

async function runInterpret() {
  if (!selected.value) return
  interpreting.value = true
  interpretError.value = ''
  try {
    const resp = await api.interpretRun(selected.value.run_id)
    interpretation.value = resp.interpretation
    interpretRunId.value = resp.run_id
  } catch (e) {
    interpretError.value = e instanceof Error ? e.message : 'AI 解读失败'
  } finally {
    interpreting.value = false
  }
}

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

function resultRows(record: RunRecord) {
  const results = record.result?.results
  if (!Array.isArray(results)) return []
  return results.filter((r) => r && typeof r === 'object')
}

function formatBody(text: string) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br/>')
}

watch(
  () => route.query.id,
  (id) => {
    if (typeof id === 'string') selectRun(id)
  },
  { immediate: true },
)

onMounted(() => {
  loadRuns()
  loadMeta()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="操作记录" desc="查看历史上架、下架任务的执行结果；看不懂报错时可点「AI 解读」">
      <template #actions>
        <el-button @click="loadRuns">刷新</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 16px" @close="error = ''" />

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never" class="stat-card">
          <el-table
            :data="runs"
            stripe
            highlight-current-row
            @row-click="(row: RunRecord) => selectRun(row.run_id)"
          >
            <el-table-column label="操作类型" width="100">
              <template #default="{ row }">
                {{ agentLabel[row.agent] || row.agent }}
              </template>
            </el-table-column>
            <el-table-column prop="account_id" label="店铺" width="100" />
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
          </el-table>
          <el-empty v-if="!runs.length" description="还没有操作记录" />
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card v-if="selected" shadow="never" class="stat-card">
          <template #header>记录详情</template>

          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="操作类型">
              {{ agentLabel[selected.agent] || selected.agent }}
            </el-descriptions-item>
            <el-descriptions-item label="店铺">{{ selected.account_id }}</el-descriptions-item>
            <el-descriptions-item label="结果">
              <el-tag :type="(runStatusType[selected.status] as any) || 'info'" size="small">
                {{ runStatusLabel[selected.status] || selected.status }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="开始时间">{{ formatTime(selected.started_at) }}</el-descriptions-item>
            <el-descriptions-item label="结束时间">{{ formatTime(selected.finished_at) }}</el-descriptions-item>
          </el-descriptions>

          <div v-if="selected.listing_labels.length" style="margin-top: 14px">
            <div class="section-label">涉及商品</div>
            <el-tag v-for="l in selected.listing_labels" :key="l" size="small" style="margin: 0 4px 4px 0">
              {{ l }}
            </el-tag>
          </div>

          <el-table
            v-if="resultRows(selected).length"
            :data="resultRows(selected)"
            size="small"
            stripe
            style="margin-top: 14px"
          >
            <el-table-column
              v-if="resultRows(selected)[0]?.listing_label"
              prop="listing_label"
              label="商品"
            />
            <el-table-column v-if="resultRows(selected)[0]?.status" prop="status" label="状态" width="90" />
            <el-table-column v-if="resultRows(selected)[0]?.error" prop="error" label="报错" show-overflow-tooltip />
            <el-table-column v-if="resultRows(selected)[0]?.hit !== undefined" prop="hit" label="命中" width="60" />
            <el-table-column v-if="resultRows(selected)[0]?.scanned !== undefined" prop="scanned" label="扫描" width="60" />
          </el-table>

          <el-collapse v-if="Object.keys(selected.result || {}).length" style="margin-top: 14px">
            <el-collapse-item title="技术详情（开发用）" name="tech">
              <pre class="json-block">{{ JSON.stringify(selected.result, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>

          <!-- AI 解读 -->
          <div class="ai-interpret">
            <div class="ai-head">
              <div class="ai-title">
                <el-icon><MagicStick /></el-icon>
                <span>AI 解读</span>
              </div>
              <el-button
                type="primary"
                :icon="MagicStick"
                :loading="interpreting"
                :disabled="!llmConfigured"
                @click="runInterpret"
              >
                {{ interpretation && interpretRunId === selected.run_id ? '重新解读' : '帮我解读' }}
              </el-button>
            </div>

            <el-alert
              v-if="!llmConfigured"
              type="warning"
              :closable="false"
              show-icon
              title="未配置 AI"
              description="请在 myTest/.env 中填写 LLM_API_KEY 后重启后台，即可使用解读功能。"
              style="margin-top: 12px"
            />

            <el-alert
              v-if="interpretError"
              type="error"
              :title="interpretError"
              show-icon
              closable
              style="margin-top: 12px"
              @close="interpretError = ''"
            />

            <div v-if="interpretation && interpretRunId === selected.run_id" v-loading="interpreting" class="ai-body">
              <el-alert
                v-if="severitySection"
                :type="severityLevel as any"
                :closable="false"
                show-icon
                style="margin-bottom: 12px"
              >
                <template #title>{{ severitySection.title }}</template>
                <template #default>{{ severitySection.body }}</template>
              </el-alert>

              <div
                v-for="sec in interpretSections.filter((s) => !s.title.includes('严重程度'))"
                :key="sec.title"
                class="ai-section"
              >
                <div class="ai-section-title">{{ sec.title }}</div>
                <div class="ai-section-body" v-html="formatBody(sec.body)" />
              </div>
            </div>

            <div v-else-if="llmConfigured && !interpreting" class="ai-placeholder">
              点击「帮我解读」，AI 会用大白话说明这次任务为什么失败、你可以先做什么。
            </div>
          </div>
        </el-card>
        <el-empty v-else description="点击左侧某条记录查看详情" />
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.section-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
  color: #475569;
}

.ai-interpret {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--border-color);
}

.ai-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.ai-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 15px;
  color: #0f172a;
}

.ai-title .el-icon {
  color: var(--brand);
}

.ai-placeholder {
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
  padding: 12px;
  background: var(--brand-light);
  border-radius: 10px;
  border: 1px solid #ffe0d0;
}

.ai-body {
  margin-top: 12px;
}

.ai-section {
  margin-bottom: 12px;
  padding: 12px 14px;
  background: #fafbfc;
  border: 1px solid var(--border-color);
  border-radius: 10px;
}

.ai-section-title {
  font-weight: 600;
  font-size: 13px;
  color: #c2410c;
  margin-bottom: 6px;
}

.ai-section-body {
  font-size: 13px;
  line-height: 1.65;
  color: #334155;
}
</style>
