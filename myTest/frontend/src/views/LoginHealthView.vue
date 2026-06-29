<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { LoginStatus } from '@/types'

const loading = ref(false)
const checking = ref(false)
const scraping = ref(false)
const statuses = ref<LoginStatus[]>([])
const selectedAccounts = ref<string[]>([])
const delayMin = ref(30)
const delayMax = ref(180)
let pollTimer: number | undefined

const accountOptions = computed(() => statuses.value.map((s) => s.account_id))

function statusLabel(status: string) {
  const map: Record<string, string> = {
    unknown: '未检查',
    pending: '等待检查',
    checking: '检查中',
    logged_in: '已登录',
    needs_login: '需登录',
    needs_manual: '需人工',
    failed: '失败',
  }
  return map[status] || status
}

function statusType(status: string) {
  if (status === 'logged_in') return 'success'
  if (status === 'checking' || status === 'pending') return 'info'
  if (status === 'needs_login' || status === 'needs_manual') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

function formatTime(t: string | null) {
  if (!t) return '-'
  return new Date(t).toLocaleString('zh-CN')
}

async function load() {
  loading.value = true
  try {
    statuses.value = await api.loginStatuses()
    if (!selectedAccounts.value.length) {
      selectedAccounts.value = statuses.value.map((s) => s.account_id)
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载登录状态失败')
  } finally {
    loading.value = false
  }
}

async function checkOne(accountId: string) {
  loading.value = true
  try {
    const row = await api.checkLogin(accountId)
    upsertRow(row)
    ElMessage.success(`${accountId} 检查完成`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '检查失败')
  } finally {
    loading.value = false
  }
}

async function scrapeShopNamesBatch() {
  const account_ids = selectedAccounts.value.length ? selectedAccounts.value : accountOptions.value
  if (!account_ids.length) {
    ElMessage.warning('没有可抓取的店铺')
    return
  }
  scraping.value = true
  try {
    await api.scrapeShopNamesBatch({
      account_ids,
      delay_min_seconds: delayMin.value,
      delay_max_seconds: delayMax.value,
    })
    ElMessage.info(
      `已提交 ${account_ids.length} 家店铺名称抓取。将依次弹出浏览器窗口，未登录会自动填账号密码；出现验证码请在窗口内完成。`,
      { duration: 8000 },
    )
    await load()
    startPolling()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '抓取店铺名称失败')
    scraping.value = false
  }
}

async function scrapeShopNameOne(accountId: string) {
  loading.value = true
  ElMessage.info(`${accountId}：正在打开浏览器，请完成登录或验证码（最多约 3 分钟）`, {
    duration: 6000,
  })
  try {
    const row = await api.scrapeShopName(accountId)
    await load()
    if (row.ok) {
      ElMessage.success(`${accountId} 店铺名：${row.shop_display_name}`)
    } else {
      ElMessage.warning(`${accountId} 抓取失败：${row.reason}`)
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '抓取失败')
  } finally {
    loading.value = false
  }
}

async function checkBatch() {
  const account_ids = selectedAccounts.value.length ? selectedAccounts.value : accountOptions.value
  if (!account_ids.length) {
    ElMessage.warning('没有可检查的店铺')
    return
  }
  checking.value = true
  try {
    await api.checkLoginBatch({
      account_ids,
      delay_min_seconds: delayMin.value,
      delay_max_seconds: delayMax.value,
    })
    ElMessage.success(`已提交 ${account_ids.length} 家店铺登录体检`)
    await load()
    startPolling()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '批量检查失败')
    checking.value = false
  }
}

async function openLogin(accountId: string) {
  try {
    await api.openLoginWindow(accountId, 300)
    ElMessage.success(`${accountId} 登录窗口已打开`)
    await load()
    startPolling()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '打开登录窗口失败')
  }
}

function upsertRow(row: LoginStatus) {
  const idx = statuses.value.findIndex((s) => s.account_id === row.account_id)
  if (idx >= 0) statuses.value[idx] = row
  else statuses.value.push(row)
}

function startPolling() {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(async () => {
    await load()
    const busy = statuses.value.some((s) => s.status === 'pending' || s.status === 'checking')
    if (!busy) {
      checking.value = false
      scraping.value = false
      stopPolling()
    }
  }, 5000)
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

onMounted(load)
onUnmounted(stopPolling)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="登录体检" desc="检查店铺登录状态；需要验证码、短信或扫码时手动完成。">
      <template #actions>
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" :loading="checking" @click="checkBatch">批量检查</el-button>
      </template>
    </PageHeader>

    <div class="section-tip" style="margin-bottom: 16px">
      批量检查会按顺序打开店铺 Profile，不会同时打开所有浏览器。无法保证规避平台风控；建议低并发、错峰、人工处理验证码。
    </div>

    <el-card shadow="never" class="stat-card settings-card">
      <el-form label-position="top">
        <el-form-item label="检查店铺">
          <el-select v-model="selectedAccounts" multiple filterable style="width: 100%" placeholder="默认检查全部启用店铺">
            <el-option v-for="id in accountOptions" :key="id" :label="id" :value="id" />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="每家检查间隔最小秒数">
              <el-input-number v-model="delayMin" :min="0" :max="3600" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="每家检查间隔最大秒数">
              <el-input-number v-model="delayMax" :min="delayMin" :max="3600" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <div class="scrape-bar">
      <el-button type="primary" plain :loading="scraping" @click="scrapeShopNamesBatch">
        抓取店铺名称
      </el-button>
      <span class="section-tip scrape-tip">
        按所选店铺依次打开可见浏览器：自动登录（含验证码等待），从商家后台右上角读取店铺名并写入数据库。
      </span>
    </div>

    <el-card shadow="never" class="stat-card">
      <el-table :data="statuses" stripe>
        <el-table-column prop="account_id" label="店铺 ID" width="110" />
        <el-table-column label="店铺名" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.shop_display_name || row.account_id }}</template>
        </el-table-column>
        <el-table-column label="登录状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status) as any" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最后检查时间" width="180">
          <template #default="{ row }">{{ formatTime(row.checked_at) }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="220" show-overflow-tooltip />
        <el-table-column prop="current_url" label="当前地址" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="checkOne(row.account_id)">检查</el-button>
            <el-button link type="success" @click="scrapeShopNameOne(row.account_id)">抓店铺名</el-button>
            <el-button link type="warning" @click="openLogin(row.account_id)">打开登录窗口</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!statuses.length" description="暂无店铺" />
    </el-card>
  </div>
</template>

<style scoped>
.settings-card {
  margin-bottom: 16px;
}

.scrape-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.scrape-tip {
  margin: 0;
  flex: 1;
  min-width: 240px;
}
</style>
