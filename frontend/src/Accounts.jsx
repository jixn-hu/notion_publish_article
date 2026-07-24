import { useEffect, useState } from 'react'
import { api } from './api'

const STATUS_LABELS = {
  pending: '等待登录',
  valid: '可用',
  invalid: '需重新登录'
}

const PROXY_STATUS_LABELS = {
  pending: '未测试',
  valid: '可用',
  invalid: '不可用'
}

const ACCOUNT_PLATFORMS = {
  xiaohongshu: { label: '小红书', mark: '红' },
  douyin: { label: '抖音', mark: '抖' },
  channels: { label: '视频号', mark: '视' },
  bilibili: { label: 'Bilibili', mark: 'B' }
}

const PROFILE_ID_LABELS = {
  xiaohongshu: '小红书号',
  douyin: '抖音号',
  channels: '视频号 ID'
}

const PROFILE_METRICS = {
  xiaohongshu: [
    ['following_count', '关注'],
    ['followers_count', '粉丝'],
    ['likes_and_collections_count', '获赞与收藏']
  ],
  douyin: [
    ['following_count', '关注'],
    ['followers_count', '粉丝'],
    ['works_count', '作品'],
    ['likes_count', '获赞']
  ],
  channels: [
    ['followers_count', '粉丝'],
    ['works_count', '作品'],
    ['likes_count', '获赞']
  ]
}

const countLabel = value => {
  if (value === null || value === undefined) return '—'
  if (value >= 10000) return `${(value / 10000).toFixed(1).replace(/\.0$/, '')}万`
  return String(value)
}

const profileMetrics = account => (
  (PROFILE_METRICS[account.platform] || [])
    .filter(([key]) => account.profile?.[key] !== null &&
      account.profile?.[key] !== undefined)
)

