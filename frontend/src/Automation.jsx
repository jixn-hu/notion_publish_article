import { useState } from 'react'
import { api } from './api'

export default function Automation ({ data, notify, onSaved }) {
  const [form, setForm] = useState({ ...data.values })
  const [saving, setSaving] = useState(false)
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))
  const save = async () => {
    setSaving(true)
    try {
      await api.saveSettings(form)
      await onSaved()
      notify('自动化规则已保存')
    } catch (error) { notify(error.message, 'error') } finally { setSaving(false) }
  }
  return <div className='page enter settings-page'>
    <section className='settings-intro'>
      <span className='section-number'>SYSTEM / AUTOMATION</span>
      <h2>设定节奏，<br />再交给系统执行。</h2>
      <p>自动任务只读取已启用的平台与已验证的浏览器账号。</p>
    </section>
    <section className='settings-section'>
      <header><span>01</span><div><h3>内容同步</h3><p>按间隔从 Notion 拉取待发布内容。</p></div></header>
      <div className='settings-content'>
        <label className='field'><span>同步间隔（分钟）</span><input type='number' min='1' value={form.notion_sync_interval_minutes} onChange={event => set('notion_sync_interval_minutes', Number(event.target.value))} /></label>
        <label className='toggle'><input type='checkbox' checked={form.notion_sync_enabled} onChange={event => set('notion_sync_enabled', event.target.checked)} /><span><b>自动同步 Notion</b><small>按设定间隔拉取新内容。</small></span></label>
      </div>
    </section>
    <section className='settings-section'>
      <header><span>02</span><div><h3>自动发布</h3><p>只处理发布方式为“自动”且状态为“待发布”的稿件。</p></div></header>
      <div className='settings-content'>
        <div className='settings-grid compact-grid'>
          <label className='field'><span>检查间隔（分钟）</span><input type='number' min='1' value={form.auto_publish_interval_minutes} onChange={event => set('auto_publish_interval_minutes', Number(event.target.value))} /></label>
          <label className='field'><span>新同步稿件默认方式</span><select value={form.default_publish_mode} onChange={event => set('default_publish_mode', event.target.value)}><option value='manual'>手动发布</option><option value='automatic'>自动发布</option></select></label>
        </div>
        <label className='toggle'><input type='checkbox' checked={form.auto_publish_enabled} onChange={event => set('auto_publish_enabled', event.target.checked)} /><span><b>启用自动发布</b><small>建议先手动验证每个平台的草稿结果。</small></span></label>
      </div>
    </section>
    <div className='save-bar'><div><b>自动化规则仅在当前设备生效</b><span>修改后在下一轮调度中生效。</span></div><button className='button vermilion' disabled={saving} onClick={save}>{saving ? '正在保存…' : '保存自动化规则'}</button></div>
  </div>
}