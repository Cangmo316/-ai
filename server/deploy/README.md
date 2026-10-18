# 比邻AI 后端部署

## 一句话

服务器上执行 **一条命令**装好后端，再 **一条命令**配 HTTPS，然后把域名填进 App 重新打包。

```bash
sudo bash server/deploy/deploy.sh                        # 装后端
sudo bash server/deploy/setup-proxy.sh api.你的域名 caddy  # 配 HTTPS
```

---

## 前提：你需要什么

| 项 | 说明 | 大概成本 |
|---|---|---|
| **一台 Linux 服务器** | Ubuntu 22.04 / 24.04；1 核 2G 就够（后端很轻） | ¥60–100/月 |
| **一个域名** | 用于 HTTPS。没有域名就只能用 IP + 自签证书 | ¥30–60/年 |
| **域名解析** | A 记录指向服务器公网 IP | — |

> **国内服务器要备案**（7–20 天）。急用可以先选香港/新加坡节点，免备案但延迟略高。
> 老人端在国内，**建议国内节点 + 走备案流程**，体验差别明显。

---

## 第一步：装后端

把仓库传到服务器（或 `git clone`），在**仓库根目录**执行：

```bash
sudo bash server/deploy/deploy.sh
```

它会做这些事，每一步都有日志：

1. 检查 Python ≥ 3.11、是否 root、目录对不对
2. 装系统依赖（python3-venv、build-essential、curl）
3. 建系统用户 `bilin`（**不可登录**，最小权限）
4. 代码 → `/opt/bilin`，建 venv，装 `requirements.txt`
5. **迁移已有数据**（账号、聊天记录、病例文件）—— 目标是空的才迁，**绝不覆盖线上数据**
6. 生成 `/etc/bilin/bilin.env`（权限 `600`），并强制 `HOST=127.0.0.1`
7. 装 systemd 服务并启动
8. 自检 `/healthz`

### 装完必须做的一件事

```bash
sudo nano /etc/bilin/bilin.env
```

填好这两个密钥（否则 AI 对话和语音不可用）：

```
LLM_API_KEY=（在这里粘贴你的 DeepSeek 密钥）
DASHSCOPE_API_KEY=（在这里粘贴你的阿里云密钥）
```

顺便**收紧 CORS**（默认是 `*`，正式环境不该放开）：

```
CORS_ORIGINS=https://你的域名
```

改完重启：

```bash
sudo systemctl restart bilin-api
```

---

## 第二步：配 HTTPS

先把域名的 A 记录指向服务器公网 IP，**确认解析生效**（`ping api.你的域名` 能看到你的 IP），然后：

```bash
sudo bash server/deploy/setup-proxy.sh api.你的域名 caddy
```

脚本会检查解析、放行 80/443、装 Caddy（自动申请并续期证书）、启动、验收 `/healthz`。

### Nginx 还是 Caddy？

| | Caddy | Nginx |
|---|---|---|
| 证书 | **自动**申请+续期，零配置 | 需要 certbot + 续期钩子 |
| 配置量 | 十几行 | 六十多行 |
| 适合 | **没有既有站点**（推荐） | 服务器上已经有别的站点在跑 |

用 Nginx：

```bash
sudo bash server/deploy/setup-proxy.sh api.你的域名 nginx
```

> 脚本里有个**关键顺序**：先只上 HTTP 配置 → certbot 签证书 → 再换成完整 HTTPS 配置。
> 反过来做会因为证书文件还不存在导致 `nginx -t` 失败。这个顺序是踩过才这么写的。

---

## 第三步：把域名填进 App

```
编辑 uni-app/.env.production
VITE_API_BASE_URL=https://api.你的域名
```

然后重新打包（HBuilderX → 发行 → 原生App-云打包）。装到手机上，**在任何网络下都能用**。

---

## ⚠️ SSE 流式回复：最容易出问题的地方

聊天回复走的是 **server-sent events**（`/v1/chat/stream`）。
Nginx / Caddy 默认都会**把后端一小段一小段的输出攒起来再一次性发**，结果是：

> AI 憋很久不吭声 → 突然整段话蹦出来

流式效果完全失效。所以两份反代配置里都对 `/v1/chat/stream` 做了特殊处理：

