import { useState } from 'react'
import {
  ArrowRight,
  CheckCircle,
  FileText,
  Image as ImageIcon,
  Newspaper,
  Send,
  Sparkles,
  StickyNote,
  X
} from 'lucide-react'
import { api } from './api'
import MarkdownPreview from './MarkdownPreview'

const TARGETS = [
  { key: 'article', label: '文章', destination: '内容库', icon: FileText },
  { key: 'news', label: '资讯', destination: '资讯库', icon: Newspaper },
  { key: 'note', label: '卡片笔记', destination: '素材库', icon: StickyNote },
  { key: 'image', label: '图片', destination: '素材库', icon: ImageIcon }
]

const INITIAL_FORM = {
  target: 'article',
  instruction: '',
  article_type: 'article',
  author: '',
  audience: '',
  style: '',
  requirements: '',
  word_count: 1200,
  image_count: 1,
  image_mode: 'auto',
  source_url: '',
  source_name: '',
  material_ids: [],
  news_ids: []
}

export default function AIAssistant ({ notify, onCreated }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(INITIAL_FORM)
  const [preview, setPreview] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState(null)

  const target = TARGETS.find(item => item.key === form.target)

  const update = (key, value) => {
    setForm(current => ({ ...current, [key]: value }))
    setPreview(null)
    setCreated(null)
    setError('')
  }

  const selectTarget = key => {
    setForm(current => ({
      ...INITIAL_FORM,
      target: key,
      instruction: current.instruction
    }))
    setPreview(null)
    setCreated(null)
    setError('')
  }

  const generate = async event => {
    event.preventDefault()
    if (form.instruction.trim().length < 2 || generating) return
    if (form.target === 'news' && !form.source_url.trim()) {
      setError('新建资讯需要填写原始来源链接')
      return
    }
    setGenerating(true)
    setError('')
    setCreated(null)
    try {
      const result = await api.previewAssistant({
        ...form,
        instruction: form.instruction.trim(),
        word_count: Number(form.word_count),
        image_count: Number(form.image_count)
      })
      setPreview(result)
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setGenerating(false)
    }
  }

  const execute = async () => {
    if (!preview || saving) return
    setSaving(true)
    setError('')
    try {
      const result = await api.executeAssistant({
        target: form.target,
        draft: preview.draft,
        article_type: form.article_type,
        author: form.author,
        image_count: Number(preview.image_count ?? form.image_count),
        image_mode: form.image_mode,
        source_url: form.source_url,
        source_name: form.source_name,
        references: preview.references || {}
      })
      setCreated(result)
      setPreview(null)
      notify(result.message)
      onCreated(result).catch(refreshError => notify(refreshError.message, 'error'))
    } catch (requestError) {
      setError(requestError.message)
    } finally {
      setSaving(false)
    }
  }

  const startAnother = () => {
    setForm(current => ({ ...INITIAL_FORM, target: current.target }))
    setPreview(null)
    setCreated(null)
    setError('')
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
                  <small>AI CONTENT OPERATOR</small>
                </div>
              </div>
              <button
                className='assistant-icon-button'
                aria-label='关闭小助手'
                title='关闭'
                onClick={() => setOpen(false)}
              >
                <X size={18} />
              </button>
            </header>

            <div className='assistant-targets' role='tablist' aria-label='创建目标'>
              {TARGETS.map(item => {
                const Icon = item.icon
                return (
                  <button
                    key={item.key}
                    className={form.target === item.key ? 'active' : ''}
                    role='tab'
                    aria-selected={form.target === item.key}
                    onClick={() => selectTarget(item.key)}
                  >
                    <Icon size={15} />
                    <span>{item.label}</span>
                  </button>
                )
              })}
            </div>

            <div className='assistant-conversation'>
              {!preview && !created && (
                <div className='assistant-empty'>
                  <span><Sparkles size={22} /></span>
                  <h3>今天想创作什么？</h3>
                  <p>{target.label + '将写入' + target.destination}</p>
                </div>
              )}

              {preview && (
                <>
                  <div className='assistant-user-message'>
                    <span>你的要求</span>
                    <p>{form.instruction}</p>
                  </div>
                  <section className='assistant-preview'>
                    <header>
                      <div>
                        <span>AI 预览</span>
                        <h3>{preview.draft.title}</h3>
                      </div>
                      <b>{target.destination}</b>
                    </header>
                    {!!preview.draft.tags?.length && (
                      <div className='assistant-tags'>
                        {preview.draft.tags.map(tag => <span key={tag}>{tag}</span>)}
                      </div>
                    )}
                    {preview.draft.summary && (
                      <p className='assistant-summary'>{preview.draft.summary}</p>
                    )}
                    {form.target === 'image'
                      ? (
                        <div className='assistant-image-prompt'>
                          <ImageIcon size={18} />
                          <p>{preview.draft.image_prompt}</p>
                        </div>
                        )
                      : (
                        <div className='assistant-markdown-preview'>
                          <MarkdownPreview markdown={preview.draft.content_md} />
                        </div>
                        )}
                  </section>
                </>
              )}

              {created && (
                <section className='assistant-created'>
                  <CheckCircle size={30} />
                  <span>已完成</span>
                  <h3>{created.item.title}</h3>
                  <p>{created.message}</p>
                  <div>
                    <button
                      className='button ink'
                      onClick={() => {
                        onCreated(created, true)
                          .catch(refreshError => notify(refreshError.message, 'error'))
                        setOpen(false)
                      }}
                    >
                      去查看
                      <ArrowRight size={15} />
                    </button>
                    <button className='button ghost' onClick={startAnother}>
                      再创建一个
                    </button>
                  </div>
                </section>
              )}

              {error && <div className='assistant-error' role='alert'>{error}</div>}
            </div>

            {!created && (
              <form className='assistant-composer' onSubmit={generate}>
                {form.target === 'article' && (
                  <div className='assistant-options'>
                    <div className='assistant-segmented' role='group' aria-label='文章类型'>
                      <button
                        type='button'
                        className={form.article_type === 'article' ? 'active' : ''}
                        onClick={() => {
                          update('article_type', 'article')
                          update('image_count', 1)
                          update('image_mode', 'auto')
                        }}
                      >
                        长文章
                      </button>
                      <button
                        type='button'
                        className={form.article_type === 'image' ? 'active' : ''}
                        onClick={() => {
                          update('article_type', 'image')
                          update('image_count', 5)
                          update('image_mode', 'auto')
                        }}
                      >
                        图文
                      </button>
                    </div>
                    <label>
                      <span>字数</span>
                      <input
                        type='number'
                        min='300'
                        max='5000'
                        step='100'
                        value={form.word_count}
                        onChange={event => update('word_count', event.target.value)}
                      />
                    </label>
                    <label>
                      <span>配图</span>
                      <select
                        value={form.image_mode}
                        onChange={event => update('image_mode', event.target.value)}
                      >
                        <option value='auto'>自动</option>
                        <option value='cover'>仅封面</option>
                        {form.article_type !== 'image' && (
                          <option value='none'>不配图</option>
                        )}
                      </select>
                    </label>
                  </div>
                )}

                {form.target === 'news' && (
                  <div className='assistant-source-fields'>
                    <label>
                      <span>来源链接 *</span>
                      <input
                        type='url'
                        required
                        value={form.source_url}
                        placeholder='https://'
                        onChange={event => update('source_url', event.target.value)}
                      />
                    </label>
                    <label>
                      <span>来源名称</span>
                      <input
                        value={form.source_name}
                        placeholder='选填'
                        onChange={event => update('source_name', event.target.value)}
                      />
                    </label>
                  </div>
                )}

                <div className='assistant-input-row'>
                  <textarea
                    autoFocus
                    minLength='2'
                    maxLength='4000'
                    value={form.instruction}
                    placeholder={
                      form.target === 'article'
                        ? '输入选题、核心观点和写作要求'
                        : form.target === 'news'
                          ? '输入需要提炼的事实、重点和时间背景'
                          : form.target === 'note'
                            ? '输入要整理成卡片笔记的内容'
                            : '描述主体、场景、构图和视觉风格'
                    }
                    onChange={event => update('instruction', event.target.value)}
                  />
                  <button
                    className='assistant-send'
                    aria-label='生成预览'
                    title='生成预览'
                    disabled={generating || saving || form.instruction.trim().length < 2}
                  >
                    {generating ? <span className='assistant-spinner' /> : <Send size={17} />}
                  </button>
                </div>

                {preview && (
                  <div className='assistant-confirm'>
                    <span>{'确认后将写入' + target.destination}</span>
                    <button
                      type='button'
                      className='button vermilion'
                      disabled={saving}
                      onClick={execute}
                    >
                      {saving ? '正在写入…' : '写入' + target.destination}
                    </button>
                  </div>
                )}
              </form>
            )}
          </aside>
        </div>
      )}
    </>
  )
}