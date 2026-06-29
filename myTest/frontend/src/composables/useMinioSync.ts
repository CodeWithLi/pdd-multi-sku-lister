import { onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api/client'
import type { MinioSyncJob } from '@/types'

export function useMinioSync() {
  const minioSyncJob = ref<MinioSyncJob | null>(null)
  const syncing = ref(false)
  let syncPollTimer: ReturnType<typeof setInterval> | null = null

  function stopSyncPolling() {
    if (syncPollTimer) {
      clearInterval(syncPollTimer)
      syncPollTimer = null
    }
  }

  function applySyncJob(job: MinioSyncJob | null) {
    minioSyncJob.value = job
    syncing.value = !!job && (job.status === 'pending' || job.status === 'running')
  }

  function startPolling(jobId: string, onError?: (message: string) => void) {
    stopSyncPolling()

    const tick = async () => {
      try {
        const job = await api.getMinioSyncStatus(jobId)
        applySyncJob(job)
        if (job.status === 'success') {
          stopSyncPolling()
          syncing.value = false
          ElMessage.success(
            `MinIO 同步完成：${job.completed_sets} 套图，新下载 ${job.downloaded_files} 张，跳过 ${job.skipped_files} 张${
              job.pruned_dirs ? `，清理多余文件夹 ${job.pruned_dirs} 个` : ''
            }`,
          )
        } else if (job.status === 'failed') {
          stopSyncPolling()
          syncing.value = false
          const msg = job.error || 'MinIO 同步失败'
          onError?.(msg)
        }
      } catch (e) {
        stopSyncPolling()
        syncing.value = false
        onError?.(e instanceof Error ? e.message : '同步状态查询失败')
      }
    }

    void tick()
    syncPollTimer = setInterval(() => {
      void tick()
    }, 1500)
  }

  async function startSync(
    productCodes: string[],
    onError?: (message: string) => void,
  ): Promise<string | null> {
    if (!productCodes.length) {
      onError?.('请至少选择一个商品或套图')
      return null
    }
    syncing.value = true
    try {
      const job = await api.startMinioSync(productCodes)
      applySyncJob(job)
      ElMessage.info(`已开始后台同步（${job.total_sets} 套图），页面可继续操作`)
      startPolling(job.job_id, onError)
      return job.job_id
    } catch (e) {
      syncing.value = false
      onError?.(e instanceof Error ? e.message : '启动同步失败')
      return null
    }
  }

  async function resumeActiveSync(onError?: (message: string) => void) {
    try {
      const job = await api.getActiveMinioSync()
      if (job && (job.status === 'pending' || job.status === 'running')) {
        applySyncJob(job)
        startPolling(job.job_id, onError)
      }
    } catch {
      // ignore
    }
  }

  onUnmounted(stopSyncPolling)

  return {
    minioSyncJob,
    syncing,
    startSync,
    resumeActiveSync,
    stopSyncPolling,
  }
}
