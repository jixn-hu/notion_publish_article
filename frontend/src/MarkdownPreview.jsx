import { useMemo } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { mediaPreviewUrl } from './api'

function prepareMarkdown (markdownText, mediaPaths) {
  let source = (markdownText || '').replace(/<empty-block\s*\/?>/gi, '')
  for (const path of mediaPaths || []) {
    if (!path || /^(https?:|data:|blob:)/i.test(path)) continue
    const previewUrl = mediaPreviewUrl(path)
    source = source.split(path).join(previewUrl)
    source = source.split(path.replace(/\\/g, '/')).join(previewUrl)
  }
  return source
}

export default function MarkdownPreview ({ markdown: markdownText, mediaPaths = [] }) {
  const html = useMemo(() => {
    const source = prepareMarkdown(markdownText, mediaPaths)
    return DOMPurify.sanitize(marked.parse(source, {
      breaks: true,
      gfm: true
    }))
  }, [markdownText, mediaPaths])

  if (!(markdownText || '').trim()) {
    return (
      <div className='markdown-preview empty'>
        <span>PREVIEW</span>
        <p>正文为空，切换到编辑模式开始写作。</p>
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