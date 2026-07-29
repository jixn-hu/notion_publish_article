import { useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  X,
  XCircle
} from 'lucide-react'
import { api } from './api'
import './PublishProgress.css'

const KIND_LABELS = {
  manual: '手动发布',
  automatic: '自动发布',
  retry: '失败重试'
}

const STATUS_LABELS = {
  running: '执行中',
  completed: '已完成',
  partial: '部分完成',
  failed: '执行失败'
}

const ACTIVE_POLL_INTERVAL = 1200
const IDLE_POLL_INTERVAL = 8000
const MANUAL_WAKE_DURATION = 10000

function eventIcon (level) {
  if (level === 'success') return <CheckCircle2 size={14} />
  if (level === 'error') return <XCircle size={14} />
  if (level === 'warning') return <AlertTriangle size={14} />
  return <span className='publish-event-dot' />
}

function formatTime (value) {
  if (!value) return ''
  return new Date(value).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function isRecent (operation) {
  if (!operation || operation.status === 'running') return Boolean(operation)
  return Date.now() - new Date(operation.finished_at || operation.updated_at).getTime() < 5 * 60 * 1000
}

export default function PublishProgress () {
  const [operation, setOperation] = useState(null)
  const [expanded, setExpanded] = useState(true)
  const [dismissedId, setDismissedId] = useState('')
  const previousId = useRef('')
  const eventList = useRef(null)

  useEffect(() => {
    let disposed = false
    let timer
    let polling = false
    let activeUntil = 0

    const schedule = delay => {
      window.clearTimeout(timer)
      timer = window.setTimeout(poll, delay)
    }

    const poll = async () => {
      if (disposed || polling) return
      polling = true
      let delay = Date.now() < activeUntil
        ? ACTIVE_POLL_INTERVAL
        : IDLE_POLL_INTERVAL
      try {
        const data = await api.publishProgress()
        const next = isRecent(data.operation) ? data.operation : null
        if (next?.status === 'running') delay = ACTIVE_POLL_INTERVAL
        if (!disposed) {
          if (next?.id && next.id !== previousId.current) {
            previousId.current = next.id
            setDismissedId('')
            setExpanded(next.status === 'running')
          }
          setOperation(next)
        }
      } catch (_) {
        // The main health indicator already reports backend connectivity.
      } finally {
        polling = false
        if (!disposed) {
          schedule(Date.now() < activeUntil ? ACTIVE_POLL_INTERVAL : delay)
        }
      }
    }

    const wake = () => {
      activeUntil = Date.now() + MANUAL_WAKE_DURATION
      schedule(0)
    }

    window.addEventListener('moflow:publish-progress', wake)
    poll()
    return () => {
      disposed = true
      window.removeEventListener('moflow:publish-progress', wake)
      window.clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    if (expanded && eventList.current) {
      eventList.current.scrollTop = eventList.current.scrollHeight
    }
  }, [expanded, operation?.events?.length])

  if (!operation || operation.id === dismissedId) return null

  const running = operation.status === 'running'
  const progress = operation.total
    ? Math.min(100, Math.round((operation.current / operation.total) * 100))
    : 0
  const latestEvent = operation.events?.[operation.events.length - 1]

  return (
    <aside
      className={`publish-monitor ${operation.status} ${expanded ? 'expanded' : 'collapsed'}`}
      aria-live='polite'
      aria-label='发布动态'
    >
      <header className='publish-monitor-head'>
        <div className='publish-monitor-mark'>
          {running ? <Loader2 className='spin' size={17} /> : <Activity size={17} />}
        </div>
        <button
          type='button'
          className='publish-monitor-summary'
          onClick={() => setExpanded(value => !value)}
          aria-expanded={expanded}
        >
          <span>{KIND_LABELS[operation.kind] || '发布任务'} · {STATUS_LABELS[operation.status] || operation.status}</span>
          <b>{operation.title}</b>
          {!expanded && latestEvent && <small>{latestEvent.message}</small>}
        </button>
        <button
          type='button'
          className='icon-button publish-monitor-toggle'
          title={expanded ? '收起发布动态' : '展开发布动态'}
          onClick={() => setExpanded(value => !value)}
        >
          {expanded ? <ChevronDown size={17} /> : <ChevronUp size={17} />}
        </button>
        {!running && (
          <button
            type='button'
            className='icon-button publish-monitor-close'
            title='关闭发布动态'
            onClick={() => setDismissedId(operation.id)}
          >
            <X size={16} />
          </button>
        )}
      </header>

      {expanded && (
        <>
          <div className='publish-progress-track'>
            <span
              className={operation.total ? '' : running ? 'indeterminate' : 'complete'}
              style={operation.total ? { width: `${progress}%` } : undefined}
            />
          </div>
          <div className='publish-progress-meta'>
            <span>
              {operation.total
                ? `${operation.current} / ${operation.total} 个平台节点`
                : running ? '正在检查任务' : '检查已结束，未发现待处理稿件'}
            </span>
            <time>开始于 {formatTime(operation.started_at)}</time>
          </div>
          <div className='publish-event-list' ref={eventList}>
            {(operation.events || []).map(event => (
              <div className={`publish-event ${event.level}`} key={event.id}>
                <span className='publish-event-icon'>{eventIcon(event.level)}</span>
                <p>{event.message}</p>
                <time>{formatTime(event.time)}</time>
              </div>
            ))}
          </div>
          {!running && operation.summary && (
            <footer className='publish-monitor-result'>
              {operation.status === 'completed'
                ? <CheckCircle2 size={15} />
                : <AlertTriangle size={15} />}
              <span>{operation.summary}</span>
            </footer>
          )}
        </>
      )}
    </aside>
  )
}
