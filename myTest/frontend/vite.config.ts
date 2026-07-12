import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

function resolveApiTarget(mode: string): string {
  const env = loadEnv(mode, process.cwd(), '')
  const explicitTarget = (env.VITE_API_TARGET || '').trim()
  if (explicitTarget) {
    return explicitTarget.replace(/\/+$/, '')
  }
  const apiBase = (env.VITE_API_BASE || '').trim()
  if (apiBase) {
    return apiBase.replace(/\/api\/?$/, '').replace(/\/+$/, '')
  }
  return 'http://127.0.0.1:8010'
}

export default defineConfig(({ mode }) => {
  const apiTarget = resolveApiTarget(mode)
  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true,
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
