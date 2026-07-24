import { useEffect, useMemo, useState } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { api } from './api'

const NAV_ITEMS = [
  { key: 'dashboard', label: '工作台', mark: '01' },
  { key: 'articles', label: '内容库', mark: '02' },
  { key: 'settings', label: '连接与自动化', mark: '03' }
]

const STATUS_LABELS = {
  ready: '待发布',
  publishing: '发布中',
  published: '已发布',
  drafted: '平台草稿',
  completed: '处理完成',
  partial: '部分成功',
  failed: '发布失败',
  draft: '草稿'
}

const PLATFORM_LABELS = {
  wechat: '公众号',
  xiaohongshu: '小红书',
  csdn: 'CSDN'
}

const NOTION_FIELD_ROWS = [
  { key: 'notion_field_title', label: '文章标题', type: 'title', required: true },
  { key: 'notion_field_article_type', label: '文章类型', type: 'select', required: true },
  { key: 'notion_field_author', label: '作者', type: 'select' },
  { key: 'notion_field_cover_url', label: '封面图片', type: 'url' },
  { key: 'notion_field_source_url', label: '阅读原文', type: 'url' },
  { key: 'notion_field_tags', label: '标签', type: 'multi_select' },
  { key: 'notion_field_status', label: '同步状态', type: 'status', required: true },
  { key: 'notion_unique_property', label: '唯一标识', type: 'unique_id' }
]

