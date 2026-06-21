<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { Account, TrafficReportSchedule } from '@/types'

const router = useRouter()

const loading = ref(false)
const saving = ref(false)
const triggering = ref(false)
const schedule = ref<TrafficReportSchedule | null>(null)
const accounts = ref<Account[]>([])

const form = reactive({
  traffic_report_enabled: true,
  schedule_hour: 0,
  schedule_minute: 1,
  account_ids: [] as string[],
})

const scheduleTimeDisplay = computed(() => {
  const h = String(form.schedule_hour).padStart(2, '0')
  const m = String(form.schedule_minute).padStart(2, '0')
  return `${h}:${m}`
})

const statusType = computed(() => {
  if (!schedule.value?.database_available) return 'warning'
  if (!schedule.value?.traffic_report_enabled) return 'info'
  if (schedule.value?.scheduler_running) return 'success'
  return 'warning'
})

function applySchedule(data: TrafficReportSchedule) {
  schedule.value = data
  form.traffic_report_enabled = data.traffic_report_enabled
  form.schedule_hour = data.schedule_hour
  form.schedule_minute = data.schedule_minute
  form.account_ids = [...data.account_ids]
}

async function load() {
  loading.value = true
  try {
    const [cfg, accs] = await Promise.all([
      api.trafficReportSchedule(),
      api.accounts(true),
    ])
    accounts.value = accs
    applySchedule(cfg)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载配置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const data = await api.updateTrafficReportSchedule({
      traffic_report_enabled: form.traffic_report_enabled,
      schedule_hour: form.schedule_hour,
      schedule_minute: form.schedule_minute,
      account_ids: form.account_ids,
    })
    applySchedule(data)
    ElMessage.success('定时任务配置已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function triggerNow() {
  triggering.value = true
  try {
    const result = await api.triggerTrafficReportSchedule()
    ElMessage.success(result.message || `已入队 ${result.enqueued} 家店铺`)
    await load()
    router.push('/runs')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '手动触发失败')
  } finally {
    triggering.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="投流日报定时任务"
      desc="每天自动抓取稳定成本推广「昨日」数据，写入飞书 PDD营销日志表。"
    >
      <template #actions>
        <el-button :loading="triggering" type="warning" @click="triggerNow">
          立即执行一次
        </el-button>
        <el-button type="primary" :loading="saving" @click="save">保存配置</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="schedule"
      :type="statusType"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    >
      <template #title>
        {{
          schedule.scheduler_running
            ? '调度器运行中'
            : schedule.database_available
              ? '调度器未启动（需数据库）'
              : '数据库不可用，定时与手动入队均不可用'
        }}
      </template>
      <template #default>
        <div>时区：{{ schedule.timezone }} · 飞书表：{{ schedule.table_name }}</div>
        <div v-if="schedule.last_run_date">上次自动调度日期：{{ schedule.last_run_date }}</div>
        <div v-else>今天尚未自动调度（到达设定时间后会入队）</div>
      </template>
    </el-alert>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" class="stat-card">
          <template #header>定时设置</template>
          <el-form label-position="top">
            <el-form-item label="启用定时任务">
              <el-switch
                v-model="form.traffic_report_enabled"
                active-text="开启"
                inactive-text="关闭"
              />
              <div class="form-tip">关闭后不会自动入队，但仍可手动「立即执行一次」。</div>
            </el-form-item>

            <el-form-item label="每天触发时间">
              <div class="time-row">
                <el-input-number
                  v-model="form.schedule_hour"
                  :min="0"
                  :max="23"
                  controls-position="right"
                />
                <span class="time-sep">时</span>
                <el-input-number
                  v-model="form.schedule_minute"
                  :min="0"
                  :max="59"
                  controls-position="right"
                />
                <span class="time-sep">分</span>
                <el-tag type="info">{{ scheduleTimeDisplay }}（{{ schedule?.timezone }}）</el-tag>
              </div>
              <div class="form-tip">
                建议设在凌晨 1:00 之后，等拼多多昨日数据更新完成再抓取。
              </div>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never" class="stat-card">
          <template #header>抓取店铺</template>
          <el-form label-position="top">
            <el-form-item label="参与定时/手动触发的店铺">
              <el-select
                v-model="form.account_ids"
                multiple
                collapse-tags
                collapse-tags-tooltip
                placeholder="选择店铺"
                style="width: 100%"
              >
                <el-option
                  v-for="acc in accounts"
                  :key="acc.account_id"
                  :label="acc.account_id"
                  :value="acc.account_id"
                />
              </el-select>
              <div class="form-tip">仅已启用的店铺会出现在列表中。</div>
            </el-form-item>
          </el-form>

          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="任务内容">
              推广概况 → 全部推广 → 稳定成本推广 → 推广消耗时间「昨日」
            </el-descriptions-item>
            <el-descriptions-item label="写入目标">
              飞书 {{ schedule?.table_name || 'PDD营销日志表' }}
            </el-descriptions-item>
            <el-descriptions-item label="去重规则">
              日期 + 商品ID（同一天同商品更新，不同天新增）
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.stat-card {
  margin-bottom: 16px;
}

.time-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.time-sep {
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
</style>
