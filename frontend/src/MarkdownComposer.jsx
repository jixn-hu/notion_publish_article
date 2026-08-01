import { useEffect, useRef, useState } from 'react'
import { EditorState } from '@codemirror/state'
import {
  drawSelection,
  dropCursor,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  placeholder
} from '@codemirror/view'
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
  redo,
  undo
} from '@codemirror/commands'
import {
  bracketMatching,
  defaultHighlightStyle,
  foldGutter,
  indentOnInput,
  syntaxHighlighting
} from '@codemirror/language'
import { markdown } from '@codemirror/lang-markdown'
import {
  Bold,
  Braces,
  Columns2,
  Eye,
  Heading1,
  Heading2,
  Heading3,
  Image,
  Italic,
  Link,
  List,
  ListOrdered,
  Minus,
  Pencil,
  Quote,
  Redo2,
  Strikethrough,
  Undo2
} from 'lucide-react'
import MarkdownPreview from './MarkdownPreview'

const editorTheme = EditorView.theme({
  '&': {
    height: '100%',
    color: '#1d1d1f',
    backgroundColor: '#fff'
  },
  '.cm-scroller': {
    minHeight: '430px',
    overflow: 'auto',
    fontFamily: '"SFMono-Regular", Consolas, "Microsoft YaHei", monospace',
    fontSize: '13px',
    lineHeight: '1.75'
  },
  '.cm-content': {
    padding: '20px 8px 48px'
  },
  '.cm-line': {
    padding: '0 14px'
  },
  '.cm-gutters': {
    color: '#a1a1a6',
    backgroundColor: '#f7f7f8',
    borderRight: '1px solid rgba(29, 29, 31, 0.07)'
  },
  '.cm-activeLine': {
    backgroundColor: 'rgba(0, 113, 227, 0.035)'
  },
  '.cm-activeLineGutter': {
    color: '#175f4a',
    backgroundColor: 'rgba(23, 95, 74, 0.07)'
  },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': {
    backgroundColor: 'rgba(0, 113, 227, 0.18) !important'
  },
  '&.cm-focused': {
    outline: 'none'
  }
})

const FORMAT_TOOLS = [
  { key: 'undo', label: '撤销', icon: Undo2 },
  { key: 'redo', label: '重做', icon: Redo2 },
  { divider: true },
  { key: 'h1', label: '一级标题', icon: Heading1 },
  { key: 'h2', label: '二级标题', icon: Heading2 },
  { key: 'h3', label: '三级标题', icon: Heading3 },
  { divider: true },
  { key: 'bold', label: '加粗', icon: Bold },
  { key: 'italic', label: '斜体', icon: Italic },
  { key: 'strike', label: '删除线', icon: Strikethrough },
  { key: 'link', label: '链接', icon: Link },
  { divider: true },
  { key: 'quote', label: '引用', icon: Quote },
  { key: 'bullet', label: '无序列表', icon: List },
  { key: 'ordered', label: '有序列表', icon: ListOrdered },
  { key: 'code', label: '行内代码', icon: Braces },
  { key: 'codeblock', label: '代码块', icon: Braces },
  { key: 'rule', label: '分隔线', icon: Minus },
  { key: 'image', label: '插入最后一张配图', icon: Image }
]

function ToolButton ({ icon: Icon, label, onClick, disabled = false }) {
  return (
    <button
      type='button'
      className='markdown-tool-button'
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
    >
      <Icon size={15} strokeWidth={1.8} />
    </button>
  )
}

