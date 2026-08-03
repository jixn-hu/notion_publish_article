import { useEffect } from 'react'
import { ExternalLink, X } from 'lucide-react'

export default function ImageViewer ({ src, title = '图片预览', alt = '', onClose }) {
  useEffect(() => {
    const onKeyDown = event => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  if (!src) return null

  return (
    <div
      className='image-viewer-backdrop'
      role='presentation'
      onMouseDown={event => {
        event.stopPropagation()
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        className='image-viewer'
        role='dialog'
        aria-modal='true'
        aria-label={title}
        onMouseDown={event => event.stopPropagation()}
      >
        <header>
          <div>
            <span>IMAGE PREVIEW</span>
            <h2>{title}</h2>
          </div>
          <div className='image-viewer-actions'>
            <a
              className='image-viewer-open'
              href={src}
              target='_blank'
              rel='noreferrer'
              aria-label='在新窗口打开图片'
              title='在新窗口打开图片'
            >
              <ExternalLink size={15} />
            </a>
            <button
              type='button'
              className='image-viewer-close'
              aria-label='关闭图片预览'
              title='关闭'
              onClick={onClose}
            >
              <X size={18} />
            </button>
          </div>
        </header>
        <div className='image-viewer-body'>
          <img src={src} alt={alt || title} />
        </div>
        <footer>{alt || '点击关闭，或按 Esc 返回'}</footer>
      </section>
    </div>
  )
}