```nginx
# Nginx
location = /v1/chat/stream {
    proxy_buffering off;        # 不攒包
    proxy_read_timeout 300s;    # 老人思考慢，别中途断
    proxy_set_header X-Accel-Buffering no;
    gzip off;                   # 压缩会把数据留在缓冲区
}
```

```
# Caddy
flush_interval -1               # 立刻 flush
read_timeout 300s
```

**如果部署后发现"回复不是逐字出现"，先查这里。**

---

## 日常运维

```bash
# 状态 / 日志
systemctl status bilin-api
journalctl -u bilin-api -f

# 重启（改了 .env 之后必须重启）
sudo systemctl restart bilin-api

# 看后端自己报的健康状态
curl -s https://api.你的域名/healthz | python3 -m json.tool
```

### 备份

```bash
sudo bash server/deploy/backup.sh
```

默认备份到 `/var/backups/bilin/<时间戳>/`，保留 14 天，内容：

- `bilin.db` —— **用 `sqlite3 .backup` 在线备份**（不能直接 `cp`！SQLite 写入中直接拷文件会得到损坏的库），并立即跑 `PRAGMA integrity_check` 验证
- `llm_overrides.json` —— 模型配置（含明文密钥，权限 600）
- `case_files.tar.gz` —— 病例文件
- `bilin.env` —— 服务配置（含密钥，权限 600）

加个定时任务：

```bash
sudo crontab -e
# 每天凌晨 3 点
0 3 * * * bash /opt/bilin/server/deploy/backup.sh >/var/log/bilin-backup.log 2>&1
```

> **备份里含明文 API KEY 和老人健康数据。**
> 要定期拷到别的机器（本机备份救不了硬盘损坏），
> 但**不要**放进公开网盘或代码仓库。

---

## 部署后自检清单

- [ ] `systemctl status bilin-api` → active (running)
- [ ] `curl https://api.你的域名/healthz` → 返回 JSON 且 `ok: true`
- [ ] `/etc/bilin/bilin.env` 里 `HOST=127.0.0.1`（后端不直接暴露公网）
- [ ] `LLM_API_KEY` / `DASHSCOPE_API_KEY` 已填
- [ ] `CORS_ORIGINS` 已收紧成自己的域名，不再是 `*`
- [ ] `chmod 600 /etc/bilin/bilin.env` 且属主 root
- [ ] 服务器防火墙 / 云厂商安全组只放行 22、80、443（**不要**放行 8000）
- [ ] 备份脚本能跑通，且生成的 `bilin.db` 通过 `integrity_check`
- [ ] **聊天回复是逐字出现的**（不是整段蹦出来）→ 验证 SSE 没被代理缓冲
- [ ] App 重新打包过，`.env.production` 指向 https 域名

---

## 出问题时按这个顺序查

| 现象 | 先查什么 |
|---|---|
| 整个站点打不开 | `systemctl status caddy`（或 nginx）→ 反代在不在 |
| 502 Bad Gateway | `systemctl status bilin-api` → 后端在不在 |
| 后端起不来 | `journalctl -u bilin-api -n 50` → 多半是 `.env` 有错或端口被占 |
| 数据"清空了" | 查 `WorkingDirectory` 是否是 `/opt/bilin/server`（`.env` 里 `DATABASE_URL` 是**相对路径**，工作目录错了数据库会建到别处） |
| 证书签不下来 | `dig api.你的域名` 看解析；`curl -I http://api.你的域名/.well-known/acme-challenge/test` 看 80 端口是否可达 |
| 回复整段蹦出 | 反代没对 `/v1/chat/stream` 关缓冲（见上面 SSE 那节） |
| App 连不上 | `.env.production` 是不是还指向 `127.0.0.1` / 局域网 IP；打包后有没有重新安装 |

---

## 文件说明

```
server/deploy/
├── deploy.sh              一键部署后端
├── setup-proxy.sh         配 HTTPS（nginx 或 caddy）
├── backup.sh              备份（SQLite 安全备份 + 校验）
├── bilin-api.service      systemd 单元
├── nginx-bilin.conf       Nginx 配置（含 SSE 特殊处理）
└── Caddyfile              Caddy 配置（含 SSE 特殊处理）
```
