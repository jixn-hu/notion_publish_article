import { useEffect, useState } from 'react'
import { api } from './api'

const STATUS = { pending: '未测试', valid: '可用', invalid: '不可用' }

export default function ProxyDirectory ({ notify }) {
  const [items, setItems] = useState([])
  const [name, setName] = useState('')
  const [address, setAddress] = useState('')
  const [busy, setBusy] = useState('')

  const load = async () => setItems(await api.proxies())
  useEffect(() => { load().catch(error => notify(error.message, 'error')) }, [])

  const create = async event => {
    event.preventDefault()
    if (!name.trim() || !address.trim()) return
    setBusy('create')
    try {
      await api.createProxy({ name: name.trim(), proxy_url: address.trim() })
      setName('')
      setAddress('')
      await load()
      notify('代理已保存，请先测试可用性')
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  const run = async (key, action, message) => {
    setBusy(key)
    try {
      await action()
      await load()
      notify(message)
    } catch (error) {
      notify(error.message, 'error')
    } finally {
      setBusy('')
    }
  }

  return (
    <section className='proxy-sheet'>
      <header>
        <div>
          <span className='eyebrow'>NETWORK ROUTES</span>
          <h3>代理管理</h3>
        </div>
        <small>{items.length} 个已保存代理</small>
      </header>
      <form className='proxy-create' onSubmit={create}>
        <label className='field'>
          <span>代理名称</span>
          <input value={name} maxLength={50} placeholder='例如：上海线路' onChange={event => setName(event.target.value)} />
        </label>
        <label className='field'>
          <span>代理地址</span>
          <input value={address} maxLength={300} placeholder='http://127.0.0.1:7890' onChange={event => setAddress(event.target.value)} />
        </label>
        <button className='button vermilion' disabled={Boolean(busy)}>{busy === 'create' ? '保存中…' : '保存代理'}</button>
      </form>
      {items.length > 0 && <div className='proxy-list'>
        {items.map(proxy => <article key={proxy.id} className='proxy-item'>
          <div><b>{proxy.name}</b><code>{proxy.proxy_url}</code></div>
          <span className={`proxy-status ${proxy.status}`}>{STATUS[proxy.status] || proxy.status}{proxy.exit_ip ? ` · ${proxy.exit_ip}` : ''}</span>
          <div>
            <button className='button ink' disabled={Boolean(busy)} onClick={() => run(`test-${proxy.id}`, () => api.testProxy(proxy.id), `代理“${proxy.name}”测试通过`)}>{busy === `test-${proxy.id}` ? '测试中…' : '测试'}</button>
            <button className='button ghost' disabled={Boolean(busy)} onClick={() => { if (window.confirm(`确定删除代理“${proxy.name}”吗？`)) run(`delete-${proxy.id}`, () => api.deleteProxy(proxy.id), '代理已删除') }}>删除</button>
          </div>
          {proxy.last_error && <small title={proxy.last_error}>{proxy.last_error}</small>}
        </article>)}
      </div>}
    </section>
  )
}