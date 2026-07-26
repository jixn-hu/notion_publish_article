# 墨舟内容发布台

墨舟是一个本地优先的内容生产、管理与多平台发布工作台。它将 Notion 同步、AI 辅助写作、Markdown 编辑、素材与资讯管理、浏览器账号会话和发布记录集中到一个 Web 界面中，适合个人创作者在自己的电脑上管理内容工作流。

> [!IMPORTANT]
> 项目当前是单用户本地工具，没有系统登录和权限隔离。请只绑定到本机地址，不要直接暴露到公网。浏览器自动化依赖平台页面结构，平台改版后可能需要更新。

## 主要功能

- **内容库**：统一管理文章、图文和视频稿件，保存标签、摘要、媒体、发布目标与结果。
- **Markdown 编辑器**：CodeMirror 编辑、实时预览、图片插入和平台内容版本管理。
- **AI 创作**：使用 OpenAI-compatible 接口生成文章、摘要、标签、平台版本和图文分镜；支持独立图片生成接口，生成图片保存到本地。
- **素材库**：管理图片、视频和卡片笔记，支持搜索、标签、稿件引用和批量 ZIP 下载。
- **资讯库**：从公开网页采集或手动录入资讯，保留来源信息，并作为 AI 生成的参考资料。
- **Notion 同步**：手动或定时同步待发布内容，可配置字段映射、状态和去重键。
- **账号管理**：每个平台账号使用独立浏览器目录，可检查登录状态、查看账号和同步资料。
- **代理管理**：集中维护代理并分配给账号，也可为 Notion、AI 等连接单独配置代理。
- **自动化**：设置同步、AI 加工和发布周期，记录每个平台的成功结果与失败原因。

## 平台能力

| 平台 | 内容类型 | 保存草稿 | 直接发布 | 实现方式 |
| --- | --- | ---: | ---: | --- |
| 微信公众号 | 图文文章 | 是 | 否 | Patchright 可见浏览器 |
| 小红书 | 图文、视频 | 否 | 是 | Patchright 可见浏览器 |
| CSDN | 图文文章 | 是 | 是 | Patchright 可见浏览器 |
| 抖音 | 单视频 | 否 | 是 | Patchright 可见浏览器 |
| 视频号 | 单视频 | 否 | 是 | Patchright 可见浏览器 |
| Bilibili | 单视频 | 否 | 是 | Patchright 可见浏览器 |

微信公众号目前只自动保存到草稿箱。正式发表需要管理员在微信侧扫码验证，项目不会尝试绕过该验证。CSDN 直发需要文章标签；Bilibili 需要配置分区和自制/转载类型，转载内容还需要来源 URL。

## 技术架构

```text
Notion ──> 同步与去重 ──┐
资讯库 ──> AI 参考 ─────┼──> SQLite 内容库 ──> 发布调度 ──> 平台浏览器
素材库 ──> 媒体与笔记 ──┘

React + Vite 管理界面 <── HTTP API ──> FastAPI 后端
                                          ├── Patchright 持久会话
                                          ├── OpenAI-compatible AI
                                          └── 本地文件与 SQLite
```

核心目录：

```text
backend/
├── app.py                 # FastAPI 路由与前端静态文件
├── services.py            # 内容、同步和发布业务
├── ai_service.py          # AI 文本加工
├── ai_generation.py       # AI 图片生成与本地保存
├── materials.py           # 素材库
├── news.py                # 资讯采集与资讯库
├── accounts.py            # 平台账号与资料
├── browser.py             # Patchright 持久浏览器
├── db.py                  # SQLite 数据结构
└── platforms/             # 各平台登录、检测与发布流程

frontend/src/
├── App.jsx                # 工作台、内容库与设置
├── MarkdownComposer.jsx   # Markdown 编辑与预览
├── Materials.jsx          # 素材库
├── News.jsx               # 资讯库
├── Accounts.jsx           # 账号管理
├── Proxies.jsx            # 代理管理
└── Automation.jsx         # 自动化设置
```

## 快速开始

### 环境要求

- Windows 10/11（桌面浏览器发布推荐）
- Python 3.10+
- Node.js 20+
- Google Chrome 或 Microsoft Edge

克隆项目后，在资源管理器中双击 `启动.cmd`，或在终端运行：

```powershell
git clone git@github.com:jixn-hu/notion_publish_article.git
cd notion_publish_article
.\启动.cmd
```

启动脚本会：

1. 在 `.venv` 不存在时创建 Python 虚拟环境并安装依赖；已存在则直接复用。
2. 在 `frontend/node_modules` 不存在时执行 `npm ci`。
3. 在前端未构建或源码比构建结果更新时自动执行 `npm run build`。
4. 启动 FastAPI，并由后端同时提供 API 和前端页面。

打开 <http://127.0.0.1:8021>。首次运行会创建 `data/publisher.db`；配置、浏览器会话、上传素材和日志都保存在 `data/`，该目录不会提交到 Git。

### 手动安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..

