<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import PageHeader from '@/components/PageHeader.vue'
import { useMinioSync } from '@/composables/useMinioSync'
import { useMinioMaterialRefresh } from '@/composables/useMinioMaterialRefresh'
import { issueLevelLabel } from '@/utils/labels'
import { formatAutoPipelineFeedback } from '@/utils/autoPipeline'
import { groupListingTargetsByFamily } from '@/utils/listingTargets'
import type { ListingUnit, PreflightResponse, ProductSummary, SkuCombo, ListingTargetOption } from '@/types'

interface PreviewImage {
  label: string
  path: string
  meta: string
}

const router = useRouter()
const loading = ref(false)
const products = ref<ProductSummary[]>([])
const materialSource = ref<'local' | 'minio'>('minio')
const minioHealth = ref<{
  available?: boolean
  error?: string
  refresh_mode?: 'poll' | 'rabbitmq'
  listing_poll_seconds?: number
  alist_url?: string
  console_url?: string
  alist?: {
    configured?: boolean
    available?: boolean
    error?: string
    root_path?: string
  }
  upload_categories?: string[]
} | null>(null)
const selectedCodes = ref<string[]>([])
const preflight = ref<PreflightResponse | null>(null)
const error = ref('')
const { minioSyncJob, syncing, startSync, resumeActiveSync } = useMinioSync()

const imagePanelTitle = ref('')
const previewImages = ref<PreviewImage[]>([])

const skuDrawerVisible = ref(false)
const activeUnit = ref<ListingUnit | null>(null)
const activeSku = ref<SkuCombo | null>(null)

const rabbitmqLoading = ref(false)
const uploading = ref(false)
const rabbitmqQueues = ref<Array<{ name: string; messages?: number; consumers?: number }>>([])
const rabbitmqSuggested = ref('')
const rabbitmqSelectedQueue = ref('')
const rabbitmqAmqpError = ref('')
const rabbitmqRecent = ref<Array<Record<string, unknown>>>([])
const rabbitmqPeek = ref('')
const rabbitmqBindingStatus = ref('')
const rabbitmqDebugOpen = ref<string[]>([])
const uploadCategory = ref('笔袋')
type UploadMode = 'family' | 'image_set' | 'product'
const uploadMode = ref<UploadMode>('family')
const uploadTargetFamily = ref('')
const uploadTargetImageSet = ref('')
const uploadListingTargets = ref<ListingTargetOption[]>([])
const uploadFolderName = ref('')
const uploadFolderEntries = ref<Array<{ file: File; relativePath: string }>>([])
const uploadFolderInputRef = ref<HTMLInputElement | null>(null)

const uploadImageCount = computed(() =>
  uploadFolderEntries.value.filter((item) => /\.(jpe?g|png|webp|gif)$/i.test(item.relativePath)).length,
)

const uploadCategoryOptions = computed(() => {
  const fromHealth = minioHealth.value?.upload_categories?.filter(Boolean)
  return fromHealth?.length ? fromHealth : ['笔袋', '公仔', '视频']
})

const uploadFamilyGroups = computed(() => groupListingTargetsByFamily(uploadListingTargets.value))

const uploadFamilyOptions = computed(() =>
  uploadFamilyGroups.value.map((group) => group.family_code).sort(),
)

const uploadImageSetOptions = computed(() => {
  const family = uploadTargetFamily.value.trim()
  if (!family) return []
  const group = uploadFamilyGroups.value.find((item) => item.family_code === family)
  return (group?.options ?? []).map((item) => item.image_set)
})

const uploadFolderPreview = computed(() => {
  if (!uploadFolderEntries.value.length) return ''
  const sample = uploadFolderEntries.value
    .slice(0, 5)
    .map((item) => item.relativePath)
    .join('\n')
  const more =
    uploadFolderEntries.value.length > 5
      ? `\n... 共 ${uploadFolderEntries.value.length} 个文件`
      : ''

  const category = uploadCategory.value
  const folder = uploadFolderName.value || '未命名文件夹'
  let targetPrefix = `${category}/${folder}`
  if (uploadMode.value === 'image_set') {
    const family = uploadTargetFamily.value || '款号'
    targetPrefix = `${category}/${family}/${folder}`
  } else if (uploadMode.value === 'product') {
    const family = uploadTargetFamily.value || '款号'
    const imageSet = uploadTargetImageSet.value || '套图'
    targetPrefix = `${category}/${family}/${imageSet}/${folder}`
  }

  return `目标路径：${targetPrefix}/\n${sample}${more}`
})

const uploadModeHint = computed(() => {
  if (uploadMode.value === 'image_set') {
    return '在已有款号下追加套图：选目标款号（如 BD713）→ 选本地套图文件夹（如 第二套图，内含各商品子目录）'
  }
  if (uploadMode.value === 'product') {
    return '在已有套图下追加商品：选目标款号与套图 → 选本地商品文件夹（如 BD713Z，内含 1.jpg 等）'
  }
  return '上传整款款号：选本地款号文件夹（如 BD713，内含 第一套图/商品编码/图片）'
})

const uploadFolderPlaceholder = computed(() => {
  if (uploadMode.value === 'image_set') return '选择套图文件夹，如 第二套图'
  if (uploadMode.value === 'product') return '选择商品文件夹，如 BD713Z'
  return '选择款号文件夹，如 BD713'
})

async function loadRabbitmqRecent() {
  try {
    const result = await api.minioRabbitmqRecent(10)
    rabbitmqRecent.value = result.batches || result.events || []
  } catch {
    rabbitmqRecent.value = []
  }
}

