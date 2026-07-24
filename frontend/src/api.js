async function request (path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
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
