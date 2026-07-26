import { useEffect, useMemo, useState } from 'react'
import {
  ExternalLink,
  FileSearch,
  Link2,
  Newspaper,
  Pencil,
  Plus,
  Search,
  Trash2,
  X
} from 'lucide-react'
import { api } from './api'

const EMPTY_DATA = {
  items: [],
  counts: { all: 0, sources: 0 },
  sources: []
}

export default function News ({ notify }) {
  const [data, setData] = useState(EMPTY_DATA)
  const [query, setQuery] = useState('')
  const [source, setSource] = useState('')
  const [collectorOpen, setCollectorOpen] = useState(false)
  const [editor, setEditor] = useState(null)

  const load = async (nextQuery = query, nextSource = source) => {
    setData(await api.news(nextQuery, nextSource))
  }

  useEffect(() => {
    load().catch(error => notify(error.message, 'error'))
  }, [])

  const changeSource = value => {
    setSource(value)
    load(query, value).catch(error => notify(error.message, 'error'))
  }

  const remove = async item => {
    if (!window.confirm('确定删除资讯“' + item.title + '”吗？')) return
    try {
      await api.deleteNews(item.id)
      await load()
      notify('资讯已删除')
    } catch (error) {
      notify(error.message, 'error')
    }
  }

  const save = async values => {
    try {
      if (editor?.id) await api.updateNews(editor.id, values)
      else await api.createNews(values)
      setEditor(null)
      await load()
      notify(editor?.id ? '资讯已更新' : '资讯已录入')
    } catch (error) {
      notify(error.message, 'error')
      throw error
    }
  }

  const collect = async url => {
    try {
      const item = await api.collectNews(url)
      setCollectorOpen(false)
      await load()
      notify('已采集：' + item.title)
    } catch (error) {
      notify(error.message, 'error')
      throw error
    }
  }

  return (
    <div className='page enter news-page'>
      <div className='news-toolbar'>
        <div className='news-stats' aria-label='资讯统计'>
          <button
            type='button'
            className={!source ? 'active' : ''}
            onClick={() => changeSource('')}
          >
            <span>全部资讯</span>
            <b>{data.counts.all || 0}</b>
          </button>
          <div>
            <span>来源站点</span>
            <b>{data.counts.sources || 0}</b>
          </div>
        </div>

        <div className='news-toolbar-actions'>
          <div className='search-box news-search'>
            <Search size={15} />
            <input
              value={query}
              placeholder='搜索标题、摘要或正文'
              onChange={event => setQuery(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') load(query, source)
              }}
            />
          </div>
          <select
            className='news-source-select'
            value={source}
            aria-label='筛选资讯来源'
            onChange={event => changeSource(event.target.value)}
          >
            <option value=''>全部来源</option>
            {data.sources.map(item => (
              <option key={item.name} value={item.value}>
                {item.name} ({item.total})
              </option>
            ))}
          </select>
          <button type='button' className='button paper' onClick={() => setEditor({})}>
            <Plus size={15} />
            手工录入
          </button>
          <button
            type='button'
            className='button vermilion'
            onClick={() => setCollectorOpen(true)}
          >
            <Link2 size={15} />
            采集网页
          </button>
        </div>
      </div>

      <div className='news-result-line'>
        <span>{data.items.length} 条结果</span>
        {(query || source) && (
          <button
            type='button'
            onClick={() => {
              setQuery('')
              setSource('')
              load('', '').catch(error => notify(error.message, 'error'))
            }}
          >
            清除筛选
          </button>
        )}
      </div>

      {data.items.length
        ? (
          <section className='news-list'>
            {data.items.map(item => (
              <NewsCard
                key={item.id}
                item={item}
                onEdit={() => setEditor(item)}
                onDelete={() => remove(item)}
              />
            ))}
          </section>
          )
        : (
          <div className='news-empty'>
            <Newspaper size={30} />
            <b>资讯库还是空的</b>
          </div>
          )}

      {collectorOpen && (
        <NewsCollector
          onClose={() => setCollectorOpen(false)}
          onCollect={collect}
        />
      )}
      {editor && (
        <NewsEditor
          item={editor}
          onClose={() => setEditor(null)}
          onSave={save}
        />
      )}
    </div>
  )
}