const {
  materialPolling,
  sseConnected,
  switchingMode,
  materialRefreshPaused,
  refreshMode,
  restart: restartMaterialRefresh,
  stop: stopMaterialRefresh,
  setMaterialRefreshPaused,
  setRefreshMode,
} = useMinioMaterialRefresh({
  materialSource,
  minioHealth,
  reloadHealth: loadMinioHealth,
  onRefresh: loadProducts,
  onUploadBatch: () => loadRabbitmqRecent(),
})

watch(refreshMode, (mode) => {
  if (mode === 'rabbitmq' && materialSource.value === 'minio') {
    void loadRabbitmqRecent()
  }
})

watch(uploadMode, () => {
  uploadFolderName.value = ''
  uploadFolderEntries.value = []
})

watch(uploadTargetFamily, (family) => {
  if (!family) {
    uploadTargetImageSet.value = ''
    return
  }
  const sets = uploadImageSetOptions.value
  if (uploadTargetImageSet.value && !sets.includes(uploadTargetImageSet.value)) {
    uploadTargetImageSet.value = sets[0] || ''
  }
})

async function loadUploadListingTargets() {
  if (materialSource.value !== 'minio') {
    uploadListingTargets.value = []
    return
  }
  try {
    uploadListingTargets.value = await api.listingTargets(undefined, 'minio')
  } catch {
    uploadListingTargets.value = []
  }
}

const productKeyword = ref('')
const currentPage = ref(1)
const pageSize = ref(15)

const filteredProducts = computed(() => {
  const keyword = productKeyword.value.trim().toUpperCase()
  if (!keyword) return products.value
  return products.value.filter((p) => p.product_code.toUpperCase().includes(keyword))
})

const paginatedProducts = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredProducts.value.slice(start, start + pageSize.value)
})

const productOptions = computed(() => products.value.map((p) => p.product_code))
const allPassed = computed(() => preflight.value?.ok === true)
const activeSkuRows = computed(() => activeUnit.value?.skus ?? [])

function assetUrl(path: string) {
  const params = new URLSearchParams({
    path,
    material_source: materialSource.value,
  })
  return `/api/catalog/asset?${params.toString()}`
}

function fileName(path: string) {
  return path.split(/[\\/]/).pop() || path
}

async function loadMinioHealth() {
  try {
    minioHealth.value = await api.minioHealth()
    const amqp = (minioHealth.value as { rabbitmq?: { amqp?: { error?: string } } })?.rabbitmq?.amqp
    rabbitmqAmqpError.value = amqp?.error || ''
  } catch (e) {
    minioHealth.value = { available: false, error: e instanceof Error ? e.message : 'MinIO 不可用' }
  }
}

async function loadRabbitmqQueues(manageLoading = true) {
  if (materialSource.value !== 'minio') return
  if (manageLoading) rabbitmqLoading.value = true
  try {
    const result = await api.minioRabbitmqQueues()
    rabbitmqQueues.value = result.queues || []
    rabbitmqSuggested.value = result.suggested_queue || ''
    rabbitmqSelectedQueue.value = result.configured_queue || result.suggested_queue || ''
    rabbitmqAmqpError.value = result.amqp?.error || result.management_error || ''
    if (manageLoading && !result.available && rabbitmqAmqpError.value) {
      ElMessage.warning(`RabbitMQ 连接失败：${rabbitmqAmqpError.value}`)
    }
    await loadRabbitmqBindingStatus()
  } catch (e) {
    if (manageLoading) {
      ElMessage.error(e instanceof Error ? e.message : '获取队列失败')
    }
  } finally {
    if (manageLoading) rabbitmqLoading.value = false
  }
}

async function saveRabbitmqQueue() {
  if (!rabbitmqSelectedQueue.value) {
    ElMessage.warning('请先选择队列')
    return
  }
  rabbitmqLoading.value = true
  try {
    await api.saveMinioRabbitmqQueue(rabbitmqSelectedQueue.value)
    ElMessage.success(`已保存队列：${rabbitmqSelectedQueue.value}`)
    await loadMinioHealth()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存队列失败')
  } finally {
    rabbitmqLoading.value = false
  }
}

async function loadRabbitmqBindingStatus() {
  if (materialSource.value !== 'minio') {
    rabbitmqBindingStatus.value = ''
    return
  }
  try {
    const result = await api.minioRabbitmqBindings(rabbitmqSelectedQueue.value)
    if (!result.available) {
      rabbitmqBindingStatus.value = result.error || '无法读取 bindings'
      return
    }
    if (result.minio_events_bound) {
      rabbitmqBindingStatus.value = `已绑定 ${result.expected_exchange} · ${result.expected_routing_key}`
      return
    }
    rabbitmqBindingStatus.value = `未绑定 MinIO 事件（需 ${result.expected_exchange} / ${result.expected_routing_key}）`
  } catch {
    rabbitmqBindingStatus.value = ''
  }
}

async function ensureRabbitmqBinding() {
  rabbitmqLoading.value = true
  try {
    const result = await api.ensureMinioRabbitmqBinding(
      rabbitmqSelectedQueue.value ? { queue: rabbitmqSelectedQueue.value } : undefined,
    )
    await loadRabbitmqBindingStatus()
    await loadRabbitmqQueues(false)
    restartMaterialRefresh()
    ElMessage.success(
      `已恢复 binding：${result.exchange} / ${result.routing_key} -> ${result.queue}`,
    )
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '恢复 binding 失败')
  } finally {
    rabbitmqLoading.value = false
  }
}

