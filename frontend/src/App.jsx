import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  HardDriveDownload,
  Image as ImageIcon,
  Plus,
  Send,
  Sparkles,
  Trash2,
  Upload,
  WandSparkles
} from 'lucide-react'
import packageMetadata from '../package.json'
import { api, mediaPreviewUrl } from './api'
import Accounts from './Accounts'
import Automation from './Automation'
import About from './About'
import ProxyDirectory from './Proxies'
import Materials, { MaterialPicker } from './Materials'
import News, { NewsPicker } from './News'
import AIAssistant from './AIAssistant'
import BackgroundTasks from './BackgroundTasks'
import PublishProgress from './PublishProgress'
import PublishDialog from './PublishDialog'
import ImageViewer from './ImageViewer'

const MarkdownComposer = lazy(() => import('./MarkdownComposer'))
const APP_VERSION = packageMetadata.version

const NAV_ITEMS = [
  { key: 'dashboard', label: '工作台', mark: '01' },
  { key: 'articles', label: '内容库', mark: '02' },
  { key: 'news', label: '资讯', mark: '03' },
  { key: 'materials', label: '素材库', mark: '04' },
  { key: 'accounts', label: '账号管理', mark: '05' },
  { key: 'settings', label: '设置', mark: '06' },
  { key: 'automation', label: '自动化', mark: '07' },
  { key: 'about', label: '关于', mark: '08' }
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
  douyin: '抖音',
  channels: '视频号',
  bilibili: 'Bilibili',
  csdn: 'CSDN'
}

const BROWSER_PLATFORM_KEYS = ['wechat', 'xiaohongshu', 'douyin', 'channels', 'bilibili', 'csdn']

const CONTENT_TYPE_LABELS = {
  article: '文章',
  image: '图文',
  video: '视频'
}

const ACTIVE_IMAGE_GENERATION = new Set(['queued', 'running'])

const imageGenerationMessage = article => {
  const generation = article?.ai_result?.image_generation
  if (!generation) return '文稿已保存'
  const progress = `${generation.completed || 0} / ${generation.total || 0}`
  if (ACTIVE_IMAGE_GENERATION.has(generation.status)) {
    return `文稿已保存，正在生成图片 ${progress}`
  }
  if (generation.status === 'completed') {
    return `文稿与图片已保存，共 ${generation.succeeded || 0} 张`
  }
  return `文稿已保存，图片成功 ${generation.succeeded || 0} 张、失败 ${generation.failed || 0} 张，可打开稿件重试`
}

