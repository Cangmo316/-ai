# 运维手册（部署之后怎么过日子）

面向已经部署好的机器。按"出事了先看哪一节"来组织。

---

## 一、日常巡检（每周 1 分钟）

```bash
# 1. 服务活着
systemctl is-active bilin-api        # 期望 active

# 2. 接口正常（healthz 免鉴权，探针用）
curl -s http://127.0.0.1:8000/healthz

# 3. 磁盘没满（SQLite + 病例图片会慢慢涨）
df -h /opt/bilin

# 4. 备份最近一份是新的
ls -lt /opt/bilin/backup/ | head -3

# 5. ZeroTier 还在线（私有化部署才需要）
zerotier-cli listnetworks
```

Windows 等价：
```powershell
Get-Service ZeroTierOneService | Select-Object Status
Get-Content C:\bilin\server.log -Tail 20
schtasks /query /tn BilinAPI /v /fo LIST
Get-ChildItem C:\bilin\backup\ | Sort-Object LastWriteTime -Descending | Select-Object -First 3
```

---

## 二、升级

```bash
cd /opt/bilin-src
git fetch --depth 1 origin main && git reset --hard origin/main
sudo bash server/deploy/deploy.sh        # 幂等：只更新代码与依赖，不动数据
sudo systemctl restart bilin-api
curl -s http://127.0.0.1:8000/healthz
```

Docker：
```bash
git pull && docker compose up -d --build
```

**升级前先备份**（`server/deploy/backup.sh`）。数据库迁移是向前兼容的，
但机器坏了没备份就真没了。

---

## 三、回滚

```bash
cd /opt/bilin-src
git log --oneline -10                    # 找到要回的上一个提交
git reset --hard <commit>
sudo bash server/deploy/deploy.sh
sudo systemctl restart bilin-api
```

Docker：
```bash
docker compose down
docker tag bilin-api:latest bilin-api:broken   # 留证据
docker compose up -d --build                   # 用回滚后的代码重建
```

**注意**：回滚代码**不会**回滚数据库。如果新版本写过新表/新字段，
旧版本可能读不了 —— 所以升级前的备份是回滚的前提。

---

## 四、排障：按现象查

### 现象 1：App 报「连不上服务器（http://…）」

这句话现在带地址了，先看地址对不对。

| 检查 | 做法 |
|---|---|
| 地址可达吗 | 用**手机浏览器**打开 `http://地址:8000/healthz`，能出 `{"ok":true}` 就通 |
| 服务在跑吗 | `systemctl is-active bilin-api` |
| 监听地址对吗 | `ss -lntp \| grep 8000`，私有化部署应该是 ZeroTier 的 `10.x.x.x`，**不是 0.0.0.0** |
| ZeroTier 在线吗 | `zerotier-cli listnetworks`，看到 `OK` 才是通的 |

### 现象 2：能登录，但进去什么都没有 / 全站 401

这是**双 token 没配齐**。服务端开了 `AUTH_MODE=required` 时，客户端必须同时带：

```
X-API-Token: <服务端 /etc/bilin/bilin.env 的 API_TOKENS>
Authorization: Bearer <登录拿到的会话 token>
```

自检：
```bash
# 不带 token 应该 401
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/v1/conversations

# 带静态 token 应该 200（或 401 提示要登录，取决于端点）
curl -s -H "X-API-Token: $TOKEN" http://127.0.0.1:8000/v1/accounts/login ...
```

客户端 token 在打包时由 `VITE_API_TOKEN` 注入（放 `uni-app/.env.production.local`）。
**改地址时容易把它抹掉** —— `apply-address.ps1` 已做保留处理，但手工改要小心。

### 现象 3：能对话，但 AI 一直不回话（流式卡住）

SSE 被中间层缓冲了。逐个排除：

```bash
# 直连后端，确认流式本身没问题
curl -N -X POST http://127.0.0.1:8000/v1/chat/stream \
  -H 'Content-Type: application/json' -d '{"text":"你好"}'

# 如果直连正常、经代理不正常 → 代理在缓冲
```

`nginx-bilin.conf` 里必须有：
```nginx
proxy_buffering off;
proxy_cache off;
gzip off;
proxy_read_timeout 300s;
```
Caddy 用 `flush_interval -1` + `read_timeout 300s`。

