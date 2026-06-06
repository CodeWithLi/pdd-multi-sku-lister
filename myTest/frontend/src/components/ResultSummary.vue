<script setup lang="ts">
import { computed } from 'vue'
import { listingStatusLabel, runStatusLabel, runStatusType } from '@/utils/labels'

const props = defineProps<{
  status?: string
  message?: string
  runId?: string
  result?: Record<string, unknown>
}>()

const emit = defineEmits<{ viewDetail: [] }>()

const listingRows = computed(() => {
  const results = props.result?.results
  if (!Array.isArray(results)) return []
  return results.filter((r) => r && typeof r === 'object' && 'listing_label' in r)
})

const delistStats = computed(() => {
  const results = props.result?.results
  if (!Array.isArray(results) || !results[0]) return null
  const s = results[0] as Record<string, unknown>
  if ('scanned' in s) return s
  return null
})
</script>

<template>
  <div class="result-summary">
    <div class="result-head">
      <span class="result-title">执行结果</span>
      <el-tag v-if="status" :type="(runStatusType[status] as any) || 'info'" size="small">
        {{ runStatusLabel[status] || status }}
      </el-tag>
    </div>

    <p v-if="message" class="result-msg">{{ message }}</p>

    <el-table v-if="listingRows.length" :data="listingRows" size="small" stripe class="result-table">
      <el-table-column prop="listing_label" label="商品/套图" min-width="160" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'listed' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'"
            size="small"
          >
            {{ listingStatusLabel[row.status as string] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="error" label="说明" show-overflow-tooltip />
    </el-table>

    <el-descriptions v-if="delistStats" :column="2" size="small" border class="delist-stats">
      <el-descriptions-item label="扫描行数">{{ delistStats.scanned }}</el-descriptions-item>
      <el-descriptions-item label="命中/下架">
        {{ delistStats.hit }}
      </el-descriptions-item>
      <el-descriptions-item label="早于门槛跳过">{{ delistStats.skipped_old }}</el-descriptions-item>
      <el-descriptions-item label="扫描页数">{{ delistStats.pages }}</el-descriptions-item>
    </el-descriptions>

    <div v-if="runId" class="result-foot">
      <span class="run-id">任务编号：{{ runId.slice(0, 8) }}…</span>
      <el-button link type="primary" @click="emit('viewDetail')">查看完整记录 →</el-button>
    </div>

    <el-collapse v-if="result && Object.keys(result).length" class="tech-collapse">
      <el-collapse-item title="技术详情（开发用）" name="tech">
        <pre class="json-block">{{ JSON.stringify(result, null, 2) }}</pre>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.result-summary {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--border-color);
}

.result-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.result-title {
  font-weight: 600;
  font-size: 15px;
}

.result-msg {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 12px;
}

.result-table,
.delist-stats {
  margin-bottom: 12px;
}

.result-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
}

.run-id {
  font-size: 12px;
  color: var(--text-muted);
}

.tech-collapse {
  margin-top: 12px;
}
</style>
