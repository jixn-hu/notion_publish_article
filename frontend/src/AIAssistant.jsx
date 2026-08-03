import { useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  FileText,
  Image as ImageIcon,
  Layers3,
  Newspaper,
  RefreshCw,
  Send,
  Server,
  Settings2,
  Sparkles,
  StickyNote,
  UserRound,
  X
} from 'lucide-react'
import { api } from './api'
import MarkdownPreview from './MarkdownPreview'

const QUICK_PROMPTS = [
  '看看我的账号状态',
  '列出最近 5 条资讯',
  '统计当前稿件和粉丝',
  '根据最近资讯写一篇文章'
]

const TYPE_LABELS = {
  article: '文章',
  image: '图文',
  video: '视频',
  wechat: '公众号',
  xiaohongshu: '小红书',
  douyin: '抖音',
  channels: '视频号',
  bilibili: 'Bilibili',
  csdn: 'CSDN'
}

const STATUS_LABELS = {
  valid: '可用',
  invalid: '失效',
  pending: '待检查',
  ready: '待发布',
  published: '已发布',
  drafted: '已存草稿',
  failed: '失败',
  partial: '部分成功',
  enabled: '已启用',
  disabled: '未启用'
}

const formatNumber = value => Number(value || 0).toLocaleString('zh-CN')

function ResultIcon ({ type }) {
  const icons = {
    accounts: UserRound,
    articles: FileText,
    article: FileText,
    news: Newspaper,
    news_detail: Newspaper,
    materials: Layers3,
    material: StickyNote,
    platforms: Server,
    proxies: Server,
    configuration: Settings2
  }
  const Icon = icons[type] || Sparkles
  return <Icon size={15} />
}

