# 微信公众号 API Nginx 中继

这套配置用于解决微信公众号官方 API 的 IP 白名单问题。

当运行墨流的电脑没有固定公网 IP 时，可以让 API 请求经过一台具有固定公网 IPv4 的服务器。微信看到的是服务器出口 IP，只需要把该 IP 加入公众号后台白名单。

## 推荐拓扑

~~~text
墨流
  |
  | http://127.0.0.1:8701/wechat
  v
本机 SSH 加密隧道
  |
  v
服务器 127.0.0.1:8701
  |
  v
Nginx -> https://api.weixin.qq.com
~~~

此方案有几个重要特点：

- 不需要域名。
- 服务器只需要开放 SSH 端口，8701 不暴露到公网。
- AppSecret、access_token 和媒体内容在公网段经过 SSH 加密。
- Nginx 不记录访问日志，避免凭据出现在日志中。
- 浏览器发布不经过此中继，只有公众号官方 API 请求会使用它。

## 准备条件

- 一台具有固定公网 IPv4 的 Linux 服务器。
- 服务器可以访问 https://api.weixin.qq.com:443。
- 服务器已安装 Nginx 和 CA 证书。
- 本地 Windows 已安装 OpenSSH Client。
- 已在墨流中创建微信公众号账号，并取得 AppID 和 AppSecret。

> [!IMPORTANT]
> 墨流是本地单用户应用。不要把墨流后端端口或此 Nginx 中继直接暴露到公网。本指南默认使用 SSH 隧道。

## 1. 安装 Nginx

Debian 或 Ubuntu：

~~~bash
sudo apt update
sudo apt install -y nginx ca-certificates
~~~

Rocky Linux、AlmaLinux 或 RHEL：

~~~bash
sudo dnf install -y nginx ca-certificates
sudo systemctl enable --now nginx
~~~

## 2. 上传配置

先在运行墨流的电脑执行：

~~~powershell
scp .\deploy\nginx\wechat-relay.conf root@服务器IP:/tmp/moflow-wechat-relay.conf
~~~

### Debian / Ubuntu

~~~bash
sudo install -m 0644 /tmp/moflow-wechat-relay.conf /etc/nginx/sites-available/moflow-wechat-relay
sudo ln -sfn /etc/nginx/sites-available/moflow-wechat-relay /etc/nginx/sites-enabled/moflow-wechat-relay
~~~

### 使用 conf.d 的系统

~~~bash
sudo install -m 0644 /tmp/moflow-wechat-relay.conf /etc/nginx/conf.d/moflow-wechat-relay.conf
~~~

只选择一种安装位置，不要同时放入 sites-enabled 和 conf.d。

配置默认监听：

~~~nginx
listen 127.0.0.1:8701;
~~~

这表示只能从服务器本机访问。SSH 会把本地端口安全地转发到这个地址，因此不需要在云服务器安全组中开放 8701。

### CA 证书路径

模板使用 Debian/Ubuntu 的证书路径：

~~~nginx
proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
~~~

在 Rocky Linux、AlmaLinux 或 RHEL 上通常需要改为：

~~~nginx
proxy_ssl_trusted_certificate /etc/pki/tls/certs/ca-bundle.crt;
~~~

可在服务器上执行以下命令确认文件存在：

~~~bash
ls -l /etc/ssl/certs/ca-certificates.crt
ls -l /etc/pki/tls/certs/ca-bundle.crt
~~~

## 3. 检查并加载配置

~~~bash
sudo nginx -t
sudo systemctl reload nginx
curl http://127.0.0.1:8701/health
~~~

健康检查应返回：

~~~json
{"status":"ok"}
~~~

如果 nginx -t 失败，先修正错误，不要跳过检查直接重启。

## 4. 配置微信 IP 白名单

在服务器上查询实际出口 IPv4：

~~~bash
curl -4 https://api.ipify.org
~~~

将返回的 IPv4 添加到微信公众号后台的 IP 白名单。应填写服务器的出口 IP，而不是家中电脑的公网 IP，也不是服务器内网 IP。

云服务器存在 NAT、共享出口或多出口网络时，实际出口 IP 可能与控制台显示不同，应以服务器请求外网时看到的地址为准。

## 5. 建立本地 SSH 隧道

项目提供了 Windows PowerShell 脚本：

~~~powershell
.\deploy\nginx\start-wechat-tunnel.ps1 -Server 服务器IP -User root
~~~

使用指定 SSH 私钥：

~~~powershell
.\deploy\nginx\start-wechat-tunnel.ps1 -Server 服务器IP -User ubuntu -IdentityFile "$HOME\.ssh\id_ed25519"
~~~

如果 PowerShell 阻止执行脚本，可以只对这一次调用放开：