async function waitForArticleImages (article, onProgress) {
  let current = article
  while (ACTIVE_IMAGE_GENERATION.has(
    current?.ai_result?.image_generation?.status
  )) {
    onProgress(imageGenerationMessage(current))
    await new Promise(resolve => window.setTimeout(resolve, 1500))
    current = await api.article(current.id)
  }
  return current
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
  const [accounts, setAccounts] = useState([])
  const [settingsData, setSettingsData] = useState(null)
  const [health, setHealth] = useState(null)
  const [busyKeys, setBusyKeys] = useState([])
  const actionRunning = useRef(new Set())
  const [backgroundTasks, setBackgroundTasks] = useState([])
  const backgroundRunning = useRef(new Set())
  const [toast, setToast] = useState(null)
  const [libraryVersion, setLibraryVersion] = useState(0)

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

  const loadAccounts = async () => {
    setAccounts(await api.accounts())
  }

  useEffect(() => {
    loadOverview().catch(error => notify(error.message, 'error'))
  }, [])

  useEffect(() => {
    if (view === 'articles') {
      Promise.all([loadArticles(), loadAccounts(), loadSettings()])
        .catch(error => notify(error.message, 'error'))
    }
    if (view === 'accounts') {
      loadAccounts().catch(error => notify(error.message, 'error'))
    }
    if (view === 'settings' || view === 'automation') {
      Promise.all([loadSettings(), api.platforms().then(setPlatforms)])
        .catch(error => notify(error.message, 'error'))
    }
  }, [view])

  const runAction = async (key, action, successMessage) => {
    if (actionRunning.current.has(key)) return
    actionRunning.current.add(key)
    setBusyKeys(current => current.includes(key) ? current : [...current, key])
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
      actionRunning.current.delete(key)
      setBusyKeys(current => current.filter(item => item !== key))
    }
  }

  const startBackgroundTask = ({ key, title, action, successMessage, destination, onSuccess }) => {
    if (backgroundRunning.current.has(key)) {
      notify(`“${title}”已在后台处理中`)
      return false
    }

    const id = `${key}-${Date.now()}`
    backgroundRunning.current.add(key)
    setBackgroundTasks(current => [{
      id,
      key,
      title,
      status: 'running',
      message: '正在处理，可继续使用其他功能',
      destination,
      startedAt: new Date().toISOString()
    }, ...current].slice(0, 8))
    notify(`“${title}”已转到后台，可继续其他操作`)

    const updateProgress = message => {
      setBackgroundTasks(current => current.map(task => (
        task.id === id ? { ...task, message } : task
      )))
    }

    Promise.resolve()
      .then(() => action(updateProgress))
      .then(async result => {
        if (onSuccess) await onSuccess(result)
        const message = typeof successMessage === 'function'
          ? successMessage(result)
          : successMessage
        setBackgroundTasks(current => current.map(task => (
          task.id === id
            ? { ...task, status: 'completed', message: message || '处理完成', result }
            : task
        )))
        notify(message || `“${title}”已完成`)
      })
      .catch(error => {
        setBackgroundTasks(current => current.map(task => (
          task.id === id
            ? { ...task, status: 'failed', message: error.message || '处理失败' }
            : task
        )))
        notify(`${title}失败：${error.message}`, 'error')
      })
      .finally(() => backgroundRunning.current.delete(key))

    return true
  }

  const handleAssistantCreated = async (result, navigate = false) => {
    await loadOverview()
    if (result.destination === 'articles') {
      await loadArticles()
    } else {
      setLibraryVersion(current => current + 1)
    }
    if (navigate) setView(result.destination)
  }

  return (
    <div className='app-shell'>
      <aside className='sidebar'>
        <div className='brand'>
          <span className='brand-seal'>墨</span>
          <div>
            <strong>墨流</strong>
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
            <small>本地发布服务 · v{APP_VERSION}</small>
          </div>
        </div>
      </aside>

      <main className='workspace'>
        <header className='topbar'>
          <div>
            <span className='eyebrow'>PUBLISHING OPERATIONS</span>
            <h1>{NAV_ITEMS.find(item => item.key === view)?.label}</h1>
          </div>
          {view !== 'about' && (
            <div className='topbar-actions'>
              <button
                className='button ghost'
                disabled={backgroundRunning.current.has('sync-notion')}
                onClick={() => startBackgroundTask({
                  key: 'sync-notion',
                  title: '从 Notion 同步',
                  action: api.syncNotion,
                  destination: 'articles',
                  successMessage: result => `同步完成：新增 ${result.created}，更新 ${result.updated}，本地化图片 ${result.images_downloaded || 0} 张，复用 ${result.images_reused || 0} 张，生成封面 ${result.covers_generated || 0} 张，Notion 已标记 ${result.marked_synced || 0} 篇${result.image_errors?.length ? `，图片下载失败 ${result.image_errors.length} 张` : ''}${result.cover_errors?.length ? `，封面生成失败 ${result.cover_errors.length} 张` : ''}`,
                  onSuccess: () => Promise.all([loadOverview(), loadArticles()])
                })}
              >
                <span className={backgroundRunning.current.has('sync-notion') ? 'spin' : ''}>↻</span>
                从 Notion 同步
              </button>
              <button className='button ink' onClick={() => setView('articles')}>
                查看内容库 →
              </button>
            </div>
          )}
        </header>

        {view === 'dashboard' && (
          <Dashboard
            data={dashboard}
            platforms={platforms}
            health={health}
            busyKeys={busyKeys}
            runAction={runAction}
            onNavigate={setView}
          />
        )}
        {view === 'articles' && (
          <Articles
            articles={articles}
            platforms={platforms}
            busyKeys={busyKeys}
            reload={loadArticles}
            reloadOverview={loadOverview}
            runAction={runAction}
            startBackgroundTask={startBackgroundTask}
            notify={notify}
            accounts={accounts}
            automationTargets={settingsData?.values?.auto_publish_targets || {}}
          />
        )}
        {view === 'news' && (
          <News key={'news-' + libraryVersion} notify={notify} />
        )}
        {view === 'materials' && (
          <Materials key={'materials-' + libraryVersion} notify={notify} />
        )}
        {view === 'accounts' && (
          <Accounts
            notify={notify}
            onChanged={setAccounts}
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
        {view === 'automation' && settingsData && (
          <Automation
            data={settingsData}
            platforms={platforms}
            notify={notify}
            onSaved={async () => {
              await Promise.all([loadSettings(), loadOverview()])
            }}
          />
        )}
        {view === 'about' && <About version={APP_VERSION} />}
      </main>

      <AIAssistant
        notify={notify}
        onCreated={handleAssistantCreated}
      />
      <PublishProgress />
      <BackgroundTasks
        tasks={backgroundTasks}
        onDismiss={id => setBackgroundTasks(current => current.filter(task => task.id !== id))}
        onOpen={task => {
          if (task.destination) setView(task.destination)
        }}
      />
      {toast && <div className={`toast ${toast.kind}`}>{toast.message}</div>}
    </div>
  )
}

function Dashboard ({ data, platforms, health, busyKeys, runAction, onNavigate }) {
  const counts = data?.by_status || {}
  const formatMetricValue = value => {
    const count = Number(value || 0)
    if (count >= 100000000) return `${(count / 100000000).toFixed(1).replace(/\.0$/, '')}亿`
    if (count >= 10000) return `${(count / 10000).toFixed(1).replace(/\.0$/, '')}万`
    return count.toLocaleString('zh-CN')
  }
  const cards = [
    {
      label: '全网粉丝',
      value: data?.total_followers || 0,
      note: `${data?.follower_accounts || 0} 个账号已同步`
    },
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
          <p>Notion 是内容源，墨流负责同步、编排、发布与留痕。</p>
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
            <strong title={Number(card.value || 0).toLocaleString('zh-CN')}>
              {formatMetricValue(card.value)}
            </strong>
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
            disabled={busyKeys.some(key => key === 'auto' || key.startsWith('publish-') || key.startsWith('retry-'))}
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

function Articles ({ articles, accounts, platforms, automationTargets, busyKeys, reload, reloadOverview, runAction, startBackgroundTask, notify }) {
  const [status, setStatus] = useState('all')
  const [query, setQuery] = useState('')
  const [articleType, setArticleType] = useState('all')
  const [editing, setEditing] = useState(null)
  const [creating, setCreating] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [publishingArticle, setPublishingArticle] = useState(null)
  const isBusy = key => busyKeys.includes(key)
  const publishingBusy = busyKeys.some(key => (
    key === 'auto' || key.startsWith('publish-') || key.startsWith('retry-')
  ))
  const platformSupports = (key, contentType) => {
    const supportedTypes = platforms.find(item => item.key === key)?.content_types
    return !Array.isArray(supportedTypes) || supportedTypes.includes(contentType)
  }

  const applyFilter = async (nextStatus = status, nextQuery = query) => {
    setStatus(nextStatus)
    await reload(nextStatus, nextQuery)
  }

  const removeArticle = article => {
    const sourceNotice = article.notion_page_id
      ? ' 这篇稿件来自 Notion，下次同步时可能重新出现。'
      : ''
    if (!window.confirm(
      `确定删除稿件“${article.title}”吗？发布记录和文章关联将一并删除，且无法恢复。${sourceNotice}`
    )) return
    runAction(
      `delete-article-${article.id}`,
      () => api.deleteArticle(article.id),
      result => result.cleanup_warning
        ? { message: `稿件已删除；部分本地配图未清理：${result.cleanup_warning}`, kind: 'error' }
        : `稿件“${article.title}”已删除`
    ).catch(() => {})
  }

  const visibleArticles = articles.filter(
    article => articleType === 'all' || article.article_type === articleType
  )
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
        <div className='library-actions'>
          <button className='button paper ai-create-button' onClick={() => setGenerating(true)}>
            <span>✦</span>
            AI 生成
          </button>
          <button className='button vermilion' onClick={() => setCreating(true)}>
            ＋ 新建稿件
          </button>
        </div>
      </div>

      <div className='content-type-tabs' role='tablist' aria-label='内容类型'>
        {[
          ['all', '全部类型'],
          ['article', '文章'],
          ['image', '图文'],
          ['video', '视频']
        ].map(([key, label]) => (
          <button
            type='button'
            role='tab'
            aria-selected={articleType === key}
            className={articleType === key ? 'active' : ''}
            key={key}
            onClick={() => setArticleType(key)}
          >
            {label}
            <span>
              {key === 'all'
                ? articles.length
                : articles.filter(article => article.article_type === key).length}
            </span>
          </button>
        ))}
      </div>
      <section className='article-sheet'>
        <div className='article-table-head'>
          <span>稿件</span>
          <span>类型 / 队列</span>
          <span>操作</span>
        </div>
        {visibleArticles.length
          ? visibleArticles.map((article, index) => (
            <article className='article-row' key={article.id}>
              <div className='article-title-cell'>
                <span className='folio'>{String(index + 1).padStart(2, '0')}</span>
                <div>
                  <button onClick={() => setEditing(article)}>{article.title}</button>
                  <small>
                    {article.author || '未署名'} · 更新于 {formatDate(article.updated_at)}
                  </small>
                  {article.ai_result?.image_generation &&
                    article.ai_result.image_generation.status !== 'completed' && (
                    <small className={`article-image-generation ${article.ai_result.image_generation.status}`}>
                      {imageGenerationMessage(article)}
                    </small>
                  )}
                </div>
              </div>
              <div className='type-cell'>
                <b>{CONTENT_TYPE_LABELS[article.article_type] || article.article_type}</b>
                <small>{article.content_status === 'ready' ? '发布队列' : '内容草稿'}</small>
              </div>
              <div className='row-actions'>
                <button onClick={() => setEditing(article)}>编辑</button>
                <button
                  className={article.ai_enriched_at ? 'ai-link done' : 'ai-link'}
                  disabled={isBusy(`ai-${article.id}`)}
                  onClick={() => runAction(
                    `ai-${article.id}`,
                    () => api.enrichArticle(article.id),
                    () => 'AI 加工完成，已生成标题建议和标签'
                  )}
                >
                  {article.ai_enriched_at ? 'AI已加工' : 'AI加工'}
                </button>
                <button
                  className='publish-link'
                  disabled={publishingBusy || article.status === 'publishing'}
                  onClick={() => setPublishingArticle(article)}
                >
                  <Send size={13} />
                  发布
                </button>
                <button
                  className='delete-link'
                  type='button'
                  title='删除稿件'
                  aria-label={`删除稿件 ${article.title}`}
                  disabled={isBusy(`delete-article-${article.id}`) || article.status === 'publishing'}
                  onClick={() => removeArticle(article)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </article>
          ))
          : <EmptyState text='内容库还是空的。你可以新建稿件，或从 Notion 同步。' />}
      </section>

      {generating && (
        <AIArticleGenerator
          onClose={() => setGenerating(false)}
          onGenerate={values => {
            const started = startBackgroundTask({
              key: `generate-article-${Date.now()}`,
              title: values.article_type === 'image'
                ? `生成图文：${values.topic}`
                : `生成文章：${values.topic}`,
              action: async updateProgress => {
                const article = await api.generateArticle(values)
                await Promise.all([reload(status, query), reloadOverview()])
                updateProgress(imageGenerationMessage(article))
                return waitForArticleImages(article, updateProgress)
              },
              destination: 'articles',
              successMessage: result => imageGenerationMessage(result),
              onSuccess: () => Promise.all([reload(status, query), reloadOverview()])
            })
            if (started) setGenerating(false)
            return started
          }}
        />
      )}
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
      {publishingArticle && (
        <PublishDialog
          article={publishingArticle}
          accounts={accounts}
          platforms={platforms}
          automationTargets={automationTargets}
          onClose={() => setPublishingArticle(null)}
          onPublish={payload => runAction(
            `publish-${publishingArticle.id}`,
            () => api.publishArticle(publishingArticle.id, payload),
            publishResultNotice
          )}
        />
      )}
    </div>
  )
}


function AIArticleGenerator ({ onClose, onGenerate }) {
  const [form, setForm] = useState({
    topic: '',
    article_type: 'article',
    author: '',
    audience: '',
    style: '',
    requirements: '',
    word_count: 1200,
    image_count: 1,
    image_mode: 'auto',
    material_ids: [],
    news_ids: []
  })
  const [storyboard, setStoryboard] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))

  const selectType = articleType => {
    setStoryboard(null)
    setForm(current => ({
      ...current,
      article_type: articleType,
      word_count: articleType === 'image' ? 700 : 1200,
      image_count: articleType === 'image' ? 5 : 1,
      image_mode: 'auto'
    }))
  }

  const requestValues = () => ({
    ...form,
    topic: form.topic.trim(),
    word_count: Number(form.word_count),
    image_count: Number(form.image_count)
  })

  const submit = async event => {
    event.preventDefault()
    if (form.topic.trim().length < 2 || submitting) return
    setError('')

    if (form.article_type !== 'image' || storyboard) {
      const started = onGenerate({
        ...requestValues(),
        storyboard: form.article_type === 'image' ? storyboard : null
      })
      if (!started) setError('相同任务正在后台处理中')
      return
    }

    setSubmitting(true)
    try {
      const result = await api.generateStoryboard(requestValues())
      setStoryboard(result)
      setForm(current => ({
        ...current,
        image_count: result.pages.length
      }))
    } catch (generationError) {
      setError(generationError.message)
    } finally {
      setSubmitting(false)
    }
  }

  const updateStoryboard = (key, value) => {
    setStoryboard(current => ({ ...current, [key]: value }))
  }

  const updateVisualStyle = (key, value) => {
    setStoryboard(current => ({
      ...current,
      visual_style: {
        ...(current.visual_style || {}),
        [key]: value
      }
    }))
  }

  const updatePage = (pageIndex, key, value) => {
    setStoryboard(current => ({
      ...current,
      pages: current.pages.map((page, index) => (
        index === pageIndex ? { ...page, [key]: value } : page
      ))
    }))
  }

  const addPage = () => {
    if (!storyboard || storyboard.pages.length >= 9) return
    const pages = [
      ...storyboard.pages,
      {
        index: storyboard.pages.length,
        role: 'content',
        headline: '新页面',
        body: '',
        visual: '根据主题补充这一页的视觉主体与场景',
        layout: ''
      }
    ]
    setStoryboard(current => ({ ...current, pages }))
    set('image_count', pages.length)
  }

  const removePage = pageIndex => {
    if (!storyboard || pageIndex === 0 || storyboard.pages.length <= 1) return
    const pages = storyboard.pages
      .filter((_, index) => index !== pageIndex)
      .map((page, index) => ({
        ...page,
        index,
        role: index === 0 ? 'cover' : page.role
      }))
    setStoryboard(current => ({ ...current, pages }))
    set('image_count', pages.length)
  }

  const isStoryboard = form.article_type === 'image' && storyboard
  const statusTitle = '正在规划图文分镜'
  const statusNote = '完成后可继续调整每一页的内容与版式'

  return (
    <div
      className='modal-backdrop ai-generator-backdrop'
      onMouseDown={onClose}
    >
      <form
        className={isStoryboard ? 'ai-generator storyboard-mode' : 'ai-generator'}
        role='dialog'
        aria-modal='true'
        aria-labelledby='ai-generator-title'
        onSubmit={submit}
        onMouseDown={event => event.stopPropagation()}
      >
        <header>
          <div>
            <span className='eyebrow'>AI DRAFT STUDIO</span>
            <h2 id='ai-generator-title'>
              {isStoryboard ? '编排图文分镜' : '生成新稿件'}
            </h2>
          </div>
          {form.article_type === 'image' && (
            <div className='ai-step-indicator' aria-label='生成进度'>
              <span className={!isStoryboard ? 'active' : 'done'}>01 选题</span>
              <i />
              <span className={isStoryboard ? 'active' : ''}>02 分镜</span>
              <i />
              <span>03 出图</span>
            </div>
          )}
          <button
            type='button'
            className='close-button'
            aria-label='关闭'
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className='ai-generator-body'>
          {!isStoryboard && (
            <>
              <div className='ai-type-switch' role='group' aria-label='内容类型'>
                <button
                  type='button'
                  className={form.article_type === 'article' ? 'active' : ''}
                  aria-pressed={form.article_type === 'article'}
                  onClick={() => selectType('article')}
                >
                  <b>文章</b>
                  <span>结构完整的长内容</span>
                </button>
                <button
                  type='button'
                  className={form.article_type === 'image' ? 'active' : ''}
                  aria-pressed={form.article_type === 'image'}
                  onClick={() => selectType('image')}
                >
                  <b>图文</b>
                  <span>可编辑分镜与统一视觉</span>
                </button>
              </div>

              <label className='field full ai-topic-field'>
                <span>创作主题</span>
                <textarea
                  autoFocus
                  required
                  minLength='2'
                  maxLength='300'
                  value={form.topic}
                  onChange={event => set('topic', event.target.value)}
                  placeholder='输入选题、核心观点或一段创作方向'
                />
              </label>

              <div className='field-grid'>
                <label className='field'>
                  <span>作者</span>
                  <input
                    maxLength='50'
                    value={form.author}
                    onChange={event => set('author', event.target.value)}
                    placeholder='可留空'
                  />
                </label>
                <label className='field'>
                  <span>目标读者</span>
                  <input
                    maxLength='200'
                    value={form.audience}
                    onChange={event => set('audience', event.target.value)}
                    placeholder='例如：内容运营从业者'
                  />
                </label>
                <label className='field'>
                  <span>表达风格</span>
                  <input
                    maxLength='100'
                    value={form.style}
                    onChange={event => set('style', event.target.value)}
                    placeholder='例如：专业、具体、克制'
                  />
                </label>
                <div className='ai-number-fields'>
                  <label className='field'>
                    <span>目标字数</span>
                    <input
                      type='number'
                      min='300'
                      max='5000'
                      step='100'
                      value={form.word_count}
                      onChange={event => set('word_count', event.target.value)}
                    />
                  </label>

                </div>
              </div>

              <div className='ai-image-mode field full'>
                <span>配图方式</span>
                <div role='group' aria-label='配图方式'>
                  <button
                    type='button'
                    className={form.image_mode === 'auto' ? 'active' : ''}
                    onClick={() => set('image_mode', 'auto')}
                  >
                    <b>自动配图</b>
                    <small>按篇幅和章节自动安排</small>
                  </button>
                  <button
                    type='button'
                    className={form.image_mode === 'cover' ? 'active' : ''}
                    onClick={() => set('image_mode', 'cover')}
                  >
                    <b>仅生成封面</b>
                    <small>正文不插入额外图片</small>
                  </button>
                  <button
                    type='button'
                    disabled={form.article_type === 'image'}
                    className={form.image_mode === 'none' ? 'active' : ''}
                    onClick={() => set('image_mode', 'none')}
                  >
                    <b>不配图</b>
                    <small>{form.article_type === 'image' ? '图文内容不可用' : '只生成正文'}</small>
                  </button>
                </div>
              </div>

              <label className='field full ai-requirements-field'>
                <span>补充要求</span>
                <textarea
                  maxLength='2000'
                  value={form.requirements}
                  onChange={event => set('requirements', event.target.value)}
                  placeholder='必须覆盖的要点、需要避开的表达、已有资料等'
                />
              </label>

              <div className='reference-picker-grid'>
                <MaterialPicker
                  selected={form.material_ids}
                  onChange={value => set('material_ids', value)}
                />
                <NewsPicker
                  selected={form.news_ids}
                  onChange={value => set('news_ids', value)}
                />
              </div>
            </>
          )}

          {isStoryboard && (
            <>
              <section className='storyboard-meta'>
                <label className='field full'>
                  <span>帖子标题</span>
                  <input
                    maxLength='120'
                    value={storyboard.title}
                    onChange={event => updateStoryboard('title', event.target.value)}
                  />
                </label>
                <label className='field full'>
                  <span>发布文案</span>
                  <textarea
                    maxLength='5000'
                    value={storyboard.caption_md}
                    onChange={event => updateStoryboard('caption_md', event.target.value)}
                  />
                </label>
                <div className='storyboard-style-grid'>
                  <label className='field'>
                    <span>视觉方向</span>
                    <input
                      value={storyboard.visual_style?.direction || ''}
                      onChange={event => updateVisualStyle('direction', event.target.value)}
                    />
                  </label>
                  <label className='field'>
                    <span>字体气质</span>
                    <input
                      value={storyboard.visual_style?.typography || ''}
                      onChange={event => updateVisualStyle('typography', event.target.value)}
                    />
                  </label>
                  <label className='field full'>
                    <span>统一版式</span>
                    <input
                      value={storyboard.visual_style?.composition || ''}
                      onChange={event => updateVisualStyle('composition', event.target.value)}
                    />
                  </label>
                </div>
                {!!storyboard.visual_style?.palette?.length && (
                  <div className='storyboard-palette' aria-label='统一色板'>
                    {storyboard.visual_style.palette.map((color, index) => (
                      <span
                        key={color + index}
                        style={{ backgroundColor: color }}
                        title={color}
                      />
                    ))}
                  </div>
                )}
              </section>

              <div className='storyboard-grid'>
                {storyboard.pages.map((page, index) => (
                  <article className='storyboard-page' key={page.index}>
                    <header>
                      <div>
                        <b>P{String(index + 1).padStart(2, '0')}</b>
                        {index === 0
                          ? <span>封面</span>
                          : (
                            <select
                              value={page.role}
                              aria-label={'第 ' + (index + 1) + ' 页类型'}
                              onChange={event => updatePage(index, 'role', event.target.value)}
                            >
                              <option value='content'>内容</option>
                              <option value='ending'>收尾</option>
                            </select>
                            )}
                      </div>
                      {index > 0 && (
                        <button
                          type='button'
                          className='icon-action'
                          title='删除此页'
                          aria-label={'删除第 ' + (index + 1) + ' 页'}
                          onClick={() => removePage(index)}
                        >
                          <Trash2 size={15} />
                        </button>
                      )}
                    </header>
                    <label className='field'>
                      <span>页面标题</span>
                      <input
                        maxLength='120'
                        value={page.headline}
                        onChange={event => updatePage(index, 'headline', event.target.value)}
                      />
                    </label>
                    <label className='field'>
                      <span>页面正文</span>
                      <textarea
                        maxLength='1200'
                        value={page.body}
                        onChange={event => updatePage(index, 'body', event.target.value)}
                      />
                    </label>
                    <label className='field visual-field'>
                      <span>视觉画面</span>
                      <textarea
                        maxLength='800'
                        value={page.visual}
                        onChange={event => updatePage(index, 'visual', event.target.value)}
                      />
                    </label>
                    <label className='field'>
                      <span>版式安排</span>
                      <textarea
                        maxLength='500'
                        value={page.layout}
                        onChange={event => updatePage(index, 'layout', event.target.value)}
                      />
                    </label>
                  </article>
                ))}
                {storyboard.pages.length < 9 && (
                  <button type='button' className='storyboard-add' onClick={addPage}>
                    <Plus size={19} />
                    <span>添加一页</span>
                  </button>
                )}
              </div>
            </>
          )}

          {error && <div className='ai-generator-error' role='alert'>{error}</div>}
          {submitting && (
            <div className='ai-generating-status' role='status'>
              <span />
              <div>
                <b>{statusTitle}</b>
                <small>{statusNote}</small>
              </div>
            </div>
          )}
        </div>

        <footer>
          {isStoryboard && (
            <button
              type='button'
              className='button ghost'
              disabled={submitting}
              onClick={() => {
                setStoryboard(null)
                setError('')
              }}
            >
              <ArrowLeft size={15} />
              返回选题
            </button>
          )}
          <button
            type='button'
            className='button ghost'
            onClick={onClose}
          >
            取消
          </button>
          <button
            type='submit'
            className='button vermilion'
            disabled={
              submitting ||
              form.topic.trim().length < 2 ||
              (isStoryboard && (
                !storyboard.title.trim() ||
                !storyboard.caption_md.trim() ||
                storyboard.pages.some(page => !page.headline.trim() || !page.visual.trim())
              ))
            }
          >
            {submitting
              ? '正在生成…'
              : isStoryboard
                ? <><WandSparkles size={16} />生成整套图片</>
                : form.article_type === 'image'
                  ? <><Sparkles size={16} />生成分镜</>
                  : '生成稿件'}
          </button>
        </footer>
      </form>
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
    media_paths: [],
    content_status: 'draft',
    ai_result: {}
  }
  const [form, setForm] = useState(article
    ? {
        ...article,
        content_status: article.content_status ||
          (article.publish_mode === 'automatic' ? 'ready' : 'draft')
      }
    : empty)
  const [saving, setSaving] = useState(false)
  const [enriching, setEnriching] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [localizingImages, setLocalizingImages] = useState(false)
  const [regeneratingImage, setRegeneratingImage] = useState(null)
  const [imageViewer, setImageViewer] = useState(null)
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))
  const aiImagePlan = form.ai_result?.image_plan || []
  const generatedImages = form.ai_result?.generated_images || []
  const imageGeneration = form.ai_result?.image_generation || {}
  const imageGenerationActive = ACTIVE_IMAGE_GENERATION.has(
    imageGeneration.status
  )
  const remoteCover = /^https?:\/\//i.test(form.cover_url || '')
  const hasRemoteImages = remoteCover ||
    /!\[[^\]]*\]\(\s*<?https?:\/\//i.test(form.content_md || '') ||
    (form.media_paths || []).some(path => /^https?:\/\//i.test(path))
  const changeArticleType = articleType => set('article_type', articleType)

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
        media_paths: form.media_paths,
        content_status: form.content_status,
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
        cover_url: enriched.cover_url,
        media_paths: enriched.media_paths,
        ai_result: enriched.ai_result,
        ai_enriched_at: enriched.ai_enriched_at
      }))
    } catch (error) {
      window.alert(error.message)
    } finally {
      setEnriching(false)
    }
  }

  const uploadFiles = async files => {
    const selected = Array.from(files || [])
    if (!selected.length) return []
    setUploading(true)
    try {
      const uploaded = await Promise.all(selected.map(file => api.uploadMedia(file)))
      const paths = uploaded.map(item => item.path)
      setForm(current => ({
        ...current,
        media_paths: [...new Set([...(current.media_paths || []), ...paths])]
      }))
      return paths
    } catch (error) {
      window.alert(error.message)
      return []
    } finally {
      setUploading(false)
    }
  }

  const uploadMedia = async event => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    await uploadFiles(files)
  }

  const uploadCover = async event => {
    const files = Array.from(event.target.files || []).slice(0, 1)
    event.target.value = ''
    const paths = await uploadFiles(files)
    if (paths[0]) set('cover_url', paths[0])
  }

  const localizeImages = async () => {
    if (!article || localizingImages) return
    setLocalizingImages(true)
    try {
      const result = await api.localizeArticleImages(article.id)
      setForm(current => ({
        ...current,
        content_md: result.article.content_md,
        cover_url: result.article.cover_url,
        media_paths: result.article.media_paths
      }))
      window.alert(
        result.errors.length
          ? '本地化完成，部分远程图片下载失败，可稍后重试'
          : '远程图片已保存到本地'
      )
    } catch (error) {
      window.alert(error.message)
    } finally {
      setLocalizingImages(false)
    }
  }

  const regenerateImage = async imageIndex => {
    if (!article || regeneratingImage !== null) return
    setRegeneratingImage(imageIndex)
    try {
      const updated = await api.regenerateArticleImage(article.id, imageIndex)
      setForm(current => ({
        ...current,
        content_md: updated.content_md,
        cover_url: updated.cover_url,
        media_paths: updated.media_paths,
        ai_result: updated.ai_result
      }))    } catch (error) {
      window.alert(error.message)
    } finally {
      setRegeneratingImage(null)
    }
  }

  const moveMedia = (index, offset) => {
    setForm(current => {
      const target = index + offset
      const mediaPaths = [...(current.media_paths || [])]
      if (target < 0 || target >= mediaPaths.length) return current
      const first = mediaPaths[index]
      const second = mediaPaths[target]
      ;[mediaPaths[index], mediaPaths[target]] = [second, first]

      const firstSource = first.replaceAll('\\', '/')
      const secondSource = second.replaceAll('\\', '/')
      const placeholder = `__MOFLOW_MEDIA_${Date.now()}_${index}__`
      const contentMd = current.content_md
        .replaceAll(firstSource, placeholder)
        .replaceAll(secondSource, firstSource)
        .replaceAll(placeholder, secondSource)
      const aiResult = { ...(current.ai_result || {}) }
      for (const key of ['image_plan', 'generated_images']) {
        if (Array.isArray(aiResult[key]) && aiResult[key].length > target) {
          aiResult[key] = [...aiResult[key]]
          ;[aiResult[key][index], aiResult[key][target]] = [
            aiResult[key][target],
            aiResult[key][index]
          ]
        }
      }
      return {
        ...current,
        content_md: contentMd,
        media_paths: mediaPaths,
        ai_result: aiResult
      }
    })
  }

  const removeMedia = index => {
    setForm(current => {
      const path = current.media_paths?.[index] || ''
      const source = path.replaceAll('\\', '/')
      const escaped = source.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      const imagePattern = new RegExp(`!?\\[[^\\]]*\\]\\(${escaped}\\)\\s*`, 'g')
      const mediaPaths = current.media_paths.filter((_, itemIndex) => itemIndex !== index)
      const aiResult = { ...(current.ai_result || {}) }
      if (Array.isArray(aiResult.image_plan)) {
        aiResult.image_plan = aiResult.image_plan.filter((_, itemIndex) => itemIndex !== index)
      }
      if (Array.isArray(aiResult.generated_images)) {
        aiResult.generated_images = aiResult.generated_images.filter((_, itemIndex) => itemIndex !== index)
      }
      return {
        ...current,
        content_md: source
          ? current.content_md.replace(imagePattern, '').trim()
          : current.content_md,
        cover_url: current.cover_url === path ? (mediaPaths[0] || '') : current.cover_url,
        media_paths: mediaPaths,
        ai_result: aiResult
      }
    })
  }

  const setMediaCover = path => {
    setForm(current => ({ ...current, cover_url: path }))
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
              <select value={form.article_type} onChange={e => changeArticleType(e.target.value)}>
                <option value='article'>文章</option>
                <option value='image'>图文（多图）</option>
                <option value='video'>视频</option>
              </select>
            </label>
          </div>
          <div className='content-status-field'>
            <span>稿件状态</span>
            <div className='segmented-control' role='group' aria-label='稿件状态'>
              <button
                type='button'
                className={form.content_status === 'draft' ? 'active' : ''}
                onClick={() => set('content_status', 'draft')}
              >
                内容草稿
              </button>
              <button
                type='button'
                className={form.content_status === 'ready' ? 'active' : ''}
                onClick={() => set('content_status', 'ready')}
              >
                加入发布队列
              </button>
            </div>
          </div>
          <section className='cover-field'>
            <div className='cover-field-copy'>
              <span>稿件封面</span>
              <small>
                {form.cover_url
                  ? remoteCover ? '远程封面，建议保存到本地' : '本地图片'
                  : '尚未设置封面，智能加工时可根据正文自动生成'}
              </small>
            </div>
            <div className={form.cover_url ? 'cover-control has-cover' : 'cover-control'}>
              <button
                type='button'
                className={form.cover_url ? 'cover-preview is-clickable' : 'cover-preview'}
                disabled={!form.cover_url}
                aria-label={form.cover_url ? '打开稿件封面' : '尚未设置封面'}
                title={form.cover_url ? '点击查看大图' : '尚未设置封面'}
                onClick={() => form.cover_url && setImageViewer({
                  src: remoteCover ? form.cover_url : mediaPreviewUrl(form.cover_url),
                  title: '稿件封面',
                  alt: form.title || '稿件封面'
                })}
              >
                {form.cover_url
                  ? (
                    <img
                      src={remoteCover ? form.cover_url : mediaPreviewUrl(form.cover_url)}
                      alt='稿件封面'
                    />
                    )
                  : <ImageIcon size={28} strokeWidth={1.5} />}
              </button>
              <div className='cover-meta'>
                <b>
                  {form.cover_url
                    ? form.cover_url.split(/[\\/]/).pop()
                    : '等待选择或生成封面'}
                </b>
                <span>
                  {form.cover_url && !remoteCover
                    ? form.cover_url
                    : remoteCover
                      ? '当前仍引用网络图片'
                      : '支持 JPG、PNG、WebP、GIF'}
                </span>
              </div>
              <div className='cover-actions'>
                <label className={uploading ? 'button paper disabled' : 'button paper'}>
                  <Upload size={14} />
                  {form.cover_url ? '替换' : '上传'}
                  <input
                    type='file'
                    hidden
                    disabled={uploading}
                    accept='image/jpeg,image/png,image/webp,image/gif'
                    onChange={uploadCover}
                  />
                </label>
                {form.cover_url && (
                  <button
                    type='button'
                    className='button ghost'
                    onClick={() => set('cover_url', '')}
                  >
                    <Trash2 size={14} />
                    移除
                  </button>
                )}
              </div>
            </div>
            {hasRemoteImages && (
              <div className='remote-image-notice'>
                <div>
                  <HardDriveDownload size={17} />
                  <span>稿件中仍有远程图片，发布前建议下载到本地。</span>
                </div>
                {article && (
                  <button
                    type='button'
                    className='button ghost'
                    disabled={localizingImages}
                    onClick={localizeImages}
                  >
                    {localizingImages ? '正在下载…' : '保存到本地'}
                  </button>
                )}
              </div>
            )}
          </section>
          {(form.article_type !== 'article' ||
            form.media_paths?.length > 0 ||
            aiImagePlan.length > 0) && (
            <div className='field full media-field'>
              <div className='media-field-head'>
                <div>
                  <span>{form.article_type === 'video' ? '视频素材' : form.article_type === 'article' ? '文章配图' : '图片素材'}</span>
                  <small>
                    {form.article_type === 'video'
                      ? '小红书视频只选择 1 个视频文件'
                      : form.article_type === 'article'
                        ? '正文配图与封面会保存在本地，发布时自动上传'
                        : '可一次选择多张图片，发布时保持当前顺序'}
                  </small>
                </div>
                <label className={uploading ? 'button paper disabled' : 'button paper'}>
                  {uploading ? '上传中…' : '选择本地素材'}
                  <input
                    type='file'
                    hidden
                    multiple={form.article_type !== 'video'}
                    disabled={uploading}
                    accept={form.article_type === 'video'
                      ? 'video/mp4,video/quicktime,video/webm'
                      : 'image/jpeg,image/png,image/webp,image/gif'}
                    onChange={uploadMedia}
                  />
                </label>
              </div>
              <div className='media-list'>
                {(form.media_paths || []).map((path, index) => (
                  <div className='media-item' key={`${path}-${index}`}>
                    {form.article_type !== 'video' && (
                      <button
                        type='button'
                        className='media-item-preview'
                        title='点击查看大图'
                        aria-label={`打开第 ${index + 1} 张图片`}
                        onClick={() => setImageViewer({
                          src: /^https?:\/\//i.test(path) ? path : mediaPreviewUrl(path),
                          title: path.split(/[\\/]/).pop() || `图片 ${index + 1}`,
                          alt: path.split(/[\\/]/).pop() || `图片 ${index + 1}`
                        })}
                      >
                        <img
                          src={/^https?:\/\//i.test(path) ? path : mediaPreviewUrl(path)}
                          alt=''
                          loading='lazy'
                        />
                      </button>
                    )}
                    <span className='media-order'>{String(index + 1).padStart(2, '0')}</span>
                    <b>{path.split(/[\\/]/).pop()}</b>
                    <div className='media-item-actions'>
                      {form.article_type !== 'video' && form.cover_url !== path && (
                        <button
                          type='button'
                          title='设为封面'
                          aria-label='设为封面'
                          onClick={() => setMediaCover(path)}
                        >
                          <ImageIcon size={13} />
                        </button>
                      )}
                      <button
                        type='button'
                        title='向前移动'
                        aria-label='向前移动'
                        disabled={index === 0}
                        onClick={() => moveMedia(index, -1)}
                      >
                        <ArrowUp size={13} />
                      </button>
                      <button
                        type='button'
                        title='向后移动'
                        aria-label='向后移动'
                        disabled={index === form.media_paths.length - 1}
                        onClick={() => moveMedia(index, 1)}
                      >
                        <ArrowDown size={13} />
                      </button>

                      <button
                        type='button'
                        title='移除图片'
                        aria-label='移除图片'
                        onClick={() => removeMedia(index)}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                ))}
                {!form.media_paths?.length && <p>还没有生成或上传的图片。</p>}
              </div>
              {article && aiImagePlan.length > 0 && (
                <div className='ai-image-status-list'>
                  <header>
                    <b>AI 图片任务</b>
                    <span>{imageGenerationMessage({ ai_result: form.ai_result })}</span>
                  </header>
                  {aiImagePlan.map((plan, imageIndex) => {
                    const generated = generatedImages[imageIndex] || {}
                    const imageStatus = generated.status ||
                      (generated.path ? 'completed' : 'pending')
                    return (
                      <div className={`ai-image-status ${imageStatus}`} key={plan.position || imageIndex}>
                        <span>{String(imageIndex + 1).padStart(2, '0')}</span>
                        <div>
                          <b>{plan.alt || `第 ${imageIndex + 1} 张图片`}</b>
                          <small>
                            {imageStatus === 'completed' && '生成成功'}
                            {imageStatus === 'failed' && (generated.error || '生成失败')}
                            {imageStatus === 'running' && '正在生成'}
                            {imageStatus === 'pending' && '等待生成'}
                          </small>
                        </div>
                        {['completed', 'failed'].includes(imageStatus) && (
                          <button
                            type='button'
                            className='regenerate'
                            disabled={imageGenerationActive || regeneratingImage !== null}
                            onClick={() => regenerateImage(imageIndex)}
                          >
                            <WandSparkles size={13} />
                            {regeneratingImage === imageIndex
                              ? '生成中…'
                              : imageStatus === 'failed' ? '重试' : '重新生成'}
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
          <div className='field full markdown-field'>
            <Suspense fallback={<div className='markdown-loading'>正在加载编辑器…</div>}>
              <MarkdownComposer
                value={form.content_md}
                mediaPaths={form.media_paths}
                onChange={value => set('content_md', value)}
                onUploadImages={uploadFiles}
                onImageClick={image => setImageViewer({
                  ...image,
                  title: image.alt || form.title || '文章图片'
                })}
                initialMode={article ? 'preview' : 'edit'}
              />
            </Suspense>
          </div>
          <label className='field full'>
            <span>阅读原文 URL</span>
            <input value={form.source_url} onChange={e => set('source_url', e.target.value)} />
          </label>
          <section className='ai-editor-panel'>
            <header>
              <div>
                <span className='eyebrow'>AI EDITOR</span>
                <h3>智能加工</h3>
              </div>
              <button
                className='button paper'
                disabled={enriching || !article}
                onClick={enrich}
              >
                {enriching ? '正在加工…' : form.ai_enriched_at ? '重新加工' : '开始 AI 加工'}
              </button>
            </header>
            {(form.ai_result?.recommended_title ||
              form.ai_result?.summary ||
              (form.ai_result?.tags || []).length)
              ? (
                <>
                  {form.ai_result?.recommended_title && (
                    <div className='ai-title-recommendation'>
                      <div>
                        <b>推荐标题</b>
                        <p>{form.ai_result.recommended_title}</p>
                      </div>
                      <button
                        type='button'
                        className='button ghost'
                        disabled={form.title === form.ai_result.recommended_title}
                        onClick={() => set('title', form.ai_result.recommended_title)}
                      >
                        {form.title === form.ai_result.recommended_title ? '已采用' : '采用标题'}
                      </button>
                    </div>
                  )}
                  <div className='ai-summary'>
                    <div>
                      <b>内容摘要</b>
                      <p>{form.ai_result.summary || '暂无摘要'}</p>
                    </div>
                    <div>
                      <b>人工确认</b>
                      <p>{form.ai_result.editor_notes || '没有额外确认事项'}</p>
                    </div>
                  </div>
                  <div className='ai-tags'>
                    {(form.ai_result.tags || []).slice(0, 5).map(tag => (
                      <span key={tag}>#{tag}</span>
                    ))}
                  </div>
                </>
                )
              : (
                <p className='ai-empty'>
                  AI 加工会保留主稿正文，生成可选标题、摘要和最多 5 个标签；缺少封面时会同时尝试生成本地封面。
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
      <ImageViewer
        {...imageViewer}
        onClose={() => setImageViewer(null)}
      />
    </div>
  )
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

  const scanRss = async () => {
    setTesting('rss')
    try {
      await api.saveSettings(form)
      const result = await api.scanRss()
      const errorNote = result.errors.length
        ? '，失败 ' + result.errors.length + ' 个源'
        : ''
      notify(
        'RSS 扫描完成：新增 ' + result.created +
        '，已存在 ' + result.existing + errorNote,
        result.errors.length ? 'error' : 'success'
      )
      await onSaved()
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
        description='只同步状态为“待同步”的文章和图文，成功后回写“已同步”。'
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
          <TextField label='同步完成状态' value={form.notion_synced_status} onChange={v => set('notion_synced_status', v)} />
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
        title='RSS 资讯订阅'
        description='维护资讯订阅源；每次扫描只把原文链接尚未出现的新条目写入资讯库。'
        action={
          <button
            className='button paper'
            disabled={Boolean(testing) || !(form.rss_feed_urls || []).length}
            onClick={scanRss}
          >
            {testing === 'rss' ? '扫描中…' : '立即扫描'}
          </button>
        }
      >
        <label className='field full rss-feed-field'>
          <span>RSS / Atom 地址（每行一个）</span>
          <textarea
            value={(form.rss_feed_urls || []).join(String.fromCharCode(10))}
            onChange={event => set(
              'rss_feed_urls',
              event.target.value
                .split(String.fromCharCode(10))
                .map(line => line.trim())
                .filter(Boolean)
            )}
            placeholder='https://example.com/rss.xml'
          />
        </label>
        <div className='integration-note'>
          <b>{(form.rss_feed_urls || []).length} 个订阅源</b>
          <span>支持 RSS 2.0 和 Atom；启用与扫描频率请在“自动化”中设置。</span>
        </div>
      </SettingsSection>
      <SettingsSection
        index='03'
        title='浏览器发布通道'
        description='每个账号使用独立的本地 Chrome 会话；公众号保存草稿，CSDN 支持草稿和直发，其余平台按各自能力发布。'
        action={
          <div className='settings-actions'>
            {BROWSER_PLATFORM_KEYS.map(key => (
              <button
                key={key}
                className='button paper'
                disabled={Boolean(testing)}
                onClick={() => test(key, () => api.testPlatform(key))}
              >
                {testing === key ? '检查中…' : `检查${PLATFORM_LABELS[key]}`}
              </button>
            ))}
          </div>
        }
      >
        <div className='settings-grid'>
          <TextField
            label='Chrome / Edge 可执行文件（可选）'
            value={form.browser_executable_path}
            onChange={v => set('browser_executable_path', v)}
            placeholder='留空时自动检测本机浏览器'
          />
          <TextField
            label='Bilibili 默认分区'
            value={form.bilibili_default_category}
            onChange={v => set('bilibili_default_category', v)}
            placeholder='例如：生活'
          />
          <label className='field'>
            <span>Bilibili 稿件类型</span>
            <select
              value={form.bilibili_copyright}
              onChange={e => set('bilibili_copyright', e.target.value)}
            >
              <option value=''>发布前必须选择</option>
              <option value='self'>自制 / 原创或已获授权</option>
              <option value='repost'>转载</option>
            </select>
          </label>
        </div>
        {BROWSER_PLATFORM_KEYS.map(key => (
          <Toggle
            key={key}
            label={`启用${PLATFORM_LABELS[key]}`}
            note='发布前请先到“账号管理”添加账号并完成浏览器登录。'
            checked={form[`${key}_enabled`]}
            onChange={v => set(`${key}_enabled`, v)}
          />
        ))}
        <div className='integration-note'>
          <b>首期发布范围</b>
          <span>抖音、视频号、Bilibili 为单视频直发；小红书为多图或单视频直发。</span>
        </div>
      </SettingsSection>

      <ProxyDirectory notify={notify} />

      <SettingsSection
        index='04'
        title='AI 内容编辑'
        description='保留主稿正文，生成可选标题、摘要和最多 5 个准确标签。'
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
          <div className='settings-subhead full'>
            <b>图片生成</b>
          </div>
          <TextField
            label='图片 API Base URL'
            value={form.ai_image_base_url}
            onChange={v => set('ai_image_base_url', v)}
            placeholder='留空时复用上方 API Base URL'
          />
          <TextField
            label='图片 API Key'
            secret
            value={form.ai_image_api_key}
            onChange={v => set('ai_image_api_key', v)}
            placeholder='留空时复用上方 API Key'
          />
          <TextField
            label='图片模型'
            value={form.ai_image_model}
            onChange={v => set('ai_image_model', v)}
            placeholder='例如：gpt-image-1'
          />
          <TextField
            label='图片尺寸'
            value={form.ai_image_size}
            onChange={v => set('ai_image_size', v)}
            placeholder='1024x1024'
          />
          <TextField
            label='图文竖版尺寸'
            value={form.ai_image_post_size}
            onChange={v => set('ai_image_post_size', v)}
            placeholder='1024x1536'
          />
          <TextField
            label='公众号封面生成尺寸'
            value={form.ai_cover_image_size}
            onChange={v => set('ai_cover_image_size', v)}
            placeholder='1536x1024'
          />

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
          note='每次从 Notion 同步新内容后，自动生成标题建议、摘要和标签。'
          checked={form.ai_auto_enrich_after_sync}
          onChange={v => set('ai_auto_enrich_after_sync', v)}
        />
        <Toggle
          label='缺少封面时自动生成'
          note='同步文章或图文时，根据标题和正文生成封面；需要配置图片模型。'
          checked={form.ai_auto_generate_cover_after_sync}
          onChange={v => set('ai_auto_generate_cover_after_sync', v)}
        />
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
