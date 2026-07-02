<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type {
  DailyCycleRelistRecord,
  DailyCycleRelistSummaryResponse,
  DailyListingRecord,
  DailyListingSummaryResponse,
  DailyPipelineListingSkipRecord,
  DailyPipelineListingSkipSummaryResponse,
} from '@/types'

const loading = ref(false)
const queryDate = ref(formatDate(new Date()))
const showActiveOnly = ref(false)
const skipKindFilter = ref('')
const listingSummary = ref<DailyListingSummaryResponse | null>(null)
const listingRecords = ref<DailyListingRecord[]>([])
const cycleSummary = ref<DailyCycleRelistSummaryResponse | null>(null)
const cycleRecords = ref<DailyCycleRelistRecord[]>([])
const skipSummary = ref<DailyPipelineListingSkipSummaryResponse | null>(null)
const skipRecords = ref<DailyPipelineListingSkipRecord[]>([])

const dateLabel = computed(() => queryDate.value || '—')
const cyclePipelineIdSet = computed(() => {
  const ids = new Set<string>()
  for (const row of cycleRecords.value) {
    const id = String(row.pipeline_id || '').trim()
    if (id) ids.add(id)
  }
  return ids
})
const cycleSuccessRecords = computed(() =>
  listingRecords.value.filter((row) => {
    const sourceKind = String(row.source_kind || '').trim()
    const pipelineId = String(row.pipeline_id || '').trim()
    const active = String(row.status || 'active') === 'active'
    return (
      active &&
      sourceKind === 'integrated_pipeline' &&
      !!pipelineId &&
      cyclePipelineIdSet.value.has(pipelineId)
    )
  }),
)
const cycleSuccessByShop = computed(() => {
  const counter = new Map<string, { account_id: string; shop_display_name: string; count: number }>()
  for (const row of cycleSuccessRecords.value) {
    const accountId = String(row.account_id || '').trim()
    const key = accountId || String(row.shop_display_name || '').trim() || 'unknown'
    const current = counter.get(key)
    if (current) {
      current.count += 1
      continue
    }
    counter.set(key, {
      account_id: accountId,
      shop_display_name: String(row.shop_display_name || '').trim(),
      count: 1,
    })
  }
  return Array.from(counter.values()).sort((a, b) => b.count - a.count)
})

