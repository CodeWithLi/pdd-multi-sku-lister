import { computed, onUnmounted, ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import { formatAutoPipelineFeedback } from '@/utils/autoPipeline'
import {
  loadMinioMaterialRefreshPaused,
  saveMinioMaterialRefreshPaused,
} from '@/utils/pipelinePreferences'

export type MinioRefreshMode = 'poll' | 'rabbitmq'

export interface MinioHealthInfo {
  available?: boolean
  error?: string
  refresh_mode?: MinioRefreshMode
  listing_poll_seconds?: number
  alist_url?: string
  console_url?: string
  rabbitmq?: {
    enabled?: boolean
    running?: boolean
    last_error?: string
    queue?: string
  }
}

export interface MinioUploadBatchEvent {
  kind?: string
  summary?: string
  detail?: string
  product_codes?: string[]
  files?: string[]
  auto_pipeline?: {
    triggered?: boolean
    reason?: string
    reason_label?: string
    product_codes?: string[]
    group_change_types?: string[]
  }
}

export function useMinioMaterialRefresh(options: {
  materialSource: Ref<'local' | 'minio'>
  minioHealth: Ref<MinioHealthInfo | null>
  onRefresh: () => Promise<void>
  reloadHealth?: () => Promise<void>
  onUploadBatch?: (data: MinioUploadBatchEvent) => void | Promise<void>
}) {
  const materialPolling = ref(false)
  const sseConnected = ref(false)
  const switchingMode = ref(false)
  const materialRefreshPaused = ref(loadMinioMaterialRefreshPaused())

  const refreshMode = computed<MinioRefreshMode>(
    () => options.minioHealth.value?.refresh_mode ?? 'poll',
  )

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let eventSource: EventSource | null = null
  let lastToastSummary = ''
  let lastToastAt = 0

  function stopPolling() {
    materialPolling.value = false
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function stopSse() {
    sseConnected.value = false
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  function stop() {
    stopPolling()
    stopSse()
  }

  function startPolling() {
    stopPolling()
    if (options.materialSource.value !== 'minio') return
    if (refreshMode.value !== 'poll') return
    const seconds = options.minioHealth.value?.listing_poll_seconds ?? 30
    if (!seconds || seconds <= 0) return
    materialPolling.value = true
    pollTimer = setInterval(() => {
      options.onRefresh().catch(() => undefined)
    }, seconds * 1000)
  }

  function startSse() {
    stopSse()
    if (options.materialSource.value !== 'minio') return
    if (refreshMode.value !== 'rabbitmq') return

    eventSource = new EventSource('/api/catalog/minio/events')
    eventSource.onopen = () => {
      sseConnected.value = true
    }
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as MinioUploadBatchEvent
        if (data.kind !== 'minio_upload' && data.kind !== 'upload_batch') return
        const summary =
          data.summary ||
          data.detail ||
          (data.product_codes?.length ? data.product_codes.join('、') : '') ||
          (data.files?.length ? data.files.join('、') : '新素材')
        const now = Date.now()
        if (summary === lastToastSummary && now - lastToastAt < 5000) return
        lastToastSummary = summary
        lastToastAt = now
        ElMessage.info(`MinIO：${summary}`)
        const autoHint = formatAutoPipelineFeedback(data.auto_pipeline)
        if (autoHint) {
          if (data.auto_pipeline?.triggered) {
            ElMessage.success(autoHint)
          } else if (
            data.auto_pipeline?.reason &&
            !['disabled'].includes(data.auto_pipeline.reason)
          ) {
            ElMessage.warning(autoHint)
          }
        }
        void options.onRefresh()
        void options.onUploadBatch?.(data)
      } catch {
        // ignore malformed payload
      }
    }
    eventSource.onerror = () => {
      sseConnected.value = false
    }
  }

  function restart() {
    stop()
    if (materialRefreshPaused.value) return
    if (options.materialSource.value !== 'minio') return
    if (refreshMode.value === 'rabbitmq') {
      startSse()
    } else {
      startPolling()
    }
  }

  function pauseRefresh() {
    if (materialRefreshPaused.value) return
    materialRefreshPaused.value = true
    saveMinioMaterialRefreshPaused(true)
    stop()
    ElMessage.info('已暂停 MinIO 自动拉取；可手动点「刷新」更新列表')
  }

  function resumeRefresh() {
    if (!materialRefreshPaused.value) return
    materialRefreshPaused.value = false
    saveMinioMaterialRefreshPaused(false)
    restart()
    ElMessage.success(
      refreshMode.value === 'rabbitmq'
        ? '已恢复 RabbitMQ 实时监听'
        : `已恢复定时拉取（每 ${options.minioHealth.value?.listing_poll_seconds ?? 30} 秒）`,
    )
  }

  function setMaterialRefreshPaused(paused: boolean) {
    if (paused) pauseRefresh()
    else resumeRefresh()
  }

  async function setRefreshMode(mode: MinioRefreshMode) {
    if (mode === refreshMode.value) return
    switchingMode.value = true
    try {
      await api.updateMinioRefreshMode(mode)
      if (options.reloadHealth) {
        await options.reloadHealth()
      }
      restart()
      ElMessage.success(
        mode === 'rabbitmq'
          ? '已切换为 RabbitMQ 实时推送（定时轮询已关闭）'
          : `已切换为定时刷新（每 ${options.minioHealth.value?.listing_poll_seconds ?? 30} 秒）`,
      )
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '切换失败')
    } finally {
      switchingMode.value = false
    }
  }

  onUnmounted(stop)

  return {
    materialPolling,
    sseConnected,
    switchingMode,
    materialRefreshPaused,
    refreshMode,
    restart,
    stop,
    pauseRefresh,
    resumeRefresh,
    setMaterialRefreshPaused,
    setRefreshMode,
  }
}