async function peekRabbitmqMessage() {
  rabbitmqLoading.value = true
  rabbitmqPeek.value = ''
  try {
    const result = await api.peekMinioRabbitmq(rabbitmqSelectedQueue.value)
    if (!result.found) {
      rabbitmqPeek.value = '队列为空，暂无消息'
    } else {
      rabbitmqPeek.value = result.body_preview || ''
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '窥探消息失败')
  } finally {
    rabbitmqLoading.value = false
  }
}

function batchTagType(item: Record<string, unknown>) {
  const groups = item.groups as Array<{ change_type?: string }> | undefined
  const type = groups?.[0]?.change_type
  if (type === 'new_product_folder' || type === 'new_image_set') return 'success'
  if (type === 'append_to_product') return 'warning'
  return 'info'
}

/** 进入 MinIO 模式：按当前配置启动轮询或 RabbitMQ，不强制改模式 */
async function setupMinioWorkspace() {
  if (materialSource.value !== 'minio') return
  rabbitmqLoading.value = true
  try {
    await loadMinioHealth()
    await loadRabbitmqQueues(false)
    await loadUploadListingTargets()
    restartMaterialRefresh()
    if (minioHealth.value?.refresh_mode === 'rabbitmq') {
      await loadRabbitmqRecent()
    }
  } catch (e) {
    ElMessage.warning(e instanceof Error ? e.message : 'MinIO 监听启动失败')
  } finally {
    rabbitmqLoading.value = false
  }
}

async function pickUploadFolder() {
  try {
    if ('showDirectoryPicker' in window) {
      const handle = await (window as unknown as { showDirectoryPicker: () => Promise<FileSystemDirectoryHandle> })
        .showDirectoryPicker()
      uploadFolderName.value = handle.name
      const entries: Array<{ file: File; relativePath: string }> = []

      async function walkDir(dir: FileSystemDirectoryHandle, prefix: string) {
        for await (const [name, child] of dir.entries()) {
          if (child.kind === 'file') {
            const file = await child.getFile()
            entries.push({ file, relativePath: `${prefix}${name}` })
          } else if (child.kind === 'directory') {
            await walkDir(child, `${prefix}${name}/`)
          }
        }
      }

      await walkDir(handle, '')
      uploadFolderEntries.value = entries
      if (!entries.length) {
        ElMessage.warning('文件夹里没有文件')
      }
      return
    }
    uploadFolderInputRef.value?.click()
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    ElMessage.error(e instanceof Error ? e.message : '选择文件夹失败')
  }
}

function onUploadFolderInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  const fileList = input.files
  if (!fileList?.length) return

  const entries: Array<{ file: File; relativePath: string }> = []
  for (const file of Array.from(fileList)) {
    const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    entries.push({ file, relativePath: rel })
  }

  const rootName = entries[0]?.relativePath.split('/')[0] || ''
  uploadFolderName.value = rootName
  uploadFolderEntries.value = entries.map((item) => ({
    file: item.file,
    relativePath: item.relativePath.includes('/')
      ? item.relativePath.split('/').slice(1).join('/')
      : item.relativePath,
  }))
  input.value = ''
}

async function uploadFolderToMinio() {
  if (!uploadFolderEntries.value.length) {
    ElMessage.warning('请先选择本地文件夹')
    return
  }
  if (!uploadFolderName.value.trim()) {
    ElMessage.warning('无法识别文件夹名，请重新选择')
    return
  }
  if (uploadMode.value === 'image_set' && !uploadTargetFamily.value.trim()) {
    ElMessage.warning('追加套图请先选择目标款号')
    return
  }
  if (uploadMode.value === 'product') {
    if (!uploadTargetFamily.value.trim()) {
      ElMessage.warning('追加商品请先选择目标款号')
      return
    }
    if (!uploadTargetImageSet.value.trim()) {
      ElMessage.warning('追加商品请先选择目标套图')
      return
    }
  }

  const imageEntries = uploadFolderEntries.value.filter((item) =>
    /\.(jpe?g|png|webp|gif)$/i.test(item.relativePath),
  )
  if (!imageEntries.length) {
    ElMessage.warning('文件夹里没有可上传的图片')
    return
  }

  uploading.value = true
  try {
    const formData = new FormData()
    formData.append('category', uploadCategory.value)
    formData.append('folder_name', uploadFolderName.value.trim())
    formData.append('upload_mode', uploadMode.value)
    if (uploadMode.value !== 'family') {
      formData.append('target_family', uploadTargetFamily.value.trim())
    }
    if (uploadMode.value === 'product') {
      formData.append('target_image_set', uploadTargetImageSet.value.trim())
    }
    for (const item of imageEntries) {
      formData.append('files', item.file, item.file.name)
      formData.append('paths', item.relativePath.replace(/\\/g, '/'))
    }

    const result = await api.uploadMinioFolder(formData)
    rabbitmqRecent.value = result.recent_events || result.batches || []
    const targetPath =
      uploadMode.value === 'family'
        ? `${result.category}/${result.folder_name}`
        : uploadMode.value === 'image_set'
          ? `${result.category}/${uploadTargetFamily.value}/${result.folder_name}`
          : `${result.category}/${uploadTargetFamily.value}/${uploadTargetImageSet.value}/${result.folder_name}`
    ElMessage.success(
      `上传成功：${result.upload_count} 张已存入 MinIO（${targetPath}），商品列表将自动更新`,
    )
    const autoHint = formatAutoPipelineFeedback(result.local_process?.auto_pipeline)
    if (autoHint) {
      if (result.local_process?.auto_pipeline?.triggered) {
        ElMessage.success(autoHint)
      } else if (
        result.local_process?.auto_pipeline?.reason &&
        !['disabled', 'append_only_batch'].includes(result.local_process.auto_pipeline.reason)
      ) {
        ElMessage.warning(autoHint)
      }
    }
    await loadRabbitmqRecent()
    await loadProducts()
    await loadUploadListingTargets()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '文件夹上传失败')
  } finally {
    uploading.value = false
  }
}

