<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import type { ConfigSummary, RuntimeConfig } from '@/types'

const loading = ref(false)
const saving = ref(false)
const clearingFeishuCache = ref(false)
const summary = ref<ConfigSummary | null>(null)

const form = reactive<RuntimeConfig>({
  app: {
    name: 'pdd-agent-platform',
    log_level: 'INFO',
  },
  paths: {
    assets_root: 'data/assets/商品上架规格文件',
    profiles_root: 'data/profiles',
    runs_root: 'data/runs',
  },
  browser: {
    headless: false,
    slow_mo: 0,
    default_timeout_ms: 30000,
    base_url: 'https://mms.pinduoduo.com',
    channel: '',
  },
  multi_spec: {
    excel: 'data/assets/拼多多所有商品.xls',
    defaults: {
      inventory: '10',
      group_price: '199.9',
      single_price: '299.9',
    },
  },
  listing: {
    category_keyword: '玩偶',
    title_mode: 'page_ai',
  },
  delist: {
    min_created_after: '',
    dry_run: true,
    merchant_code_contains: '',
    max_delist_per_run: 50,
    account_ids: [],
  },
  batch: {
    max_concurrent_stores: 3,
    store_start_delay_min_seconds: 30,
    store_start_delay_max_seconds: 180,
    activity_schedule_jitter_max_seconds: 1800,
  },
})

function applyConfig(cfg: RuntimeConfig) {
  form.app = { ...cfg.app }
  form.paths = { ...cfg.paths }
  form.browser = { ...cfg.browser }
  form.multi_spec = {
    excel: cfg.multi_spec.excel,
    defaults: {
      inventory: cfg.multi_spec.defaults.inventory ?? '10',
      group_price: cfg.multi_spec.defaults.group_price ?? '199.9',
      single_price: cfg.multi_spec.defaults.single_price ?? '299.9',
    },
  }
  form.listing = { ...cfg.listing }
  form.delist = { ...cfg.delist, account_ids: [...cfg.delist.account_ids] }
  form.batch = { ...cfg.batch }
}

