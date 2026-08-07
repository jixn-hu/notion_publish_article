import { useEffect, useState } from 'react'
import { Monitor, RadioTower, Settings2, Trash2, UserRoundCheck, X } from 'lucide-react'
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
  wechat: { label: '公众号', mark: '公' },
  xiaohongshu: { label: '小红书', mark: '红' },
  douyin: { label: '抖音', mark: '抖' },
  channels: { label: '视频号', mark: '视' },
  bilibili: { label: 'Bilibili', mark: 'B' },
  csdn: { label: 'CSDN', mark: 'C' }
}

const PROFILE_ID_LABELS = {
  wechat: '微信号',
  xiaohongshu: '小红书号',
  douyin: '抖音号',
  channels: '视频号 ID',
  bilibili: 'UID'
}

const PROFILE_METRICS = {
  wechat: [
    ['followers_count', '粉丝'],
    ['new_followers_count', '昨日新增粉丝']
  ],
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
  ],
  bilibili: [
    ['following_count', '关注'],
    ['followers_count', '粉丝'],
    ['works_count', '视频'],
    ['level', '等级']
  ],
  csdn: [
    ['followers_count', '\u7c89\u4e1d'],
    ['works_count', '\u539f\u521b'],
    ['read_count', '\u9605\u8bfb'],
    ['favorites_count', '\u6536\u85cf']
  ]
}