function App () {
  const [view, setView] = useState('dashboard')
  const [dashboard, setDashboard] = useState(null)
  const [articles, setArticles] = useState([])
  const [platforms, setPlatforms] = useState([])
  const [settingsData, setSettingsData] = useState(null)
  const [health, setHealth] = useState(null)
  const [busy, setBusy] = useState('')
  const [toast, setToast] = useState(null)

  const notify = (message, kind = 'success') => {
    setToast({ message, kind })
    window.setTimeout(() => setToast(null), kind === 'error' ? 8000 : 3600)
  }

  const loadOverview = async () => {
    const [summary, platformData, healthData] = await Promise.all([
      api.dashboard(),
      api.platforms(),
      api.health()
    ])
    setDashboard(summary)
    setPlatforms(platformData)
    setHealth(healthData)
  }

  const loadArticles = async (status = 'all', q = '') => {
    setArticles(await api.articles(status, q))
  }

  const loadSettings = async () => {
    setSettingsData(await api.settings())
  }

  useEffect(() => {
    loadOverview().catch(error => notify(error.message, 'error'))
  }, [])

  useEffect(() => {
    if (view === 'articles') {
      loadArticles().catch(error => notify(error.message, 'error'))
    }
    if (view === 'settings') {
      Promise.all([loadSettings(), api.platforms().then(setPlatforms)])
        .catch(error => notify(error.message, 'error'))
    }
  }, [view])

  const runAction = async (key, action, successMessage) => {
    setBusy(key)
    try {
      const result = await action()
      const notice = successMessage(result)
      if (typeof notice === 'string') {
        notify(notice)
      } else {
        notify(notice.message, notice.kind)
      }
      await Promise.all([loadOverview(), loadArticles()])
      return result
    } catch (error) {
      notify(error.message, 'error')
      throw error
    } finally {
      setBusy('')
    }
  }

  return (
    <div className='app-shell'>
      <aside className='sidebar'>
        <div className='brand'>
          <span className='brand-seal'>墨</span>
          <div>
            <strong>墨舟</strong>
            <small>CONTENT DESK</small>
          </div>
        </div>

        <nav>
          {NAV_ITEMS.map(item => (
            <button
              key={item.key}
              className={view === item.key ? 'nav-item active' : 'nav-item'}
              onClick={() => setView(item.key)}
            >
              <span>{item.mark}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className='sidebar-foot'>
          <span className={health?.status === 'ok' ? 'live-dot' : 'live-dot off'} />
          <div>
            <b>{health?.status === 'ok' ? '系统在线' : '正在连接'}</b>
            <small>本地发布服务</small>
          </div>
        </div>
      </aside>

      <main className='workspace'>
        <header className='topbar'>
          <div>
            <span className='eyebrow'>PUBLISHING OPERATIONS</span>
            <h1>{NAV_ITEMS.find(item => item.key === view)?.label}</h1>
          </div>
          <div className='topbar-actions'>
            <button
              className='button ghost'
              disabled={Boolean(busy)}
              onClick={() => runAction(
                'sync',
                api.syncNotion,
                result => `同步完成：新增 ${result.created}，更新 ${result.updated}`
              )}
            >
              <span className={busy === 'sync' ? 'spin' : ''}>↻</span>
              从 Notion 同步
            </button>
            <button className='button ink' onClick={() => setView('articles')}>
              查看内容库 →
            </button>
          </div>
        </header>

        {view === 'dashboard' && (
          <Dashboard
            data={dashboard}
            platforms={platforms}
            health={health}
            busy={busy}
            runAction={runAction}
            onNavigate={setView}
          />
        )}
        {view === 'articles' && (
          <Articles
            articles={articles}
            busy={busy}
            reload={loadArticles}
            runAction={runAction}
            notify={notify}
          />
        )}
        {view === 'settings' && settingsData && (
          <Settings
            data={settingsData}
            platforms={platforms}
            notify={notify}
            onSaved={async () => {
              await Promise.all([loadSettings(), loadOverview()])
            }}
          />
        )}
      </main>

      {toast && <div className={`toast ${toast.kind}`}>{toast.message}</div>}
    </div>
  )
}

function Dashboard ({ data, platforms, health, busy, runAction, onNavigate }) {
  const counts = data?.by_status || {}
  const cards = [
    { label: '内容总量', value: data?.total || 0, note: '系统内全部稿件' },
    { label: '等待发布', value: counts.ready || 0, note: '已同步，可立即发布' },
    {
      label: '处理完成',
      value: (counts.published || 0) + (counts.drafted || 0) + (counts.completed || 0),
      note: '已发布或已存草稿'
    },
    {
      label: '需要处理',
      value: (counts.failed || 0) + (counts.partial || 0),
      note: '失败或部分成功'
    }
  ]

  return (
    <div className='page enter'>
      <section className='dispatch-banner'>
        <div className='banner-copy'>
          <span className='section-number'>VOL. 01 / 今日编务</span>
          <h2>让内容先归档，<br /><em>再抵达每一个平台。</em></h2>
          <p>Notion 是内容源，墨舟负责同步、编排、发布与留痕。</p>
        </div>
        <div className='banner-stamp'>
          <span>自动调度</span>
          <strong>{health?.scheduler?.running ? 'ON' : 'OFF'}</strong>
          <small>每 15 秒检查任务</small>
        </div>
      </section>

      <section className='metrics'>
        {cards.map((card, index) => (
          <article className='metric-card' key={card.label}>
            <span>0{index + 1}</span>
            <strong>{String(card.value).padStart(2, '0')}</strong>
            <div>
              <b>{card.label}</b>
              <small>{card.note}</small>
            </div>
          </article>
        ))}
      </section>

      <div className='dashboard-grid'>
        <section className='panel activity-panel'>
          <PanelHead
            kicker='RECENT LOG'
            title='最近发布记录'
            action={<button className='text-button' onClick={() => onNavigate('articles')}>全部内容 →</button>}
          />
          <div className='activity-list'>
            {data?.recent_records?.length
              ? data.recent_records.map(record => (
                <div className='activity-row' key={record.id}>
                  <div className={`platform-avatar ${record.platform}`}>
                    {PLATFORM_LABELS[record.platform]?.slice(0, 1) || '?'}
                  </div>
                  <div className='activity-copy'>
                    <b>{record.title}</b>
                    <span>{PLATFORM_LABELS[record.platform] || record.platform}</span>
                  </div>
                  <StatusPill value={record.status} />
                  <time>{formatDate(record.created_at)}</time>
                </div>
              ))
              : <EmptyState compact text='还没有发布记录，先从 Notion 同步一篇内容。' />}
          </div>
        </section>

        <section className='panel channel-panel'>
          <PanelHead kicker='CHANNELS' title='发布通道' />
          <div className='channel-list'>
            {platforms.map(platform => (
              <div className='channel-row' key={platform.key}>
                <div className={`channel-symbol ${platform.key}`}>
                  {PLATFORM_LABELS[platform.key]?.slice(0, 1)}
                </div>
                <div>
                  <b>{platform.name}</b>
                  <small>
                    {!platform.implemented
                      ? '接口预留 · 等待开发'
                      : platform.configured
                        ? '配置完整'
                        : '等待配置'}
                  </small>
                </div>
                <span className={platform.enabled && platform.implemented ? 'signal on' : 'signal'} />
              </div>
            ))}
          </div>
          <button
            className='button wide paper'
            disabled={Boolean(busy)}
            onClick={() => runAction(
              'auto',
              api.runAutomation,
              result => `自动发布检查完成，处理 ${result.processed} 篇`
            )}
          >
            立即执行自动发布
          </button>
        </section>
      </div>
    </div>
  )
}

function Articles ({ articles, busy, reload, runAction, notify }) {
  const [status, setStatus] = useState('all')
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState(null)
  const [creating, setCreating] = useState(false)

  const applyFilter = async (nextStatus = status, nextQuery = query) => {
    setStatus(nextStatus)
    await reload(nextStatus, nextQuery)
  }

  return (
    <div className='page enter'>
      <div className='library-toolbar'>
        <div className='filter-tabs'>
          {[
            ['all', '全部'],
            ['ready', '待发布'],
            ['drafted', '平台草稿'],
            ['published', '已发布'],
            ['failed', '异常']
          ].map(([key, label]) => (
            <button
              key={key}
              className={status === key ? 'active' : ''}
              onClick={() => applyFilter(key)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className='search-box'>
          <span>⌕</span>
          <input
            value={query}
            placeholder='搜索标题或作者'
            onChange={event => setQuery(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') applyFilter(status, query)
            }}
          />
        </div>
        <button className='button vermilion' onClick={() => setCreating(true)}>
          ＋ 新建稿件
        </button>
      </div>

      <section className='article-sheet'>
        <div className='article-table-head'>
          <span>稿件</span>
          <span>类型 / 模式</span>
          <span>目标平台</span>
          <span>状态</span>
          <span>操作</span>
        </div>
        {articles.length
          ? articles.map((article, index) => (
            <article className='article-row' key={article.id}>
              <div className='article-title-cell'>
                <span className='folio'>{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <button onClick={() => setEditing(article)}>{article.title}</button>
                  <small>
                    {article.author || '未署名'} · 更新于 {formatDate(article.updated_at)}
                  </small>
                  {articleFailureReason(article) && (
                    <small
                      className='article-error'
                      title={articleFailureReason(article)}
                    >
                      失败原因：{articleFailureReason(article)}
                    </small>
                  )}
                </div>
              </div>
              <div className='type-cell'>
                <b>{article.article_type === 'image' ? '图片' : '图文'}</b>
                <small>{article.publish_mode === 'automatic' ? '自动发布' : '手动发布'}</small>
              </div>
              <div className='platform-chips'>
                {article.target_platforms.map(key => (
                  <span key={key}>
                    {PLATFORM_LABELS[key] || key}
                    · {article.platform_actions?.[key] === 'publish' ? '直发' : '草稿'}
                  </span>
                ))}
              </div>
              <StatusPill value={article.status} />
              <div className='row-actions'>
                <button onClick={() => setEditing(article)}>编辑</button>
                <button
                  className={article.ai_enriched_at ? 'ai-link done' : 'ai-link'}
                  disabled={Boolean(busy)}
                  onClick={() => runAction(
                    `ai-${article.id}`,
                    () => api.enrichArticle(article.id),
                    () => 'AI 加工完成，已生成标签和平台版本'
                  )}
                >
                  {article.ai_enriched_at ? 'AI已加工' : 'AI加工'}
                </button>
                <button
                  className='publish-link'
                  disabled={Boolean(busy) || article.status === 'publishing'}
                  onClick={() => runAction(
                    `publish-${article.id}`,
                    () => api.publishArticle(article.id),
                    publishResultNotice
                  )}
                >
                  发布 →
                </button>
              </div>
            </article>
          ))
          : <EmptyState text='内容库还是空的。你可以新建稿件，或从 Notion 同步。' />}
      </section>

      {(editing || creating) && (
        <ArticleEditor
          article={editing}
          onClose={() => {
            setEditing(null)
            setCreating(false)
          }}
          onSaved={async message => {
            notify(message)
            setEditing(null)
            setCreating(false)
            await reload(status, query)
          }}
        />
      )}
    </div>
  )
}

function ArticleEditor ({ article, onClose, onSaved }) {
  const empty = {
    title: '',
    author: '',
    article_type: 'article',
    content_md: '',
    cover_url: '',
    source_url: '',
    tags: [],
    publish_mode: 'manual',
    target_platforms: ['wechat'],
    platform_actions: { wechat: 'draft' },
    ai_result: {}
  }
  const [form, setForm] = useState(article ? { ...article } : empty)
  const [saving, setSaving] = useState(false)
  const [enriching, setEnriching] = useState(false)
  const [contentView, setContentView] = useState('edit')
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))

  const save = async () => {
    setSaving(true)
    try {
      const values = {
        title: form.title,
        author: form.author,
        article_type: form.article_type,
        content_md: form.content_md,
        cover_url: form.cover_url,
        source_url: form.source_url,
        tags: form.tags,
        publish_mode: form.publish_mode,
        target_platforms: form.target_platforms,
        platform_actions: form.platform_actions,
        ai_result: form.ai_result
      }
      if (article) {
        await api.updateArticle(article.id, values)
      } else {
        await api.createArticle(values)
      }
      await onSaved(article ? '稿件已更新' : '稿件已创建')
    } catch (error) {
      window.alert(error.message)
    } finally {
      setSaving(false)
    }
  }

  const enrich = async () => {
    if (!article) {
      window.alert('请先保存稿件，再进行 AI 加工')
      return
    }
    setEnriching(true)
    try {
      const enriched = await api.enrichArticle(article.id)
      setForm(current => ({
        ...current,
        tags: enriched.tags,
        ai_result: enriched.ai_result,
        ai_enriched_at: enriched.ai_enriched_at
      }))
    } catch (error) {
      window.alert(error.message)
    } finally {
      setEnriching(false)
    }
  }

  const updatePlatformVariant = (platform, key, value) => {
    setForm(current => ({
      ...current,
      ai_result: {
        ...current.ai_result,
        platforms: {
          ...(current.ai_result?.platforms || {}),
          [platform]: {
            ...(current.ai_result?.platforms?.[platform] || {}),
            [key]: value
          }
        }
      }
    }))
  }

  return (
    <div className='modal-backdrop' onMouseDown={onClose}>
      <section className='editor-drawer' onMouseDown={event => event.stopPropagation()}>
        <header>
          <div>
            <span className='eyebrow'>{article ? `ARTICLE / ${article.id}` : 'NEW ARTICLE'}</span>
            <h2>{article ? '编辑稿件' : '创建稿件'}</h2>
          </div>
          <button className='close-button' onClick={onClose}>×</button>
        </header>
        <div className='editor-body'>
          {articleFailureReason(form) && (
            <div className='publish-error-panel' role='alert'>
              <span>上次发布失败</span>
              <p>{articleFailureReason(form)}</p>
            </div>
          )}
          <label className='field full'>
            <span>标题</span>
            <input value={form.title} onChange={e => set('title', e.target.value)} />
          </label>
          <div className='field-grid'>
            <label className='field'>
              <span>作者</span>
              <input value={form.author} onChange={e => set('author', e.target.value)} />
            </label>
            <label className='field'>
              <span>内容类型</span>
              <select value={form.article_type} onChange={e => set('article_type', e.target.value)}>
                <option value='article'>公众号图文</option>
                <option value='image'>图片消息</option>
              </select>
            </label>
          </div>
          <div className='field full markdown-field'>
            <div className='markdown-field-head'>
              <span>Markdown 正文</span>
              <div className='view-switch' role='group' aria-label='正文显示方式'>
                <button
                  type='button'
                  className={contentView === 'edit' ? 'active' : ''}
                  aria-pressed={contentView === 'edit'}
                  onClick={() => setContentView('edit')}
                >
                  编辑
                </button>
                <button
                  type='button'
                  className={contentView === 'preview' ? 'active' : ''}
                  aria-pressed={contentView === 'preview'}
                  onClick={() => setContentView('preview')}
                >
                  预览
                </button>
              </div>
            </div>
            {contentView === 'edit'
              ? (
                <textarea
                  className='content-editor'
                  value={form.content_md}
                  onChange={e => set('content_md', e.target.value)}
                  placeholder='# 从这里开始写作'
                />
                )
              : <MarkdownPreview markdown={form.content_md} />}
          </div>
          <label className='field full'>
            <span>封面图片 URL</span>
            <input value={form.cover_url} onChange={e => set('cover_url', e.target.value)} />
          </label>
          <label className='field full'>
            <span>阅读原文 URL</span>
            <input value={form.source_url} onChange={e => set('source_url', e.target.value)} />
          </label>
          <div className='field-grid'>
            <label className='field'>
              <span>发布方式</span>
              <select value={form.publish_mode} onChange={e => set('publish_mode', e.target.value)}>
                <option value='manual'>手动发布</option>
                <option value='automatic'>自动发布</option>
              </select>
            </label>
            <div className='field platform-target-field'>
              <span>目标平台</span>
              <div className='platform-action-list'>
                {Object.entries(PLATFORM_LABELS).map(([key, label]) => (
                  <div className='platform-action-row' key={key}>
                    <label>
                      <input
                        type='checkbox'
                        checked={form.target_platforms.includes(key)}
                        onChange={e => {
                          const next = e.target.checked
                            ? [...form.target_platforms, key]
                            : form.target_platforms.filter(item => item !== key)
                          setForm(current => ({
                            ...current,
                            target_platforms: next,
                            platform_actions: {
                              ...current.platform_actions,
                              [key]: current.platform_actions?.[key] ||
                                (key === 'wechat' ? 'draft' : 'publish')
                            }
                          }))
                        }}
                      />
                      {label}
                    </label>
                    <select
                      disabled={!form.target_platforms.includes(key)}
                      value={form.platform_actions?.[key] || (key === 'wechat' ? 'draft' : 'publish')}
                      onChange={e => set('platform_actions', {
                        ...form.platform_actions,
                        [key]: e.target.value
                      })}
                    >
                      <option value='draft'>保存草稿</option>
                      <option value='publish'>直接发布</option>
                    </select>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <section className='ai-editor-panel'>
            <header>
              <div>
                <span className='eyebrow'>AI EDITOR</span>
                <h3>智能加工与平台版本</h3>
              </div>
              <button
                className='button paper'
                disabled={enriching || !article}
                onClick={enrich}
              >
                {enriching ? '正在加工…' : form.ai_enriched_at ? '重新加工' : '开始 AI 加工'}
              </button>
            </header>
            {form.ai_result?.summary
              ? (
                <>
                  <div className='ai-summary'>
                    <div>
                      <b>内容摘要</b>
                      <p>{form.ai_result.summary}</p>
                    </div>
                    <div>
                      <b>人工确认</b>
                      <p>{form.ai_result.editor_notes || '没有额外确认事项'}</p>
                    </div>
                  </div>
                  <div className='ai-tags'>
                    {(form.ai_result.tags || []).map(tag => <span key={tag}>#{tag}</span>)}
                  </div>
                  <div className='ai-variants'>
                    {Object.entries(form.ai_result.platforms || {}).map(([key, variant]) => (
                      <article key={key}>
                        <header>
                          <b>{PLATFORM_LABELS[key] || key}版本</b>
                          <button
                            onClick={() => setForm(current => ({
                              ...current,
                              title: variant.title || current.title,
                              content_md: variant.content_md || current.content_md
                            }))}
                          >
                            应用到主稿
                          </button>
                        </header>
                        <input
                          value={variant.title || ''}
                          onChange={e => updatePlatformVariant(key, 'title', e.target.value)}
                        />
                        <textarea
                          value={variant.content_md || ''}
                          onChange={e => updatePlatformVariant(key, 'content_md', e.target.value)}
                        />
                      </article>
                    ))}
                  </div>
                </>
                )
              : (
                <p className='ai-empty'>
                  AI 会在不虚构事实的前提下生成标签、摘要和各平台专用版本。
                  生成结果可以人工修改，发布时优先使用对应平台版本。
                </p>
                )}
          </section>
        </div>
        <footer>
          <button className='button ghost' onClick={onClose}>取消</button>
          <button className='button ink' disabled={saving} onClick={save}>
            {saving ? '正在保存…' : '保存稿件'}
          </button>
        </footer>
      </section>
    </div>
  )
}

function MarkdownPreview ({ markdown }) {
  const html = useMemo(() => {
    const source = (markdown || '').replace(/<empty-block\s*\/?>/gi, '')
    return DOMPurify.sanitize(marked.parse(source, {
      breaks: true,
      gfm: true
    }))
  }, [markdown])

  if (!(markdown || '').trim()) {
    return (
      <div className='markdown-preview empty'>
        <span>PREVIEW</span>
        <p>正文为空，切换到“编辑”开始写作。</p>
      </div>
    )
  }

  return (
    <article
      className='markdown-preview'
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

function articleFailureReason (article) {
  if (!article || !['failed', 'partial'].includes(article.status)) return ''
  return article.latest_publish_error || article.last_error || ''
}

function publishResultNotice (result) {
  const issues = (result.results || [])
    .filter(item => item.status === 'failed' || item.status === 'warning')
    .map(item => {
      const platform = PLATFORM_LABELS[item.platform] || item.platform
      return `${platform}：${item.error || '未知错误'}`
    })

  if (issues.length) {
    const prefix = result.status === 'partial'
      ? '部分平台发布失败'
      : result.status === 'published'
        ? '文章已发布，但后续处理失败'
        : '发布失败'
    return {
      message: `${prefix}：${issues.join('；')}`,
      kind: 'error'
    }
  }
  if (result.status === 'drafted') return '已保存到平台草稿箱'
  if (result.status === 'published') return '发布成功'
  return `任务已完成，当前状态：${STATUS_LABELS[result.status] || result.status}`
}

function Settings ({ data, platforms, notify, onSaved }) {
  const [form, setForm] = useState({ ...data.values })
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState('')
  const [notionFields, setNotionFields] = useState([])
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))

  const save = async () => {
    setSaving(true)
    try {
      await api.saveSettings(form)
      notify('配置已保存，自动任务会在下一轮读取新配置')
      await onSaved()
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  const test = async (key, action) => {
    setTesting(key)
    try {
      await api.saveSettings(form)
      const result = await action()
      notify(result.message || `连接成功：${result.name || ''}`)
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setTesting('')
    }
  }

  const loadNotionFields = async () => {
    setTesting('notion-schema')
    try {
      await api.saveSettings(form)
      const schema = await api.notionSchema()
      setNotionFields(schema.fields)
      notify(`已读取 ${schema.fields.length} 个 Notion 字段`)
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setTesting('')
    }
  }

  return (
    <div className='page enter settings-page'>
      <section className='settings-intro'>
        <span className='section-number'>SYSTEM / CONNECTIONS</span>
        <h2>把钥匙留在本机，<br />让流程自己运转。</h2>
        <p>敏感配置保存在本地 SQLite。前端返回时会自动遮罩，不会重复显示明文。</p>
      </section>

      <SettingsSection
        index='01'
        title='Notion 内容源'
        description='同步状态为“待发布”的页面，并读取官方 Markdown。'
        action={
          <div className='settings-actions'>
            <button
              className='button paper'
              disabled={Boolean(testing)}
              onClick={loadNotionFields}
            >
              {testing === 'notion-schema' ? '读取中…' : '读取字段'}
            </button>
            <button
              className='button paper'
              disabled={Boolean(testing)}
              onClick={() => test('notion', api.testNotion)}
            >
              {testing === 'notion' ? '测试中…' : '测试连接'}
            </button>
          </div>
        }
      >
        <div className='settings-grid'>
          <TextField label='Integration Token' secret value={form.notion_token} onChange={v => set('notion_token', v)} />
          <TextField label='Database ID' value={form.notion_database_id} onChange={v => set('notion_database_id', v)} />
          <TextField label='Data Source ID（可选）' value={form.notion_data_source_id} onChange={v => set('notion_data_source_id', v)} />
          <TextField label='代理地址（留空直连）' value={form.notion_proxy_url} onChange={v => set('notion_proxy_url', v)} placeholder='http://127.0.0.1:7890' />
          <TextField label='待同步状态' value={form.notion_pending_status} onChange={v => set('notion_pending_status', v)} />
          <TextField label='发布完成状态' value={form.notion_published_status} onChange={v => set('notion_published_status', v)} />
          <NumberField label='同步间隔（分钟）' value={form.notion_sync_interval_minutes} onChange={v => set('notion_sync_interval_minutes', v)} />
        </div>
        <div className='mapping-editor'>
          <header>
            <div>
              <b>字段对应关系</b>
              <span>系统字段 → Notion 数据源字段 → 期望类型</span>
            </div>
            <small>
              {notionFields.length
                ? `已加载 ${notionFields.length} 个实际字段`
                : '可手动填写，或点击“读取字段”'}
            </small>
          </header>
          <div className='mapping-table'>
            {NOTION_FIELD_ROWS.map(row => (
              <MappingField
                key={row.key}
                row={row}
                value={form[row.key]}
                fields={notionFields}
                onChange={value => set(row.key, value)}
              />
            ))}
          </div>
          <div className='mapping-values'>
            <TextField label='Notion 图文类型值' value={form.notion_value_article} onChange={v => set('notion_value_article', v)} />
            <TextField label='Notion 图片类型值' value={form.notion_value_image} onChange={v => set('notion_value_image', v)} />
          </div>
        </div>
        <Toggle
          label='自动同步 Notion'
          note='开启后，后台按设定间隔拉取新内容。'
          checked={form.notion_sync_enabled}
          onChange={v => set('notion_sync_enabled', v)}
        />
      </SettingsSection>

      <SettingsSection
        index='02'
        title='微信公众号'
        description='当前唯一已实现的发布通道，支持图文和图片消息。'
        action={
          <button
            className='button paper'
            disabled={testing === 'wechat'}
            onClick={() => test('wechat', () => api.testPlatform('wechat'))}
          >
            {testing === 'wechat' ? '测试中…' : '验证凭据'}
          </button>
        }
      >
        <div className='settings-grid'>
          <TextField label='AppID' value={form.wechat_app_id} onChange={v => set('wechat_app_id', v)} />
          <TextField label='AppSecret' secret value={form.wechat_app_secret} onChange={v => set('wechat_app_secret', v)} />
          <TextField
            label='微信专用代理（留空直连）'
            value={form.wechat_proxy_url}
            onChange={v => set('wechat_proxy_url', v)}
            placeholder='http://127.0.0.1:7890'
          />
        </div>
        <Toggle
          label='启用微信公众号'
          note='关闭后，即使稿件选择了公众号也不会发布。'
          checked={form.wechat_enabled}
          onChange={v => set('wechat_enabled', v)}
        />
      </SettingsSection>

      <SettingsSection
        index='03'
        title='AI 内容编辑'
        description='自动提取标签、生成摘要，并按目标平台生成可人工修改的内容版本。'
        action={
          <button
            className='button paper'
            disabled={testing === 'ai'}
            onClick={() => test('ai', api.testAI)}
          >
            {testing === 'ai' ? '测试中…' : '测试 AI 接口'}
          </button>
        }
      >
        <div className='settings-grid'>
          <TextField label='API Base URL' value={form.ai_base_url} onChange={v => set('ai_base_url', v)} />
          <TextField label='API Key' secret value={form.ai_api_key} onChange={v => set('ai_api_key', v)} />
          <TextField label='模型名称' value={form.ai_model} onChange={v => set('ai_model', v)} placeholder='例如：gpt-5-mini' />
          <TextField label='AI 专用代理（留空直连）' value={form.ai_proxy_url} onChange={v => set('ai_proxy_url', v)} />
          <label className='field full ai-prompt-field'>
            <span>自定义编辑要求</span>
            <textarea
              value={form.ai_custom_prompt}
              onChange={e => set('ai_custom_prompt', e.target.value)}
              placeholder='例如：保持专业克制，不使用夸张标题，不删除代码示例。'
            />
          </label>
        </div>
        <Toggle
          label='启用 AI 内容加工'
          note='关闭时仍可正常同步和发布原稿。'
          checked={form.ai_enabled}
          onChange={v => set('ai_enabled', v)}
        />
        <Toggle
          label='同步后自动加工'
          note='每次从 Notion 同步新内容后，自动生成标签和平台版本。'
          checked={form.ai_auto_enrich_after_sync}
          onChange={v => set('ai_auto_enrich_after_sync', v)}
        />
      </SettingsSection>

      <SettingsSection
        index='04'
        title='自动发布'
        description='只处理发布方式为“自动”且状态为“待发布”的稿件。'
      >
        <div className='settings-grid compact-grid'>
          <NumberField label='检查间隔（分钟）' value={form.auto_publish_interval_minutes} onChange={v => set('auto_publish_interval_minutes', v)} />
          <label className='field'>
            <span>新同步稿件默认方式</span>
            <select value={form.default_publish_mode} onChange={e => set('default_publish_mode', e.target.value)}>
              <option value='manual'>手动发布</option>
              <option value='automatic'>自动发布</option>
            </select>
          </label>
        </div>
        <Toggle
          label='启用自动发布'
          note='建议先完成平台测试，并用一篇稿件手动验证。'
          checked={form.auto_publish_enabled}
          onChange={v => set('auto_publish_enabled', v)}
        />
      </SettingsSection>

      <SettingsSection
        index='05'
        title='后续平台'
        description='接口和发布记录已经预留，接入时无需改动文章模型。'
      >
        <div className='roadmap-grid'>
          {platforms.filter(item => item.key !== 'wechat').map(platform => (
            <article key={platform.key}>
              <span>{PLATFORM_LABELS[platform.key]}</span>
              <b>ADAPTER READY</b>
              <p>模块已注册，登录与发布实现待下一阶段接入。</p>
            </article>
          ))}
        </div>
      </SettingsSection>

      <div className='save-bar'>
        <div>
          <b>配置只保存在当前设备</b>
          <span>修改后不会自动触发发布。</span>
        </div>
        <button className='button vermilion' disabled={saving} onClick={save}>
          {saving ? '正在保存…' : '保存全部配置'}
        </button>
      </div>
    </div>
  )
}

function SettingsSection ({ index, title, description, action, children }) {
  return (
    <section className='settings-section'>
      <header>
        <span>{index}</span>
        <div>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        {action}
      </header>
      <div className='settings-content'>{children}</div>
    </section>
  )
}

function MappingField ({ row, value, fields, onChange }) {
  const compatible = fields.filter(field => field.type === row.type)
  const currentExists = compatible.some(field => field.name === value)
  return (
    <div className='mapping-row'>
      <div>
        <b>{row.label}{row.required ? ' *' : ''}</b>
        <small>{row.key.replace('notion_field_', '').replace('notion_unique_property', 'source_key')}</small>
      </div>
      <span className='mapping-arrow'>→</span>
      {fields.length
        ? (
          <select value={value || ''} onChange={event => onChange(event.target.value)}>
            {!row.required && <option value=''>不映射</option>}
            {!currentExists && value && <option value={value}>{value}（当前配置）</option>}
            {compatible.map(field => (
              <option value={field.name} key={field.id || field.name}>{field.name}</option>
            ))}
          </select>
          )
        : (
          <input value={value || ''} onChange={event => onChange(event.target.value)} />
          )}
      <span className='type-badge'>{row.type}</span>
    </div>
  )
}

function TextField ({ label, value, onChange, placeholder, secret = false }) {
  return (
    <label className='field'>
      <span>{label}</span>
      <input
        type={secret ? 'password' : 'text'}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={event => onChange(event.target.value)}
      />
    </label>
  )
}

function NumberField ({ label, value, onChange }) {
  return (
    <label className='field'>
      <span>{label}</span>
      <input
        type='number'
        min='1'
        value={value}
        onChange={event => onChange(Number(event.target.value))}
      />
    </label>
  )
}

function Toggle ({ label, note, checked, onChange }) {
  return (
    <label className='toggle-row'>
      <div>
        <b>{label}</b>
        <small>{note}</small>
      </div>
      <input type='checkbox' checked={Boolean(checked)} onChange={e => onChange(e.target.checked)} />
      <span className='toggle-track'><i /></span>
    </label>
  )
}

function PanelHead ({ kicker, title, action }) {
  return (
    <header className='panel-head'>
      <div>
        <span>{kicker}</span>
        <h3>{title}</h3>
      </div>
      {action}
    </header>
  )
}

function StatusPill ({ value }) {
  return <span className={`status-pill ${value}`}>{STATUS_LABELS[value] || value}</span>
}

function EmptyState ({ text, compact = false }) {
  return (
    <div className={compact ? 'empty-state compact' : 'empty-state'}>
      <span>空</span>
      <p>{text}</p>
    </div>
  )
}

function formatDate (value) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(value))
}

export default App
