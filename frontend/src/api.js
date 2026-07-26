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
  articles: (status = 'all', q = '', articleType = 'all') => {
    const params = new URLSearchParams()
    if (status !== 'all') params.set('status', status)
    if (q) params.set('q', q)
    if (articleType !== 'all') params.set('article_type', articleType)
    return request('/articles?' + params.toString())
  },
  news: (q = '', source = '') => {
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (source) params.set('source', source)
    return request('/news?' + params.toString())
  },
  collectNews: url => request('/news/collect', {
    method: 'POST',
    body: JSON.stringify({ url })
  }),
  createNews: values => request('/news', {
    method: 'POST',
    body: JSON.stringify(values)
  }),
  updateNews: (id, values) => request('/news/' + id, {
    method: 'PATCH',
    body: JSON.stringify(values)
  }),
  deleteNews: id => request('/news/' + id, { method: 'DELETE' }),  materials: (kind = '', q = '') => {
    const params = new URLSearchParams()
    if (kind) params.set('kind', kind)
    if (q) params.set('q', q)
    return request('/materials?' + params.toString())
  },
  uploadMaterial: file => {
    const body = new FormData()
    body.append('file', file)
    return request('/materials/files', { method: 'POST', body })
  },
  createMaterialNote: values => request('/materials/notes', {
    method: 'POST',
    body: JSON.stringify(values)
  }),
  updateMaterial: (id, values) => request('/materials/' + id, {
    method: 'PATCH',
    body: JSON.stringify(values)
  }),
  deleteMaterial: id => request('/materials/' + id, { method: 'DELETE' }),
  downloadMaterials: async ids => {
    const response = await fetch('/api/materials/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids })
    })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new Error(data.detail || '请求失败 (' + response.status + ')')
    }
    return response.blob()
  },  article: id => request(`/articles/${id}`),
  createArticle: values => request('/articles', {
    method: 'POST',
    body: JSON.stringify(values)
  }),
  generateStoryboard: values => request('/articles/generate-storyboard', {
    method: 'POST',
    body: JSON.stringify(values)
  }),
  generateArticle: values => request('/articles/generate', {
    method: 'POST',
    body: JSON.stringify(values)
  }),
  regenerateArticleImage: (id, imageIndex) =>
    request('/articles/' + id + '/images/' + imageIndex + '/regenerate', { method: 'POST' }),  updateArticle: (id, values) => request(`/articles/${id}`, {
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
  openAccountBrowser: id => request(`/accounts/${id}/browser`, { method: 'POST' }),
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

export const materialFileUrl = id => '/api/materials/' + id + '/file'

export const mediaPreviewUrl = path =>
  `/api/media/file?path=${encodeURIComponent(path)}`
