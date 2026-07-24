# 墨舟 · 内容发布台

一个本地运行的内容同步与多平台发布系统。

当前支持：

- 从 Notion 手动或自动同步待发布内容
- 使用可配置 AI 自动提取标签、生成摘要和平台专用版本
- 在内容库中创建、编辑和管理文章、视频、图文稿件
- 上传本地图片或视频素材，并为平台选择发布账号
- 每个平台可单独选择“保存草稿”或“直接发布”
- 手动或自动提交到微信公众号（默认保存草稿）
- 分平台记录发布结果和错误
- 在管理界面配置 Notion、公众号、代理和自动化间隔
- 使用 Patchright + 独立浏览器会话发布小红书视频/图文，以及
  Bilibili、视频号、抖音视频
- CSDN 已预留独立发布适配器，发布实现待后续接入

## 架构

```text
Notion ──> 同步服务 ──> AI 编辑加工 ──> SQLite 内容库 ──> 发布调度
                                                     ├── 微信公众号（已实现）
                                                     ├── 小红书（Patchright 浏览器发布）
                                                     ├── 抖音（Patchright 视频发布）
                                                     ├── 视频号（Patchright 视频发布）
                                                     ├── Bilibili（Patchright 视频发布）
                                                     └── CSDN（适配器占位）

React 管理界面 <── HTTP API ──> FastAPI 后端
```

后端采用模块化结构：

```text
backend/
├── app.py                 # HTTP API 和前端静态文件服务
├── ai_service.py          # OpenAI-compatible 内容加工
├── accounts.py            # 平台账号和浏览器会话目录
├── browser.py             # Patchright 持久化浏览器
├── db.py                  # SQLite 数据模型
├── media.py               # 本地图片/视频素材上传
├── notion_client.py       # Notion 2026-03-11 API
├── services.py            # 同步、文章、发布业务逻辑
├── scheduler.py           # 自动同步和自动发布
├── settings.py            # 配置与敏感字段遮罩
└── platforms/
    ├── base.py            # 平台发布器统一接口
    ├── registry.py        # 平台注册表
    ├── browser_video.py   # 浏览器视频平台共享校验
    ├── wechat.py          # 微信公众号
    ├── xiaohongshu.py     # 小红书视频/图文浏览器发布
    ├── douyin.py          # 抖音视频浏览器发布
    ├── channels.py        # 视频号视频浏览器发布
    ├── bilibili.py        # Bilibili 视频浏览器发布
    └── csdn.py            # CSDN 占位
```

## 安装

要求：

- Python 3.10+
- Node.js 20+
- Google Chrome 或 Chromium 内核的 Microsoft Edge

```powershell
cd D:\jixn\notion_publish_article

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# 可选：本机没有 Chrome/Edge 时安装 Chrome
patchright install chrome

cd frontend
npm install
npm run build
cd ..
```

## 运行

```powershell
python main.py
```

然后访问：

```text
http://127.0.0.1:8021
```

第一次运行会创建 `data/publisher.db`。如果项目中存在旧版
`config.py`，系统会将其中的 Notion 和公众号配置迁移到本地数据库；
之后都可以在“连接与自动化”页面修改。

### 浏览器平台发布流程

1. 在“账号管理”选择小红书、抖音、视频号或 Bilibili，并添加账号。
2. 点击“打开浏览器登录”，在弹出的可见浏览器中完成扫码或平台验证。
   小红书登录或检查状态成功后，会同步昵称、账号 ID、头像、关注数、
   粉丝数和获赞收藏数；也可以在账号卡片点击“刷新资料”。
3. 在“连接与自动化”启用对应平台；如自动检测不到浏览器，填写
   `chrome.exe` 或 `msedge.exe` 的完整路径。
4. 新建稿件并上传素材：小红书支持图文和视频，其余三个平台首期只支持
   单视频直发。
5. Bilibili 发布前必须明确选择“自制/转载”并填写默认分区；转载稿件还要
   在稿件中填写来源 URL。
6. 先手动发布一条验证页面选择器和账号状态，再考虑开启自动发布。

每个账号使用独立的 `data/browser_profiles/<platform>/<account_id>` 浏览器
目录。系统不保存账号密码，也不会把 Cookie 返回给前端。浏览器自动化只
使用 Patchright 持久化上下文，不包含 Playwright 运行路径。平台页面更新后，
选择器仍可能需要调整；Patchright 也不能保证平台永远无法识别自动化，
请遵守各平台规则，不要规避验证码、频率限制或内容审核。

## Docker Compose 部署

项目已包含：

- `Dockerfile`：Node 构建前端 + Python 运行时的多阶段镜像
- `compose.yaml`：持久卷、健康检查和安全限制
- `.dockerignore`：排除密钥、开发依赖和本地数据
- `.env.docker.example`：端口配置示例

启动：