Cloudflare 隧道一般不会缓冲，但企业代理/负载均衡可能会。

### 现象 4：能对话，但听不到声音

| 可能 | 检查 |
|---|---|
| TTS 没就绪 | `curl -s http://127.0.0.1:8000/v1/voice/capabilities` 看 `ttsReady` |
| 云端 TTS 没 key | `.env` 里 `DASHSCOPE_API_KEY` |
| 本地 TTS 命令错 | 手动跑一次 `BILIN_TTS_CMD` 里的命令，看报错 |
| 音频路径错位 | 用 Docker 桥接网络时会出现，已改用 host 网络规避 |

### 现象 5：登录很慢 / 对话很慢

| 环节 | 判断 |
|---|---|
| 模型慢 | 本地模型纯 CPU 约 4–8 字/秒；GPU 30–50 字/秒 |
| 网络慢 | `curl -w '%{time_total}'` 打 healthz 看基础延迟 |
| 数据库变大 | `ls -lh data/bilin.db`，超过几百 MB 要考虑归档旧消息 |

---

## 五、日志

```bash
sudo journalctl -u bilin-api -n 100 --no-pager      # 最近 100 行
sudo journalctl -u bilin-api -f                     # 实时
sudo journalctl -u bilin-api --since '1 hour ago' | grep -i error
```

Windows：
```powershell
Get-Content C:\bilin\server.log -Tail 100
Get-Content C:\bilin\server.err -Tail 50
```

日志里有用的信号：
- `鉴权失败：path=... ip=...` → 有人带错 token，或客户端没配
- 每请求一行 `GET /v1/... 200` → 看流量是否异常
- `⚠️ 接口未鉴权` → **危险**，`AUTH_MODE` 没生效，立刻查

---

## 六、备份与恢复

备份见 `README.md` 的「备份」一节。恢复：

```bash
sudo systemctl stop bilin-api
cd /opt/bilin/server
sudo cp data/bilin.db data/bilin.db.broken          # 留证据
sudo tar/uzip 解出的 bilin.db → data/bilin.db
sudo chown bilin:bilin data/bilin.db
sudo systemctl start bilin-api
curl -s http://127.0.0.1:8000/healthz
```

**验证恢复成功**：登录一次、看会话列表、发一条消息。
只看 healthz 不够 —— 它不查数据库。

---

## 七、换机器（迁移）

```bash
# 旧机器：打一键包（含 .env + 数据快照 + 全部脚本）
python server/deploy/build-bundle.py --out /tmp/dist --token <现有 token>

# 传到新机器，然后一条命令
sudo bash install.sh --network <ZeroTier 网络ID>   # 或省略 --network 走普通部署
```

**token 要沿用旧的**（`--token`），否则手机端还要改配置。

---

## 八、安全检查清单（对外提供服务前）

- [ ] `AUTH_MODE=required` 且 `API_TOKENS` 已配
- [ ] `HOST` 不是 `0.0.0.0`（除非前面有代理且防火墙收紧）
- [ ] HTTPS（域名 + Let's Encrypt），或只走 ZeroTier 内网
- [ ] `chmod 600 /etc/bilin/bilin.env`
- [ ] 备份已挂定时任务，且**验证过能恢复**
- [ ] 日志轮转已配（否则日志能把盘写满）
- [ ] 隐私政策与用户授权到位（老人健康数据属敏感个人信息）

---

## 九、已知的未验证项（不要当成已保证）

| 项 | 状态 |
|---|---|
| `backup.ps1` | ✅ 实测通过（integrity=ok / 294 账号 / 261 病例） |
| `backup.sh` | ⚠️ 未在本机实测（开发机没有 bash），逻辑与 ps1 对齐 |
| `Dockerfile` / `compose` | ⚠️ 本机无 Docker，未构建验证 |
| `setup-linux.sh` / `setup-windows.ps1` | ⚠️ 未在真实 ZeroTier 网络跑过（开发机无管理员权限装 ZT 服务） |
| `serve_local_model.py` | ✅ 实测通过（产品全链路跑在本地模型上） |
| GGUF 量化导出 | ❌ 未完成：本机下载不到 llama.cpp 二进制，已用本地推理服务替代 |

首次使用这几项时按各自文档里的"注意"逐条确认。