~~~powershell
powershell -ExecutionPolicy Bypass -File .\deploy\nginx\start-wechat-tunnel.ps1 -Server 服务器IP -User ubuntu
~~~

也可以直接使用系统 SSH：

~~~powershell
ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 8701:127.0.0.1:8701 ubuntu@服务器IP
~~~

隧道窗口需要保持运行。按 Ctrl+C 会停止中继连接。

Linux 或 macOS 使用相同参数：

~~~bash
ssh -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -L 8701:127.0.0.1:8701 ubuntu@服务器IP
~~~

## 6. 验证本地隧道

新开一个终端执行：

~~~powershell
Invoke-RestMethod http://127.0.0.1:8701/health
~~~

应看到 status 为 ok。此检查成功表示：

1. 本地端口已监听。
2. SSH 隧道已连接。
3. 服务器 Nginx 已加载配置。

## 7. 在墨流中接入

1. 打开“账号管理”。
2. 新增或选择一个微信公众号账号。
3. 打开“API 与发布方式”设置。
4. 填写公众号 AppID 和 AppSecret。
5. 在“API 请求线路”选择“Nginx 中继”。
6. 中继地址填写 http://127.0.0.1:8701/wechat。
7. 保存后点击“测试 API 权限”。

中继地址只填写到 /wechat，不要手动添加 /cgi-bin。墨流会根据微信接口自动拼接后续路径。

选择“微信官网”时，墨流直接请求：

~~~text
https://api.weixin.qq.com/cgi-bin/
~~~

选择“Nginx 中继”时，墨流通过本地隧道请求：

~~~text
http://127.0.0.1:8701/wechat/cgi-bin/
~~~

每个公众号账号独立保存请求线路、AppID 和 AppSecret，账号之间不会相互覆盖。

## 使用其他本地端口

如果本机 8701 已被占用，可以改用其他本地端口，服务器端口无需变化：

~~~powershell
.\deploy\nginx\start-wechat-tunnel.ps1 -Server 服务器IP -User ubuntu -LocalPort 18701
~~~

墨流中的中继地址相应改为：

~~~text
http://127.0.0.1:18701/wechat
~~~

## Docker 场景

如果墨流运行在 Docker 中，而 SSH 隧道运行在 Windows 宿主机，容器内的 127.0.0.1 指向容器自身。中继地址应填写：

~~~text
http://host.docker.internal:8701/wechat
~~~

Linux Docker 需要为容器配置宿主机网关，例如 Compose 中加入：

~~~yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
~~~

## 常见问题

### 微信返回 40164 invalid ip

说明请求到达了微信，但微信看到的出口 IP 不在白名单中。

检查：

1. 墨流账号是否选择了“Nginx 中继”。
2. 本地 SSH 隧道是否仍在运行。
3. 微信白名单是否填写了服务器实际出口 IPv4。
4. 服务器是否经过额外 NAT 或代理。

### 本地访问 8701 显示连接失败

检查隧道窗口是否退出，并在服务器执行：

~~~bash
sudo ss -lntp | grep 8701
curl http://127.0.0.1:8701/health
~~~

### Nginx 返回 502 Bad Gateway

检查服务器 DNS、系统时间、CA 证书路径和到微信 443 端口的出站连接：

~~~bash
curl -I https://api.weixin.qq.com
sudo tail -n 50 /var/log/nginx/moflow-wechat-relay-error.log
~~~

### 返回 404 Not Found

墨流中的地址必须包含 /wechat：

~~~text
http://127.0.0.1:8701/wechat
~~~

不要只填写 http://127.0.0.1:8701。

### SSH 提示本地端口已被占用

指定其他本地端口：

~~~powershell
.\deploy\nginx\start-wechat-tunnel.ps1 -Server 服务器IP -User ubuntu -LocalPort 18701
~~~

然后同步修改墨流账号的中继地址。

### API 凭据有效但没有直接发布权限

这是公众号接口权限问题，与 Nginx 无关。墨流会根据接口检查结果区分草稿权限和直接发布权限；没有发布权限时只能选择保存草稿。

## 安全说明

- 不要把服务器 8701 端口开放到公网。
- 不要开启此中继的访问日志或 Nginx debug 日志。
- 不要把真实 AppID、AppSecret、access_token、SSH 私钥写入仓库。
- SSH 建议使用密钥登录，并禁用服务器密码登录。
- 定期更新 Nginx、OpenSSH 和系统 CA 证书。
- 此中继仅固定转发到微信官方 API，不应改造成通用开放代理。
- 若必须让多台设备接入，优先使用 WireGuard、Tailscale 等私有网络，再限制 Nginx 监听地址和来源网段。

直接使用公网 IP 加 HTTP 访问会让凭据和 token 以明文经过公网，不应使用。需要公网直连时，应配置可信 HTTPS、访问控制和独立鉴权；当前模板不提供不安全的公网监听示例。
