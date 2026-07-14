import { computed, onUnmounted, ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'

export type MinioRefreshMode = 'poll' | 'rabbitmq'

export interface MinioHealthInfo {
  configured?: boolean
  available?: boolean
  error?: string
  refresh_mode?: MinioRefreshMode
  listing_poll_seconds?: number
  alist_url?: string
  console_url?: string
}

export function useMinioMaterialRefresh(options: {
  materialSource: Ref<'local' | 'minio'>
  minioHealth: Ref<MinioHealthInfo | null>
  onRefresh: () => Promise<void>
}) {
  const materialPolling = ref(false)
  const materialRefreshPaused = ref(false)

  const refreshMode = computed<MinioRefreshMode>(
    () => options.minioHealth.value?.refresh_mode ?? 'poll',
  )

  let pollTimer: ReturnType<typeof setInterval> | null = null

  function stopPolling() {
    materialPolling.value = false
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  function stop() {
    stopPolling()
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

  function restart() {
    stop()
    if (materialRefreshPaused.value) return
    if (options.materialSource.value !== 'minio') return
    startPolling()
  }

  function setMaterialRefreshPaused(paused: boolean) {
    materialRefreshPaused.value = paused
    if (paused) {
      stop()
      ElMessage.info('已暂停 MinIO 自动拉取；可手动刷新页面更新列表')
    } else {
      restart()
      ElMessage.success(`已恢复定时拉取（每 ${options.minioHealth.value?.listing_poll_seconds ?? 30} 秒）`)
    }
  }

  onUnmounted(stop)

  return {
    materialPolling,
    materialRefreshPaused,
    refreshMode,
    restart,
    stop,
    setMaterialRefreshPaused,
  }
}