function NewsCard ({ item, onEdit, onDelete }) {
  const excerpt = item.summary || item.content_md
  return (
    <article className='news-card'>
      <div className='news-date-block'>
        <b>{dayLabel(item.published_at || item.created_at)}</b>
        <span>{monthLabel(item.published_at || item.created_at)}</span>
      </div>
      <div className='news-card-main'>
        <div className='news-card-meta'>
          <span>{item.source_name || sourceFromUrl(item.source_url)}</span>
          {item.author && <i>{item.author}</i>}
          <time>{fullDateLabel(item.published_at || item.created_at)}</time>
        </div>
        <h3>{item.title}</h3>
        {excerpt && <p>{excerpt}</p>}
        <div className='news-card-foot'>
          <div className='news-tags'>
            {(item.tags || []).slice(0, 5).map(tag => <span key={tag}>#{tag}</span>)}
          </div>
          {item.reference_count > 0 && <small>AI 已引用 {item.reference_count} 次</small>}
        </div>
      </div>
      <div className='news-card-actions'>
        <a
          href={item.source_url}
          target='_blank'
          rel='noreferrer'
          title='打开原文'
          aria-label={'打开原文：' + item.title}
        >
          <ExternalLink size={15} />
        </a>
        <button type='button' title='编辑资讯' aria-label='编辑资讯' onClick={onEdit}>
          <Pencil size={15} />
        </button>
        <button type='button' title='删除资讯' aria-label='删除资讯' onClick={onDelete}>
          <Trash2 size={15} />
        </button>
      </div>
    </article>
  )
}

function NewsCollector ({ onClose, onCollect }) {
  const [url, setUrl] = useState('')
  const [collecting, setCollecting] = useState(false)
  const [error, setError] = useState('')

  const submit = async event => {
    event.preventDefault()
    if (!url.trim() || collecting) return
    setCollecting(true)
    setError('')
    try {
      await onCollect(url.trim())
    } catch (collectError) {
      setError(collectError.message)
      setCollecting(false)
    }
  }

  return (
    <div className='modal-backdrop news-modal-backdrop' onMouseDown={onClose}>
      <form className='news-collector' onSubmit={submit} onMouseDown={event => event.stopPropagation()}>
        <header>
          <div>
            <span className='eyebrow'>WEB CLIPPER</span>
            <h2>采集网页资讯</h2>
          </div>
          <button type='button' className='close-button' aria-label='关闭' onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className='news-collector-body'>
          <label className='field full'>
            <span>原文链接</span>
            <div className='news-url-input'>
              <Link2 size={16} />
              <input
                autoFocus
                required
                type='url'
                maxLength='2000'
                value={url}
                placeholder='https://'
                onChange={event => setUrl(event.target.value)}
              />
            </div>
          </label>
          {error && <div className='news-form-error' role='alert'>{error}</div>}
        </div>
        <footer>
          <button type='button' className='button ghost' disabled={collecting} onClick={onClose}>
            取消
          </button>
          <button type='submit' className='button ink' disabled={collecting || !url.trim()}>
            <FileSearch size={15} />
            {collecting ? '正在采集…' : '开始采集'}
          </button>
        </footer>
      </form>
    </div>
  )
}

function NewsEditor ({ item, onClose, onSave }) {
  const [form, setForm] = useState({
    title: item.title || '',
    source_name: item.source_name || '',
    source_url: item.source_url || '',
    author: item.author || '',
    summary: item.summary || '',
    content_md: item.content_md || '',
    published_at: localDateValue(item.published_at),
    tags: (item.tags || []).join('，')
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))

  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      await onSave({
        title: form.title.trim(),
        source_name: form.source_name.trim(),
        source_url: form.source_url.trim(),
        author: form.author.trim(),
        summary: form.summary.trim(),
        content_md: form.content_md.trim(),
        published_at: form.published_at || null,
        tags: form.tags.split(/[，,]/).map(tag => tag.trim()).filter(Boolean)
      })
    } catch (saveError) {
      setError(saveError.message)
      setSaving(false)
    }
  }

  return (
    <div className='modal-backdrop news-modal-backdrop' onMouseDown={onClose}>
      <form className='news-editor' onSubmit={submit} onMouseDown={event => event.stopPropagation()}>
        <header>
          <div>
            <span className='eyebrow'>NEWS RECORD</span>
            <h2>{item.id ? '编辑资讯' : '手工录入资讯'}</h2>
          </div>
          <button type='button' className='close-button' aria-label='关闭' onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className='news-editor-body'>
          <label className='field full'>
            <span>标题</span>
            <input
              autoFocus
              required
              maxLength='200'
              value={form.title}
              onChange={event => set('title', event.target.value)}
            />
          </label>
          <div className='field-grid'>
            <label className='field'>
              <span>来源站点</span>
              <input
                maxLength='120'
                value={form.source_name}
                onChange={event => set('source_name', event.target.value)}
              />
            </label>
            <label className='field'>
              <span>作者</span>
              <input
                maxLength='120'
                value={form.author}
                onChange={event => set('author', event.target.value)}
              />
            </label>
          </div>
          <label className='field full'>
            <span>原文链接</span>
            <input
              required
              type='url'
              maxLength='2000'
              value={form.source_url}
              onChange={event => set('source_url', event.target.value)}
            />
          </label>
          <div className='field-grid'>
            <label className='field'>
              <span>发布时间</span>
              <input
                type='datetime-local'
                value={form.published_at}
                onChange={event => set('published_at', event.target.value)}
              />
            </label>
            <label className='field'>
              <span>标签</span>
              <input
                value={form.tags}
                placeholder='使用逗号分隔'
                onChange={event => set('tags', event.target.value)}
              />
            </label>
          </div>
          <label className='field full'>
            <span>摘要</span>
            <textarea
              maxLength='1000'
              value={form.summary}
              onChange={event => set('summary', event.target.value)}
            />
          </label>
          <label className='field full'>
            <span>采集正文</span>
            <textarea
              className='news-content-input'
              maxLength='50000'
              value={form.content_md}
              onChange={event => set('content_md', event.target.value)}
            />
          </label>
          {error && <div className='news-form-error' role='alert'>{error}</div>}
        </div>
        <footer>
          <button type='button' className='button ghost' disabled={saving} onClick={onClose}>取消</button>
          <button
            type='submit'
            className='button ink'
            disabled={saving || !form.title.trim() || !form.source_url.trim()}
          >
            {saving ? '保存中…' : '保存资讯'}
          </button>
        </footer>
      </form>
    </div>
  )
}

