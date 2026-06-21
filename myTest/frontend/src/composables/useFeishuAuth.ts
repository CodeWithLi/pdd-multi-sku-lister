import { api } from '@/api/client'

const RETURN_KEY = 'feishu_oauth_return'
const STATE_KEY = 'feishu_oauth_state'
const REDIRECT_KEY = 'feishu_oauth_redirect'

export type FeishuAuthDisplayStatus = 'loading' | 'authorized' | 'unauthorized' | 'unknown'

/** 查询飞书 OAuth 是否有效。 */
export async function fetchFeishuAuthStatus() {
  return api.feishuOAuthStatus()
}

/** 手动发起飞书 OAuth（跳转飞书授权页）。 */
export async function startFeishuOAuth(returnPath?: string) {
  const auth = await api.feishuOAuthAuthorizeUrl()
  const back = returnPath || `${window.location.pathname}${window.location.search}` || '/'
  sessionStorage.setItem(RETURN_KEY, back)
  sessionStorage.setItem(STATE_KEY, auth.state)
  sessionStorage.setItem(REDIRECT_KEY, auth.redirect_uri)
  window.location.href = auth.authorize_url
}

export async function completeFeishuOAuthCallback(
  router: import('vue-router').Router,
  query: Record<string, string | string[] | undefined>,
): Promise<{ ok: boolean; message: string }> {
  const code = String(query.code || '').trim()
  const state = String(query.state || sessionStorage.getItem(STATE_KEY) || '').trim()
  if (!code) {
    return { ok: false, message: '授权回调缺少 code 参数' }
  }

  const result = await api.feishuOAuthExchangeCode({
    code,
    state,
    redirect_uri:
      sessionStorage.getItem(REDIRECT_KEY) ||
      `${window.location.origin}/feishu/oauth/callback`,
  })

  sessionStorage.removeItem(STATE_KEY)
  sessionStorage.removeItem(REDIRECT_KEY)
  const returnTo = sessionStorage.getItem(RETURN_KEY) || '/'
  sessionStorage.removeItem(RETURN_KEY)

  if (result.ok) {
    const { ElMessage } = await import('element-plus')
    ElMessage.success(result.message || '飞书授权成功')
    await router.replace(returnTo)
    return { ok: true, message: result.message || '飞书授权成功' }
  }
  return { ok: false, message: result.message || '飞书授权失败' }
}
