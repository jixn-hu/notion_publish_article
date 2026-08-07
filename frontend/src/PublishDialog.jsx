import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ExternalLink,
  History,
  RotateCcw,
  Send,
  X
} from 'lucide-react'
import { api } from './api'

const PLATFORM_LABELS = {
  wechat: '公众号',
  xiaohongshu: '小红书',
  douyin: '抖音',
  channels: '视频号',
  bilibili: 'Bilibili',
  csdn: 'CSDN'
}

const CONTENT_TYPE_LABELS = {
  article: '文章',
  image: '图文',
  video: '视频'
}

const DRAFT_PLATFORMS = new Set(['wechat', 'csdn'])
const SUCCESS_STATUSES = new Set(['drafted', 'published'])
const STATUS_LABELS = {
  publishing: '发布中',
  published: '已发布',
  drafted: '草稿已保存',
  failed: '发布失败',
  pending: '未发布'
}
const TRIGGER_LABELS = {
  manual: '手动发布',
  automatic: '自动发布',
  retry: '手动重试',
  republish: '再次发布'
}

function supportsArticle (platform, articleType) {
  return !Array.isArray(platform?.content_types) ||
    platform.content_types.includes(articleType)
}

function isAvailablePlatform (platform, articleType) {
  return Boolean(
    platform?.implemented &&
    platform?.enabled &&
    supportsArticle(platform, articleType)
  )
}

function sameAccount (left, right) {
  return Number(left || 0) === Number(right || 0)
}

function matchingState (article, target) {
  return (article.platform_states || []).find(state => (
    state.platform === target.platform &&
    state.action === target.action &&
    sameAccount(state.account_id, target.account_id)
  ))
}

function resolveArticleTargets (article, platforms, automationTargets) {
  const available = new Map(
    platforms
      .filter(platform => isAvailablePlatform(platform, article.article_type))
      .map(platform => [platform.key, platform])
  )
  const defaults = Object.entries(automationTargets || {})
    .filter(([key, target]) => target?.enabled && available.has(key))
    .map(([platform, target]) => ({
      platform,
      action: target.action || (DRAFT_PLATFORMS.has(platform) ? 'draft' : 'publish'),
      account_id: target.account_id ?? null
    }))
  if (defaults.length) return defaults

  return (article.target_platforms || [])
    .filter(platform => available.has(platform))
    .map(platform => ({
      platform,
      action: article.platform_actions?.[platform] ||
        (DRAFT_PLATFORMS.has(platform) ? 'draft' : 'publish'),
      account_id: article.platform_accounts?.[platform] ?? null
    }))
}

function accountLabel (accounts, accountId) {
  return accounts.find(account => account.id === Number(accountId))?.name ||
    (accountId ? `账号 #${accountId}` : '未选择账号')
}

function preferredAccountId (article, target, platform, platformAccounts) {
  const candidates = [
    target?.account_id,
    article.platform_accounts?.[platform]
  ]
  for (const candidate of candidates) {
    if (platformAccounts.some(account => account.id === Number(candidate))) {
      return Number(candidate)
    }
  }
  return platformAccounts.find(account => account.status === 'valid')?.id ||
    platformAccounts[0]?.id || ''
}

function statusIcon (status) {
  if (SUCCESS_STATUSES.has(status)) return <CheckCircle2 size={16} />
  if (status === 'failed') return <AlertTriangle size={16} />
  return <Clock3 size={16} />
}