function formatDate(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function setToday() {
  queryDate.value = formatDate(new Date())
  void load()
}

function setYesterday() {
  const d = new Date()
  d.setDate(d.getDate() - 1)
  queryDate.value = formatDate(d)
  void load()
}

function listingStatusLabel(status: string) {
  return String(status || 'active') === 'active' ? '仍在上架' : '已下架'
}

function listingStatusType(status: string): 'success' | 'info' {
  return String(status || 'active') === 'active' ? 'success' : 'info'
}

function skipKindTagType(kind: string): 'warning' | 'danger' | 'info' {
  if (kind === 'platform_skip_dedupe') return 'warning'
  if (kind === 'bag_view_missing') return 'danger'
  return 'info'
}

async function load() {
  const date = String(queryDate.value || '').trim()
  if (!date) {
    ElMessage.warning('请选择查询日期')
    return
  }
  loading.value = true
  try {
    const [listingSum, listingRows, cycleSum, cycleRows, pipelineSkipSum, pipelineSkipRows] =
      await Promise.all([
      api.dailyListingSummary({ listed_date: date }),
      api.dailyListingRecords({
        listed_date: date,
        limit: 200,
        active_only: showActiveOnly.value,
      }),
      api.dailyCycleRelistSummary({ triggered_date: date }),
      api.dailyCycleRelistRecords({ triggered_date: date, limit: 200 }),
      api.dailyPipelineListingSkipSummary({ skip_date: date }),
      api.dailyPipelineListingSkipRecords({
        skip_date: date,
        skip_kind: skipKindFilter.value || undefined,
        limit: 200,
      }),
    ])
    listingSummary.value = listingSum
    listingRecords.value = listingRows.items
    cycleSummary.value = cycleSum
    cycleRecords.value = cycleRows.items
    skipSummary.value = pipelineSkipSum
    skipRecords.value = pipelineSkipRows.items
  } catch (e) {
    listingSummary.value = null
    listingRecords.value = []
    cycleSummary.value = null
    cycleRecords.value = []
    skipSummary.value = null
    skipRecords.value = []
    ElMessage.error(e instanceof Error ? e.message : '加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page" v-loading="loading">
    <PageHeader
      title="每日统计"
      subtitle="按日期查询上架成功数、整合链路上架跳过数与失败日志循环跑整合链路次数"
    />

    <el-card shadow="never" class="mb-16">
      <el-form inline @submit.prevent="load">
        <el-form-item label="查询日期">
          <el-date-picker
            v-model="queryDate"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择日期"
            :clearable="false"
            style="width: 180px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="load">查询</el-button>
          <el-button @click="setToday">今天</el-button>
          <el-button @click="setYesterday">昨天</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="mb-16">
      <template #header>
        <div class="card-header">
          <span>{{ dateLabel }} 上架成功</span>
          <div class="summary-tags">
            <el-tag type="primary">当天总共 {{ listingSummary?.total ?? 0 }} 件</el-tag>
            <el-tag type="success">仍在上架 {{ listingSummary?.active_total ?? 0 }} 件</el-tag>
            <el-tag type="info">已下架 {{ listingSummary?.delisted_total ?? 0 }} 件</el-tag>
          </div>
        </div>
      </template>

      <el-row v-if="listingSummary?.by_shop?.length" :gutter="12" class="mb-12">
        <el-col
          v-for="shop in listingSummary.by_shop"
          :key="`listing-${shop.account_id}`"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
        >
          <div class="shop-stat-card">
            <div class="shop-stat-title">{{ shop.shop_display_name || shop.account_id }}</div>
            <div class="shop-stat-values">
              <span>总共 {{ shop.count }} 件</span>
              <span class="active">仍在上架 {{ shop.active_count }} 件</span>
              <span class="delisted">已下架 {{ shop.delisted_count }} 件</span>
            </div>
          </div>
        </el-col>
      </el-row>

      <div class="table-toolbar mb-12">
        <el-checkbox v-model="showActiveOnly" @change="load">
          仅显示仍在上架
        </el-checkbox>
      </div>

      <el-table
        :data="listingRecords"
        stripe
        border
        size="small"
        empty-text="该日暂无上架成功记录"
      >
        <el-table-column label="状态" width="100">
          <template #default="{ row }: { row: DailyListingRecord }">
            <el-tag :type="listingStatusType(row.status)" size="small">
              {{ listingStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="listed_at" label="上架时间" width="170" />
        <el-table-column prop="delisted_at" label="下架时间" width="170">
          <template #default="{ row }: { row: DailyListingRecord }">
            {{ row.delisted_at || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="shop_display_name" label="店铺" width="120" show-overflow-tooltip />
        <el-table-column prop="pdd_product_id" label="商品 ID" width="130" show-overflow-tooltip />
        <el-table-column prop="product_code" label="货号" width="110" show-overflow-tooltip />
        <el-table-column prop="listing_label" label="套图" width="140" show-overflow-tooltip />
        <el-table-column prop="title" label="标题" min-width="160" show-overflow-tooltip />
        <el-table-column prop="merchant_code" label="平台货号" width="110" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never" class="mb-16">
      <template #header>
        <div class="card-header">
          <span>{{ dateLabel }} 整合链路上架跳过</span>
          <div class="summary-tags">
            <el-tag type="warning">共 {{ skipSummary?.total ?? 0 }} 件</el-tag>
            <el-tag type="info">
              涉及链路 {{ skipSummary?.pipeline_count ?? 0 }} 条
            </el-tag>
            <el-tag>平台去重 {{ skipSummary?.platform_skip_dedupe ?? 0 }} 件</el-tag>
            <el-tag type="danger">笔袋无编码 {{ skipSummary?.bag_view_missing ?? 0 }} 件</el-tag>
          </div>
        </div>
      </template>

      <el-row v-if="skipSummary?.by_shop?.length" :gutter="12" class="mb-12">
        <el-col
          v-for="shop in skipSummary.by_shop"
          :key="`skip-${shop.account_id}`"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
        >
          <div class="shop-stat-card">
            <div class="shop-stat-title">{{ shop.shop_display_name || shop.account_id }}</div>
            <div class="shop-stat-values">
              <span>跳过 {{ shop.total }} 件</span>
              <span class="active">平台去重 {{ shop.platform_skip_dedupe }} 件</span>
              <span class="delisted">笔袋无编码 {{ shop.bag_view_missing }} 件</span>
            </div>
          </div>
        </el-col>
      </el-row>

      <div class="table-toolbar mb-12">
        <el-select
          v-model="skipKindFilter"
          clearable
          placeholder="全部跳过类型"
          style="width: 180px"
          @change="load"
        >
          <el-option label="平台跳过去重" value="platform_skip_dedupe" />
          <el-option label="笔袋视图无编码" value="bag_view_missing" />
        </el-select>
      </div>

      <el-table
        :data="skipRecords"
        stripe
        border
        size="small"
        empty-text="该日暂无整合链路上架跳过记录"
      >
        <el-table-column label="跳过类型" width="130">
          <template #default="{ row }: { row: DailyPipelineListingSkipRecord }">
            <el-tag :type="skipKindTagType(row.skip_kind)" size="small">
              {{ row.skip_kind_label || row.skip_kind }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="记录时间" width="170" />
        <el-table-column prop="shop_display_name" label="店铺" width="120" show-overflow-tooltip />
        <el-table-column prop="merchant_code" label="商品编码" width="110" show-overflow-tooltip />
        <el-table-column prop="listing_label" label="套图/选择器" min-width="160" show-overflow-tooltip />
        <el-table-column prop="pipeline_id" label="链路 ID" width="150" show-overflow-tooltip />
        <el-table-column prop="listing_run_id" label="上架 run_id" width="150" show-overflow-tooltip />
        <el-table-column prop="message" label="说明" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-card>

    <el-card shadow="never" class="mb-16">
      <template #header>
        <div class="card-header">
          <span>{{ dateLabel }} 循环跑整合链路</span>
          <el-tag type="primary">共 {{ cycleSummary?.total ?? 0 }} 次</el-tag>
        </div>
      </template>

      <el-row v-if="cycleSummary?.by_shop?.length" :gutter="12" class="mb-12">
        <el-col
          v-for="shop in cycleSummary.by_shop"
          :key="`cycle-${shop.account_id}`"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
        >
          <el-statistic
            :title="shop.shop_display_name || shop.account_id"
            :value="shop.count"
            suffix="次"
          />
        </el-col>
      </el-row>

      <el-table
        :data="cycleRecords"
        stripe
        border
        size="small"
        empty-text="该日暂无循环跑链路记录"
      >
        <el-table-column prop="triggered_at" label="触发时间" width="170" />
        <el-table-column prop="shop_display_name" label="店铺" width="120" show-overflow-tooltip />
        <el-table-column prop="merchant_code" label="商品编码" width="130" show-overflow-tooltip />
        <el-table-column prop="pipeline_id" label="链路 ID" width="150" show-overflow-tooltip />
        <el-table-column prop="feishu_record_id" label="飞书 record_id" width="150" show-overflow-tooltip />
        <el-table-column label="来源" width="90">
          <template #default="{ row }: { row: DailyCycleRelistRecord }">
            {{ row.trigger_source === 'manual_api' ? '手动' : '自动' }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="mb-16">
      <template #header>
        <div class="card-header">
          <span>{{ dateLabel }} 循环跑上架成功</span>
          <el-tag type="success">共 {{ cycleSuccessRecords.length }} 件</el-tag>
        </div>
      </template>

      <el-row v-if="cycleSuccessByShop.length" :gutter="12" class="mb-12">
        <el-col
          v-for="shop in cycleSuccessByShop"
          :key="`cycle-success-${shop.account_id || shop.shop_display_name}`"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
        >
          <el-statistic
            :title="shop.shop_display_name || shop.account_id || '未知店铺'"
            :value="shop.count"
            suffix="件"
          />
        </el-col>
      </el-row>

      <el-table
        :data="cycleSuccessRecords"
        stripe
        border
        size="small"
        empty-text="该日暂无循环跑上架成功记录"
      >
        <el-table-column prop="listed_at" label="上架时间" width="170" />
        <el-table-column prop="shop_display_name" label="店铺" width="120" show-overflow-tooltip />
        <el-table-column prop="product_code" label="货号" width="110" show-overflow-tooltip />
        <el-table-column prop="listing_label" label="套图" width="140" show-overflow-tooltip />
        <el-table-column prop="pdd_product_id" label="商品 ID" width="130" show-overflow-tooltip />
        <el-table-column prop="merchant_code" label="平台货号" width="120" show-overflow-tooltip />
        <el-table-column prop="pipeline_id" label="链路 ID" width="150" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.page {
  padding: 0 4px 24px;
}
.mb-16 {
  margin-bottom: 16px;
}
.mb-12 {
  margin-bottom: 12px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.summary-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.shop-stat-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
  background: var(--el-fill-color-blank);
}
.shop-stat-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}
.shop-stat-values {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.shop-stat-values .active {
  color: var(--el-color-success);
}
.shop-stat-values .delisted {
  color: var(--el-text-color-secondary);
}
.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
}
</style>