function Accounts ({ notify, onChanged }) {
  const [accounts, setAccounts] = useState([])
  const [proxies, setProxies] = useState([])
  const [platform, setPlatform] = useState('xiaohongshu')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState('')
  const [proxyAccountId, setProxyAccountId] = useState(null)
  const [selectedProxyId, setSelectedProxyId] = useState('')
  const [proxyName, setProxyName] = useState('')
  const [proxyAddress, setProxyAddress] = useState('')

  const load = async () => {
    const [accountResult, proxyResult] = await Promise.all([
      api.accounts(),
      api.proxies()
    ])
    setAccounts(accountResult)
    setProxies(proxyResult)
    if (onChanged) onChanged(accountResult)
  }

  useEffect(() => {
    load().catch(error => notify(error.message, 'error'))
  }, [])

  const create = async event => {
    event.preventDefault()
    if (!name.trim()) return
    setBusy('create')
    try {
      const account = await api.createAccount({
        platform,
        name: name.trim()
      })
      setName('')
      await load()
      notify(`账号“${account.name}”已创建，请继续登录`)
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const run = async (key, action, success) => {
    setBusy(key)
    try {
      await action()
      await load()
      notify(success)
    } catch (error) {
      await load().catch(() => {})
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const editProxy = account => {
    setProxyAccountId(account.id)
    setSelectedProxyId(account.proxy_id ? String(account.proxy_id) : '')
  }

  const saveProxy = async event => {
    event.preventDefault()
    const accountId = proxyAccountId
    const proxyId = selectedProxyId ? Number(selectedProxyId) : null
    setBusy(`proxy-${accountId}`)
    try {
      await api.updateAccountProxy(accountId, proxyId)
      await load()
      setProxyAccountId(null)
      setSelectedProxyId('')
      notify(proxyId ? '账号代理设置已保存' : '账号已改为直连')
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const createProxy = async event => {
    event.preventDefault()
    if (!proxyName.trim() || !proxyAddress.trim()) return
    setBusy('create-proxy')
    try {
      await api.createProxy({
        name: proxyName.trim(),
        proxy_url: proxyAddress.trim()
      })
      setProxyName('')
      setProxyAddress('')
      await load()
      notify('代理已保存，请先测试可用性')
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const testSavedProxy = proxy => run(
    `test-proxy-${proxy.id}`,
    () => api.testProxy(proxy.id),
    `代理“${proxy.name}”测试通过`
  )

  const removeProxy = async proxy => {
    if (!window.confirm(`确定删除代理“${proxy.name}”吗？使用它的账号将改为直连。`)) return
    setBusy(`delete-proxy-${proxy.id}`)
    try {
      await api.deleteProxy(proxy.id)
      await load()
      notify(`代理“${proxy.name}”已删除`)
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className='page enter accounts-page'>
      <section className='accounts-hero'>
        <div>
          <span className='section-number'>BROWSER ACCOUNTS / PATCHRIGHT</span>
          <h2>一个账号，<br />一套独立浏览器会话。</h2>
          <p>
            登录时会打开可见 Chrome。扫码或完成平台验证后，会话保存在本机，
            不保存账号密码，也不把 Cookie 回传给前端。
          </p>
        </div>
        <form className='account-create' onSubmit={create}>
          <label className='field'>
            <span>发布平台</span>
            <select value={platform} onChange={event => setPlatform(event.target.value)}>
              {Object.entries(ACCOUNT_PLATFORMS).map(([key, item]) => (
                <option key={key} value={key}>{item.label}</option>
              ))}
            </select>
          </label>
          <label className='field'>
            <span>账号备注名</span>
            <input
              value={name}
              maxLength={50}
              placeholder={`例如：${ACCOUNT_PLATFORMS[platform].label}主账号`}
              onChange={event => setName(event.target.value)}
            />
          </label>
          <button className='button vermilion' disabled={Boolean(busy)}>
            {busy === 'create'
              ? '正在创建…'
              : `＋ 添加${ACCOUNT_PLATFORMS[platform].label}账号`}
          </button>
        </form>
      </section>

      <section className='proxy-sheet'>
        <header>
          <div>
            <span className='eyebrow'>PROXY DIRECTORY</span>
            <h3>代理管理</h3>
          </div>
          <small>{proxies.length} 个已保存代理</small>
        </header>
        <form className='proxy-create' onSubmit={createProxy}>
          <label className='field'>
            <span>代理名称</span>
            <input
              value={proxyName}
              maxLength={50}
              placeholder='例如：上海线路'
              onChange={event => setProxyName(event.target.value)}
            />
          </label>
          <label className='field'>
            <span>代理地址</span>
            <input
              value={proxyAddress}
              maxLength={300}
              placeholder='http://127.0.0.1:7890 或 https:http://主机:端口'
              onChange={event => setProxyAddress(event.target.value)}
            />
          </label>
          <button className='button vermilion' disabled={Boolean(busy)}>
            {busy === 'create-proxy' ? '保存中…' : '＋ 保存代理'}
          </button>
          <small className='proxy-create-hint'>
            代理按账号全局生效，HTTP 和 HTTPS 请求都会通过它；
            兼容“https:http://…”格式并自动规范为“http://…”。
          </small>
        </form>
        {proxies.length > 0 && (
          <div className='proxy-list'>
            {proxies.map(proxy => (
              <article key={proxy.id} className='proxy-item'>
                <div>
                  <b>{proxy.name}</b>
                  <code>{proxy.proxy_url}</code>
                </div>
                <span className={`proxy-status ${proxy.status}`}>
                  {PROXY_STATUS_LABELS[proxy.status] || proxy.status}
                  {proxy.exit_ip ? ` · ${proxy.exit_ip}` : ''}
                  {proxy.last_latency_ms !== null ? ` · ${proxy.last_latency_ms}ms` : ''}
                </span>
                {proxy.last_error && <small title={proxy.last_error}>{proxy.last_error}</small>}
                <div>
                  <button
                    className='button ink'
                    disabled={Boolean(busy)}
                    onClick={() => testSavedProxy(proxy)}
                  >
                    {busy === `test-proxy-${proxy.id}` ? '测试中…' : '测试'}
                  </button>
                  <button
                    className='button ghost'
                    disabled={Boolean(busy)}
                    onClick={() => removeProxy(proxy)}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className='account-sheet'>
        <header>
          <div>
            <span className='eyebrow'>ACCOUNT DIRECTORY</span>
            <h3>发布账号</h3>
          </div>
          <small>{accounts.length} 个本地账号</small>
        </header>
        {accounts.length
          ? (
            <div className='account-grid'>
              {accounts.map(account => (
                <article key={account.id} className='account-card'>
                  <div className={`account-avatar ${account.platform}`}>
                    {account.profile?.avatar_cached
                      ? (
                        <img
                          src={`/api/accounts/${account.id}/avatar?v=${encodeURIComponent(account.profile_synced_at || '')}`}
                          alt={account.profile.display_name || account.name}
                        />
                        )
                      : ACCOUNT_PLATFORMS[account.platform]?.mark || '?'}
                  </div>
                  <div className='account-meta'>
                    <span>
                      {ACCOUNT_PLATFORMS[account.platform]?.label || account.platform}
                      {' · #'}{account.id}
                      {account.profile?.display_name &&
                        account.profile.display_name !== account.name
                        ? ` · 备注 ${account.name}`
                        : ''}
                    </span>
                    <h4>{account.profile?.display_name || account.name}</h4>
                    {account.profile?.platform_user_id && (
                      <small className='account-platform-id'>
                        {PROFILE_ID_LABELS[account.platform] || '平台账号'}{' '}
                        {account.profile.platform_user_id}
                      </small>
                    )}
                    <p className={`account-status ${account.status}`}>
                      <i />
                      {STATUS_LABELS[account.status] || account.status}
                    </p>
                    <small className={`account-proxy ${account.proxy ? 'enabled' : ''}`}>
                      {account.proxy ? `代理 ${account.proxy.name}` : '网络 直连'}
                    </small>
                    {account.last_error && (
                      <small title={account.last_error}>{account.last_error}</small>
                    )}
                    {profileMetrics(account).length > 0 && (
                      <div className='account-metrics'>
                        {profileMetrics(account).map(([key, label]) => (
                          <span key={key}>
                            <b>{countLabel(account.profile[key])}</b>
                            {label}
                          </span>
                        ))}
                      </div>
                    )}
                    {account.profile_error && (
                      <small title={account.profile_error}>{account.profile_error}</small>
                    )}
                  </div>
                  <div className='account-actions'>
                    <button
                      className='button ink'
                      disabled={Boolean(busy)}
                      onClick={() => run(
                        `login-${account.id}`,
                        () => api.loginAccount(account.id),
                        `账号“${account.name}”登录成功`
                      )}
                    >
                      {busy === `login-${account.id}` ? '等待浏览器登录…' : '打开浏览器登录'}
                    </button>
                    <button
                      className='button ghost'
                      disabled={Boolean(busy)}
                      onClick={() => run(
                        `check-${account.id}`,
                        () => api.checkAccount(account.id),
                        `账号“${account.name}”状态有效`
                      )}
                    >
                      {busy === `check-${account.id}` ? '检查中…' : '检查状态'}
                    </button>
                    {['xiaohongshu', 'douyin', 'channels'].includes(account.platform) && (
                      <button
                        className='button ghost'
                        disabled={Boolean(busy) || account.status !== 'valid'}
                        onClick={() => run(
                          `profile-${account.id}`,
                          () => api.refreshAccountProfile(account.id),
                          `账号“${account.name}”资料已更新`
                        )}
                      >
                        {busy === `profile-${account.id}` ? '同步中…' : '刷新资料'}
                      </button>
                    )}
                    <button
                      className='button ghost'
                      disabled={Boolean(busy)}
                      onClick={() => editProxy(account)}
                    >
                      代理设置
                    </button>
                  </div>
                  {proxyAccountId === account.id && (
                    <form className='account-proxy-form' onSubmit={saveProxy}>
                      <label className='field'>
                        <span>账号专用代理</span>
                        <select
                          autoFocus
                          value={selectedProxyId}
                          onChange={event => setSelectedProxyId(event.target.value)}
                        >
                          <option value=''>直连（不使用代理）</option>
                          {proxies.map(proxy => (
                            <option key={proxy.id} value={proxy.id}>
                              {proxy.name} · {PROXY_STATUS_LABELS[proxy.status] || proxy.status}
                            </option>
                          ))}
                        </select>
                      </label>
                      <div>
                        <button
                          className='button ink'
                          disabled={Boolean(busy)}
                        >
                          {busy === `proxy-${account.id}` ? '保存中…' : '保存'}
                        </button>
                        <button
                          type='button'
                          className='button ghost'
                          disabled={Boolean(busy)}
                          onClick={() => {
                            setProxyAccountId(null)
                            setSelectedProxyId('')
                          }}
                        >
                          取消
                        </button>
                      </div>
                      <small>
                        代理需要先在上方保存并测试；选择直连时不使用代理。
                      </small>
                    </form>
                  )}
                </article>
              ))}
            </div>
            )
          : (
            <div className='account-empty'>
              <span>01</span>
              <p>先选择平台并添加账号，再打开浏览器完成登录。</p>
            </div>
            )}
      </section>

      <aside className='browser-note'>
        <b>浏览器原则</b>
        <p>
          当前只使用 Patchright 持久化 Chrome，不注入 stealth.js、不改 User-Agent，
          也不启用 Playwright 路径。同一时间只运行一个登录或发布任务。
        </p>
      </aside>
    </div>
  )
}

export default Accounts