export default function PublishDialog ({
  article,
  accounts,
  platforms,
  automationTargets,
  onClose,
  onPublish
}) {
  const [detail, setDetail] = useState(article)
  const [loading, setLoading] = useState(true)
  const [historyError, setHistoryError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [confirmKey, setConfirmKey] = useState('')

  const initialTargets = useMemo(
    () => resolveArticleTargets(article, platforms, automationTargets),
    [article, platforms, automationTargets]
  )
  const availablePlatforms = useMemo(
    () => platforms.filter(platform => (
      isAvailablePlatform(platform, article.article_type)
    )),
    [article.article_type, platforms]
  )
  const [rows, setRows] = useState(() => (
    availablePlatforms.map(platform => {
      const target = initialTargets.find(item => item.platform === platform.key)
      const platformAccounts = accounts.filter(
        account => account.platform === platform.key
      )
      const action = target?.action || article.platform_actions?.[platform.key] ||
        (DRAFT_PLATFORMS.has(platform.key) ? 'draft' : 'publish')
      const accountId = preferredAccountId(
        article,
        target,
        platform.key,
        platformAccounts
      )
      const state = matchingState(article, {
        platform: platform.key,
        action,
        account_id: accountId
      })
      return {
        platform: platform.key,
        action,
        account_id: accountId,
        selected: Boolean(target) && Boolean(accountId) && !SUCCESS_STATUSES.has(state?.status)
      }
    })
  ))

  useEffect(() => {
    let active = true
    api.article(article.id)
      .then(value => {
        if (active) setDetail(value)
      })
      .catch(error => {
        if (active) setHistoryError(error.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [article.id])

  useEffect(() => {
    const close = event => {
      if (event.key === 'Escape' && !submitting) onClose()
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onClose, submitting])

  const updateRow = (platform, values) => {
    setConfirmKey('')
    setRows(current => current.map(row => (
      row.platform === platform ? { ...row, ...values } : row
    )))
  }

  const selectedRows = rows.filter(row => row.selected)
  const publishSelected = async () => {
    if (!selectedRows.length) return
    setSubmitting(true)
    try {
      await onPublish({
        platformActions: Object.fromEntries(
          selectedRows.map(row => [row.platform, row.action])
        ),
        platformAccounts: Object.fromEntries(
          selectedRows.map(row => [row.platform, Number(row.account_id)])
        )
      })
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  const republish = async row => {
    const key = `${row.platform}:${row.account_id}:${row.action}`
    if (confirmKey !== key) {
      setConfirmKey(key)
      return
    }
    setSubmitting(true)
    try {
      await onPublish({
        platformActions: { [row.platform]: row.action },
        platformAccounts: { [row.platform]: Number(row.account_id) },
        force: true
      })
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className='modal-backdrop publish-modal-backdrop'
      onMouseDown={() => { if (!submitting) onClose() }}
    >
      <section
        className='publish-dialog'
        aria-modal='true'
        role='dialog'
        aria-labelledby='publish-dialog-title'
        onMouseDown={event => event.stopPropagation()}
      >
        <header className='publish-dialog-head'>
          <div>
            <span className='eyebrow'>DELIVERY / {article.id} · {CONTENT_TYPE_LABELS[article.article_type] || article.article_type}</span>
            <h2 id='publish-dialog-title'>发布管理</h2>
            <p>{article.title}</p>
          </div>
          <button
            className='icon-button'
            type='button'
            aria-label='关闭发布管理'
            title='关闭'
            disabled={submitting}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>

        <div className='publish-dialog-body'>
          <section className='publish-target-section'>
            <div className='publish-section-title'>
              <div>
                <span>发布目标</span>
                <b>{CONTENT_TYPE_LABELS[article.article_type] || article.article_type} · {rows.length} 个可用平台</b>
              </div>
              <span className={article.content_status === 'ready' ? 'queue-ready' : 'queue-draft'}>
                {article.content_status === 'ready' ? '发布队列' : '内容草稿'}
              </span>
            </div>

            <div className='publish-target-list'>
              {!rows.length && (
                <div className='publish-target-empty'>
                  <AlertTriangle size={18} />
                  <div>
                    <b>暂无可用发布平台</b>
                    <span>当前稿件为{CONTENT_TYPE_LABELS[article.article_type] || article.article_type}，请先在设置中启用支持该类型的渠道。</span>
                  </div>
                </div>
              )}
              {rows.map(row => {

                const platformAccounts = accounts.filter(
                  account => account.platform === row.platform
                )
                const selectedAccount = platformAccounts.find(
                  account => account.id === Number(row.account_id)
                )
                const apiCannotPublish = row.platform === 'wechat' &&
                  selectedAccount?.wechat?.publish_method === 'api' &&
                  selectedAccount.wechat?.api_capabilities?.publish !== true
                const state = matchingState(detail, row)
                const successful = SUCCESS_STATUSES.has(state?.status)
                const canSelect = Boolean(row.account_id) && !successful
                return (
                  <div
                    className={`publish-target-row ${state?.status || 'pending'}`}
                    key={row.platform}
                  >
                    <label className='publish-target-choice'>
                      <input
                        type='checkbox'
                        checked={row.selected}
                        disabled={!canSelect || submitting}
                        onChange={event => updateRow(row.platform, {
                          selected: event.target.checked
                        })}
                      />
                      <span className='publish-platform-mark'>
                        {(PLATFORM_LABELS[row.platform] || row.platform).slice(0, 1)}
                      </span>
                      <span>
                        <b>{PLATFORM_LABELS[row.platform] || row.platform}</b>
                        <small>{platformAccounts.length
                          ? accountLabel(accounts, row.account_id)
                          : '尚未添加账号'}</small>
                      </span>
                    </label>

                    <select
                      value={row.account_id}
                      disabled={!platformAccounts.length || submitting}
                      aria-label={`${PLATFORM_LABELS[row.platform]}发布账号`}
                      onChange={event => {
                        const accountId = event.target.value
                        const account = platformAccounts.find(
                          item => item.id === Number(accountId)
                        )
                        const onlyDraft = row.platform === 'wechat' &&
                          account?.wechat?.publish_method === 'api' &&
                          account.wechat?.api_capabilities?.publish !== true
                        updateRow(row.platform, {
                          account_id: accountId,
                          action: onlyDraft ? 'draft' : row.action,
                          selected: Boolean(accountId)
                        })
                      }}
                    >
                      <option value=''>选择账号</option>
                      {platformAccounts.map(account => (
                        <option value={account.id} key={account.id}>
                          {account.name} · {account.status === 'valid' ? '可用' : '未验证'}
                        </option>
                      ))}
                    </select>

                    <select
                      value={row.action}
                      disabled={!platformAccounts.length || submitting}
                      aria-label={`${PLATFORM_LABELS[row.platform]}执行方式`}
                      onChange={event => updateRow(row.platform, {
                        action: event.target.value,
                        selected: Boolean(row.account_id)
                      })}
                    >
                      {DRAFT_PLATFORMS.has(row.platform) && (
                        <option value='draft'>保存草稿</option>
                      )}
                      {!apiCannotPublish && <option value='publish'>直接发布</option>}
                    </select>

                    <div className={`publish-target-status ${state?.status || 'pending'}`}>
                      {statusIcon(state?.status)}
                      <span>
                        <b>{STATUS_LABELS[state?.status] || '未发布'}</b>
                        <small>{state ? `已尝试 ${state.attempts} 次` : '等待首次发布'}</small>
                      </span>
                    </div>

                    {successful && (
                      <button
                        type='button'
                        className={confirmKey === `${row.platform}:${row.account_id}:${row.action}`
                          ? 'republish-button confirming'
                          : 'republish-button'}
                        disabled={submitting}
                        onClick={() => republish(row)}
                      >
                        <RotateCcw size={14} />
                        {confirmKey === `${row.platform}:${row.account_id}:${row.action}`
                          ? '确认再次发布'
                          : '再次发布'}
                      </button>
                    )}
                    {!successful && state?.status === 'failed' && (
                      <small className='publish-target-error' title={state.last_error}>
                        {state.last_error}
                      </small>
                    )}
                  </div>
                )
              })}
            </div>
          </section>

          <section className='publish-history-section'>
            <div className='publish-section-title'>
              <div>
                <History size={16} />
                <span>发布历史</span>
              </div>
              <b>{detail.publish_records?.length || 0} 条</b>
            </div>
            <div className='publish-history-list'>
              {loading && <p className='publish-history-empty'>正在读取发布记录...</p>}
              {!loading && historyError && (
                <p className='publish-history-empty error'>发布历史读取失败：{historyError}</p>
              )}
              {!loading && !historyError && !(detail.publish_records || []).length && (
                <p className='publish-history-empty'>暂无发布记录</p>
              )}
              {(detail.publish_records || []).map(record => (
                <div className={`publish-history-row ${record.status}`} key={record.id}>
                  <span>{statusIcon(record.status)}</span>
                  <div>
                    <b>
                      {PLATFORM_LABELS[record.platform] || record.platform} · {STATUS_LABELS[record.status] || record.status}
                    </b>
                    <small>
                      {accountLabel(accounts, record.account_id)} ·
                      {record.action === 'draft' ? ' 保存草稿' : ' 直接发布'}
                    </small>
                    {record.error && (
                      <small className='publish-history-error' title={record.error}>
                        {record.error}
                      </small>
                    )}
                  </div>
                  <div>
                    <b>
                      {TRIGGER_LABELS[record.trigger_source] || '手动发布'}
                      {record.forced ? ' · 强制' : ''}
                    </b>
                    <small>{new Date(record.created_at).toLocaleString('zh-CN')}</small>
                  </div>
                  {/^https?:\/\//i.test(record.external_id || '') && (
                    <a
                      href={record.external_id}
                      target='_blank'
                      rel='noreferrer'
                      aria-label='打开平台内容'
                      title='打开平台内容'
                    >
                      <ExternalLink size={15} />
                    </a>
                  )}
                </div>
              ))}
            </div>
          </section>
        </div>

        <footer className='publish-dialog-footer'>
          <div>
            <b>{selectedRows.length ? `已选择 ${selectedRows.length} 个平台` : '请选择发布目标'}</b>
            <span>已成功的平台默认不会重复发布</span>
          </div>
          <button
            type='button'
            className='button vermilion'
            disabled={!selectedRows.length || submitting}
            onClick={publishSelected}
          >
            <Send size={15} />
            {submitting ? '正在发布...' : '发布所选平台'}
          </button>
        </footer>
      </section>
    </div>
  )
}
