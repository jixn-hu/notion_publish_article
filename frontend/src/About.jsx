import {
  BookOpen,
  Bug,
  ExternalLink,
  GitFork,
  Info,
  Scale,
  Tag
} from 'lucide-react'

const GITHUB_URL = 'https://github.com/jixn-hu/notion_publish_article'

export default function About ({ version }) {
  const links = [
    {
      label: '项目仓库',
      detail: 'SOURCE',
      href: GITHUB_URL,
      icon: GitFork
    },
    {
      label: '使用文档',
      detail: 'README',
      href: `${GITHUB_URL}#readme`,
      icon: BookOpen
    },
    {
      label: '问题反馈',
      detail: 'ISSUES',
      href: `${GITHUB_URL}/issues`,
      icon: Bug
    },
    {
      label: '版本发布',
      detail: 'RELEASES',
      href: `${GITHUB_URL}/releases`,
      icon: Tag
    }
  ]

  return (
    <div className='page about-page'>
      <section className='about-identity'>
        <span className='about-mark' aria-hidden='true'>墨</span>
        <div className='about-copy'>
          <span className='eyebrow'>MOFLOW · CONTENT DESK</span>
          <h2>墨流</h2>
          <p>本地优先的内容创作与多平台发布工作台</p>
        </div>
        <div className='about-version'>
          <span>当前版本</span>
          <strong>v{version}</strong>
          <small>LOCAL BUILD</small>
        </div>
      </section>

      <section className='about-project'>
        <header>
          <div>
            <span className='eyebrow'>PROJECT</span>
            <h3>项目链接</h3>
          </div>
          <a
            className='about-repository'
            href={GITHUB_URL}
            target='_blank'
            rel='noreferrer'
          >
            jixn-hu/notion_publish_article
            <ExternalLink size={15} aria-hidden='true' />
          </a>
        </header>

        <div className='about-links'>
          {links.map(item => {
            const Icon = item.icon
            return (
              <a
                className='about-link'
                href={item.href}
                target='_blank'
                rel='noreferrer'
                key={item.label}
              >
                <span className='about-link-icon'><Icon size={19} aria-hidden='true' /></span>
                <span>
                  <b>{item.label}</b>
                  <small>{item.detail}</small>
                </span>
                <ExternalLink size={16} aria-hidden='true' />
              </a>
            )
          })}
        </div>
      </section>

      <section className='about-meta'>
        <div>
          <Scale size={18} aria-hidden='true' />
          <span>开源许可</span>
          <strong>Apache License 2.0</strong>
        </div>
        <div>
          <Info size={18} aria-hidden='true' />
          <span>版本标识</span>
          <strong>MoFlow v{version}</strong>
        </div>
      </section>
    </div>
  )
}
