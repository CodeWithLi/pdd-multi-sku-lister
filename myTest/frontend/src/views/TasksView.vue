<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import ResultSummary from '@/components/ResultSummary.vue'
import type { Account, BatchTaskResponse, DelistTaskResponse, ListingTaskResponse } from '@/types'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const success = ref('')
const activeTab = ref('listing')

const accounts = ref<Account[]>([])
const productOptions = ref<string[]>([])
const defaultConcurrentStores = ref(3)
const defaultStartDelayMin = ref(30)
const defaultStartDelayMax = ref(180)

const accountId = ref('')
const batchAccountIds = ref<string[]>([])
const productCodes = ref<string[]>([])
const listingMode = ref<'check' | 'run'>('check')
const categoryKeyword = ref('玩偶')
const listingResult = ref<ListingTaskResponse | null>(null)
const listingBatchResult = ref<BatchTaskResponse | null>(null)
const listingBatchEnabled = ref(false)
const listingConcurrentStores = ref(3)
const listingStartDelayMin = ref(30)
const listingStartDelayMax = ref(180)

const delistAccountId = ref('')
const delistBatchAccountIds = ref<string[]>([])
const delistMode = ref<'scan' | 'run'>('scan')
const delistMinCreated = ref('2026-06-04 14:25')
const delistMaxPerRun = ref(1)
const delistResult = ref<DelistTaskResponse | null>(null)
const delistBatchResult = ref<BatchTaskResponse | null>(null)
const delistBatchEnabled = ref(false)
const delistConcurrentStores = ref(3)
const delistStartDelayMin = ref(30)
const delistStartDelayMax = ref(180)

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))

