<script setup lang="ts">
import { computed } from 'vue'
import { listingStatusLabel, runStatusLabel, runStatusType } from '@/utils/labels'
import {
  extractActivityRemovedSpecRows,
  extractActivitySpecLookupMeta,
  extractActivitySpecLookupRows,
  extractCampaignStepRows,
} from '@/utils/runMessage'

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

const campaignStepRows = computed(() => extractCampaignStepRows(props.result))

const specLookupRows = computed(() => extractActivitySpecLookupRows(props.result))

const removedSpecRows = computed(() => extractActivityRemovedSpecRows(props.result))

const specLookupMeta = computed(() => extractActivitySpecLookupMeta(props.result))

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

    <el-table v-if="campaignStepRows.length" :data="campaignStepRows" size="small" stripe class="result-table">
      <el-table-column prop="step" label="步骤" width="220" show-overflow-tooltip />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'success' ? 'success' : 'danger'"
            size="small"
          >
            {{ row.status || row.reason || '-' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="说明" min-width="280" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.error || row.reason || row.action || row.url || row.current_url || '-' }}
        </template>
      </el-table-column>
    </el-table>

    <el-table v-if="listingRows.length" :data="listingRows" size="small" stripe class="result-table">
      <el-table-column prop="listing_label" label="商品/套图" min-width="160" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'success' || row.status === 'listed' ? 'success' : row.status === 'failed' ? 'danger' : row.status === 'retryable' ? 'warning' : 'info'"
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

    <div v-if="removedSpecRows.length" class="spec-lookup-block removed-spec-block">
      <div class="spec-lookup-head">
        <span class="spec-lookup-title">不符合条件 / 已删除规格</span>
        <el-tag size="small" type="danger" effect="plain">
          {{ removedSpecRows.filter((row) => row.deleted !== false).length }}/{{ removedSpecRows.length }} 已删除
        </el-tag>
      </div>
      <p class="spec-lookup-hint">以下 SKU 因价格或定价数据问题被剔除，可按底价调整活动价后重新报名。</p>
      <el-table :data="removedSpecRows" size="small" stripe class="result-table spec-full-table">
        <el-table-column type="index" label="#" width="44" align="center" />
        <el-table-column prop="spec_code" label="规格编码" width="150">
          <template #default="{ row }">
            <div class="spec-code-ok">{{ row.spec_code || '—' }}</div>
            <div v-if="row.parent_code" class="spec-name-sub">
              母 {{ row.parent_code }}<span v-if="row.child_code"> + 子 {{ row.child_code }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="完整规格名称" min-width="260">
          <template #default="{ row }">
            <div class="spec-name-full">{{ row.spec_name || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="活动价" width="72" align="right">
          <template #default="{ row }">{{ row.activity_price }}</template>
        </el-table-column>
        <el-table-column label="底价" width="72" align="right">
          <template #default="{ row }">
            {{ row.floor_price != null ? row.floor_price : '—' }}
          </template>
        </el-table-column>
        <el-table-column label="定价/控价" width="110" align="right">
          <template #default="{ row }">
            <div v-if="row.pricing != null">母 {{ row.pricing }}</div>
            <div v-if="row.control_price != null">子 {{ row.control_price }}</div>
            <span v-if="row.pricing == null && row.control_price == null">—</span>
          </template>
        </el-table-column>
        <el-table-column label="原因" min-width="220">
          <template #default="{ row }">
            <div class="reason-text">{{ row.reason_text || row.reason || '—' }}</div>
            <div v-if="row.delete_error_text" class="spec-name-sub">删除失败：{{ row.delete_error_text }}</div>
          </template>
        </el-table-column>
        <el-table-column label="删除" width="80" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.deleted === false ? 'warning' : 'danger'"
              effect="plain"
            >
              {{ row.deleted === false ? '未删' : '已删' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="specLookupRows.length" class="spec-lookup-block spec-lookup-block--full">
      <div class="spec-lookup-head">
        <span class="spec-lookup-title">价格确认页规格（完整名称）</span>
        <el-tag size="small" type="success" effect="plain">
          {{ specLookupMeta?.matched_count ?? 0 }}/{{ specLookupMeta?.spec_count ?? specLookupRows.length }} 已匹配
        </el-tag>
      </div>
      <p class="spec-lookup-hint">展开后的完整规格名如下，便于与活动页逐条对比。</p>
      <el-table :data="specLookupRows" size="small" stripe class="result-table spec-full-table">
        <el-table-column type="index" label="#" width="44" align="center" />
        <el-table-column label="完整规格名称" min-width="320">
          <template #default="{ row }">
            <div class="spec-name-full">{{ row.spec_name || '—' }}</div>
            <div v-if="row.spec_combined && row.spec_combined !== row.spec_name" class="spec-name-sub">
              合并键：{{ row.spec_combined }}
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="activity_price" label="活动价" width="72" align="right" />
        <el-table-column
          v-if="specLookupRows.some((row) => row.floor_price != null)"
          label="底价"
          width="72"
          align="right"
        >
          <template #default="{ row }">
            {{ row.floor_price != null ? row.floor_price : '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="spec_code" label="规格编码" width="140">
          <template #default="{ row }">
            <span :class="row.spec_code ? 'spec-code-ok' : 'spec-code-miss'">
              {{ row.spec_code || '未匹配' }}
            </span>
            <div v-if="row.parent_code" class="spec-name-sub">
              母 {{ row.parent_code }}<span v-if="row.child_code"> + 子 {{ row.child_code }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column
          v-if="specLookupRows.some((row) => row.spec_name_source)"
          label="名称来源"
          width="100"
        >
          <template #default="{ row }">
            {{ row.spec_name_source || '—' }}
          </template>
        </el-table-column>
        <el-table-column
          v-if="specLookupRows.some((row) => row.valid != null)"
          label="价格"
          width="72"
          align="center"
        >
          <template #default="{ row }">
            <el-tag
              v-if="row.valid != null"
              size="small"
              :type="row.valid ? 'success' : 'danger'"
              effect="plain"
            >
              {{ row.valid ? '通过' : '偏低' }}
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="匹配" width="72" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.spec_code ? 'success' : 'danger'" effect="plain">
              {{ row.spec_code ? 'OK' : '—' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>

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

.spec-lookup-block {
  margin-bottom: 12px;
}

.spec-lookup-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.spec-lookup-title {
  font-weight: 600;
  font-size: 14px;
}

.spec-lookup-block--full {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--border-color);
}

.spec-lookup-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--text-muted);
}

.spec-full-table :deep(.el-table__cell) {
  vertical-align: top;
}

.spec-name-full {
  white-space: normal;
  word-break: break-word;
  line-height: 1.5;
  font-size: 13px;
}

.spec-name-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
  white-space: normal;
  word-break: break-word;
}

.spec-code-ok {
  font-weight: 600;
}

.spec-code-miss {
  color: var(--text-muted);
}

.removed-spec-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px dashed var(--el-color-danger-light-5);
}

.reason-text {
  white-space: normal;
  word-break: break-word;
  line-height: 1.45;
  font-size: 13px;
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