async function onMaterialSourceChange(source: 'local' | 'minio') {
  materialSource.value = source
  selectedCodes.value = []
  productKeyword.value = ''
  currentPage.value = 1
  preflight.value = null
  imagePanelTitle.value = ''
  previewImages.value = []
  stopMaterialRefresh()
  if (source === 'minio') {
    await setupMinioWorkspace()
    if (!minioHealth.value?.available) {
      ElMessage.warning(minioHealth.value?.error || 'MinIO 未就绪，请检查 config/minio.yaml')
    }
  } else {
    stopMaterialRefresh()
  }
  await loadProducts()
}

async function loadProducts() {
  loading.value = true
  error.value = ''
  try {
    products.value = await api.products(materialSource.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function runMinioSync() {
  if (!selectedCodes.value.length) {
    error.value = '请至少勾选一个商品'
    return
  }
  error.value = ''
  await startSync(selectedCodes.value, (msg) => {
    error.value = msg
  })
}

async function runPreflight() {
  if (!selectedCodes.value.length) {
    error.value = '请至少勾选一个商品'
    return
  }
  if (materialSource.value === 'minio' && syncing.value) {
    ElMessage.warning('MinIO 仍在同步中，请稍候或等同步完成后再检查')
    return
  }
  loading.value = true
  error.value = ''
  preflight.value = null
  imagePanelTitle.value = ''
  previewImages.value = []
  try {
    const result = await api.preflight(selectedCodes.value, materialSource.value)
    preflight.value = result
    const firstUnit = result.units[0]
    if (firstUnit) {
      showAllUnitImages(firstUnit)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '检查失败'
  } finally {
    loading.value = false
  }
}

function selectAll() {
  selectedCodes.value = [...productOptions.value]
}

function selectCurrentPage() {
  const merged = new Set(selectedCodes.value)
  for (const p of paginatedProducts.value) {
    merged.add(p.product_code)
  }
  selectedCodes.value = [...merged]
}

function clearSelection() {
  selectedCodes.value = []
}

watch([productKeyword, pageSize], () => {
  currentPage.value = 1
})

watch(filteredProducts, (list) => {
  const maxPage = Math.max(1, Math.ceil(list.length / pageSize.value) || 1)
  if (currentPage.value > maxPage) currentPage.value = maxPage
})

function goListing() {
  router.push('/tasks')
}

function openImages(title: string, images: PreviewImage[]) {
  if (!images.length) {
    ElMessage.warning('当前没有可查看的图片')
    return
  }
  imagePanelTitle.value = title
  previewImages.value = images
}

function openUnitImages(unit: ListingUnit, kind: 'carousel' | 'detail') {
  const source = kind === 'carousel' ? unit.carousel_images : unit.detail_images
  const label = kind === 'carousel' ? '主图' : '详情图'
  openImages(
    `${unit.listing_label} · ${label}`,
    source.map((path, index) => ({
      label: `${label}${index + 1}`,
      path,
      meta: fileName(path),
    })),
  )
}

function unitAllImages(unit: ListingUnit) {
  const carousel = unit.carousel_images.map((path, index) => ({
    label: `主图${index + 1}`,
    path,
    meta: fileName(path),
  }))
  const detail = unit.detail_images.map((path, index) => ({
    label: `详情${index + 1}`,
    path,
    meta: fileName(path),
  }))
  const skuPreviews = unit.skus.map((sku) => ({
    label: `${sku.style_name}/${sku.model_name}`,
    path: sku.preview_image,
    meta: sku.combo_folder,
  }))
  return [...carousel, ...detail, ...skuPreviews]
}

function showAllUnitImages(unit: ListingUnit) {
  imagePanelTitle.value = `${unit.listing_label} · 全部图片`
  previewImages.value = unitAllImages(unit)
}

function openAllUnitImages(unit: ListingUnit) {
  openImages(`${unit.listing_label} · 全部图片`, unitAllImages(unit))
}

function openSkuDrawer(unit: ListingUnit) {
  activeUnit.value = unit
  activeSku.value = unit.skus[0] ?? null
  skuDrawerVisible.value = true
}

function selectSku(row: SkuCombo) {
  activeSku.value = row
}

function openSkuPreview(sku: SkuCombo) {
  openImages(`${sku.style_name}/${sku.model_name} · SKU预览图`, [
    {
      label: `${sku.style_code}+${sku.model_code}`,
      path: sku.preview_image,
      meta: sku.combo_folder,
    },
  ])
}

onMounted(async () => {
  await loadMinioHealth()
  await loadProducts()
  if (materialSource.value === 'minio') {
    await setupMinioWorkspace()
    await resumeActiveSync((msg) => {
      error.value = msg
    })
  }
})

</script>

<template>
  <div v-loading="loading">
    <PageHeader
      title="素材检查"
      desc="上架前检查图片、Excel、SKU 是否齐全。这一步不会打开浏览器，也不消耗拼多多账号。"
    />

    <el-alert
      v-if="error"
      type="error"
      :title="error"
      show-icon
      closable
      style="margin-bottom: 16px"
      @close="error = ''"
    />

    <el-row :gutter="16">
      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="stat-card">
          <template #header>
            <div class="card-head">
              <span>选择要检查的商品</span>
              <span v-if="products.length" class="card-head-meta">共 {{ products.length }} 个</span>
              <span class="card-head-actions">
                <el-button link type="primary" @click="selectCurrentPage">本页全选</el-button>
                <el-button link type="primary" @click="selectAll">全部全选</el-button>
                <el-button link @click="clearSelection">清空</el-button>
              </span>
            </div>
          </template>

          <div class="material-source-bar">
            <el-radio-group
              :model-value="materialSource"
              size="small"
              @change="onMaterialSourceChange($event as 'local' | 'minio')"
            >
              <el-radio-button label="local">本地文件夹</el-radio-button>
              <el-radio-button label="minio">MinIO</el-radio-button>
            </el-radio-group>
            <template v-if="materialSource === 'minio'">
              <el-tag size="small" :type="minioHealth?.available ? 'success' : 'danger'">
                {{ minioHealth?.available ? 'MinIO 已连接' : (minioHealth?.error || 'MinIO 未连接') }}
              </el-tag>
              <el-radio-group
                :model-value="refreshMode"
                size="small"
                :disabled="switchingMode"
                @change="setRefreshMode($event as 'poll' | 'rabbitmq')"
              >
                <el-radio-button label="poll">
                  定时 {{ minioHealth?.listing_poll_seconds ?? 30 }}s
                </el-radio-button>
                <el-radio-button label="rabbitmq">RabbitMQ 推送</el-radio-button>
              </el-radio-group>
              <el-switch
                :model-value="!materialRefreshPaused"
                inline-prompt
                active-text="自动拉取"
                inactive-text="已关闭"
                @change="setMaterialRefreshPaused(!$event)"
              />
              <el-tag v-if="materialRefreshPaused" size="small" type="warning">
                已暂停拉取
              </el-tag>
              <el-tag v-else-if="refreshMode === 'poll' && materialPolling" size="small" type="info">
                轮询中
              </el-tag>
              <el-tag v-else-if="refreshMode === 'rabbitmq' && sseConnected" size="small" type="success">
                实时监听
              </el-tag>
              <el-tag v-else-if="refreshMode === 'rabbitmq'" size="small" type="warning">
                推送未连接
              </el-tag>
            </template>
          </div>

          <div v-if="materialSource === 'minio'" class="minio-workspace" v-loading="rabbitmqLoading">
            <div class="minio-upload-section">
              <div class="rabbitmq-panel-head">
                <span>上传素材文件夹</span>
              </div>
              <div class="form-tip">{{ uploadModeHint }}</div>
              <div v-if="minioHealth?.alist?.available === false" class="form-tip" style="color: var(--el-color-warning)">
                Alist 未就绪：{{ minioHealth?.alist?.error || '请检查 config/minio.yaml' }}
              </div>
              <input
                ref="uploadFolderInputRef"
                type="file"
                webkitdirectory
                directory
                multiple
                class="hidden-folder-input"
                @change="onUploadFolderInputChange"
              />
              <el-form label-width="72px" size="small" class="rabbitmq-form compact-upload-form">
                <el-form-item label="上传方式">
                  <el-radio-group v-model="uploadMode">
                    <el-radio-button label="family">新款号</el-radio-button>
                    <el-radio-button label="image_set">追加套图</el-radio-button>
                    <el-radio-button label="product">追加商品</el-radio-button>
                  </el-radio-group>
                </el-form-item>
                <el-form-item label="类目">
                  <el-select v-model="uploadCategory" style="width: 100%">
                    <el-option
                      v-for="cat in uploadCategoryOptions"
                      :key="cat"
                      :label="cat"
                      :value="cat"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item v-if="uploadMode !== 'family'" label="目标款号">
                  <el-select
                    v-model="uploadTargetFamily"
                    filterable
                    placeholder="选择已有款号，如 BD713"
                    style="width: 100%"
                  >
                    <el-option
                      v-for="family in uploadFamilyOptions"
                      :key="family"
                      :label="family"
                      :value="family"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item v-if="uploadMode === 'product'" label="目标套图">
                  <el-select
                    v-model="uploadTargetImageSet"
                    filterable
                    placeholder="选择已有套图"
                    style="width: 100%"
                    :disabled="!uploadTargetFamily"
                  >
                    <el-option
                      v-for="imageSet in uploadImageSetOptions"
                      :key="imageSet"
                      :label="imageSet"
                      :value="imageSet"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="文件夹">
                  <div class="folder-pick-row">
                    <el-input
                      v-model="uploadFolderName"
                      readonly
                      :placeholder="uploadFolderPlaceholder"
                    />
                    <el-button @click="pickUploadFolder">选择</el-button>
                    <el-button
                      type="primary"
                      :loading="uploading"
                      :disabled="!uploadFolderEntries.length"
                      @click="uploadFolderToMinio"
                    >
                      上传{{ uploadImageCount ? ` ${uploadImageCount} 张` : '' }}
                    </el-button>
                  </div>
                </el-form-item>
              </el-form>
              <pre v-if="uploadFolderPreview" class="rabbitmq-peek folder-preview">{{ uploadFolderPreview }}</pre>
            </div>

            <div v-if="refreshMode === 'rabbitmq' && rabbitmqRecent.length" class="rabbitmq-recent">
              <div class="form-tip">最近上传（已合并 MQ 消息）</div>
              <div v-for="(item, idx) in rabbitmqRecent" :key="idx" class="upload-batch-card">
                <div class="upload-batch-head">
                  <el-tag :type="item.status === 'success' ? 'success' : batchTagType(item)" size="small">
                    {{
                      item.status === 'success'
                        ? '上传成功'
                        : (item.groups as Array<{ change_label?: string }> | undefined)?.[0]?.change_label || '上传'
                    }}
                  </el-tag>
                  <span class="upload-batch-meta">
                    {{ item.raw_message_count ?? '?' }} 条消息 · {{ item.matched_file_count ?? '?' }} 张图
                  </span>
                </div>
                <div class="upload-batch-summary">{{ item.summary }}</div>
                <details v-if="(item.groups as unknown[] | undefined)?.length" class="upload-batch-details">
                  <summary>文件列表</summary>
                  <div
                    v-for="group in item.groups as Array<{
                      change_label: string
                      path: string
                      file_count: number
                      files: string[]
                    }>"
                    :key="group.path"
                    class="upload-batch-group"
                  >
                    <div class="upload-batch-group-title">
                      {{ group.change_label }} · {{ group.path }}（{{ group.file_count }} 张）
                    </div>
                    <div class="upload-batch-files">{{ group.files.join('、') }}</div>
                  </div>
                </details>
              </div>
            </div>
            <div v-else-if="refreshMode === 'rabbitmq' && sseConnected" class="form-tip minio-idle-tip">
              RabbitMQ 监听中。上传文件夹或同事经 Alist 上传后，会在这里显示摘要。
            </div>
            <div v-else-if="refreshMode === 'poll'" class="form-tip minio-idle-tip">
              当前为定时 {{ minioHealth?.listing_poll_seconds ?? 30 }}s 刷新，不会实时显示上传通知。要即时感知新素材请切到「RabbitMQ 推送」。
            </div>

            <el-collapse v-model="rabbitmqDebugOpen" class="minio-debug-collapse">
              <el-collapse-item title="运维调试（一般不用点）" name="debug">
                <div v-if="rabbitmqAmqpError" class="form-tip rabbitmq-error">
                  AMQP：{{ rabbitmqAmqpError }}
                </div>
                <el-form label-width="72px" size="small" class="rabbitmq-form">
                  <el-form-item label="队列">
                    <el-select
                      v-model="rabbitmqSelectedQueue"
                      filterable
                      allow-create
                      style="width: 100%"
                    >
                      <el-option
                        v-for="q in rabbitmqQueues"
                        :key="q.name"
                        :label="`${q.name}（${q.messages ?? 0}）`"
                        :value="q.name"
                      />
                    </el-select>
                  </el-form-item>
                  <el-form-item v-if="rabbitmqSuggested && rabbitmqSuggested !== rabbitmqSelectedQueue" label="推荐">
                    <el-button link type="primary" @click="rabbitmqSelectedQueue = rabbitmqSuggested">
                      {{ rabbitmqSuggested }}
                    </el-button>
                  </el-form-item>
                </el-form>
                <div class="rabbitmq-actions">
                  <el-button size="small" @click="loadRabbitmqQueues">刷新队列</el-button>
                  <el-button size="small" plain @click="saveRabbitmqQueue">保存队列</el-button>
                  <el-button size="small" type="primary" plain @click="ensureRabbitmqBinding">
                    恢复 MinIO 绑定
                  </el-button>
                  <el-button size="small" @click="peekRabbitmqMessage">窥探消息</el-button>
                </div>
                <div v-if="rabbitmqBindingStatus" class="form-tip">{{ rabbitmqBindingStatus }}</div>
                <pre v-if="rabbitmqPeek" class="rabbitmq-peek">{{ rabbitmqPeek }}</pre>
              </el-collapse-item>
            </el-collapse>
          </div>

          <el-input
            v-if="products.length"
            v-model="productKeyword"
            clearable
            size="small"
            placeholder="搜索商品编码"
            class="product-search"
          />

          <el-empty
            v-if="!products.length"
            :description="materialSource === 'minio' ? 'MinIO 中暂无可用笔袋素材' : '素材文件夹里还没有商品'"
          >
            <div class="form-tip">
              {{
                materialSource === 'minio'
                  ? '请确认 config/minio.yaml 与同事 MinIO 配置一致，且 bucket 内已有套图'
                  : '请把商品素材放到 data/assets 目录中'
              }}
            </div>
          </el-empty>

          <el-empty
            v-else-if="!filteredProducts.length"
            description="没有匹配的商品编码"
          />

          <template v-else>
            <el-checkbox-group v-model="selectedCodes" class="code-list">
              <div v-for="p in paginatedProducts" :key="p.product_code" class="code-row">
                <el-checkbox :value="p.product_code">
                  <span class="code-name">{{ p.product_code }}</span>
                  <span class="code-meta">
                    共 {{ p.listing_unit_count }} 套图
                    <template v-if="p.image_sets.length"> · {{ p.image_sets.join('、') }}</template>
                  </span>
                </el-checkbox>
              </div>
            </el-checkbox-group>

            <div class="product-pagination">
              <el-pagination
                v-model:current-page="currentPage"
                v-model:page-size="pageSize"
                :total="filteredProducts.length"
                :page-sizes="[10, 15, 20, 30]"
                layout="total, sizes, prev, pager, next"
                small
                background
              />
            </div>
          </template>

          <div v-if="selectedCodes.length" class="selection-summary">
            已选 {{ selectedCodes.length }} 个商品
          </div>

          <div
            v-if="materialSource === 'minio' && minioSyncJob"
            class="minio-sync-progress"
          >
            <div class="minio-sync-progress-head">
              <span>MinIO 同步</span>
              <el-tag
                size="small"
                :type="
                  minioSyncJob.status === 'success'
                    ? 'success'
                    : minioSyncJob.status === 'failed'
                      ? 'danger'
                      : 'warning'
                "
              >
                {{
                  minioSyncJob.status === 'success'
                    ? '已完成'
                    : minioSyncJob.status === 'failed'
                      ? '失败'
                      : '进行中'
                }}
              </el-tag>
            </div>
            <el-progress
              :percentage="minioSyncJob.progress_percent"
              :status="
                minioSyncJob.status === 'success'
                  ? 'success'
                  : minioSyncJob.status === 'failed'
                    ? 'exception'
                    : undefined
              "
              :stroke-width="10"
            />
            <div class="form-tip">
              {{ minioSyncJob.completed_sets }}/{{ minioSyncJob.total_sets }} 套图
              <template v-if="minioSyncJob.current_label">
                · 当前 {{ minioSyncJob.current_label }}
              </template>
              <template v-if="minioSyncJob.downloaded_files || minioSyncJob.skipped_files">
                · 新下载 {{ minioSyncJob.downloaded_files }} · 跳过 {{ minioSyncJob.skipped_files }}
              </template>
            </div>
          </div>

          <template v-if="materialSource === 'minio'">
            <el-button
              type="primary"
              size="large"
              style="width: 100%; margin-top: 16px"
              :disabled="!selectedCodes.length"
              :loading="syncing"
              @click="runMinioSync"
            >
              {{ syncing ? 'MinIO 同步中…' : '① 从 MinIO 同步素材' }}
            </el-button>
            <el-button
              size="large"
              style="width: 100%; margin-top: 8px"
              :disabled="!selectedCodes.length || syncing"
              :loading="loading"
              @click="runPreflight"
            >
              ② 开始检查（读本地缓存）
            </el-button>
            <div class="form-tip" style="margin-top: 8px">
              同步在后台进行，不阻塞页面；检查前请先完成同步。
            </div>
          </template>
          <el-button
            v-else
            type="primary"
            size="large"
            style="width: 100%; margin-top: 16px"
            :disabled="!selectedCodes.length"
            :loading="loading"
            @click="runPreflight"
          >
            开始检查
          </el-button>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="14">
        <el-card v-if="preflight" shadow="never" class="stat-card result-card">
          <template #header>
            <div class="card-head">
              <span>检查结果</span>
              <el-tag :type="preflight.ok ? 'success' : 'danger'" effect="dark" size="large">
                {{ preflight.ok ? '可以上架' : '有问题需处理' }}
              </el-tag>
            </div>
          </template>

          <el-row :gutter="12" style="margin-bottom: 16px">
            <el-col :span="8">
              <div class="mini-stat">
                <div class="mini-val">{{ preflight.unit_count }}</div>
                <div class="mini-label">套图数量</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="mini-stat error">
                <div class="mini-val">{{ preflight.error_count }}</div>
                <div class="mini-label">错误</div>
              </div>
            </el-col>
            <el-col :span="8">
              <div class="mini-stat warn">
                <div class="mini-val">{{ preflight.warning_count }}</div>
                <div class="mini-label">警告</div>
              </div>
            </el-col>
          </el-row>

          <el-button
            v-if="allPassed"
            type="success"
            size="large"
            style="width: 100%; margin-bottom: 16px"
            @click="goListing"
          >
            检查通过，去上架 →
          </el-button>

          <el-table v-if="preflight.issues.length" :data="preflight.issues" size="small" stripe style="margin-bottom: 16px">
            <el-table-column label="级别" width="72">
              <template #default="{ row }">
                <el-tag :type="row.level === 'error' ? 'danger' : 'warning'" size="small">
                  {{ issueLevelLabel[row.level] || row.level }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="listing_label" label="套图" width="160" />
            <el-table-column prop="message" label="问题说明" show-overflow-tooltip />
          </el-table>

          <div v-if="preflight.units.length">
            <div class="section-label">检查明细</div>
            <el-table :data="preflight.units" size="small" stripe max-height="360" @row-dblclick="openAllUnitImages">
              <el-table-column label="商品/套图" min-width="180">
                <template #default="{ row }">
                  <el-button link type="primary" class="unit-link" @click="openAllUnitImages(row)">
                    {{ row.listing_label }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column label="SKU数" width="80">
                <template #default="{ row }">
                  <el-button link type="primary" :disabled="!row.sku_count" @click="openSkuDrawer(row)">
                    {{ row.sku_count }}
                  </el-button>
                </template>
              </el-table-column>
              <el-table-column label="图片" width="168">
                <template #default="{ row }">
                  <div class="image-actions">
                    <el-button size="small" :disabled="!row.carousel_count" @click="openUnitImages(row, 'carousel')">
                      主图 {{ row.carousel_count }}
                    </el-button>
                    <el-button size="small" :disabled="!row.detail_count" @click="openUnitImages(row, 'detail')">
                      详情 {{ row.detail_count }}
                    </el-button>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="merchant_code" label="货号" min-width="140" show-overflow-tooltip />
            </el-table>
          </div>
        </el-card>

        <section v-if="preflight" class="inline-image-panel">
          <div class="inline-image-head">
            <span>{{ imagePanelTitle || '图片预览' }}</span>
            <el-tag v-if="previewImages.length" size="small">{{ previewImages.length }} 张</el-tag>
          </div>
          <div v-if="previewImages.length" class="inline-image-grid">
            <div v-for="img in previewImages" :key="img.path" class="inline-image-item">
              <div class="inline-image-box">
                <img :src="assetUrl(img.path)" :alt="img.label" loading="lazy" />
              </div>
              <div class="inline-image-info">
                <strong>{{ img.label }}</strong>
                <span>{{ img.meta }}</span>
              </div>
            </div>
          </div>
          <el-empty v-else description="点击上方主图、详情或商品/套图后，在这里显示图片" />
        </section>

        <el-empty v-else description="勾选商品后点击“开始检查”" />
      </el-col>
    </el-row>

    <el-drawer v-model="skuDrawerVisible" :title="activeUnit ? `${activeUnit.listing_label} · SKU数据` : 'SKU数据'" size="760px">
      <div v-if="activeUnit" class="sku-panel">
        <el-descriptions :column="3" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="商品">{{ activeUnit.product_code }}</el-descriptions-item>
          <el-descriptions-item label="套图">{{ activeUnit.image_set || '默认' }}</el-descriptions-item>
          <el-descriptions-item label="货号">{{ activeUnit.merchant_code }}</el-descriptions-item>
        </el-descriptions>

        <el-table :data="activeSkuRows" size="small" stripe height="360" highlight-current-row @row-click="selectSku">
          <el-table-column prop="style_code" label="款式编码" width="92" />
          <el-table-column prop="style_name" label="款式名称" min-width="120" show-overflow-tooltip />
          <el-table-column prop="model_code" label="型号编码" width="92" />
          <el-table-column prop="model_name" label="型号名称" min-width="120" show-overflow-tooltip />
          <el-table-column prop="inventory" label="库存" width="72" />
          <el-table-column prop="group_price" label="拼单价" width="82" />
          <el-table-column prop="single_price" label="单买价" width="82" />
          <el-table-column label="图片" width="72">
            <template #default="{ row }">
              <el-button link type="primary" @click.stop="openSkuPreview(row)">查看</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="activeSku" class="sku-detail">
          <div class="section-label">当前SKU</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="组合文件夹">{{ activeSku.combo_folder }}</el-descriptions-item>
            <el-descriptions-item label="预览图">{{ fileName(activeSku.preview_image) }}</el-descriptions-item>
            <el-descriptions-item label="款式">{{ activeSku.style_code }} · {{ activeSku.style_name }}</el-descriptions-item>
            <el-descriptions-item label="型号">{{ activeSku.model_code }} · {{ activeSku.model_name }}</el-descriptions-item>
            <el-descriptions-item label="库存">{{ activeSku.inventory }}</el-descriptions-item>
            <el-descriptions-item label="价格">{{ activeSku.group_price }} / {{ activeSku.single_price }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.card-head-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.card-head-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}

.product-search {
  margin-bottom: 12px;
}

.product-pagination {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}

.selection-summary {
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-secondary);
}

.minio-sync-progress {
  margin-top: 12px;
  padding: 12px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}

.minio-sync-progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.material-source-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.source-tip {
  margin-bottom: 12px;
}

.result-card {
  min-height: 348px;
}

.code-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-height: 420px;
  overflow-y: auto;
  padding-right: 4px;
}

.code-row {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 10px 12px;
  background: #fafbfc;
}

.code-row :deep(.el-checkbox) {
  height: auto;
  align-items: flex-start;
  width: 100%;
}

.code-name {
  font-weight: 600;
  margin-right: 8px;
}

.code-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.section-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #475569;
}

.unit-link {
  padding: 0;
  font-weight: 600;
}

.image-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}

.image-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.mini-stat {
  text-align: center;
  padding: 12px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid var(--border-color);
}

.mini-stat.error .mini-val {
  color: #dc2626;
}

.mini-stat.warn .mini-val {
  color: #d97706;
}

.mini-val {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
}

.mini-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.inline-image-panel {
  margin-top: 16px;
  min-height: 420px;
  padding: 12px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.72);
}