const countLabel = value => {
  if (value === null || value === undefined) return '—'
  if (value >= 10000) return `${(value / 10000).toFixed(1).replace(/\.0$/, '')}万`
  return String(value)
}
const profileSyncedLabel = value => {
  if (!value) return ''
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  })
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
  const [settingsAccountId, setSettingsAccountId] = useState(null)
  const [selectedProxyId, setSelectedProxyId] = useState('')
  const [proxyName, setProxyName] = useState('')
  const [proxyAddress, setProxyAddress] = useState('')
  const [wechatForm, setWechatForm] = useState({
    publish_method: 'browser',
    api_connection_mode: 'direct',
    api_base_url: 'http://127.0.0.1:8701/wechat',
    app_id: '',
    app_secret: ''
  })


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

  const manageAccount = async account => {
    setBusy(`manage-${account.id}`)
    try {
      const result = await api.loginAccount(account.id)
      await load()
      const isLogin = result.management_mode === 'login'
      if (result.profile_error) {
        notify(
          `账号“${account.name}”状态有效，但资料采集失败：${result.profile_error}`,
          'error'
        )
      } else {
        notify(
          isLogin
            ? `账号“${account.name}”登录成功，会话与资料已保存`
            : `账号“${account.name}”状态已检查，资料已刷新`
        )
      }
    } catch (error) {
      await load().catch(() => {})
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const removeAccount = async account => {
    const label = account.profile?.display_name || account.name
    if (!window.confirm(
      `确定删除账号“${label}”吗？本地浏览器登录会话和 API 配置将一并删除，且无法恢复。`
    )) return
    setBusy(`delete-account-${account.id}`)
    try {
      const result = await api.deleteAccount(account.id)
      if (settingsAccountId === account.id) setSettingsAccountId(null)
      await load()
      notify(
        result.cleanup_warning
          ? `账号已删除；${result.cleanup_warning}`
          : `账号“${label}”已删除`
      )
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const openAccountSettings = account => {
    setSettingsAccountId(account.id)
    setSelectedProxyId(account.proxy_id ? String(account.proxy_id) : '')
    setWechatForm({
      publish_method: account.wechat?.publish_method || 'browser',
      api_connection_mode: account.wechat?.api_connection_mode || 'direct',
      api_base_url: account.wechat?.api_base_url || 'http://127.0.0.1:8701/wechat',
      app_id: account.wechat?.app_id || '',
      app_secret: ''
    })
  }

  const closeAccountSettings = () => {
    setSettingsAccountId(null)
    setSelectedProxyId('')
    setWechatForm(current => ({ ...current, app_secret: '' }))
  }

  const saveAccountSettings = async event => {
    event.preventDefault()
    const account = accounts.find(item => item.id === settingsAccountId)
    if (!account) return
    const proxyId = selectedProxyId ? Number(selectedProxyId) : null
    setBusy(`account-settings-${account.id}`)
    try {
      await api.updateAccountProxy(account.id, proxyId)
      if (account.platform === 'wechat') {
        const values = {
          publish_method: wechatForm.publish_method,
          api_connection_mode: wechatForm.api_connection_mode,
          api_base_url: wechatForm.api_base_url.trim(),
          app_id: wechatForm.app_id.trim()
        }
        if (wechatForm.app_secret) values.app_secret = wechatForm.app_secret
        await api.updateWechatAccount(account.id, values)
      }
      await load()
      closeAccountSettings()
      notify(`账号“${account.name}”设置已保存`)
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


  const testWechat = async account => {
    setBusy(`wechat-test-${account.id}`)
    try {
      const result = await api.testWechatAccount(account.id)
      await load()
      const available = [
        result.capabilities?.draft && '草稿',
        result.capabilities?.publish && '发布'
      ].filter(Boolean)
      notify(
        available.length
          ? `公众号 API 可用：${available.join('、')}`
          : 'API 凭据有效，但草稿和发布接口尚未授权',
        available.length ? 'success' : 'error'
      )
    } catch (error) {
      await load().catch(() => {})
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const setWechat = (key, value) => {
    setWechatForm(current => ({ ...current, [key]: value }))
  }
  const settingsAccount = accounts.find(item => item.id === settingsAccountId) || null

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
                <article
                  key={account.id}
                  className={'account-card ' + account.platform}
                >
                  <header className='account-card-head'>
                    <div className={'account-avatar ' + account.platform}>
                      {account.profile?.avatar_cached
                        ? (
                          <img
                            src={'/api/accounts/' + account.id + '/avatar?v=' + encodeURIComponent(account.profile_synced_at || '')}
                            alt={account.profile.display_name || account.name}
                          />
                          )
                        : ACCOUNT_PLATFORMS[account.platform]?.mark || '?'}
                    </div>

                    <div className='account-identity'>
                      <div className='account-kicker'>
                        <span>{ACCOUNT_PLATFORMS[account.platform]?.label || account.platform}</span>
                        <span>#{account.id}</span>
                      </div>
                      <h4>{account.profile?.display_name || account.name}</h4>
                      {account.profile?.display_name &&
                        account.profile.display_name !== account.name && (
                          <p className='account-note'>备注 {account.name}</p>
                      )}
                      <div className='account-identifiers'>
                        {account.profile?.platform_user_id && (
                          <span>
                            {PROFILE_ID_LABELS[account.platform] || '平台账号'}{' '}
                            {account.profile.platform_user_id}
                          </span>
                        )}
                        {account.platform === 'wechat' && account.wechat?.app_id && (
                          <span>AppID {account.wechat.app_id}</span>
                        )}
                      </div>
                    </div>

                    <span className={'account-health ' + account.status}>
                      <i />
                      {STATUS_LABELS[account.status] || account.status}
                    </span>
                  </header>

                  <div className='account-facts'>
                    {account.platform === 'wechat' && (
                      <>
                        <span className={'account-fact ' + (account.wechat?.api_status || 'pending')}>
                          <RadioTower size={14} />
                          <small>公众号 API</small>
                          <b>{{
                            pending: '未配置',
                            valid: '凭据有效',
                            invalid: '凭据无效'
                          }[account.wechat?.api_status] || account.wechat?.api_status}</b>
                        </span>
                        <span className='account-fact'>
                          <Monitor size={14} />
                          <small>默认发布</small>
                          <b>{account.wechat?.publish_method === 'api' ? '官方 API' : '浏览器'}</b>
                        </span>
                        <span className='account-fact'>
                          <RadioTower size={14} />
                          <small>API 线路</small>
                          <b>{account.wechat?.api_connection_mode === 'nginx' ? 'Nginx 中继' : '微信官网'}</b>
                        </span>
                      </>
                    )}
                    <span className={'account-fact ' + (account.proxy ? 'valid' : '')}>
                      <small>网络</small>
                      <b>{account.proxy ? account.proxy.name : '直连'}</b>
                    </span>
                    <span className='account-fact'>
                      <small>资料更新</small>
                      <b>{account.profile_synced_at
                        ? profileSyncedLabel(account.profile_synced_at)
                        : '尚未同步'}</b>
                    </span>
                  </div>

                  {profileMetrics(account).length > 0 && (
                    <div className='account-metrics'>
                      {profileMetrics(account).map(([key, label]) => (
                        <span key={key}>
                          <b>{countLabel(account.profile[key])}</b>
                          <small>{label}</small>
                        </span>
                      ))}
                    </div>
                  )}

                  {(account.last_error || account.profile_error) && (
                    <div className='account-errors'>
                      {account.last_error && (
                        <small title={account.last_error}>{account.last_error}</small>
                      )}
                      {account.profile_error && (
                        <small title={account.profile_error}>{account.profile_error}</small>
                      )}
                    </div>
                  )}

                  <footer className='account-actions'>
                    <button
                      className='button ghost'
                      disabled={Boolean(busy)}
                      title='打开账号页面，浏览器由你手动关闭'
                      onClick={() => run(
                        'browser-' + account.id,
                        () => api.openAccountBrowser(account.id),
                        '已打开“' + account.name + '”的账号浏览器'
                      )}
                    >
                      <Monitor size={15} />
                      {busy === 'browser-' + account.id ? '正在打开…' : '查看账号'}
                    </button>
                    <button
                      className='button ink'
                      disabled={Boolean(busy)}
                      title='登录账号、检查状态并刷新资料，完成后自动关闭'
                      onClick={() => manageAccount(account)}
                    >
                      <UserRoundCheck size={15} />
                      {busy === 'manage-' + account.id ? '检查刷新中…' : '登录 / 检查 / 刷新'}
                    </button>
                    <button
                      className='button ghost'
                      disabled={Boolean(busy)}
                      title='配置代理、发布方式和平台 API'
                      onClick={() => openAccountSettings(account)}
                    >
                      <Settings2 size={15} />
                      设置
                    </button>
                    <button
                      className='button danger account-delete'
                      disabled={Boolean(busy)}
                      title='删除账号'
                      aria-label={'删除账号 ' + (account.profile?.display_name || account.name)}
                      onClick={() => removeAccount(account)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </footer>
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

      {settingsAccount && (
        <div
          className='modal-backdrop account-settings-backdrop'
          onMouseDown={event => {
            if (event.target === event.currentTarget && !busy) closeAccountSettings()
          }}
        >
          <section
            className='account-settings-modal'
            role='dialog'
            aria-modal='true'
            aria-labelledby='account-settings-title'
          >
            <header>
              <div>
                <span>{ACCOUNT_PLATFORMS[settingsAccount.platform]?.label} · #{settingsAccount.id}</span>
                <h3 id='account-settings-title'>
                  {settingsAccount.profile?.display_name || settingsAccount.name}
                </h3>
              </div>
              <button
                type='button'
                className='account-settings-close'
                title='关闭'
                aria-label='关闭账号设置'
                disabled={Boolean(busy)}
                onClick={closeAccountSettings}
              >
                <X size={18} />
              </button>
            </header>
            <form className='account-settings-form' onSubmit={saveAccountSettings}>
              <section className='account-settings-section'>
                <header>
                  <span>01</span>
                  <div><b>网络代理</b><small>当前账号独立生效</small></div>
                </header>
                <label className='field'>
                  <span>连接方式</span>
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
              </section>

              {settingsAccount.platform === 'wechat' && (
                <section className='account-settings-section wechat-account-settings'>
                  <header>
                    <span>02</span>
                    <div><b>公众号发布</b><small>浏览器与官方 API 状态独立</small></div>
                  </header>
                  <div className='wechat-method-switch' role='group' aria-label='公众号发布方式'>
                    <button
                      type='button'
                      className={wechatForm.publish_method === 'browser' ? 'active' : ''}
                      onClick={() => setWechat('publish_method', 'browser')}
                    >
                      <Monitor size={15} />
                      <span><b>浏览器</b><small>适合交互发布与账号资料同步</small></span>
                    </button>
                    <button
                      type='button'
                      className={wechatForm.publish_method === 'api' ? 'active' : ''}
                      onClick={() => setWechat('publish_method', 'api')}
                    >
                      <RadioTower size={15} />
                      <span><b>官方 API</b><small>无需浏览器登录，按接口权限发布</small></span>
                    </button>
                  </div>
                  <div className='wechat-route-settings'>
                    <div className='wechat-route-heading'>
                      <b>API 请求线路</b>
                      <small>仅影响官方 API 请求，不影响浏览器发布</small>
                    </div>
                    <div className='wechat-route-switch' role='group' aria-label='公众号 API 请求线路'>
                      <button
                        type='button'
                        className={wechatForm.api_connection_mode === 'direct' ? 'active' : ''}
                        onClick={() => setWechat('api_connection_mode', 'direct')}
                      >
                        微信官网
                      </button>
                      <button
                        type='button'
                        className={wechatForm.api_connection_mode === 'nginx' ? 'active' : ''}
                        onClick={() => setWechat('api_connection_mode', 'nginx')}
                      >
                        Nginx 中继
                      </button>
                    </div>
                    {wechatForm.api_connection_mode === 'nginx' && (
                      <label className='field wechat-relay-field'>
                        <span>中继地址</span>
                        <input
                          type='url'
                          value={wechatForm.api_base_url}
                          placeholder='http://127.0.0.1:8701/wechat'
                          onChange={event => setWechat('api_base_url', event.target.value)}
                        />
                        <small>本机 SSH 转发可用 127.0.0.1；直接访问服务器时填写服务器地址。</small>
                      </label>
                    )}
                  </div>
                  <div className='wechat-api-fields'>
                    <label className='field'>
                      <span>AppID</span>
                      <input
                        value={wechatForm.app_id}
                        placeholder='公众号开发者 AppID'
                        onChange={event => setWechat('app_id', event.target.value)}
                      />
                    </label>
                    <label className='field'>
                      <span>AppSecret</span>
                      <input
                        type='password'
                        value={wechatForm.app_secret}
                        autoComplete='new-password'
                        placeholder={settingsAccount.wechat?.app_secret_configured
                          ? '已配置，留空表示不修改'
                          : '填写后加密保存在本机'}
                        onChange={event => setWechat('app_secret', event.target.value)}
                      />
                    </label>
                  </div>
                  <div className='account-api-status'>
                    <div className='wechat-capabilities'>
                      <span className={settingsAccount.wechat?.api_capabilities?.credentials ? 'valid' : ''}>凭据</span>
                      <span className={settingsAccount.wechat?.api_capabilities?.draft ? 'valid' : ''}>草稿</span>
                      <span className={settingsAccount.wechat?.api_capabilities?.publish ? 'valid' : ''}>发布</span>
                      {settingsAccount.wechat?.api_last_error && (
                        <small title={settingsAccount.wechat.api_last_error}>
                          {settingsAccount.wechat.api_last_error}
                        </small>
                      )}
                    </div>
                    <button
                      type='button'
                      className='button ghost'
                      disabled={Boolean(busy) || !settingsAccount.wechat?.app_secret_configured}
                      onClick={() => testWechat(settingsAccount)}
                    >
                      {busy === `wechat-test-${settingsAccount.id}` ? '检查中…' : '测试 API 权限'}
                    </button>
                  </div>
                </section>
              )}

              <footer>
                <button type='button' className='button ghost' disabled={Boolean(busy)} onClick={closeAccountSettings}>
                  取消
                </button>
                <button className='button ink' disabled={Boolean(busy)}>
                  {busy === `account-settings-${settingsAccount.id}` ? '保存中…' : '保存设置'}
                </button>
              </footer>
            </form>
          </section>
        </div>
      )}

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
