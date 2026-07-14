<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import ResultSummary from '@/components/ResultSummary.vue'
import { useMinioMaterialRefresh, type MinioHealthInfo } from '@/composables/useMinioMaterialRefresh'
import type { Account, ListingTargetOption, ListingTaskResponse } from '@/types'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const success = ref('')

const accounts = ref<Account[]>([])
const productOptions = ref<ListingTargetOption[]>([])
const accountId = ref('')
const productCodes = ref<string[]>([])
const listingMode = ref<'check' | 'run'>('run')
const categoryKeyword = ref('玩偶')
const listingResult = ref<ListingTaskResponse | null>(null)
const materialSource = ref<'local' | 'minio'>('minio')
const minioHealth = ref<MinioHealthInfo | null>(null)

const slotAlignmentTest = ref(false)
const specFillVerifyTest = ref(true)
const primaryStyleFirstTest = ref(true)
const categoryNextBurstDemo = ref(true)
const accessoryCostPricing = ref(true)
const accessoryTieredFloat = ref(true)
const brandName = ref('无品牌')
const manufacturerName = ref('')
const attrsHydrated = ref(false)
let persistTimer: ReturnType<typeof setTimeout> | null = null

const enabledAccounts = computed(() => accounts.value.filter((a) => a.enabled))

async function persistCategoryAttrs() {
  const cfg = await api.runtimeConfig()
  await api.updateRuntimeConfig({
    ...cfg,
    listing: {
      ...cfg.listing,
      category_keyword: categoryKeyword.value || cfg.listing.category_keyword || '玩偶',
      brand_name: brandName.value || '无品牌',
      manufacturer_name: manufacturerName.value || '',
    },
  })
}

function schedulePersistCategoryAttrs() {
  if (!attrsHydrated.value) return
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(() => {
    void persistCategoryAttrs().catch((e) => {
      console.warn('类目属性持久化失败', e)
    })
  }, 400)
}

function filterValidProductCodes(codes: string[]) {
  const valid = new Set(productOptions.value.map((item) => item.selector))
  return (codes || []).filter((code) => valid.has(code))
}

async function loadMinioHealth() {
  try {
    minioHealth.value = await api.minioHealth()
  } catch (e) {
    minioHealth.value = { available: false, error: e instanceof Error ? e.message : 'MinIO 不可用' }
  }
}

async function loadListingTargets() {
  productOptions.value = await api.listingTargets(materialSource.value)
  productCodes.value = filterValidProductCodes(productCodes.value)
}