async function loadMeta() {
  try {
    const [accs, products, cfg] = await Promise.all([
      api.accounts(true),
      api.products(),
      api.runtimeConfig(),
    ])
    accounts.value = accs
    productOptions.value = products.map((p) => p.product_code)
    categoryKeyword.value = cfg.listing.category_keyword || '玩偶'
    delistMinCreated.value = cfg.delist.min_created_after || delistMinCreated.value
    delistMaxPerRun.value = cfg.delist.max_delist_per_run || delistMaxPerRun.value
    delistMode.value = cfg.delist.dry_run ? 'scan' : 'run'
    defaultConcurrentStores.value = cfg.batch.max_concurrent_stores || 3
    defaultStartDelayMin.value = cfg.batch.store_start_delay_min_seconds ?? 30
    defaultStartDelayMax.value = cfg.batch.store_start_delay_max_seconds ?? 180
    listingConcurrentStores.value = defaultConcurrentStores.value
    delistConcurrentStores.value = defaultConcurrentStores.value
    listingStartDelayMin.value = defaultStartDelayMin.value
    listingStartDelayMax.value = defaultStartDelayMax.value
    delistStartDelayMin.value = defaultStartDelayMin.value
    delistStartDelayMax.value = defaultStartDelayMax.value

    if (accs.length && !accountId.value) {
      accountId.value = accs[0].account_id
      productCodes.value = [...accs[0].product_codes]
      delistAccountId.value = accs[0].account_id
      batchAccountIds.value = accs.map((a) => a.account_id)
      delistBatchAccountIds.value = accs.map((a) => a.account_id)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败，请确认后台已启动'
  }
}

function onAccountChange(id: string) {
  const acc = accounts.value.find((a) => a.account_id === id)
  if (acc?.product_codes.length) {
    productCodes.value = [...acc.product_codes]
  }
}

function selectedListingAccounts() {
  return listingBatchEnabled.value ? batchAccountIds.value : [accountId.value]
}

function selectedDelistAccounts() {
  return delistBatchEnabled.value ? delistBatchAccountIds.value : [delistAccountId.value]
}

function validateAccounts(ids: string[]) {
  const cleaned = ids.filter(Boolean)
  if (!cleaned.length) {
    error.value = '请至少选择一家店铺'
    return []
  }
  return cleaned
}

async function runListing() {
  const accountIds = validateAccounts(selectedListingAccounts())
  if (!accountIds.length) return
  if (!productCodes.value.length) {
    error.value = '请至少选择一个商品编码'
    return
  }

  loading.value = true
  error.value = ''
  success.value = ''
  listingResult.value = null
  listingBatchResult.value = null
  const isCheck = listingMode.value === 'check'

  try {
    if (listingBatchEnabled.value) {
      listingBatchResult.value = await api.listingBatch({
        account_ids: accountIds,
        product_codes: productCodes.value,
        dry_run: isCheck,
        category_keyword: categoryKeyword.value,
        max_concurrent_stores: listingConcurrentStores.value,
        store_start_delay_min_seconds: listingStartDelayMin.value,
        store_start_delay_max_seconds: listingStartDelayMax.value,
      })
      success.value = `批量上架任务已提交：${listingBatchResult.value.total} 家店铺，并发 ${listingBatchResult.value.max_concurrent_stores} 家，启动间隔 ${listingBatchResult.value.store_start_delay_min_seconds}-${listingBatchResult.value.store_start_delay_max_seconds} 秒`
      return
    }

    listingResult.value = await api.listing({
      account_id: accountIds[0],
      product_codes: productCodes.value,
      dry_run: isCheck,
      category_keyword: categoryKeyword.value,
      background: !isCheck,
    })
    success.value = isCheck ? '素材检查完成' : '上架任务已提交'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    loading.value = false
  }
}

async function runDelist() {
  const accountIds = validateAccounts(selectedDelistAccounts())
  if (!accountIds.length) return

  loading.value = true
  error.value = ''
  success.value = ''
  delistResult.value = null
  delistBatchResult.value = null
  const isScan = delistMode.value === 'scan'

  try {
    if (delistBatchEnabled.value) {
      delistBatchResult.value = await api.delistBatch({
        account_ids: accountIds,
        dry_run: isScan,
        min_created_after: delistMinCreated.value,
        max_delist_per_run: delistMaxPerRun.value,
        max_concurrent_stores: delistConcurrentStores.value,
        store_start_delay_min_seconds: delistStartDelayMin.value,
        store_start_delay_max_seconds: delistStartDelayMax.value,
      })
      success.value = `批量下架任务已提交：${delistBatchResult.value.total} 家店铺，并发 ${delistBatchResult.value.max_concurrent_stores} 家，启动间隔 ${delistBatchResult.value.store_start_delay_min_seconds}-${delistBatchResult.value.store_start_delay_max_seconds} 秒`
      return
    }

    delistResult.value = await api.delist({
      account_id: accountIds[0],
      dry_run: isScan,
      min_created_after: delistMinCreated.value,
      max_delist_per_run: delistMaxPerRun.value,
      background: true,
    })
    success.value = isScan ? '下架扫描任务已提交' : '下架任务已提交'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '下架失败'
  } finally {
    loading.value = false
  }
}

function goRunDetail(runId: string) {
  router.push({ path: '/runs', query: { id: runId } })
}

onMounted(() => {
  if (route.query.tab === 'delist') activeTab.value = 'delist'
  loadMeta()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="上架 / 下架"
      desc="支持单店铺与批量店铺任务；批量执行会按配置限制同时运行的店铺数。"
    />

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 12px" @close="error = ''" />
    <el-alert v-if="success" type="success" :title="success" show-icon closable style="margin-bottom: 12px" @close="success = ''" />

    <el-tabs v-model="activeTab" class="task-tabs">
      <el-tab-pane label="商品上架" name="listing">
        <div class="section-tip">
          正式上架会打开浏览器窗口。批量任务建议先用“仅检查”跑一遍，再执行正式上架。
        </div>

        <el-card shadow="never" class="stat-card">
          <el-form label-position="top" class="task-form">
            <el-form-item label="批量店铺">
              <el-switch v-model="listingBatchEnabled" active-text="开启" inactive-text="关闭" />
            </el-form-item>

            <el-form-item v-if="listingBatchEnabled" label="选择店铺" required>
              <el-select v-model="batchAccountIds" multiple filterable style="width: 100%" placeholder="选择要执行的店铺">
                <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>

            <el-form-item v-else label="选择店铺" required>
              <el-select v-model="accountId" style="width: 100%" placeholder="请选择" @change="onAccountChange">
                <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>

            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="类目关键词">
                  <el-input v-model="categoryKeyword" />
                </el-form-item>
              </el-col>
              <el-col v-if="listingBatchEnabled" :span="12">
                <el-form-item label="同时运行店铺数">
                  <el-input-number v-model="listingConcurrentStores" :min="1" :max="5" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-row v-if="listingBatchEnabled" :gutter="20">
              <el-col :span="12">
                <el-form-item label="启动间隔最小秒数">
                  <el-input-number v-model="listingStartDelayMin" :min="0" :max="3600" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="启动间隔最大秒数">
                  <el-input-number
                    v-model="listingStartDelayMax"
                    :min="listingStartDelayMin"
                    :max="3600"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <div v-if="listingBatchEnabled" class="form-tip">
              批量任务会先打开一家店，随机等待该区间后再打开下一家。
            </div>

            <el-form-item label="商品编码" required>
              <el-select v-model="productCodes" multiple filterable style="width: 100%" placeholder="选择商品编码">
                <el-option v-for="c in productOptions" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>

            <el-form-item label="执行方式">
              <el-radio-group v-model="listingMode">
                <el-radio-button value="check">仅检查</el-radio-button>
                <el-radio-button value="run">正式上架</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>

          <el-button type="primary" size="large" style="width: 100%" @click="runListing">
            {{ listingBatchEnabled ? '提交批量上架' : listingMode === 'check' ? '开始检查' : '开始上架' }}
          </el-button>

          <ResultSummary
            v-if="listingResult"
            :status="listingResult.status"
            :message="listingResult.message"
            :run-id="listingResult.run_id"
            :result="listingResult.result"
            @view-detail="goRunDetail(listingResult!.run_id)"
          />

          <el-table v-if="listingBatchResult" :data="listingBatchResult.runs" size="small" stripe class="batch-table">
            <el-table-column prop="account_id" label="店铺" width="140" />
            <el-table-column prop="run_id" label="任务编号" min-width="220" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" @click="goRunDetail(row.run_id)">查看记录</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="商品下架" name="delist">
        <div class="section-tip">
          “仅扫描”不会真正下架。批量下架前建议先批量扫描，确认命中结果后再执行。
        </div>

        <el-card shadow="never" class="stat-card">
          <el-form label-position="top" class="task-form">
            <el-form-item label="批量店铺">
              <el-switch v-model="delistBatchEnabled" active-text="开启" inactive-text="关闭" />
            </el-form-item>

            <el-form-item v-if="delistBatchEnabled" label="选择店铺" required>
              <el-select v-model="delistBatchAccountIds" multiple filterable style="width: 100%" placeholder="选择要执行的店铺">
                <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>

            <el-form-item v-else label="选择店铺" required>
              <el-select v-model="delistAccountId" style="width: 100%" placeholder="请选择">
                <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
              </el-select>
            </el-form-item>

            <el-row :gutter="20">
              <el-col :span="14">
                <el-form-item label="可下架最早创建时间">
                  <el-input v-model="delistMinCreated" placeholder="2026-06-04 14:25" />
                </el-form-item>
              </el-col>
              <el-col :span="10">
                <el-form-item label="单店最多处理数量">
                  <el-input-number v-model="delistMaxPerRun" :min="1" :max="500" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item v-if="delistBatchEnabled" label="同时运行店铺数">
              <el-input-number v-model="delistConcurrentStores" :min="1" :max="5" style="width: 100%" />
            </el-form-item>

            <el-row v-if="delistBatchEnabled" :gutter="20">
              <el-col :span="12">
                <el-form-item label="启动间隔最小秒数">
                  <el-input-number v-model="delistStartDelayMin" :min="0" :max="3600" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="启动间隔最大秒数">
                  <el-input-number
                    v-model="delistStartDelayMax"
                    :min="delistStartDelayMin"
                    :max="3600"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <div v-if="delistBatchEnabled" class="form-tip">
              批量任务会先打开一家店，随机等待该区间后再打开下一家。
            </div>

            <el-form-item label="执行方式">
              <el-radio-group v-model="delistMode">
                <el-radio-button value="scan">仅扫描</el-radio-button>
                <el-radio-button value="run">执行下架</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>

          <el-button :type="delistMode === 'scan' ? 'warning' : 'danger'" size="large" style="width: 100%" @click="runDelist">
            {{ delistBatchEnabled ? '提交批量下架' : delistMode === 'scan' ? '扫描可下架商品' : '确认执行下架' }}
          </el-button>

          <ResultSummary
            v-if="delistResult"
            :status="delistResult.status"
            :message="delistResult.message"
            :run-id="delistResult.run_id"
            :result="delistResult.result"
            @view-detail="goRunDetail(delistResult!.run_id)"
          />

          <el-table v-if="delistBatchResult" :data="delistBatchResult.runs" size="small" stripe class="batch-table">
            <el-table-column prop="account_id" label="店铺" width="140" />
            <el-table-column prop="run_id" label="任务编号" min-width="220" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button link type="primary" @click="goRunDetail(row.run_id)">查看记录</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.task-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.task-form {
  max-width: 760px;
}

.batch-table {
  margin-top: 16px;
}
</style>
