import { useEffect, useMemo, useRef } from 'react'
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

export default function MarkdownPreview ({
  markdown: markdownText,
  mediaPaths = [],
  onImageClick
}) {
  const previewRef = useRef(null)
  const html = useMemo(() => {
    const source = prepareMarkdown(markdownText, mediaPaths)
    return DOMPurify.sanitize(marked.parse(source, {
      breaks: true,
      gfm: true
    }))
  }, [markdownText, mediaPaths])

  useEffect(() => {
    if (!previewRef.current || !onImageClick) return undefined
    previewRef.current.querySelectorAll('img').forEach(image => {
      image.tabIndex = 0
      image.setAttribute('role', 'button')
      image.setAttribute('aria-label', image.alt || '打开图片预览')
    })
    return undefined
  }, [html, onImageClick])

  const imageDetails = event => {
    const image = event.target.closest('img')
    if (!image || !previewRef.current?.contains(image)) return null
    return {
      src: image.currentSrc || image.src,
      alt: image.alt || ''
    }
  }

  const openImage = event => {
    const image = imageDetails(event)
    if (image) onImageClick?.(image)
  }

  const openImageWithKeyboard = event => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    const image = imageDetails(event)
    if (!image) return
    event.preventDefault()
    onImageClick?.(image)
  }

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
      ref={previewRef}
      className={onImageClick ? 'markdown-preview images-clickable' : 'markdown-preview'}
      onClick={openImage}
      onKeyDown={openImageWithKeyboard}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}