<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import ResultSummary from '@/components/ResultSummary.vue'
import type { Account, CampaignTaskResponse } from '@/types'

const router = useRouter()

const loading = ref(false)
const error = ref('')
const success = ref('')
const accounts = ref<Account[]>([])
const accountId = ref('')
const result = ref<CampaignTaskResponse | null>(null)

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))

async function loadMeta() {
  try {
    accounts.value = await api.accounts(true)
    if (accounts.value.length && !accountId.value) {
      accountId.value = accounts.value[0].account_id
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载店铺失败，请确认后台已启动'
  }
}

async function startLimitedTimeSetup() {
  if (!accountId.value) {
    error.value = '请选择店铺'
    return
  }

  loading.value = true
  error.value = ''
  success.value = ''
  result.value = null
  try {
    result.value = await api.campaignLimitedTimeSetup({ account_id: accountId.value })
    success.value = result.value.message || '限时限量购活动设置任务已启动'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '启动活动任务失败'
  } finally {
    loading.value = false
  }
}

function goRunDetail(runId: string) {
  router.push({ path: '/runs', query: { id: runId } })
}

onMounted(loadMeta)
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="活动"
      desc="当前先支持进入限时限量购创建页，并取消底部“同步设置惊喜优惠”。"
    />

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      style="margin-bottom: 12px"
      @close="error = ''"
    />
    <el-alert
      v-if="success"
      type="success"
      :title="success"
      show-icon
      closable
      style="margin-bottom: 12px"
      @close="success = ''"
    />

    <div class="section-tip">
      任务会打开对应店铺的浏览器窗口，依次进入营销工具、限时限量购、立即创建。
      到活动设置页后只处理“同步设置惊喜优惠”复选框，不会点击最终创建按钮。
    </div>

    <el-card shadow="never" class="stat-card campaign-card">
      <template #header>限时限量购</template>

      <el-form label-position="top" class="campaign-form">
        <el-form-item label="选择店铺" required>
          <el-select v-model="accountId" filterable style="width: 100%" placeholder="请选择店铺">
            <el-option
              v-for="a in enabledAccounts"
              :key="a.account_id"
              :label="a.account_id"
              :value="a.account_id"
            />
          </el-select>
        </el-form-item>
      </el-form>

      <el-button type="primary" size="large" class="submit-btn" @click="startLimitedTimeSetup">
        打开限时限量购并取消惊喜优惠
      </el-button>

      <ResultSummary
        v-if="result"
        :status="result.status"
        :message="result.message"
        :run-id="result.run_id"
        :result="result.result"
        @view-detail="goRunDetail(result!.run_id)"
      />
    </el-card>
  </div>
</template>

<style scoped>
.campaign-card {
  max-width: 760px;
}

.campaign-form {
  max-width: 520px;
}

.submit-btn {
  width: 100%;
  max-width: 520px;
}
</style>