.inline-image-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}

.inline-image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(132px, 1fr));
  gap: 12px;
}

.inline-image-item {
  min-width: 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.inline-image-box {
  width: 100%;
  aspect-ratio: 1 / 1;
  background: #f8fafc;
}

.inline-image-box img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.inline-image-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px;
}

.inline-image-info strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: #334155;
}

.inline-image-info span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--text-secondary);
}

.sku-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sku-detail {
  margin-top: 4px;
}

.rabbitmq-panel,
.minio-workspace {
  margin: 12px 0 16px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.minio-upload-section {
  margin-bottom: 12px;
}

.minio-idle-tip {
  margin: 8px 0 4px;
  color: #64748b;
}

.minio-debug-collapse {
  margin-top: 10px;
  border: none;
}

.minio-debug-collapse :deep(.el-collapse-item__header) {
  font-size: 12px;
  color: #64748b;
  height: 36px;
  border-bottom: none;
}

.minio-debug-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.compact-upload-form :deep(.el-form-item) {
  margin-bottom: 10px;
}

.rabbitmq-panel {
  margin: 12px 0 16px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.rabbitmq-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-weight: 600;
  color: #334155;
}

.rabbitmq-error {
  color: #b45309;
  margin-bottom: 8px;
}

.rabbitmq-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 4px;
}

.rabbitmq-peek {
  margin-top: 8px;
  padding: 8px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 220px;
  overflow: auto;
}

.rabbitmq-test-upload {
  display: none;
}

.hidden-folder-input {
  display: none;
}

.folder-pick-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.folder-pick-row .el-input {
  flex: 1;
}

.folder-preview {
  max-height: 120px;
}

.upload-batch-card {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.upload-batch-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.upload-batch-meta {
  font-size: 12px;
  color: #64748b;
}

.upload-batch-summary {
  margin-top: 6px;
  font-size: 13px;
  color: #0f172a;
  line-height: 1.5;
}

.upload-batch-details {
  margin-top: 8px;
  font-size: 12px;
  color: #475569;
}

.upload-batch-group {
  margin-top: 6px;
}

.upload-batch-group-title {
  font-weight: 600;
  color: #334155;
}

.upload-batch-files {
  margin-top: 2px;
  color: #64748b;
  word-break: break-all;
}

@media (max-width: 900px) {
  .inline-image-panel {
    min-height: 280px;
  }

  .inline-image-grid {
    grid-template-columns: repeat(auto-fill, minmax(112px, 1fr));
  }
}
</style>
