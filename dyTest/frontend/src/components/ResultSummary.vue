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

const isFailed = computed(() => props.status === 'failed')
</script>

<template>
  <div class="result-summary" :class="{ 'result-summary--failed': isFailed }">
    <div class="result-head">
      <span class="result-title">执行结果</span>
      <el-tag v-if="status" :type="(runStatusType[status] as any) || 'info'" size="small">
        {{ runStatusLabel[status] || status }}
      </el-tag>
    </div>

    <p v-if="message" class="result-msg">{{ message }}</p>

    <el-table v-if="listingRows.length" :data="listingRows" size="small" stripe class="result-table">
      <el-table-column prop="listing_label" label="商品" min-width="160" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'step5_done' || row.status === 'step4_done' || row.status === 'step3_done' || row.status === 'step2_done' || row.status === 'step1_done' || row.status === 'success' ? 'success' : row.status === 'failed' ? 'danger' : 'info'"
            size="small"
          >
            {{ listingStatusLabel[row.status as string] || row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="message" label="说明" show-overflow-tooltip />
      <el-table-column prop="dy_product_id" label="商品ID" width="180" show-overflow-tooltip />
      <el-table-column prop="list_status" label="状态" width="90" />
      <el-table-column prop="listed_at" label="上架时间" width="160" show-overflow-tooltip />
      <el-table-column prop="error" label="报错" show-overflow-tooltip />
    </el-table>

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
  padding: 14px 16px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 12px;
}
.result-summary--failed {
  border-color: rgba(245, 108, 108, 0.35);
  background: linear-gradient(180deg, rgba(254, 240, 240, 0.45) 0%, #fff 120px);
}
.result-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.result-title { font-weight: 600; font-size: 15px; }
.result-msg { font-size: 13px; color: var(--text-secondary); margin: 0 0 12px; white-space: pre-wrap; }
.result-table { margin-bottom: 12px; }
.result-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
.run-id { font-size: 12px; color: var(--text-muted); }
.tech-collapse { margin-top: 12px; }
</style>
