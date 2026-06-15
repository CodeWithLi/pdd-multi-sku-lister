<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type {
  Account,
  IntegratedPipeline,
  ListingTargetOption,
  MarketingActivityOption,
} from '@/types'

const router = useRouter()
const loading = ref(false)
const polling = ref(false)
const error = ref('')
const success = ref('')

const accounts = ref<Account[]>([])
const productOptions = ref<ListingTargetOption[]>([])
const activities = ref<MarketingActivityOption[]>([])
const pipelines = ref<IntegratedPipeline[]>([])
const activePipeline = ref<IntegratedPipeline | null>(null)

const accountId = ref('')
const productCodes = ref<string[]>([])
const checkedProductsBySet = ref<Record<string, string[]>>({})
const activityId = ref('20981')
const categoryKeyword = ref('玩偶')
const autoPromotion = ref(true)
const demoMode = ref(true)
const activityDelayHours = ref(24)
const slotAlignmentTest = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))

const selectedSetGroups = computed(() =>
  productCodes.value
    .map((sel) => productOptions.value.find((item) => item.selector === sel))
    .filter((item): item is ListingTargetOption => !!item),
)

const resolvedListingSelectors = computed(() => {
  const result: string[] = []
  for (const group of selectedSetGroups.value) {
    const checked = checkedProductsBySet.value[group.selector] || []
    for (const code of checked) {
      if (group.product_codes.includes(code)) {
        result.push(`${group.selector}/${code}`)
      }
    }
  }
  return result
})

function syncCheckedProductsForSets(setSelectors: string[]) {
  const next: Record<string, string[]> = { ...checkedProductsBySet.value }
  for (const sel of setSelectors) {
    const opt = productOptions.value.find((item) => item.selector === sel)
    if (!opt) continue
    const prev = next[sel] || []
    const valid = prev.filter((code) => opt.product_codes.includes(code))
    next[sel] = valid.length ? valid : [...opt.product_codes]
  }
  for (const key of Object.keys(next)) {
    if (!setSelectors.includes(key)) delete next[key]
  }
  checkedProductsBySet.value = next
}

function updateCheckedProducts(selector: string, codes: string[]) {
  checkedProductsBySet.value = { ...checkedProductsBySet.value, [selector]: codes }
}

function stepTagType(status: string) {
  if (['success', 'completed', 'skipped'].includes(status)) return 'success'
  if (['running', 'scheduled', 'pending'].includes(status)) return 'warning'
  if (['failed', 'canceled'].includes(status)) return 'danger'
  return 'info'
}

function pipelineTagType(status: string) {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'waiting_activity') return 'warning'
  return 'info'
}

function formatTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

async function loadBaseData() {
  const [acc, targets, activityList] = await Promise.all([
    api.accounts(true),
    api.listingTargets(),
    api.campaignMarketingActivities(),
  ])
  accounts.value = acc
  productOptions.value = targets
  activities.value = activityList.items || []
  if (!accountId.value && enabledAccounts.value.length) {
    accountId.value = enabledAccounts.value[0].account_id
  }
  if (!activityId.value && activities.value.length) {
    activityId.value = activities.value[0].activity_id
  }
}

async function refreshPipelines() {
  const data = await api.listIntegratedPipelines(30)
  pipelines.value = data.items || []
  if (activePipeline.value) {
    const latest = pipelines.value.find((p) => p.pipeline_id === activePipeline.value?.pipeline_id)
    if (latest) activePipeline.value = latest
  }
}