```powershell
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

默认访问地址：

```text
http://127.0.0.1:8000
```

修改宿主机端口：

```powershell
Copy-Item .env.docker.example .env
# 修改 .env 中的 APP_PORT
docker compose up -d
```

数据保存在 Docker 卷 `mozhou-publisher-data`。如果项目的 `data` 目录
已经存在 `publisher.db`，首次启动且 Docker 卷为空时会自动导入；卷内
已经有数据库时不会覆盖。

升级：

```powershell
git pull
docker compose up -d --build
```

停止和删除容器：

```powershell
docker compose down
```

上面的命令不会删除数据卷。只有明确不再需要数据时才能执行：

```powershell
docker compose down -v
```

### Docker 中的代理地址

容器里的 `127.0.0.1` 指向容器本身，不是宿主机。如果代理运行在宿主机
的 `7890` 端口，应在前端配置：

```text
http://host.docker.internal:7890
```

Compose 已配置 `host.docker.internal:host-gateway`，兼容 Docker Desktop
和现代 Linux Docker。

当前 Compose 默认将端口绑定到宿主机 `127.0.0.1`。系统尚未实现用户
登录，不要直接改成 `0.0.0.0` 暴露公网。正式绑定域名之前应增加认证、
HTTPS 和反向代理。

小红书首期依赖桌面环境中的可见浏览器，不建议在当前 Docker Compose
容器中运行；容器部署目前主要用于 Notion、AI 和公众号 API 发布。

## Notion 数据源要求

默认同步状态为“待发布”的页面。数据源需要包含以下字段：

| 字段 | Notion 类型 | 必填 |
| --- | --- | --- |
| 标题 | Title | 是 |
| 文章类型 | Select，值为“图文”或“图片” | 是 |
| 作者 | Select | 否 |
| 封面图片 | URL | 图文发布时是 |
| 阅读原文 | URL | 否 |
| 标签 | Multi-select | 否 |
| 状态 | Status | 是 |
| 唯一ID | Unique ID | 推荐；字段名可在前端修改 |

Notion Integration 需要具有读取内容和更新内容权限，并且目标数据库
必须共享给该 Integration。

### 前端字段映射

在“连接与自动化 → Notion 内容源 → 字段对应关系”中可以修改系统字段与
Notion 字段的对应关系，包括：

- 文章标题、文章类型和作者
- 封面图片、阅读原文和标签
- 同步状态和唯一标识
- Notion 中代表“图文”和“图片”的 Select 值
- 待同步状态和发布完成状态

填写 Token、Database ID 后点击“读取字段”，系统会读取实际 Data Source
Schema，并按照期望类型提供可选字段。例如文章标题只显示 `title` 类型，
封面图片只显示 `url` 类型。也可以不读取 Schema，直接手动填写字段名。

## 同步与图片去重

- 如果配置的 Notion 唯一字段存在，系统优先用它识别文章。
- 没有唯一字段时，使用 Notion 自带且稳定的 `page_id`。
- 同一来源再次同步只覆盖原记录，不会创建重复文章。
- 如果唯一字段和 `page_id` 命中不同文章，系统停止本次同步并保留旧数据，
  不会尝试新增。
- Markdown 正文图片和封面图会生成稳定素材键。URL 中过期时间、签名、
  Token 等临时参数不参与判断，图片处理参数会保留。
- 微信永久素材上传成功后保存 `media_id`。再次遇到相同图片时直接复用，
  不会重复上传到公众号素材库。

## 自动化规则

- 自动同步：按配置间隔，从 Notion 拉取“待发布”页面。
- AI 自动加工：同步后生成标签、摘要、人工确认事项和平台专用内容。
- 自动发布：只处理发布方式为“自动”且状态为“待发布”的稿件。
- 公众号默认保存到草稿箱；可以在单篇稿件中改为直接发布。
- 已发布平台和每次发布结果保存在本系统；只有全部平台直发成功后才将
  Notion 状态改为“已发布”。
- 发布时优先使用经过人工确认的对应平台 AI 版本。
- 新同步稿件的默认发布方式可以在前端配置。
- 建议先完成连接测试，并手动成功发布一篇稿件后再打开自动发布。

## AI 内容加工

在“连接与自动化 → AI 内容编辑”中配置兼容 OpenAI Chat Completions
协议的接口：

- API Base URL
- API Key
- 模型名称
- 可选代理
- 自定义编辑要求

AI 不会直接覆盖 Notion 原稿。生成结果包括标签、摘要、人工确认事项以及
公众号、小红书、CSDN 的独立版本。用户可以在稿件编辑器中修改生成内容，
或将某个平台版本应用到主稿。没有启用 AI 时，原有同步、编辑和发布流程
仍可正常使用。

## 代理

Notion 和微信公众号分别配置代理：

- 留空：直接连接，不读取系统代理。
- 填写 `http://127.0.0.1:7890`：仅该连接通过指定代理。

公众号后台的 IP 白名单必须包含微信请求的实际出口 IP。如果代理节点
会变化，不建议公众号请求使用该代理。

## 测试

```powershell
python -m unittest -v test_backend.py test_notion_utool.py
```

端到端测试使用 Patchright：

```powershell
pip install -r requirements-dev.txt
python main.py
# 另一个终端运行
python test_e2e.py
```

## 开发日志

后端默认使用 `DEBUG` 级别，同时输出到启动终端和
`data/backend.log`。日志文件达到 10 MB 后自动轮转，最多保留 5 份。

日志会记录 Notion 查询条件与命中数量、逐篇同步和去重结果、素材缓存、
AI 加工、自动发布筛选原因、各平台发布结果、HTTP 状态码和耗时。不会记录
Token、Secret、请求正文或完整文章正文，URL 中的签名参数也会遮罩。

可通过环境变量调整：

```powershell
$env:LOG_LEVEL = "INFO"       # 上线后建议 INFO 或 WARNING
$env:LOG_FILE = "data/app.log"
python main.py
```

Docker Compose 默认也是 `DEBUG`，部署时可在 `.env` 中设置：

```dotenv
LOG_LEVEL=INFO
```

## 安全说明

这是一个本地单用户工具，目前没有系统用户登录和权限控制。平台账号指
浏览器发布账号，不是本系统的多用户权限账号。敏感配置保存在本机
SQLite 中，API 返回时会遮罩 Token 和 Secret。请勿将服务直接暴露到公网；
若以后部署到服务器，需要先增加身份认证、HTTPS 和密钥加密。