async function loadMeta() {
  attrsHydrated.value = false
  try {
    const [accs, cfg] = await Promise.all([api.accounts(true), api.runtimeConfig()])
    accounts.value = accs
    categoryKeyword.value = cfg.listing.category_keyword || '玩偶'
    slotAlignmentTest.value = cfg.listing.slot_alignment_test
    specFillVerifyTest.value = cfg.listing.spec_fill_verify_test
    primaryStyleFirstTest.value = cfg.listing.primary_style_first_test
    categoryNextBurstDemo.value = cfg.listing.category_next_burst_demo
    accessoryCostPricing.value = cfg.listing.accessory_cost_pricing
    accessoryTieredFloat.value = cfg.listing.accessory_tiered_float
    brandName.value = cfg.listing.brand_name || '无品牌'
    manufacturerName.value = cfg.listing.manufacturer_name || ''

    if (materialSource.value === 'minio') {
      await loadMinioHealth()
    }
    await loadListingTargets()

    if (accs.length && !accountId.value) {
      accountId.value = accs[0].account_id
      productCodes.value = filterValidProductCodes(accs[0].product_codes)
    }
    attrsHydrated.value = true
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
}

const { materialPolling, materialRefreshPaused, refreshMode, restart, setMaterialRefreshPaused } =
  useMinioMaterialRefresh({
    materialSource,
    minioHealth,
    onRefresh: loadListingTargets,
  })

async function onMaterialSourceChange(source: 'local' | 'minio') {
  materialSource.value = source
  productCodes.value = []
  if (source === 'minio') {
    await loadMinioHealth()
    if (!minioHealth.value?.available) {
      ElMessage.warning(minioHealth.value?.error || 'MinIO 未就绪，请检查 config/minio.yaml')
    }
  }
  await loadListingTargets()
  restart()
}

function onAccountChange(id: string) {
  const acc = accounts.value.find((a) => a.account_id === id)
  productCodes.value = acc ? filterValidProductCodes(acc.product_codes) : []
}

async function runListing() {
  if (!accountId.value) {
    error.value = '请选择店铺'
    return
  }
  if (!productCodes.value.length) {
    error.value = '请至少选择一个商品/套图'
    return
  }

  loading.value = true
  error.value = ''
  success.value = ''
  listingResult.value = null

  try {
    await persistCategoryAttrs()
    listingResult.value = await api.createListing({
      account_id: accountId.value,
      product_codes: productCodes.value,
      dry_run: listingMode.value === 'check',
      category_keyword: categoryKeyword.value,
      material_source: materialSource.value,
      slot_alignment_test: slotAlignmentTest.value,
      spec_fill_verify_test: specFillVerifyTest.value,
      primary_style_first_test: primaryStyleFirstTest.value,
      category_next_burst_demo: categoryNextBurstDemo.value,
      accessory_cost_pricing: accessoryCostPricing.value,
      accessory_tiered_float: accessoryTieredFloat.value,
      brand_name: brandName.value || '无品牌',
      manufacturer_name: manufacturerName.value || '',
    })
    success.value =
      listingMode.value === 'check'
        ? '素材检查任务已提交'
        : '上架任务已提交，浏览器将自动打开。可在操作记录查看进度。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    loading.value = false
  }
}

function goRunDetail(runId: string) {
  router.push({ path: '/runs', query: { id: runId } })
}

watch(accountId, onAccountChange)
watch([brandName, manufacturerName, categoryKeyword], schedulePersistCategoryAttrs)

onMounted(async () => {
  await loadMeta()
  restart()
})
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="商品上架" desc="自动完成抖店发布页 Step1~4（含规格创建类型填表：颜色分类/尺寸大小）。" />

    <el-alert v-if="error" type="error" :title="error" show-icon closable style="margin-bottom: 12px" @close="error = ''" />
    <el-alert v-if="success" type="success" :title="success" show-icon closable style="margin-bottom: 12px" @close="success = ''" />

    <div class="section-tip">
      正式上架会打开浏览器，首次需先完成短信登录。MinIO 模式下上架前会自动从 MinIO 同步图片到本地缓存。
    </div>

    <el-card shadow="never" class="stat-card">
      <el-form label-position="top" class="task-form">
        <el-form-item label="选择店铺" required>
          <el-select v-model="accountId" style="width: 100%" placeholder="请选择">
            <el-option v-for="a in enabledAccounts" :key="a.account_id" :label="a.account_id" :value="a.account_id" />
          </el-select>
        </el-form-item>

        <div class="material-source-bar">
          <span class="material-source-label">素材来源</span>
          <el-radio-group
            :model-value="materialSource"
            size="small"
            @change="onMaterialSourceChange($event as 'local' | 'minio')"
          >
            <el-radio-button label="local">本地文件夹</el-radio-button>
            <el-radio-button label="minio">MinIO</el-radio-button>
          </el-radio-group>
          <el-tag
            v-if="materialSource === 'minio'"
            size="small"
            :type="minioHealth?.available ? 'success' : 'danger'"
          >
            {{ minioHealth?.available ? 'MinIO 已连接' : (minioHealth?.error || 'MinIO 未连接') }}
          </el-tag>
          <el-tag v-if="materialSource === 'minio' && materialRefreshPaused" size="small" type="warning">
            已暂停拉取
          </el-tag>
          <el-tag
            v-else-if="materialSource === 'minio' && refreshMode === 'poll' && materialPolling"
            size="small"
            type="info"
          >
            自动刷新
          </el-tag>
          <template v-if="materialSource === 'minio'">
            <el-switch
              :model-value="!materialRefreshPaused"
              inline-prompt
              active-text="自动拉取"
              inactive-text="已关闭"
              @change="setMaterialRefreshPaused(!$event)"
            />
            <el-button link type="primary" size="small" @click="loadListingTargets">刷新列表</el-button>
          </template>
        </div>

        <el-form-item label="商品 / 套图" required>
          <el-select v-model="productCodes" multiple filterable style="width: 100%" placeholder="如 BD046/第一套">
            <el-option
              v-for="item in productOptions"
              :key="item.selector"
              :label="`${item.selector}（${item.product_count}个商品）`"
              :value="item.selector"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="类目关键词">
          <el-input
            v-model="categoryKeyword"
            placeholder="如：玩偶"
            @blur="schedulePersistCategoryAttrs"
          />
        </el-form-item>

        <el-form-item label="类目属性（基础信息必填）">
          <div class="attr-grid">
            <div>
              <div class="attr-label">品牌</div>
              <el-input
                v-model="brandName"
                placeholder="默认：无品牌（搜索后选第一项）"
                @blur="schedulePersistCategoryAttrs"
              />
            </div>
            <div>
              <div class="attr-label">生产企业名称</div>
              <el-input
                v-model="manufacturerName"
                placeholder="必填，填入文本框的内容"
                @blur="schedulePersistCategoryAttrs"
              />
            </div>
          </div>
        </el-form-item>

        <el-form-item label="执行方式">
          <el-radio-group v-model="listingMode">
            <el-radio-button value="check">仅检查（dry_run）</el-radio-button>
            <el-radio-button value="run">正式上架</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="试验开关（可选）">
          <div class="flag-grid">
            <el-checkbox v-model="slotAlignmentTest">
              <el-tooltip content="待开发：规格槽位对齐" placement="top">槽位对齐</el-tooltip>
            </el-checkbox>
            <el-checkbox v-model="specFillVerifyTest">
              <el-tooltip content="已实现：逐行填写价格/现货库存/商家编码，并正向+反查校验" placement="top">规格填表校验</el-tooltip>
            </el-checkbox>
            <el-checkbox v-model="primaryStyleFirstTest">
              <el-tooltip content="已实现：上架前将主款款式排到第一位" placement="top">主款优先</el-tooltip>
            </el-checkbox>
            <el-checkbox v-model="categoryNextBurstDemo">
              <el-tooltip content="已实现：类目渲染与下一步连点" placement="top">类目连点下一步</el-tooltip>
            </el-checkbox>
            <el-checkbox v-model="accessoryCostPricing">
              <el-tooltip content="已实现：飞书算价写入 SKU，Step5 填入价格/库存" placement="top">配件成本定价</el-tooltip>
            </el-checkbox>
            <el-checkbox v-model="accessoryTieredFloat">
              <el-tooltip content="已实现：子商品按成本档位浮动（需开启配件成本定价）" placement="top">配件阶梯浮动</el-tooltip>
            </el-checkbox>
          </div>
        </el-form-item>
      </el-form>

      <el-button type="primary" size="large" style="width: 100%" @click="runListing">
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
  </div>
</template>

<style scoped>
.task-form { max-width: 640px; }
.flag-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; }
.attr-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  width: 100%;
}
.attr-label {
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
}
.material-source-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}
.material-source-label {
  font-size: 14px;
  color: var(--el-text-color-regular);
}
</style>