export default function MarkdownComposer ({
  value,
  onChange,
  mediaPaths = [],
  onUploadImages,
  initialMode = 'edit'
}) {
  const hostRef = useRef(null)
  const previewRef = useRef(null)
  const viewRef = useRef(null)
  const onChangeRef = useRef(onChange)
  const uploadRef = useRef(onUploadImages)
  const startingMode = ['edit', 'split', 'preview'].includes(initialMode)
    ? initialMode
    : 'edit'
  const modeRef = useRef(startingMode)
  const [mode, setMode] = useState(startingMode)
  const [cursor, setCursor] = useState({ line: 1, column: 1 })

  onChangeRef.current = onChange
  uploadRef.current = onUploadImages
  modeRef.current = mode

  const updateCursor = view => {
    const head = view.state.selection.main.head
    const line = view.state.doc.lineAt(head)
    setCursor({
      line: line.number,
      column: head - line.from + 1
    })
  }

  const insertUploadedImages = async files => {
    if (!uploadRef.current || !files.length) return
    const paths = await uploadRef.current(files)
    if (!paths?.length || !viewRef.current) return
    const text = paths
      .map((path, index) => {
        const name = path.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, '') || `配图 ${index + 1}`
        return `![${name}](${path.replace(/\\/g, '/')})`
      })
      .join('\n\n')
    const view = viewRef.current
    view.dispatch(view.state.replaceSelection(`\n${text}\n`))
    view.focus()
  }

  useEffect(() => {
    if (!hostRef.current) return undefined

    const state = EditorState.create({
      doc: value || '',
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightActiveLine(),
        highlightSpecialChars(),
        history(),
        foldGutter(),
        drawSelection(),
        dropCursor(),
        indentOnInput(),
        bracketMatching(),
        markdown(),
        syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
        keymap.of([
          indentWithTab,
          ...defaultKeymap,
          ...historyKeymap
        ]),
        placeholder('# 从这里开始写作'),
        EditorView.lineWrapping,
        EditorView.contentAttributes.of({ 'aria-label': 'Markdown 正文编辑器' }),
        editorTheme,
        EditorView.updateListener.of(update => {
          if (update.docChanged) {
            onChangeRef.current(update.state.doc.toString())
          }
          if (update.docChanged || update.selectionSet) {
            updateCursor(update.view)
          }
        }),
        EditorView.domEventHandlers({
          paste: (event) => {
            const files = Array.from(event.clipboardData?.files || [])
              .filter(file => file.type.startsWith('image/'))
            if (!files.length || !uploadRef.current) return false
            event.preventDefault()
            void insertUploadedImages(files)
            return true
          },
          scroll: (_event, view) => {
            if (modeRef.current !== 'split' || !previewRef.current) return false
            const source = view.scrollDOM
            const sourceRange = source.scrollHeight - source.clientHeight
            const target = previewRef.current
            const targetRange = target.scrollHeight - target.clientHeight
            if (sourceRange > 0 && targetRange > 0) {
              target.scrollTop = (source.scrollTop / sourceRange) * targetRange
            }
            return false
          }
        })
      ]
    })

    const view = new EditorView({
      state,
      parent: hostRef.current
    })
    viewRef.current = view
    updateCursor(view)

    return () => {
      view.destroy()
      viewRef.current = null
    }
  }, [])

  useEffect(() => {
    const view = viewRef.current
    if (!view) return
    const current = view.state.doc.toString()
    if (current === (value || '')) return
    view.dispatch({
      changes: { from: 0, to: current.length, insert: value || '' }
    })
  }, [value])

  useEffect(() => {
    viewRef.current?.requestMeasure()
  }, [mode])

  const applyChange = (from, to, insert, anchor, head = anchor) => {
    const view = viewRef.current
    if (!view) return
    view.dispatch({
      changes: { from, to, insert },
      selection: { anchor, head },
      scrollIntoView: true
    })
    view.focus()
  }

  const wrapSelection = (prefix, suffix, placeholderText) => {
    const view = viewRef.current
    if (!view) return
    const selection = view.state.selection.main
    const selected = view.state.doc.sliceString(selection.from, selection.to)
    const body = selected || placeholderText
    const insert = `${prefix}${body}${suffix}`
    const start = selection.from + prefix.length
    applyChange(
      selection.from,
      selection.to,
      insert,
      start,
      start + body.length
    )
  }

  const prefixLines = (prefixFactory) => {
    const view = viewRef.current
    if (!view) return
    const selection = view.state.selection.main
    const firstLine = view.state.doc.lineAt(selection.from)
    const lastLine = view.state.doc.lineAt(selection.to)
    const source = view.state.doc.sliceString(firstLine.from, lastLine.to)
    const insert = source
      .split('\n')
      .map((line, index) => `${prefixFactory(index)}${line}`)
      .join('\n')
    applyChange(firstLine.from, lastLine.to, insert, firstLine.from, firstLine.from + insert.length)
  }

  const setHeading = level => {
    const view = viewRef.current
    if (!view) return
    const selection = view.state.selection.main
    const firstLine = view.state.doc.lineAt(selection.from)
    const lastLine = view.state.doc.lineAt(selection.to)
    const source = view.state.doc.sliceString(firstLine.from, lastLine.to)
    const marker = `${'#'.repeat(level)} `
    const insert = source
      .split('\n')
      .map(line => `${marker}${line.replace(/^#{1,6}\s+/, '')}`)
      .join('\n')
    applyChange(firstLine.from, lastLine.to, insert, firstLine.from + marker.length)
  }

  const runTool = key => {
    const view = viewRef.current
    if (!view) return
    if (key === 'undo') {
      undo(view)
      return
    }
    if (key === 'redo') {
      redo(view)
      return
    }
    if (key === 'h1' || key === 'h2' || key === 'h3') {
      setHeading(Number(key.slice(1)))
      return
    }
    if (key === 'bold') wrapSelection('**', '**', '加粗文字')
    if (key === 'italic') wrapSelection('*', '*', '斜体文字')
    if (key === 'strike') wrapSelection('~~', '~~', '删除文字')
    if (key === 'code') wrapSelection('`', '`', 'code')
    if (key === 'quote') prefixLines(() => '> ')
    if (key === 'bullet') prefixLines(() => '- ')
    if (key === 'ordered') prefixLines(index => `${index + 1}. `)
    if (key === 'link') wrapSelection('[', '](https://)', '链接文字')
    if (key === 'codeblock') wrapSelection('\n\n```\n', '\n```\n', 'code')
    if (key === 'rule') {
      const selection = view.state.selection.main
      applyChange(selection.from, selection.to, '\n\n---\n\n', selection.from + 7)
    }
    if (key === 'image' && mediaPaths.length) {
      const selection = view.state.selection.main
      const path = mediaPaths[mediaPaths.length - 1].replace(/\\/g, '/')
      const name = path.split('/').pop()?.replace(/\.[^.]+$/, '') || '文章配图'
      const insert = `\n\n![${name}](${path})\n\n`
      applyChange(selection.from, selection.to, insert, selection.from + insert.length)
    }
  }

  const readingCount = (value || '')
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_~`>|]/g, '')
    .replace(/\s/g, '')
    .length
  const lineCount = (value || '').split('\n').length

  return (
    <section className={`markdown-workbench mode-${mode}`}>
      <header className='markdown-workbench-head'>
        <div>
          <span>Markdown 正文</span>
          <small>{readingCount} 字 · {lineCount} 行</small>
        </div>
        <div className='markdown-view-tabs' role='tablist' aria-label='正文显示方式'>
          <button
            type='button'
            role='tab'
            aria-selected={mode === 'edit'}
            className={mode === 'edit' ? 'active' : ''}
            onClick={() => setMode('edit')}
          >
            <Pencil size={14} />
            编辑
          </button>
          <button
            type='button'
            role='tab'
            aria-selected={mode === 'split'}
            className={mode === 'split' ? 'active' : ''}
            onClick={() => setMode('split')}
          >
            <Columns2 size={14} />
            分栏
          </button>
          <button
            type='button'
            role='tab'
            aria-selected={mode === 'preview'}
            className={mode === 'preview' ? 'active' : ''}
            onClick={() => setMode('preview')}
          >
            <Eye size={14} />
            预览
          </button>
        </div>
      </header>

      <div className='markdown-toolbar' role='toolbar' aria-label='Markdown 格式'>
        {FORMAT_TOOLS.map((tool, index) => (
          tool.divider
            ? <span className='markdown-tool-divider' key={`divider-${index}`} />
            : (
              <ToolButton
                key={tool.key}
                icon={tool.icon}
                label={tool.label}
                disabled={tool.key === 'image' && !mediaPaths.length}
                onClick={() => runTool(tool.key)}
              />
              )
        ))}
      </div>

      <div className='markdown-workspace'>
        <div className='markdown-editor-pane'>
          <div ref={hostRef} className='codemirror-host' />
        </div>
        <div ref={previewRef} className='markdown-preview-pane'>
          <MarkdownPreview markdown={value} mediaPaths={mediaPaths} />
        </div>
      </div>

      <footer className='markdown-statusbar'>
        <span>Ln {cursor.line}, Col {cursor.column}</span>
        <span>{(value || '').length} 字符</span>
      </footer>
    </section>
  )
}
