<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import ResultSummary from '@/components/ResultSummary.vue'
import type { Account, DelistTaskResponse, ListingTaskResponse } from '@/types'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const success = ref('')
const activeTab = ref('listing')

const accounts = ref<Account[]>([])
const productOptions = ref<string[]>([])

// 上架
const accountId = ref('')
const productCodes = ref<string[]>([])
const listingMode = ref<'check' | 'run'>('check')
const categoryKeyword = ref('玩偶')
const listingResult = ref<ListingTaskResponse | null>(null)

// 下架
const delistAccountId = ref('')
const delistMode = ref<'scan' | 'run'>('scan')
const delistMinCreated = ref('2026-06-04 14:25')
const delistMaxPerRun = ref(1)
const delistResult = ref<DelistTaskResponse | null>(null)

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))

async function loadMeta() {
  try {
    const [accs, products] = await Promise.all([api.accounts(true), api.products()])
    accounts.value = accs
    productOptions.value = products.map((p) => p.product_code)
    if (accs.length && !accountId.value) {
      accountId.value = accs[0].account_id
      productCodes.value = [...accs[0].product_codes]
      delistAccountId.value = accs[0].account_id
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

async function runListing() {
  if (!accountId.value) {
    error.value = '请先选择店铺'
    return
  }
  if (!productCodes.value.length) {
    error.value = '请至少选择一个商品编码'
    return
  }
  loading.value = true
  error.value = ''
  success.value = ''
  listingResult.value = null
  const isCheck = listingMode.value === 'check'
  try {
    listingResult.value = await api.listing({
      account_id: accountId.value,
      product_codes: productCodes.value,
      dry_run: isCheck,
      category_keyword: categoryKeyword.value,
      background: !isCheck,
    })
    success.value = isCheck
      ? '素材检查完成，请查看下方结果'
      : '上架任务已提交，浏览器会自动操作，请勿关闭弹出的窗口'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    loading.value = false
  }
}

async function runDelist() {
  if (!delistAccountId.value) {
    error.value = '请先选择店铺'
    return
  }
  loading.value = true
  error.value = ''
  success.value = ''
  delistResult.value = null
  const isScan = delistMode.value === 'scan'
  try {
    delistResult.value = await api.delist({
      account_id: delistAccountId.value,
      dry_run: isScan,
      min_created_after: delistMinCreated.value,
      max_delist_per_run: delistMaxPerRun.value,
      background: true,
    })
    success.value = isScan
      ? '扫描完成，请查看符合下架条件的商品数量'
      : '下架任务已提交，请在浏览器窗口确认操作'
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
      desc="选择店铺和商品，系统会自动打开浏览器完成操作。首次使用需手工完成登录验证。"
    />

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 12px" @close="error = ''" />
    <el-alert v-if="success" type="success" :title="success" show-icon closable style="margin-bottom: 12px" @close="success = ''" />

    <el-tabs v-model="activeTab" class="task-tabs">
      <el-tab-pane label="商品上架" name="listing">
        <div class="section-tip">
          <strong>上架前建议：</strong>先到「素材检查」确认图片和 SKU 无报错，再选「正式上架」。
          正式上架时会弹出 Chrome 窗口，<strong>不要关闭</strong>，如需登录请手工完成验证。
        </div>

        <el-card shadow="never" class="stat-card">
          <el-form label-position="top" class="task-form">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="选择店铺" required>
                  <el-select v-model="accountId" style="width: 100%" placeholder="请选择" @change="onAccountChange">
                    <el-option
                      v-for="a in enabledAccounts"
                      :key="a.account_id"
                      :label="a.account_id"
                      :value="a.account_id"
                    />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="拼多多类目关键词">
                  <el-input v-model="categoryKeyword" placeholder="如：玩偶、挂件" />
                  <div class="form-tip">发布商品时搜索类目用的关键词</div>
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="要上架的商品编码" required>
              <el-select
                v-model="productCodes"
                multiple
                filterable
                style="width: 100%"
                placeholder="选择商品编码，可多选"
              >
                <el-option v-for="c in productOptions" :key="c" :label="c" :value="c" />
              </el-select>
              <div class="form-tip">可在「店铺设置」里配置默认商品，这里会自动带入</div>
            </el-form-item>

            <el-form-item label="执行方式">
              <el-radio-group v-model="listingMode">
                <el-radio-button value="check">仅检查（不打开浏览器）</el-radio-button>
                <el-radio-button value="run">正式上架</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>

          <el-button
            type="primary"
            size="large"
            style="width: 100%"
            @click="runListing"
          >
            {{ listingMode === 'check' ? '开始检查' : '开始上架' }}
          </el-button>

          <ResultSummary
            v-if="listingResult"
            :status="listingResult.status"
            :message="listingResult.message"
            :run-id="listingResult.run_id"
            :result="listingResult.result"
            @view-detail="goRunDetail(listingResult!.run_id)"
          />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="商品下架" name="delist">
        <div class="section-tip">
          <strong>安全提示：</strong>默认「仅扫描」不会真的下架。确认扫描结果无误后，再切换为「执行下架」。
          只会下架<strong>创建时间晚于</strong>下方设定时间的商品。
        </div>

        <el-card shadow="never" class="stat-card">
          <el-form label-position="top" class="task-form">
            <el-form-item label="选择店铺" required>
              <el-select v-model="delistAccountId" style="width: 100%" placeholder="请选择">
                <el-option
                  v-for="a in enabledAccounts"
                  :key="a.account_id"
                  :label="a.account_id"
                  :value="a.account_id"
                />
              </el-select>
            </el-form-item>

            <el-row :gutter="20">
              <el-col :span="14">
                <el-form-item label="可下架的最早创建时间">
                  <el-input v-model="delistMinCreated" placeholder="2026-06-04 14:25" />
                  <div class="form-tip">只有创建时间<strong>严格晚于</strong>这个时间的商品才会被下架</div>
                </el-form-item>
              </el-col>
              <el-col :span="10">
                <el-form-item label="本次最多处理几条">
                  <el-input-number v-model="delistMaxPerRun" :min="1" :max="50" style="width: 100%" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="执行方式">
              <el-radio-group v-model="delistMode">
                <el-radio-button value="scan">仅扫描（不实际下架）</el-radio-button>
                <el-radio-button value="run">执行下架</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>

          <el-button
            :type="delistMode === 'scan' ? 'warning' : 'danger'"
            size="large"
            style="width: 100%"
            @click="runDelist"
          >
            {{ delistMode === 'scan' ? '扫描可下架商品' : '确认执行下架' }}
          </el-button>

          <ResultSummary
            v-if="delistResult"
            :status="delistResult.status"
            :message="delistResult.message"
            :run-id="delistResult.run_id"
            :result="delistResult.result"
            @view-detail="goRunDetail(delistResult!.run_id)"
          />
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
  max-width: 720px;
}
</style>
