import { useEffect, useMemo, useState } from 'react'
import {
  Check,
  Download,
  Eye,
  FileText,
  Film,
  Image as ImageIcon,
  Pencil,
  Plus,
  Search,
  Trash2,
  Upload,
  X
} from 'lucide-react'
import { api, materialFileUrl } from './api'
import MarkdownPreview from './MarkdownPreview'

const KIND_LABELS = {
  all: '全部',
  image: '图片',
  video: '视频',
  note: '卡片笔记'
}

const KIND_ICONS = {
  image: ImageIcon,
  video: Film,
  note: FileText
}

function formatBytes (value) {
  const bytes = Number(value || 0)
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(1) + ' GB'
}

function dateLabel (value) {
  if (!value) return ''
  return new Date(value).toLocaleDateString('zh-CN', {
    month: '2-digit',
    day: '2-digit'
  })
}

export default function Materials ({ notify }) {
  const [data, setData] = useState({
    items: [],
    counts: { all: 0, image: 0, video: 0, note: 0 }
  })
  const [kind, setKind] = useState('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [editor, setEditor] = useState(null)
  const [viewer, setViewer] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const load = async (nextKind = kind, nextQuery = query) => {
    const result = await api.materials(nextKind === 'all' ? '' : nextKind, nextQuery)
    setData(result)
    setSelected(current => {
      const available = new Set(result.items.map(item => item.id))
      return new Set([...current].filter(id => available.has(id)))
    })
  }

  useEffect(() => {
    load().catch(error => notify(error.message, 'error'))
  }, [])

  const changeKind = nextKind => {
    setKind(nextKind)
    load(nextKind, query).catch(error => notify(error.message, 'error'))
  }

  const toggle = materialId => {
    setSelected(current => {
      const next = new Set(current)
      if (next.has(materialId)) next.delete(materialId)
      else next.add(materialId)
      return next
    })
  }

  const uploadFiles = async event => {
    const files = Array.from(event.target.files || [])
    event.target.value = ''
    if (!files.length) return
    setUploading(true)
    try {
      for (const file of files) {
        await api.uploadMaterial(file)
      }
      await load()
      notify('已导入 ' + files.length + ' 个素材')
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setUploading(false)
    }
  }

  const downloadSelected = async () => {
    if (!selected.size || downloading) return
    setDownloading(true)
    try {
      const blob = await api.downloadMaterials([...selected])
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'materials.zip'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      notify('素材压缩包已生成')
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setDownloading(false)
    }
  }

  const remove = async material => {
    if (!window.confirm('确定删除素材“' + material.title + '”吗？')) return
    try {
      await api.deleteMaterial(material.id)
      await load()
      notify('素材已删除')
    } catch (error) {
      notify(error.message, 'error')
    }
  }

  const saveEditor = async values => {
    try {
      if (editor?.id) await api.updateMaterial(editor.id, values)
      else await api.createMaterialNote(values)
      setEditor(null)
      await load()
      notify(editor?.id ? '素材信息已更新' : '卡片笔记已创建')
    } catch (error) {
      notify(error.message, 'error')
    }
  }

  const allVisibleSelected = data.items.length > 0 &&
    data.items.every(item => selected.has(item.id))

  return (
    <div className='page enter material-page'>
      <div className='material-toolbar'>
        <div className='material-kind-tabs' role='tablist' aria-label='素材类型'>
          {Object.entries(KIND_LABELS).map(([key, label]) => (
            <button
              type='button'
              role='tab'
              aria-selected={kind === key}
              className={kind === key ? 'active' : ''}
              key={key}
              onClick={() => changeKind(key)}
            >
              <span>{label}</span>
              <b>{data.counts[key] || 0}</b>
            </button>
          ))}
        </div>

        <div className='material-toolbar-actions'>
          <div className='search-box material-search'>
            <Search size={15} />
            <input
              value={query}
              placeholder='搜索标题、说明或笔记'
              onChange={event => setQuery(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') load(kind, query)
              }}
            />
          </div>
          <button
            type='button'
            className='button paper'
            disabled={!selected.size || downloading}
            onClick={downloadSelected}
          >
            <Download size={15} />
            {downloading ? '打包中…' : '下载选中 (' + selected.size + ')'}
          </button>
          <label className={uploading ? 'button paper disabled' : 'button paper'}>
            <Upload size={15} />
            {uploading ? '导入中…' : '导入文件'}
            <input
              hidden
              type='file'
              multiple
              disabled={uploading}
              accept='image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm'
              onChange={uploadFiles}
            />
          </label>
          <button
            type='button'
            className='button vermilion'
            onClick={() => setEditor({ kind: 'note' })}
          >
            <Plus size={16} />
            新建笔记
          </button>
        </div>
      </div>

      <div className='material-selection-bar'>
        <label>
          <input
            type='checkbox'
            checked={allVisibleSelected}
            onChange={() => {
              setSelected(current => {
                const next = new Set(current)
                if (allVisibleSelected) data.items.forEach(item => next.delete(item.id))
                else data.items.forEach(item => next.add(item.id))
                return next
              })
            }}
          />
          选择当前结果
        </label>
        <span>{data.items.length} 个结果</span>
      </div>

      {data.items.length
        ? (
          <section className='material-grid'>
            {data.items.map(material => (
              <MaterialCard
                key={material.id}
                material={material}
                selected={selected.has(material.id)}
                onToggle={() => toggle(material.id)}
                onView={() => setViewer(material)}
                onEdit={() => setEditor(material)}
                onDelete={() => remove(material)}
              />
            ))}
          </section>
          )
        : (
          <div className='material-empty'>
            <FileText size={28} />
            <b>没有符合条件的素材</b>
          </div>
          )}

      {editor && (
        <MaterialEditor
          material={editor}
          onClose={() => setEditor(null)}
          onSave={saveEditor}
        />
      )}

      {viewer && (
        <MaterialViewer
          material={viewer}
          onClose={() => setViewer(null)}
        />
      )}
    </div>
  )
}

function MaterialCard ({ material, selected, onToggle, onView, onEdit, onDelete }) {
  const KindIcon = KIND_ICONS[material.kind] || FileText
  return (
    <article className={selected ? 'material-card selected' : 'material-card'}>
      <div className='material-preview'>
        <button
          type='button'
          className='material-preview-button'
          aria-label={'查看素材 ' + material.title}
          onClick={onView}
        >
          {material.kind === 'image' && (
            <img src={materialFileUrl(material.id)} alt={material.title} loading='lazy' />
          )}
          {material.kind === 'video' && (
            <video src={materialFileUrl(material.id)} muted preload='metadata' />
          )}
          {material.kind === 'note' && (
            <div className='note-preview'>
              <FileText size={25} />
              <p>{material.content_md}</p>
            </div>
          )}
          <span className='material-view-cue'>
            <Eye size={15} />
            查看
          </span>
        </button>
        <label className='material-check'>
          <input
            type='checkbox'
            checked={selected}
            onChange={onToggle}
            aria-label={'选择素材 ' + material.title}
          />
        </label>
        <span className={'material-kind-badge ' + material.kind}>
          <KindIcon size={12} />
          {KIND_LABELS[material.kind]}
        </span>
      </div>
      <div className='material-card-body'>
        <div className='material-card-title'>
          <div>
            <button
              type='button'
              className='material-title-button'
              onClick={onView}
            >
              {material.title}
            </button>
            <span>
              {material.kind === 'note'
                ? material.content_md.length + ' 字'
                : formatBytes(material.size_bytes)}
              {' · ' + dateLabel(material.updated_at)}
            </span>
          </div>
          <div className='material-card-actions'>
            <button type='button' title='编辑素材' aria-label='编辑素材' onClick={onEdit}>
              <Pencil size={14} />
            </button>
            <button type='button' title='删除素材' aria-label='删除素材' onClick={onDelete}>
              <Trash2 size={14} />
            </button>
          </div>
        </div>
        {material.description && <p>{material.description}</p>}
        <div className='material-card-foot'>
          <div>
            {(material.tags || []).slice(0, 3).map(tag => <span key={tag}>#{tag}</span>)}
          </div>
          {material.reference_count > 0 && <small>已引用 {material.reference_count} 次</small>}
        </div>
      </div>
    </article>
  )
}

function MaterialViewer ({ material, onClose }) {
  const KindIcon = KIND_ICONS[material.kind] || FileText

  useEffect(() => {
    const closeOnEscape = event => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return (
    <div className='modal-backdrop material-viewer-backdrop' onMouseDown={onClose}>
      <section
        className={'material-viewer ' + material.kind}
        role='dialog'
        aria-modal='true'
        aria-label={'查看素材 ' + material.title}
        onMouseDown={event => event.stopPropagation()}
      >
        <header>
          <div>
            <span className='eyebrow'>MATERIAL PREVIEW</span>
            <h2>{material.title}</h2>
          </div>
          <button type='button' className='close-button' aria-label='关闭' onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className='material-viewer-body'>
          {material.kind === 'image' && (
            <img src={materialFileUrl(material.id)} alt={material.title} />
          )}
          {material.kind === 'video' && (
            <video src={materialFileUrl(material.id)} controls autoPlay preload='metadata' />
          )}
          {material.kind === 'note' && (
            <div className='material-note-document'>
              <MarkdownPreview markdown={material.content_md} />
            </div>
          )}
        </div>
        <footer>
          <span className={'material-kind-label ' + material.kind}>
            <KindIcon size={13} />
            {material.kind === 'note' ? 'Markdown 笔记' : KIND_LABELS[material.kind]}
          </span>
          <span>
            {material.kind === 'note'
              ? material.content_md.length + ' 字'
              : formatBytes(material.size_bytes)}
            {' · 更新于 ' + dateLabel(material.updated_at)}
          </span>
        </footer>
      </section>
    </div>
  )
}

function MaterialEditor ({ material, onClose, onSave }) {
  const isNew = !material.id
  const isNote = material.kind === 'note'
  const [form, setForm] = useState({
    title: material.title || '',
    description: material.description || '',
    content_md: material.content_md || '',
    tags: (material.tags || []).join('，')
  })
  const [saving, setSaving] = useState(false)
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))

  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    const values = {
      title: form.title.trim(),
      description: form.description.trim(),
      tags: form.tags.split(/[，,]/).map(tag => tag.trim()).filter(Boolean)
    }
    if (isNote) values.content_md = form.content_md.trim()
    await onSave(values)
    setSaving(false)
  }

  return (
    <div className='modal-backdrop material-editor-backdrop' onMouseDown={onClose}>
      <form className='material-editor' onSubmit={submit} onMouseDown={event => event.stopPropagation()}>
        <header>
          <div>
            <span className='eyebrow'>MATERIAL RECORD</span>
            <h2>{isNew ? '新建卡片笔记' : '编辑素材'}</h2>
          </div>
          <button type='button' className='close-button' aria-label='关闭' onClick={onClose}>
            <X size={18} />
          </button>
        </header>
        <div className='material-editor-body'>
          <label className='field full'>
            <span>标题</span>
            <input
              autoFocus
              required
              maxLength='120'
              value={form.title}
              onChange={event => set('title', event.target.value)}
            />
          </label>
          <label className='field full'>
            <span>说明</span>
            <textarea
              maxLength='1000'
              value={form.description}
              onChange={event => set('description', event.target.value)}
            />
          </label>
          {isNote && (
            <label className='field full'>
              <span>Markdown 内容</span>
              <textarea
                required
                className='note-content-input'
                maxLength='20000'
                placeholder={'# 标题\n\n使用 Markdown 记录可复用的观点、资料和写作片段。'}
                value={form.content_md}
                onChange={event => set('content_md', event.target.value)}
              />
            </label>
          )}
          <label className='field full'>
            <span>标签</span>
            <input
              value={form.tags}
              onChange={event => set('tags', event.target.value)}
              placeholder='使用逗号分隔'
            />
          </label>
        </div>
        <footer>
          <button type='button' className='button ghost' onClick={onClose}>取消</button>
          <button
            type='submit'
            className='button ink'
            disabled={saving || !form.title.trim() || (isNote && !form.content_md.trim())}
          >
            {saving ? '保存中…' : '保存素材'}
          </button>
        </footer>
      </form>
    </div>
  )
}

export function MaterialPicker ({ selected = [], onChange }) {
  const [data, setData] = useState({
    items: [],
    counts: { all: 0, image: 0, video: 0, note: 0 }
  })
  const [kind, setKind] = useState('all')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.materials()
      .then(setData)
      .finally(() => setLoading(false))
  }, [])

  const visible = useMemo(
    () => data.items.filter(item => kind === 'all' || item.kind === kind).slice(0, 30),
    [data.items, kind]
  )

  const toggle = materialId => {
    if (selected.includes(materialId)) {
      onChange(selected.filter(id => id !== materialId))
    } else if (selected.length < 20) {
      onChange([...selected, materialId])
    }
  }

  return (
    <section className='material-picker'>
      <header>
        <div>
          <b>参考素材</b>
          <span>{selected.length ? '已选择 ' + selected.length + ' 个' : '未选择'}</span>
        </div>
        <div className='material-picker-tabs'>
          {Object.entries(KIND_LABELS).map(([key, label]) => (
            <button
              type='button'
              className={kind === key ? 'active' : ''}
              key={key}
              onClick={() => setKind(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </header>
      <div className='material-picker-list'>
        {loading && <span className='material-picker-empty'>正在读取素材…</span>}
        {!loading && visible.map(material => {
          const KindIcon = KIND_ICONS[material.kind] || FileText
          const active = selected.includes(material.id)
          const detailText = material.kind === 'note'
            ? String(material.content_md || '').replace(/[#*_>]/g, '').trim()
            : material.description || `${formatBytes(material.size_bytes)} · ${dateLabel(material.updated_at)}`
          const detail = detailText.length > 80
            ? detailText.slice(0, 80) + '…'
            : detailText
          return (
            <button
              type='button'
              className={active ? 'active' : ''}
              aria-pressed={active}
              key={material.id}
              onClick={() => toggle(material.id)}
            >
              <span className={`reference-item-icon ${material.kind}`}>
                <KindIcon size={17} />
              </span>
              <span className='reference-item-copy'>
                <b>{material.title}</b>
                <small>{KIND_LABELS[material.kind]}{detail ? ` · ${detail}` : ''}</small>
              </span>
              <span className='reference-item-check'>
                {active && <Check size={14} />}
              </span>
            </button>
          )
        })}
        {!loading && !visible.length && (
          <span className='material-picker-empty'>当前类型没有素材</span>
        )}
      </div>
    </section>
  )
}