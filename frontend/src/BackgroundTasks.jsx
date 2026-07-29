import { useEffect, useState } from 'react'
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  ExternalLink,
  Loader2,
  X
} from 'lucide-react'
import './BackgroundTasks.css'

function formatTime (value) {
  return new Date(value).toLocaleTimeString('zh-CN', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit'
  })
}

export default function BackgroundTasks ({ tasks, onDismiss, onOpen }) {
  const [expanded, setExpanded] = useState(true)
  const runningCount = tasks.filter(task => task.status === 'running').length

  useEffect(() => {
    if (runningCount > 0) setExpanded(true)
  }, [runningCount])

  if (!tasks.length) return null

  return (
    <aside className={`background-tasks ${expanded ? 'expanded' : 'collapsed'}`} aria-live='polite'>
      <header>
        <button
          type='button'
          className='background-tasks-summary'
          onClick={() => setExpanded(value => !value)}
          aria-expanded={expanded}
        >
          {runningCount > 0 ? <Loader2 className='spin' size={16} /> : <CheckCircle2 size={16} />}
          <span>
            <b>后台任务</b>
            <small>{runningCount > 0 ? `${runningCount} 项正在处理，可继续操作` : '最近任务已处理完成'}</small>
          </span>
        </button>
        <button
          type='button'
          className='icon-button background-tasks-toggle'
          title={expanded ? '收起后台任务' : '展开后台任务'}
          onClick={() => setExpanded(value => !value)}
        >
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </header>

      {expanded && (
        <div className='background-task-list'>
          {tasks.map(task => (
            <article className={`background-task ${task.status}`} key={task.id}>
              <span className='background-task-icon'>
                {task.status === 'running' && <Loader2 className='spin' size={15} />}
                {task.status === 'completed' && <CheckCircle2 size={15} />}
                {task.status === 'failed' && <CircleAlert size={15} />}
              </span>
              <div>
                <b>{task.title}</b>
                <small>{task.message}</small>
                <time>{formatTime(task.startedAt)}</time>
              </div>
              {task.status !== 'running' && task.destination && (
                <button
                  type='button'
                  className='background-task-open'
                  title='查看结果'
                  onClick={() => onOpen(task)}
                >
                  <ExternalLink size={14} />
                </button>
              )}
              {task.status !== 'running' && (
                <button
                  type='button'
                  className='background-task-dismiss'
                  title='移除此任务'
                  onClick={() => onDismiss(task.id)}
                >
                  <X size={14} />
                </button>
              )}
            </article>
          ))}
        </div>
      )}
    </aside>
  )
}
