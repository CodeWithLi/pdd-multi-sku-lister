<script setup lang="ts">
import { computed } from 'vue'
import { listingStatusLabel, runStatusLabel, runStatusType } from '@/utils/labels'
import {
  extractActivityRegistrationSummary,
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
  expanded?: boolean
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

const registrationSummary = computed(() => extractActivityRegistrationSummary(props.result))

const registrationTagType = computed(() => {
  const type = registrationSummary.value?.headline_type
  if (type === 'success') return 'success'
  if (type === 'warning') return 'warning'
  if (type === 'danger') return 'danger'
  return 'info'
})

const productOutcomeTagType = (outcome: string) => {
  if (outcome === 'submitted') return 'success'
  if (outcome === 'blocked') return 'warning'
  if (outcome === 'removed' || outcome === 'not_submitted') return 'danger'
  return 'info'
}

const priceCheckSummary = computed(() => {
  const rows = specLookupRows.value
  if (!rows.length) return null
  const passed = rows.filter((row) => row.valid === true && !row.should_remove).length
  const failed = rows.filter((row) => row.should_remove || row.valid === false).length
  const matched = rows.filter((row) => row.spec_code).length
  return { total: rows.length, matched, passed, failed }
})

const isFailed = computed(() => props.status === 'failed' || props.status === 'cancelled')

const campaignStep = computed(() => {
  const results = props.result?.results
  if (!Array.isArray(results) || !results[0] || typeof results[0] !== 'object') return ''
  return String((results[0] as Record<string, unknown>).step || '')
})

/** 任务标 success 但只做了规格反查/价格页准备，未点「确认提交」。 */
const isPartialCampaignSuccess = computed(
  () => props.status === 'success' && campaignStep.value === 'price_page_prepared',
)

const displayStatusLabel = computed(() => {
  if (isPartialCampaignSuccess.value) return '未完成提交'
  if (props.status) return runStatusLabel[props.status] || props.status
  return ''
})

const displayStatusType = computed(() => {
  if (isPartialCampaignSuccess.value) return 'warning'
  if (props.status) return (runStatusType[props.status] as string) || 'info'
  return 'info'
})

const messageLines = computed(() => {
  const msg = String(props.message || '').trim()
  if (!msg) return []
  return msg.split('\n').map((line) => line.trim()).filter(Boolean)
})

const resultAlertTitle = computed(() => {
  const lines = messageLines.value
  if (!lines.length) return isFailed.value ? '报名未完成' : '执行说明'
  const first = lines[0]
  if (first.length <= 36) return first
  return isFailed.value ? '价格校验未通过' : '执行说明'
})

const resultAlertBody = computed(() => {
  const lines = messageLines.value
  if (!lines.length) return ''
  if (lines.length === 1 && lines[0].length > 36) return lines[0]
  return lines.slice(1).join('\n') || lines[0]
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
  <div
    class="result-summary"
    :class="{ 'result-summary--failed': isFailed, 'result-summary--expanded': expanded }"
  >
    <div class="result-head">
      <span class="result-title">执行结果</span>
      <el-tag v-if="displayStatusLabel" :type="displayStatusType as any" size="small">
        {{ displayStatusLabel }}
      </el-tag>
    </div>

    <div v-if="registrationSummary?.visible" class="registration-summary">
      <el-alert
        :type="registrationTagType"
        :closable="false"
        show-icon
        class="registration-alert"
      >
        <template #title>{{ registrationSummary.headline }}</template>
        <div class="registration-alert-body">
          <div class="registration-stats">
            <span>选品 {{ registrationSummary.selected_count }} 个</span>
            <span>已提交 {{ registrationSummary.submitted_count }} 个</span>
            <span v-if="registrationSummary.blocked_count">待核对 {{ registrationSummary.blocked_count }} 个</span>
            <span v-if="registrationSummary.removed_count">未报名 {{ registrationSummary.removed_count }} 个</span>
            <span v-if="registrationSummary.spec_total">
              规格 {{ registrationSummary.spec_passed }}/{{ registrationSummary.spec_total }} 合格
            </span>
          </div>
          <p v-for="(note, index) in registrationSummary.notes" :key="index" class="registration-note">
            {{ note }}
          </p>
        </div>
      </el-alert>

      <div v-if="registrationSummary.products.length" class="table-scroll registration-product-table">
        <el-table :data="registrationSummary.products" size="small" stripe class="result-table">
          <el-table-column prop="pdd_product_id" label="拼多多商品ID" width="140" />
          <el-table-column prop="product_code" label="识别编码" width="110" />
          <el-table-column label="报名结果" width="120">
            <template #default="{ row }">
              <el-tag size="small" :type="productOutcomeTagType(row.outcome)" effect="plain">
                {{ row.outcome_label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="规格" width="120">
            <template #default="{ row }">
              {{ row.passed_specs }}/{{ row.total_specs || '—' }} 合格
            </template>
          </el-table-column>
          <el-table-column prop="detail" label="说明" min-width="220" show-overflow-tooltip />
        </el-table>
      </div>
    </div>

    <el-alert
      v-if="message && isFailed"
      class="result-alert"
      type="error"
      :closable="false"
      show-icon
    >
      <template #title>{{ resultAlertTitle }}</template>
      <div class="result-alert-body">{{ resultAlertBody }}</div>
    </el-alert>
    <p v-else-if="message && !registrationSummary?.visible" class="result-msg">{{ message }}</p>

    <div v-if="removedSpecRows.length" class="spec-lookup-block removed-spec-block">
      <div class="spec-lookup-head">
        <span class="spec-lookup-title">不符合条件 / 已删除规格</span>
        <el-tag size="small" type="danger" effect="plain">
          {{ removedSpecRows.length }} 条需处理
        </el-tag>
      </div>
      <p class="spec-lookup-hint">以下 SKU 价格不合格或缺少控价数据。请按底价调高活动价，或补全控价表后重新报名。</p>
      <div class="table-scroll">
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
    </div>

    <div v-if="specLookupRows.length" class="spec-lookup-block spec-lookup-block--full">
      <div class="spec-lookup-head">
        <span class="spec-lookup-title">价格确认页规格（完整名称）</span>
        <div class="spec-lookup-tags">
          <el-tag size="small" type="info" effect="plain">
            编码 {{ priceCheckSummary?.matched ?? 0 }}/{{ priceCheckSummary?.total ?? specLookupRows.length }}
          </el-tag>
          <el-tag
            v-if="priceCheckSummary && priceCheckSummary.failed > 0"
            size="small"
            type="danger"
            effect="plain"
          >
            价格 {{ priceCheckSummary.passed }} 通过 / {{ priceCheckSummary.failed }} 不合格
          </el-tag>
          <el-tag
            v-else-if="priceCheckSummary"
            size="small"
            type="success"
            effect="plain"
          >
            价格 {{ priceCheckSummary.passed }} 条全部通过
          </el-tag>
        </div>
      </div>
      <p class="spec-lookup-hint">
        「编码」= 是否反查到规格编码；「价格」= 活动价是否高于底价。两者独立，编码 OK 不代表价格合格。
      </p>
      <div class="table-scroll">
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
          v-if="specLookupRows.some((row) => row.valid != null || row.should_remove)"
          label="价格"
          width="80"
          align="center"
        >
          <template #default="{ row }">
            <el-tag
              v-if="row.should_remove || row.valid === false"
              size="small"
              type="danger"
              effect="plain"
            >
              不合格
            </el-tag>
            <el-tag
              v-else-if="row.valid === true"
              size="small"
              type="success"
              effect="plain"
            >
              通过
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="编码" width="72" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.spec_code ? 'success' : 'danger'" effect="plain">
              {{ row.spec_code ? 'OK' : '—' }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </div>

    <el-table v-if="campaignStepRows.length" :data="campaignStepRows" size="small" stripe class="result-table step-table">
      <el-table-column prop="step" label="步骤" min-width="140" show-overflow-tooltip />
      <el-table-column label="状态" width="88">
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'success' ? 'success' : 'danger'"
            size="small"
          >
            {{ row.status || row.reason || '-' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="说明" min-width="160" show-overflow-tooltip>
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
  padding: 14px 16px 16px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid var(--border-color);
  border-radius: 12px;
}

.result-summary--failed {
  border-color: rgba(245, 108, 108, 0.35);
  background: linear-gradient(180deg, rgba(254, 240, 240, 0.45) 0%, rgba(255, 255, 255, 0.95) 120px);
}

.result-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.result-title {
  font-weight: 600;
  font-size: 15px;
}

.registration-summary {
  margin-bottom: 14px;
}

.registration-alert {
  margin-bottom: 10px;
}

.registration-alert-body {
  margin-top: 4px;
}

.registration-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.registration-note {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-secondary);
}

.registration-product-table {
  margin-bottom: 0;
}

.result-alert {
  margin-bottom: 12px;
}

.result-alert :deep(.el-alert__content) {
  min-width: 0;
  width: 100%;
}

.result-alert-body {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
  font-size: 13px;
  margin-top: 4px;
}

.result-msg {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0 0 12px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
}

.result-table,
.delist-stats {
  margin-bottom: 12px;
}

.step-table {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--border-color);
}

.table-scroll {
  overflow-x: auto;
  margin-bottom: 12px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
}

.table-scroll .result-table {
  margin-bottom: 0;
  min-width: 640px;
}

.result-summary--expanded .table-scroll {
  overflow-x: visible;
}

.result-summary--expanded .table-scroll .result-table {
  min-width: 0;
  width: 100%;
}

.result-summary--expanded .spec-lookup-head {
  flex-wrap: nowrap;
}

.result-summary--expanded .spec-lookup-title {
  font-size: 15px;
}

.result-summary--expanded .spec-name-full,
.result-summary--expanded .reason-text {
  font-size: 14px;
}

.spec-lookup-block {
  margin-bottom: 12px;
}

.spec-lookup-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  gap: 8px;
  flex-wrap: wrap;
}

.spec-lookup-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
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
  margin-top: 12px;
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