async function load() {
  loading.value = true
  try {
    const [cfg, sum] = await Promise.all([api.runtimeConfig(), api.configSummary()])
    applyConfig(cfg)
    summary.value = sum
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '加载配置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const cfg = await api.updateRuntimeConfig(JSON.parse(JSON.stringify(form)))
    applyConfig(cfg)
    summary.value = await api.configSummary()
    ElMessage.success('系统设置已保存')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function clearFeishuCache() {
  clearingFeishuCache.value = true
  try {
    const result = await api.feishuClearCache()
    if (result.success) {
      ElMessage.success(
        `${result.message}（${result.cleared.length} 项：${result.cleared.join('、')}）`,
      )
    } else {
      ElMessage.warning(result.message || '部分缓存清理失败')
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '清理飞书缓存失败')
  } finally {
    clearingFeishuCache.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <PageHeader title="系统设置" desc="维护素材路径、浏览器参数、默认上架与下架规则。">
      <template #actions>
        <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
      </template>
    </PageHeader>

    <el-alert
      v-if="summary?.database_configured"
      :type="summary.database_available ? 'success' : 'warning'"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    >
      <template #title>
        {{ summary.database_available ? 'MySQL 已连接' : 'MySQL 未连接' }}
      </template>
      <template #default>
        {{ summary.database_available ? '店铺和运行记录会写入 MySQL。' : summary.database_error }}
      </template>
    </el-alert>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never" class="stat-card settings-card">
          <template #header>基础配置</template>
          <el-form label-position="top">
            <el-form-item label="系统名称">
              <el-input v-model="form.app.name" />
            </el-form-item>
            <el-form-item label="日志级别">
              <el-select v-model="form.app.log_level" style="width: 100%">
                <el-option label="INFO" value="INFO" />
                <el-option label="DEBUG" value="DEBUG" />
                <el-option label="WARNING" value="WARNING" />
                <el-option label="ERROR" value="ERROR" />
              </el-select>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="never" class="stat-card settings-card">
          <template #header>素材与数据路径</template>
          <el-form label-position="top">
            <el-form-item label="素材根目录">
              <el-input v-model="form.paths.assets_root" />
              <div class="form-tip">相对 myTest 根目录，固定使用 data/assets/商品上架规格文件</div>
            </el-form-item>
            <el-form-item label="浏览器 Profile 目录">
              <el-input v-model="form.paths.profiles_root" />
            </el-form-item>
            <el-form-item label="运行记录目录">
              <el-input v-model="form.paths.runs_root" />
              <div class="form-tip">MySQL 不可用时会回退写入该目录</div>
            </el-form-item>
            <el-form-item label="商品表路径（拼多多所有商品.xls）">
              <el-input v-model="form.multi_spec.excel" />
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="never" class="stat-card settings-card">
          <template #header>浏览器参数</template>
          <el-form label-position="top">
            <el-form-item label="后台运行">
              <el-switch v-model="form.browser.headless" active-text="开启" inactive-text="关闭" />
            </el-form-item>
            <el-form-item label="慢动作延迟(ms)">
              <el-input-number v-model="form.browser.slow_mo" :min="0" :max="5000" style="width: 100%" />
            </el-form-item>
            <el-form-item label="默认等待超时(ms)">
              <el-input-number
                v-model="form.browser.default_timeout_ms"
                :min="5000"
                :max="180000"
                :step="5000"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="商家后台地址">
              <el-input v-model="form.browser.base_url" />
            </el-form-item>
            <el-form-item label="浏览器通道">
              <el-select v-model="form.browser.channel" clearable style="width: 100%" placeholder="Playwright Chromium">
                <el-option label="Playwright Chromium" value="" />
                <el-option label="本机 Chrome" value="chrome" />
                <el-option label="Microsoft Edge" value="msedge" />
              </el-select>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="never" class="stat-card settings-card">
          <template #header>飞书数据缓存</template>
          <p class="form-tip" style="margin-top: 0">
            修改飞书「拼多多比价定价」表后，若上架仍读到旧数据，可在此清空当前后端进程的内存缓存（商品表、比价定价、上架快照等，默认约 5 分钟自动过期）。
          </p>
          <p class="form-tip">
            若后端为多 worker 部署，每个进程各有一份缓存；点一次只清当前处理请求的 worker，仍异常时可重启后端。
          </p>
          <el-button type="warning" plain :loading="clearingFeishuCache" @click="clearFeishuCache">
            清空飞书数据缓存
          </el-button>
        </el-card>

        <el-card shadow="never" class="stat-card settings-card">
          <template #header>上架 / 下架默认值</template>
          <el-form label-position="top">
            <el-row :gutter="12">
              <el-col :span="8">
                <el-form-item label="默认库存">
                  <el-input v-model="form.multi_spec.defaults.inventory" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="默认拼单价">
                  <el-input v-model="form.multi_spec.defaults.group_price" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="默认单买价">
                  <el-input v-model="form.multi_spec.defaults.single_price" />
                </el-form-item>
              </el-col>
            </el-row>

            <el-form-item label="默认类目关键词">
              <el-input v-model="form.listing.category_keyword" />
            </el-form-item>
            <el-form-item label="标题来源">
              <el-select v-model="form.listing.title_mode" style="width: 100%">
                <el-option label="页面 AI 推荐" value="page_ai" />
                <el-option label="自定义标题" value="custom" />
                <el-option label="LLM 生成" value="ai" />
              </el-select>
            </el-form-item>
            <el-form-item label="默认下架门槛时间">
              <el-input v-model="form.delist.min_created_after" placeholder="2026-06-04 14:25" />
            </el-form-item>
            <el-form-item label="下架试运行默认开启">
              <el-switch v-model="form.delist.dry_run" active-text="开启" inactive-text="关闭" />
            </el-form-item>
            <el-form-item label="商家编码包含">
              <el-input v-model="form.delist.merchant_code_contains" clearable />
            </el-form-item>
            <el-form-item label="单店最多下架数量">
              <el-input-number v-model="form.delist.max_delist_per_run" :min="1" :max="500" style="width: 100%" />
            </el-form-item>
            <el-form-item label="批量任务并发店铺数">
              <el-input-number
                v-model="form.batch.max_concurrent_stores"
                :min="1"
                :max="5"
                style="width: 100%"
              />
              <div class="form-tip">正式跑浏览器时建议 3-5 家，机器配置低时用 1-2 家。</div>
            </el-form-item>
            <el-row :gutter="12">
              <el-col :span="12">
                <el-form-item label="店铺启动间隔最小秒数">
                  <el-input-number
                    v-model="form.batch.store_start_delay_min_seconds"
                    :min="0"
                    :max="3600"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="店铺启动间隔最大秒数">
                  <el-input-number
                    v-model="form.batch.store_start_delay_max_seconds"
                    :min="form.batch.store_start_delay_min_seconds"
                    :max="3600"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="活动预约抖动上限（秒）">
              <el-input-number
                v-model="form.batch.activity_schedule_jitter_max_seconds"
                :min="0"
                :max="7200"
                style="width: 100%"
              />
              <div class="form-tip">整合链路上架完成后，活动任务在基础延迟上再随机 0～该值 秒，避免几百条同时到期。默认 1800（30 分钟）。</div>
            </el-form-item>
            <div class="form-tip">批量任务会先启动一家店，再随机等待这个区间后启动下一家。</div>
          </el-form>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.settings-card {
  margin-bottom: 16px;
}
</style>