async function startPipeline() {
  error.value = ''
  success.value = ''
  if (!accountId.value) {
    error.value = '请选择店铺'
    return
  }
  if (!resolvedListingSelectors.value.length) {
    error.value = '请至少选择一套图里的一个商品'
    return
  }
  if (!activityId.value) {
    error.value = '请选择活动'
    return
  }
  loading.value = true
  try {
    const result = await api.startIntegratedPipeline({
      account_id: accountId.value,
      product_codes: resolvedListingSelectors.value,
      activity_id: activityId.value,
      category_keyword: categoryKeyword.value,
      auto_promotion: autoPromotion.value,
      activity_delay_hours: demoMode.value ? 0 : activityDelayHours.value,
      demo_mode: demoMode.value,
      slot_alignment_test: slotAlignmentTest.value,
    })
    activePipeline.value = result
    success.value = demoMode.value
      ? `整合链路已启动（演示模式：约 2 分钟后自动报活动）`
      : `整合链路已启动（${activityDelayHours.value} 小时后自动报活动）`
    await refreshPipelines()
    startPolling()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function startPolling() {
  if (pollTimer) return
  polling.value = true
  pollTimer = setInterval(() => {
    refreshPipelines().catch(() => undefined)
  }, 5000)
}

function stopPolling() {
  polling.value = false
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function openRun(runId: string) {
  if (!runId) return
  router.push({ path: '/runs', query: { run_id: runId } })
}

watch(productCodes, (codes) => syncCheckedProductsForSets(codes), { deep: true })

onMounted(async () => {
  try {
    await loadBaseData()
    await refreshPipelines()
    startPolling()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

onUnmounted(stopPolling)
</script>

<template>
  <div class="page">
    <PageHeader
      title="整合链路"
      subtitle="一套图走完：上架 → 隔日自动报活动 → 活动成功后自动推广（Demo）"
    />

    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="tip"
      title="链路说明"
      description="选好店铺、一套图、活动后点一次即可。上架完成后系统会按设定时间自动报活动；活动成功后再自动创建推广。拼多多要求新上架商品通常隔 1 天才能报活动，正式使用请关闭演示模式并设 24 小时。"
    />

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never" class="card">
          <template #header>新建整合任务</template>

          <el-form label-width="108px">
            <el-form-item label="店铺">
              <el-select v-model="accountId" placeholder="选择店铺" style="width: 100%">
                <el-option
                  v-for="acc in enabledAccounts"
                  :key="acc.account_id"
                  :label="acc.account_id"
                  :value="acc.account_id"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="素材套图">
              <el-select
                v-model="productCodes"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择套图（如 BD720/第一套图）"
                style="width: 100%"
              >
                <el-option
                  v-for="opt in productOptions"
                  :key="opt.selector"
                  :label="`${opt.selector}（${opt.product_codes.length} 个商品）`"
                  :value="opt.selector"
                />
              </el-select>
            </el-form-item>

            <el-form-item v-if="selectedSetGroups.length" label="上架商品">
              <div class="product-picks">
                <div v-for="group in selectedSetGroups" :key="group.selector" class="pick-group">
                  <div class="pick-title">{{ group.selector }}</div>
                  <el-checkbox-group
                    :model-value="checkedProductsBySet[group.selector] || []"
                    @update:model-value="(v) => updateCheckedProducts(group.selector, v as string[])"
                  >
                    <el-checkbox v-for="code in group.product_codes" :key="code" :label="code" :value="code">
                      {{ code }}
                    </el-checkbox>
                  </el-checkbox-group>
                </div>
              </div>
            </el-form-item>

            <el-form-item label="活动">
              <el-select v-model="activityId" placeholder="选择活动" style="width: 100%">
                <el-option
                  v-for="act in activities"
                  :key="act.activity_id"
                  :label="`${act.activity_id} · ${act.name || '活动'}`"
                  :value="act.activity_id"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="类目关键词">
              <el-input v-model="categoryKeyword" placeholder="上架类目，默认玩偶" />
            </el-form-item>

            <el-form-item label="自动推广">
              <el-switch v-model="autoPromotion" />
            </el-form-item>

            <el-form-item label="演示模式">
              <el-switch v-model="demoMode" />
              <span class="hint">开启后活动延迟约 2 分钟（便于测试整条链路）</span>
            </el-form-item>

            <el-form-item v-if="!demoMode" label="活动延迟">
              <el-input-number v-model="activityDelayHours" :min="1" :max="168" />
              <span class="hint">小时（建议 24，对应上架后隔一天报活动）</span>
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :loading="loading" @click="startPipeline">
                一键启动整合链路
              </el-button>
            </el-form-item>
          </el-form>

          <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="msg" />
          <el-alert v-if="success" type="success" :title="success" show-icon :closable="false" class="msg" />
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card v-if="activePipeline" shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>当前链路</span>
              <el-tag :type="pipelineTagType(activePipeline.status)">{{ activePipeline.status }}</el-tag>
            </div>
          </template>
          <p class="meta">ID：{{ activePipeline.pipeline_id }}</p>
          <p v-if="activePipeline.scheduled_activity_at" class="meta">
            活动计划时间：{{ formatTime(activePipeline.scheduled_activity_at) }}
          </p>
          <p v-if="activePipeline.pdd_product_ids.length" class="meta">
            拼多多商品：{{ activePipeline.pdd_product_ids.join(', ') }}
          </p>
          <p v-if="activePipeline.error" class="error-text">{{ activePipeline.error }}</p>

          <el-steps direction="vertical" :active="3" class="steps">
            <el-step v-for="step in activePipeline.steps" :key="step.key" :title="step.label">
              <template #description>
                <div class="step-desc">
                  <el-tag size="small" :type="stepTagType(step.status)">{{ step.status }}</el-tag>
                  <span>{{ step.detail }}</span>
                  <el-button
                    v-if="step.run_id"
                    link
                    type="primary"
                    size="small"
                    @click="openRun(step.run_id)"
                  >
                    查看记录
                  </el-button>
                </div>
              </template>
            </el-step>
          </el-steps>
        </el-card>

        <el-card shadow="never" class="card">
          <template #header>
            <div class="card-head">
              <span>最近链路</span>
              <el-tag v-if="polling" size="small" type="info">自动刷新</el-tag>
            </div>
          </template>
          <el-table :data="pipelines" size="small" empty-text="暂无整合链路">
            <el-table-column prop="pipeline_id" label="ID" min-width="140" show-overflow-tooltip />
            <el-table-column prop="account_id" label="店铺" width="90" />
            <el-table-column prop="status" label="状态" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="pipelineTagType(row.status)">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="activePipeline = row">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tip {
  margin-bottom: 4px;
}
.card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.product-picks {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}
.pick-group {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
}
.pick-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.hint {
  margin-left: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.slot-align-test {
  margin: 0;
}
.form-tip {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.msg {
  margin-top: 12px;
}
.meta {
  margin: 0 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.error-text {
  color: var(--el-color-danger);
  margin-bottom: 12px;
}
.steps {
  margin-top: 8px;
}
.step-desc {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.pipeline-item.active,
.nav-item.active {
  /* sidebar highlight handled globally */
}
</style>
