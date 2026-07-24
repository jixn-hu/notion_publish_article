async function request (path, options = {}) {
  const isFormData = options.body instanceof FormData
  const response = await fetch(`/api${path}`, {
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers
    },
    ...options
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || `请求失败 (${response.status})`)
  }
  return data
}

export const api = {
  health: () => request('/health'),
  dashboard: () => request('/dashboard'),
  articles: (status = 'all', q = '') => {
    const params = new URLSearchParams()
    if (status !== 'all') params.set('status', status)
    if (q) params.set('q', q)
    return request(`/articles?${params}`)
  },
  article: id => request(`/articles/${id}`),
  createArticle: values => request('/articles', {
    method: 'POST',
    body: JSON.stringify(values)
  }),
  updateArticle: (id, values) => request(`/articles/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(values)
  }),
  publishArticle: (id, platformActions = null) => request(`/articles/${id}/publish`, {
    method: 'POST',
    body: JSON.stringify({ platform_actions: platformActions })
  }),
  enrichArticle: id => request(`/articles/${id}/enrich`, { method: 'POST' }),
  syncNotion: () => request('/sync/notion', { method: 'POST' }),
  runAutomation: () => request('/automation/publish', { method: 'POST' }),
  accounts: (platform = '') => request(`/accounts${platform ? `?platform=${encodeURIComponent(platform)}` : ''}`),
  createAccount: values => request('/accounts', {
    method: 'POST',
    body: JSON.stringify(values)
  }),
  loginAccount: id => request(`/accounts/${id}/login`, { method: 'POST' }),
  checkAccount: id => request(`/accounts/${id}/check`, { method: 'POST' }),
  refreshAccountProfile: id => request(`/accounts/${id}/profile`, { method: 'POST' }),
  updateAccountProxy: (id, proxyId) => request(`/accounts/${id}/proxy`, {
    method: 'PUT',
    body: JSON.stringify({ proxy_id: proxyId })
  }),
  proxies: () => request('/proxies'),
  createProxy: values => request('/proxies', {
    method: 'POST',
    body: JSON.stringify(values)
  }),
  testProxy: id => request(`/proxies/${id}/test`, { method: 'POST' }),
  deleteProxy: id => request(`/proxies/${id}`, { method: 'DELETE' }),
  uploadMedia: file => {
    const body = new FormData()
    body.append('file', file)
    return request('/media', { method: 'POST', body })
  },
  settings: () => request('/settings'),
  saveSettings: values => request('/settings', {
    method: 'PUT',
    body: JSON.stringify({ values })
  }),
  platforms: () => request('/platforms'),
  testNotion: () => request('/connections/notion/test', { method: 'POST' }),
  notionSchema: () => request('/connections/notion/schema'),
  testAI: () => request('/connections/ai/test', { method: 'POST' }),
  testPlatform: key => request(`/platforms/${key}/test`, { method: 'POST' })
}