python main.py
```

如果系统没有可用的 Chrome/Edge，可运行 `patchright install chrome`。开发前端时使用 `npm run dev` 可获得热更新；正式页面仍由 `npm run build` 的结果提供。

## 初次配置

界面中的“设置”只管理连接和平台配置，“自动化”单独管理定时任务。

1. **AI**：填写兼容 Chat Completions 协议的 Base URL、API Key 和模型。图片模型可复用该密钥，也可配置独立的图片接口、模型与尺寸。
2. **Notion**：填写 Integration Token、Database ID，读取 Schema 后检查字段映射。
3. **浏览器平台**：启用需要的平台；自动识别失败时填写 Chrome/Edge 可执行文件路径。
4. **代理**：先在代理管理中新增并测试，再分配给对应账号；留空表示直连。
5. **账号**：新增平台账号，点击“打开浏览器登录”，等待系统确认后台账号信息。

每个账号的浏览器数据位于 `data/browser_profiles/<platform>/<account_id>`。系统不保存账号密码，也不会把 Cookie 返回给前端。删除该目录会同时丢失对应登录会话。

## 推荐工作流

1. 从 Notion 同步稿件，或直接在内容库创建文章、图文或视频。
2. 在资讯库采集公开资料，在素材库整理自己的图片、视频和卡片笔记。
3. 创建或 AI 生成稿件时选择参考资讯和素材，在 Markdown 编辑器中校对结果。
4. 选择目标平台、账号以及草稿/直发动作，先用一篇测试稿验证流程。
5. 确认账号、页面选择器和内容格式稳定后，再开启自动同步或自动发布。

AI 生成内容仅作为草稿。请核实事实、版权、引用和平台规则，不要将未经审核的内容直接自动发布。

## Notion 数据源

默认字段如下，名称和值都可在设置页修改：

| 字段 | Notion 类型 | 必填 |
| --- | --- | --- |
| 标题 | Title | 是 |
| 文章类型 | Select（默认值：图文/图片） | 是 |
| 作者 | Select | 否 |
| 封面图片 | URL | 视内容而定 |
| 阅读原文 | URL | 否 |
| 标签 | Multi-select | 否 |
| 状态 | Status | 是 |
| 唯一ID | Unique ID | 推荐 |

Notion Integration 必须有读取、更新权限，目标数据库也必须共享给该 Integration。系统优先使用配置的唯一字段去重，否则使用稳定的 `page_id`。旧版 `config.py` 存在时，首次启动会迁移其中的 Notion 和公众号配置；新安装无需创建该文件。

## 浏览器发布说明

- 登录、状态检查和发布都会打开真实浏览器，账号会话相互隔离。
- 系统只在检测到明确的账号后台元素和有效会话后标记账号可用。
- 图片上传、编辑器保存和发布结果都有等待与校验；成功后浏览器会短暂停留再关闭。
- 平台页面、风控策略和验证码可能随时变化。请遵守服务条款，不要规避验证、限流或审核。
- 自动发布前应先手动完成一次登录和测试发布。重要内容建议保存草稿后人工复核。

## Docker Compose

```powershell
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

默认访问 <http://127.0.0.1:8000>，数据保存在 Docker 卷 `mozhou-publisher-data`。可复制 `.env.docker.example` 为 `.env` 并修改 `APP_PORT`。

Docker 适合运行 API、内容管理、Notion 同步和 AI 功能。当前浏览器发布依赖可见桌面浏览器和本机持久会话，不建议在容器内使用。容器中的 `127.0.0.1` 指向容器自身；访问宿主机代理应使用 `http://host.docker.internal:7890`。

## 开发与测试

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_backend.py test_notion_utool.py
cd frontend
npm run build
```

端到端测试需要先启动应用，并确保本机存在测试脚本指定的浏览器：

```powershell
.\.venv\Scripts\python.exe test_e2e.py
```

后端日志默认写入 `data/backend.log`。可通过 `LOG_LEVEL` 和 `LOG_FILE` 调整：

```powershell
$env:LOG_LEVEL = "INFO"
$env:LOG_FILE = "data/app.log"
python main.py
```

`notion_utool.py`、`publish_gzh.py` 和 `config-example.py` 是早期兼容代码；当前 Web 工作台以 `backend/` 下的服务和浏览器发布器为主。修改旧脚本前请确认仍有兼容需求。

## 安全与隐私

- API Key、Token、Cookie、`data/`、`.env` 和浏览器资料目录都不应提交。
- 设置接口会遮罩敏感字段，但 SQLite 当前没有对本地密钥做静态加密，请保护电脑和备份。
- 资讯采集会拒绝本机和内网地址，以降低 SSRF 风险；仍应只采集有权使用的公开网页。
- 项目没有多用户鉴权。远程部署前必须增加身份认证、HTTPS、访问控制和密钥管理。
- 提交漏洞请阅读 [SECURITY.md](SECURITY.md)，不要在公开 Issue 中附带真实凭据或 Cookie。

## 参与贡献

欢迎提交问题和改进。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)；第三方项目声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证

本项目使用 [Apache License 2.0](LICENSE)。平台名称和商标归各自权利人所有，本项目与 Notion、微信、CSDN、小红书、抖音、视频号或 Bilibili 没有官方关联。