export function NewsPicker ({ selected = [], onChange }) {
  const [data, setData] = useState(EMPTY_DATA)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.news()
      .then(setData)
      .finally(() => setLoading(false))
  }, [])

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase()
    return data.items
      .filter(item => !term || [item.title, item.source_name, item.summary]
        .some(value => String(value || '').toLowerCase().includes(term)))
      .slice(0, 30)
  }, [data.items, query])

  const toggle = newsId => {
    if (selected.includes(newsId)) {
      onChange(selected.filter(id => id !== newsId))
    } else if (selected.length < 20) {
      onChange([...selected, newsId])
    }
  }

  return (
    <section className='news-picker'>
      <header>
        <div>
          <b>参考资讯</b>
          <span>{selected.length ? '已选择 ' + selected.length + ' 条' : '未选择'}</span>
        </div>
        <label>
          <Search size={13} />
          <input
            value={query}
            aria-label='搜索参考资讯'
            placeholder='搜索资讯'
            onChange={event => setQuery(event.target.value)}
          />
        </label>
      </header>
      <div className='news-picker-list'>
        {loading && <span className='news-picker-empty'>正在读取资讯…</span>}
        {!loading && visible.map(item => {
          const active = selected.includes(item.id)
          return (
            <button
              type='button'
              className={active ? 'active' : ''}
              aria-pressed={active}
              key={item.id}
              onClick={() => toggle(item.id)}
            >
              <Newspaper size={14} />
              <span>
                <b>{item.title}</b>
                <small>{item.source_name || sourceFromUrl(item.source_url)}</small>
              </span>
            </button>
          )
        })}
        {!loading && !visible.length && (
          <span className='news-picker-empty'>没有符合条件的资讯</span>
        )}
      </div>
    </section>
  )
}

function sourceFromUrl (url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return '未知来源'
  }
}

function localDateValue (value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16)
  const offset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function fullDateLabel (value) {
  if (!value) return '时间未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(date)
}

function dayLabel (value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '--' : String(date.getDate()).padStart(2, '0')
}

function monthLabel (value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'NEWS'
    : new Intl.DateTimeFormat('en', { month: 'short' }).format(date).toUpperCase()
}