function DashboardResult ({ result }) {
  const metrics = result.metrics || {}
  const byStatus = metrics.by_status || {}
  const cards = [
    { label: '全网粉丝', value: metrics.total_followers },
    { label: '稿件总量', value: metrics.total_articles },
    { label: '待发布', value: byStatus.ready },
    {
      label: '已完成',
      value: Number(byStatus.published || 0) + Number(byStatus.drafted || 0)
    }
  ]
  return (
    <section className='assistant-result dashboard'>
      <header><BarChart3 size={15} /><b>{result.title}</b></header>
      <div className='assistant-metrics'>
        {cards.map(card => (
          <div key={card.label}>
            <strong>{formatNumber(card.value)}</strong>
            <span>{card.label}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function AccountsResult ({ result }) {
  return (
    <section className='assistant-result'>
      <header><UserRound size={15} /><b>{result.title}</b></header>
      <div className='assistant-account-grid'>
        {(result.items || []).map(account => {
          const profile = account.profile || {}
          return (
            <article key={account.id}>
              <div className='assistant-account-head'>
                <span>{(profile.nickname || profile.name || account.name || '?').slice(0, 1)}</span>
                <div>
                  <b>{profile.nickname || profile.name || account.name}</b>
                  <small>{TYPE_LABELS[account.platform] || account.platform}</small>
                </div>
                <i className={account.status}>{STATUS_LABELS[account.status] || account.status}</i>
              </div>
              <dl>
                <div>
                  <dt>粉丝</dt>
                  <dd>{formatNumber(profile.followers_count)}</dd>
                </div>
                <div>
                  <dt>获赞</dt>
                  <dd>{formatNumber(profile.likes_count || profile.total_likes)}</dd>
                </div>
              </dl>
            </article>
          )
        })}
      </div>
    </section>
  )
}

function DetailResult ({ result }) {
  const item = result.item || {}
  return (
    <section className='assistant-result detail'>
      <header><ResultIcon type={result.type} /><b>{result.title}</b></header>
      {!!item.tags?.length && (
        <div className='assistant-tags'>
          {item.tags.map(tag => <span key={tag}>{tag}</span>)}
        </div>
      )}
      {item.preview_url && item.kind === 'image' && (
        <img className='assistant-result-image' src={item.preview_url} alt={item.title || ''} />
      )}
      {item.content_md && (
        <div className='assistant-result-markdown'>
          <MarkdownPreview markdown={item.content_md} />
        </div>
      )}
      {!item.content_md && item.summary && <p>{item.summary}</p>}
    </section>
  )
}

function ConfigurationResult ({ result }) {
  const entries = Object.entries(result.values || {})
    .filter(([key]) => (
      key.endsWith('_enabled') ||
      ['ai_model', 'default_publish_mode', 'rss_scan_interval_minutes'].includes(key)
    ))
    .slice(0, 18)
  return (
    <section className='assistant-result'>
      <header><Settings2 size={15} /><b>{result.title}</b></header>
      <div className='assistant-config-list'>
        {entries.map(([key, value]) => (
          <div key={key}>
            <span>{key}</span>
            <b>{typeof value === 'boolean' ? (value ? '已启用' : '未启用') : String(value || '未配置')}</b>
          </div>
        ))}
      </div>
    </section>
  )
}

function ListResult ({ result }) {
  return (
    <section className='assistant-result'>
      <header><ResultIcon type={result.type} /><b>{result.title}</b></header>
      <div className='assistant-result-list'>
        {(result.items || []).map((item, index) => (
          <article key={item.id || item.key || index}>
            {item.preview_url && item.kind === 'image'
              ? <img src={item.preview_url} alt='' />
              : <span className='assistant-result-index'>{String(index + 1).padStart(2, '0')}</span>}
            <div>
              <b>{item.title || item.name || item.label || item.key || '未命名'}</b>
              <small>
                {TYPE_LABELS[item.platform] || TYPE_LABELS[item.article_type] ||
                  STATUS_LABELS[item.status] || item.source_name || item.kind || ''}
                {item.id ? ` · ID ${item.id}` : ''}
              </small>
              {item.summary && <p>{item.summary}</p>}
            </div>
            {item.status && <i className={item.status}>{STATUS_LABELS[item.status] || item.status}</i>}
          </article>
        ))}
        {!(result.items || []).length && <p className='assistant-result-empty'>没有匹配的数据</p>}
      </div>
    </section>
  )
}

function ResultPanel ({ result }) {
  if (result.type === 'dashboard') return <DashboardResult result={result} />
  if (result.type === 'accounts') return <AccountsResult result={result} />
  if (['article', 'news_detail', 'material'].includes(result.type)) {
    return <DetailResult result={result} />
  }
  if (result.type === 'configuration') return <ConfigurationResult result={result} />
  if (result.type === 'error') {
    return <div className='assistant-error'>{result.message || result.title}</div>
  }
  return <ListResult result={result} />
}

function DraftCard ({ response, saving, onConfirm }) {
  const action = response.action
  const preview = action?.preview || {}
  const draft = preview.draft || {}
  const target = action?.target
  const destinations = {
    article: '内容库',
    news: '资讯库',
    note: '素材库',
    image: '素材库'
  }
  return (
    <section className='assistant-preview'>
      <header>
        <div>
          <span>待确认草稿</span>
          <h3>{draft.title}</h3>
        </div>
        <b>{destinations[target] || '内容库'}</b>
      </header>
      {!!draft.tags?.length && (
        <div className='assistant-tags'>
          {draft.tags.map(tag => <span key={tag}>{tag}</span>)}
        </div>
      )}
      {draft.summary && <p className='assistant-summary'>{draft.summary}</p>}
      {target === 'image'
        ? (
          <div className='assistant-image-prompt'>
            <ImageIcon size={18} />
            <p>{draft.image_prompt}</p>
          </div>
          )
        : (
          <div className='assistant-markdown-preview'>
            <MarkdownPreview markdown={draft.content_md} />
          </div>
          )}
      <footer className='assistant-draft-footer'>
        <span>确认后写入{destinations[target]}</span>
        <button className='button vermilion' disabled={saving} onClick={onConfirm}>
          {saving ? '正在写入…' : '确认写入'}
        </button>
      </footer>
    </section>
  )
}

function CompletedCard ({ result, onOpen }) {
  return (
    <section className='assistant-created compact'>
      <CheckCircle2 size={25} />
      <div>
        <span>已完成</span>
        <h3>{result.item?.title}</h3>
        <p>{result.message}</p>
      </div>
      <button className='button ink' onClick={onOpen}>
        去查看
        <ArrowRight size={14} />
      </button>
    </section>
  )
}

function historyContent (response) {
  const data = JSON.stringify(response.results || []).slice(0, 10000)
  return data ? `${response.message}\n项目数据：${data}` : response.message
}

export default function AIAssistant ({ notify, onCreated }) {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [savingId, setSavingId] = useState(null)
  const [error, setError] = useState('')
  const inputRef = useRef(null)
  const conversationRef = useRef(null)

  useEffect(() => {
    const host = conversationRef.current
    if (host) host.scrollTop = host.scrollHeight
  }, [messages, busy, error])

  const submit = async event => {
    event?.preventDefault()
    const message = input.trim()
    if (message.length < 2 || busy) return
    const history = messages.slice(-12).map(item => ({
      role: item.role,
      content: item.historyContent || item.content
    }))
    const userMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: message
    }
    setMessages(current => [...current, userMessage])
    setInput('')
    setBusy(true)
    setError('')
    try {
      const response = await api.assistantChat({ message, history })
      setMessages(current => [
        ...current,
        {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          content: response.message,
          historyContent: historyContent(response),
          response
        }
      ])
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setBusy(false)
    }
  }

  const confirmAction = async message => {
    const action = message.response?.action
    const preview = action?.preview
    if (!action || !preview || savingId) return
    setSavingId(message.id)
    setError('')
    try {
      const values = action.values || {}
      const result = await api.executeAssistant({
        target: action.target,
        draft: preview.draft,
        article_type: values.article_type || 'article',
        author: values.author || '',
        image_count: Number(preview.image_count || 0),
        image_mode: preview.image_mode || values.image_mode || 'auto',
        source_url: values.source_url || '',
        source_name: values.source_name || '',
        references: preview.references || {}
      })
      setMessages(current => current.map(item => (
        item.id === message.id
          ? {
              ...item,
              response: {
                ...item.response,
                kind: 'completed',
                created: result,
                action: null
              }
            }
          : item
      )))
      notify(result.message)
      await onCreated(result)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSavingId(null)
    }
  }

  const clearConversation = () => {
    setMessages([])
    setError('')
    setInput('')
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }

  const choosePrompt = prompt => {
    setInput(prompt)
    inputRef.current?.focus()
  }

  return (
    <>
      <button
        className={open ? 'assistant-launcher active' : 'assistant-launcher'}
        aria-label='打开 AI 小助手'
        title='AI 小助手'
        onClick={() => setOpen(true)}
      >
        <Sparkles size={18} />
        <span>AI 小助手</span>
      </button>

      {open && (
        <div className='assistant-backdrop' onMouseDown={() => setOpen(false)}>
          <aside
            className='assistant-drawer'
            role='dialog'
            aria-modal='true'
            aria-labelledby='assistant-title'
            onMouseDown={event => event.stopPropagation()}
          >
            <header className='assistant-header'>
              <div className='assistant-identity'>
                <span><Sparkles size={17} /></span>
                <div>
                  <h2 id='assistant-title'>墨流小助手</h2>
                  <small>CONTENT OPERATOR</small>
                </div>
              </div>
              <div className='assistant-header-actions'>
                <button
                  className='assistant-icon-button'
                  aria-label='清空对话'
                  title='清空对话'
                  disabled={!messages.length || busy}
                  onClick={clearConversation}
                >
                  <RefreshCw size={16} />
                </button>
                <button
                  className='assistant-icon-button'
                  aria-label='关闭小助手'
                  title='关闭'
                  onClick={() => setOpen(false)}
                >
                  <X size={18} />
                </button>
              </div>
            </header>

            <div className='assistant-conversation' ref={conversationRef}>
              {!messages.length && !busy && (
                <div className='assistant-empty assistant-home'>
                  <span><Sparkles size={22} /></span>
                  <h3>今天从哪里开始？</h3>
                  <div className='assistant-quick-prompts'>
                    {QUICK_PROMPTS.map(prompt => (
                      <button key={prompt} type='button' onClick={() => choosePrompt(prompt)}>
                        {prompt}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map(message => (
                <div
                  className={message.role === 'user' ? 'assistant-turn user' : 'assistant-turn'}
                  key={message.id}
                >
                  {message.role === 'user'
                    ? (
                      <div className='assistant-user-message'>
                        <span>你</span>
                        <p>{message.content}</p>
                      </div>
                      )
                    : (
                      <>
                        <div className='assistant-response-copy'>
                          <span><Sparkles size={13} /></span>
                          <div className='assistant-response-markdown'>
                            <MarkdownPreview markdown={message.content} />
                          </div>
                        </div>
                        {(message.response?.results || []).map((result, index) => (
                          <ResultPanel result={result} key={`${message.id}-result-${index}`} />
                        ))}
                        {message.response?.kind === 'confirmation' && (
                          <DraftCard
                            response={message.response}
                            saving={savingId === message.id}
                            onConfirm={() => confirmAction(message)}
                          />
                        )}
                        {message.response?.kind === 'completed' && (
                          <CompletedCard
                            result={message.response.created}
                            onOpen={() => {
                              onCreated(message.response.created, true)
                                .catch(refreshError => notify(refreshError.message, 'error'))
                              setOpen(false)
                            }}
                          />
                        )}
                      </>
                      )}
                </div>
              ))}

              {busy && (
                <div className='assistant-working'>
                  <span className='assistant-spinner dark' />
                  <p>正在读取与处理…</p>
                </div>
              )}
              {error && <div className='assistant-error' role='alert'>{error}</div>}
            </div>

            <form className='assistant-composer universal' onSubmit={submit}>
              {!!messages.length && (
                <div className='assistant-inline-prompts'>
                  {QUICK_PROMPTS.slice(0, 3).map(prompt => (
                    <button key={prompt} type='button' onClick={() => choosePrompt(prompt)}>
                      {prompt}
                    </button>
                  ))}
                </div>
              )}
              <div className='assistant-input-row'>
                <textarea
                  ref={inputRef}
                  autoFocus
                  minLength='2'
                  maxLength='4000'
                  value={input}
                  placeholder='查询账号、资讯、素材，或创建一篇新稿件'
                  onChange={event => setInput(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      submit()
                    }
                  }}
                />
                <button
                  className='assistant-send'
                  aria-label='发送'
                  title='发送'
                  disabled={busy || input.trim().length < 2}
                >
                  {busy ? <span className='assistant-spinner' /> : <Send size={17} />}
                </button>
              </div>
            </form>
          </aside>
        </div>
      )}
    </>
  )
}
