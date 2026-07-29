import { useEffect, useMemo, useState } from 'react'
import { api } from './api'

const PLATFORM_LABELS = {
  wechat: '公众号',
  xiaohongshu: '小红书',
  douyin: '抖音',
  channels: '视频号',
  bilibili: 'Bilibili',
  csdn: 'CSDN'
}
const PLATFORM_KEYS = Object.keys(PLATFORM_LABELS)
const DRAFT_PLATFORMS = new Set(['wechat', 'csdn'])

function normalizeTargets (targets = {}) {
  return Object.fromEntries(PLATFORM_KEYS.map(platform => [
    platform,
    {
      enabled: Boolean(targets[platform]?.enabled),
      account_id: targets[platform]?.account_id ?? null,
      action: DRAFT_PLATFORMS.has(platform)
        ? (targets[platform]?.action || 'draft')
        : 'publish'
    }
  ]))
}

export default function Automation ({ data, platforms = [], notify, onSaved }) {
  const makeForm = values => ({
    ...values,
    auto_publish_targets: normalizeTargets(values.auto_publish_targets)
  })
  const [form, setForm] = useState(() => makeForm(data.values))
  const [accounts, setAccounts] = useState([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setForm(makeForm(data.values))
  }, [data])

  useEffect(() => {
    api.accounts()
      .then(setAccounts)
      .catch(error => notify(error.message, 'error'))
  }, [])

  const platformStatus = useMemo(
    () => Object.fromEntries(platforms.map(item => [item.key, item])),
    [platforms]
  )
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))
  const wechatApiCannotPublish = account => (
    account?.platform === 'wechat' &&
    account.wechat?.publish_method === 'api' &&
    account.wechat?.api_capabilities?.publish !== true
  )
  const setTarget = (platform, values) => {
    setForm(current => ({
      ...current,
      auto_publish_targets: {
        ...current.auto_publish_targets,
        [platform]: {
          ...current.auto_publish_targets[platform],
          ...values
        }
      }
    }))
  }

  const setTargetAccount = (platform, value) => {
    const accountId = value ? Number(value) : null
    const account = accounts.find(item => (
      item.platform === platform && item.id === accountId
    ))
    setTarget(platform, {
      account_id: accountId,
      ...(wechatApiCannotPublish(account) ? { action: 'draft' } : {})
    })
  }

  useEffect(() => {
    if (!accounts.length) return
    setForm(current => {
      const target = current.auto_publish_targets.wechat
      const account = accounts.find(item => (
        item.platform === 'wechat' && item.id === target.account_id
      ))
      if (!wechatApiCannotPublish(account) || target.action !== 'publish') return current
      return {
        ...current,
        auto_publish_targets: {
          ...current.auto_publish_targets,
          wechat: { ...target, action: 'draft' }
        }
      }
    })
  }, [accounts, data])

  const save = async () => {
    const missingAccount = PLATFORM_KEYS.find(platform => {
      const target = form.auto_publish_targets[platform]
      return target.enabled && !target.account_id
    })
    if (missingAccount) {
      notify(`${PLATFORM_LABELS[missingAccount]}启用前需要选择账号`, 'error')
      return
    }
    setSaving(true)
    try {
      await api.saveSettings(form)
      await onSaved()
      notify('自动化规则已保存')
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className='page enter settings-page'>
      <section className='settings-intro'>
        <span className='section-number'>SYSTEM / AUTOMATION</span>
        <h2>设定节奏，<br />再交给系统执行。</h2>
        <p>自动发布按“稿件 + 平台”独立记录结果，已成功的平台不会重复处理。</p>
      </section>

      <section className='settings-section'>
        <header>
          <span>01</span>
          <div>
            <h3>内容同步</h3>
            <p>按间隔从 Notion 拉取状态为“待同步”的稿件。</p>
          </div>
        </header>
        <div className='settings-content'>
          <label className='field'>
            <span>同步间隔（分钟）</span>
            <input
              type='number'
              min='1'
              value={form.notion_sync_interval_minutes}
              onChange={event => set('notion_sync_interval_minutes', Number(event.target.value))}
            />
          </label>
          <label className='toggle'>
            <input
              type='checkbox'
              checked={form.notion_sync_enabled}
              onChange={event => set('notion_sync_enabled', event.target.checked)}
            />
            <span>
              <b>自动同步 Notion</b>
              <small>同步成功后，Notion 状态会更新为“已同步”。</small>
            </span>
          </label>
        </div>
      </section>

      <section className='settings-section'>
        <header>
          <span>02</span>
          <div>
            <h3>RSS 资讯扫描</h3>
            <p>定期检查订阅列表，只将新增条目写入资讯库。</p>
          </div>
        </header>
        <div className='settings-content'>
          <div className='settings-grid compact-grid'>
            <label className='field'>
              <span>扫描间隔（分钟）</span>
              <input
                type='number'
                min='1'
                value={form.rss_scan_interval_minutes}
                onChange={event => set('rss_scan_interval_minutes', Number(event.target.value))}
              />
            </label>
            <div className='automation-source-count'>
              <span>已配置订阅源</span>
              <b>{(form.rss_feed_urls || []).length}</b>
            </div>
          </div>
          <label className='toggle'>
            <input
              type='checkbox'
              checked={form.rss_enabled}
              onChange={event => set('rss_enabled', event.target.checked)}
            />
            <span>
              <b>启用 RSS 自动扫描</b>
              <small>已存在的原文链接会自动跳过。</small>
            </span>
          </label>
        </div>
      </section>

      <section className='settings-section'>
        <header>
          <span>03</span>
          <div>
            <h3>自动发布</h3>
            <p>选择参与自动发布的账号，并为每个平台指定保存草稿或直接发布。</p>
          </div>
        </header>
        <div className='settings-content'>
          <div className='settings-grid compact-grid'>
            <label className='field'>
              <span>检查间隔（分钟）</span>
              <input
                type='number'
                min='1'
                value={form.auto_publish_interval_minutes}
                onChange={event => set('auto_publish_interval_minutes', Number(event.target.value))}
              />
            </label>
            <label className='field'>
              <span>新同步稿件默认方式</span>
              <select
                value={form.default_publish_mode}
                onChange={event => set('default_publish_mode', event.target.value)}
              >
                <option value='manual'>手动发布</option>
                <option value='automatic'>自动发布</option>
              </select>
            </label>
          </div>

          <div className='automation-targets'>
            <div className='automation-target-head'>
              <span>平台</span>
              <span>发布账号</span>
              <span>执行方式</span>
            </div>
            {PLATFORM_KEYS.map(platform => {
              const target = form.auto_publish_targets[platform]
              const platformAccounts = accounts.filter(account => account.platform === platform)
              const selectedAccount = platformAccounts.find(account => account.id === target.account_id)
              const canDirectPublish = !wechatApiCannotPublish(selectedAccount)
              const status = platformStatus[platform]
              return (
                <div className={target.enabled ? 'automation-target active' : 'automation-target'} key={platform}>
                  <label className='automation-platform-toggle'>
                    <input
                      type='checkbox'
                      checked={target.enabled}
                      onChange={event => setTarget(platform, { enabled: event.target.checked })}
                    />
                    <span>
                      <b>{PLATFORM_LABELS[platform]}</b>
                      <small>{status?.enabled ? '渠道已启用' : '需先在设置中启用渠道'}</small>
                    </span>
                  </label>
                  <label className='field compact'>
                    <span className='sr-only'>发布账号</span>
                    <select
                      value={target.account_id ?? ''}
                      disabled={!target.enabled}
                      onChange={event => setTargetAccount(platform, event.target.value)}
                    >
                      <option value=''>选择账号</option>
                      {platformAccounts.map(account => (
                        <option value={account.id} key={account.id}>
                          {account.name}
                          {wechatApiCannotPublish(account)
                            ? ' · API · 仅草稿'
                            : account.status === 'valid' ? ' · 可用' : ' · 未验证'}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className='field compact'>
                    <span className='sr-only'>执行方式</span>
                    <select
                      value={target.action}
                      disabled={!target.enabled}
                      onChange={event => setTarget(platform, { action: event.target.value })}
                    >
                      {DRAFT_PLATFORMS.has(platform) && <option value='draft'>保存草稿</option>}
                      {canDirectPublish && <option value='publish'>直接发布</option>}
                    </select>
                  </label>
                </div>
              )
            })}
          </div>

          <label className='toggle automation-master-toggle'>
            <input
              type='checkbox'
              checked={form.auto_publish_enabled}
              onChange={event => set('auto_publish_enabled', event.target.checked)}
            />
            <span>
              <b>启用自动发布</b>
              <small>失败的平台会暂停自动重试，可在内容库中单独重试。</small>
            </span>
          </label>
        </div>
      </section>

      <div className='save-bar'>
        <div>
          <b>自动化规则仅在当前设备生效</b>
          <span>修改后在下一轮调度中生效。</span>
        </div>
        <button className='button vermilion' disabled={saving} onClick={save}>
          {saving ? '正在保存…' : '保存自动化规则'}
        </button>
      </div>
    </div>
  )
}