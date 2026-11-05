# 部署：本机 / ZeroTier 私有化 / 公网

三条路，同一套代码，区别只在 `.env` 和网络拓扑。

| 路径 | 适用 | 手机怎么连 | 成本 |
|---|---|---|---|
| **A 本机（开发验收）** | 现在这个阶段 | 同一 WiFi，App 填局域网 IP | 0 |
| **B ZeroTier 私有化** | 家里/机构一台常开机器 | 手机装 ZeroTier 加入同一网络 | 一台机器 |
| **C 公网（阿里云 ECS）** | 给不特定用户用 | 域名或公网 IP | 月费 |

---

## ⚠️ A 路（本机）的最大坑：IP 会变

实测同一天内开发机的 WLAN IP 变了三次：

```
10.60.114.113  →  10.60.124.153  →  10.60.119.229
```

每次变化，**已经装好的 APK 立刻连不上**（包里的地址是死的）。
这就是反复出现「连不上服务器，让家里人看一下」的真正原因，不是代码问题。

三条应对：

1. **App 里改地址**（最快）：我的 → 服务器地址 → 填新地址 → 测试连接 → 保存
2. **路由器里给这台机器绑定固定 IP**（DHCP 保留），一次性解决
3. **别用 A 路交付给老人** —— 用 B 或 C

### A 路操作

```powershell
# 1. 启动后端（脱离了终端，不会被回收）
wscript.exe E:\UI\.uni-shot\start-bilin.vbs

# 2. 把当前 IP 写进客户端配置
powershell -ExecutionPolicy Bypass -File server\deploy\zerotier\apply-address.ps1 `
    -Address http://<当前IP>:8000

# 3. 全链路验证（6 步：TCP → healthz → 登录 → 账号 → 会话 → 对话 → SSE）
python server\deploy\zerotier\verify.py http://<当前IP>:8000
```

---

## B 路：ZeroTier 私有化（推荐正式用）

### 为什么选它

- **不需要公网 IP、不开路由器端口、不买云服务器**
- 点对点加密，**数据不经过任何第三方云**
- 老人健康数据不出户，合规上最干净
- 家属装同一个客户端就能远程看到老人（不受 WiFi 限制）

### 前提

养成为：**服务器 + 每台要访问的手机，都加入同一个 ZeroTier 网络。**

ZeroTier 网络在你自己的账号里（my.zerotier.com），不依赖我们。

### 步骤

**① 建网络**（一次性，2 分钟）

```
my.zerotier.com → 注册/登录 → Create A Network
→ 记下 Network ID（16 位十六进制，如 8056c2e21c000001）
→ 网络详情里把 Access Control 设为 Private（默认就是）
```

**② 服务器上跑一键脚本**

Linux：
```bash
sudo bash server/deploy/zerotier/setup-linux.sh --network <NetworkID>
```

Windows（**管理员** PowerShell）：
```powershell
powershell -ExecutionPolicy Bypass -File server\deploy\zerotier\setup-windows.ps1 -Network <NetworkID>
```

**③ 去 zeroTier 控制台授权节点**

第一次跑脚本会停在"等待地址"，因为 ZeroTier 默认要手动授权：

```
my.zerotier.com → 你的网络 → Members
→ 勾选刚出现的节点（Auth）
→ 建议：给它设一个固定 IP（Managed IPs），否则重启后地址可能变
```

授权后重跑脚本，它会拿到 `10.x.x.x` 并继续部署。

**④ 手机关联**

```
手机装 ZeroTier（应用商店搜 ZeroTier One）→ Add Network → 填同一个 NetworkID
→ 回到 my.zerotier.com 把手机节点也勾上 Auth
```

**⑤ App 里填地址**

```
我的 → 服务器地址 → http://10.x.x.x:8000 → 测试连接 → 保存 → 登录
```

### 脚本做了什么（安全相关的重点）

| 动作 | 为什么 |
|---|---|
| 后端 `HOST` 绑到 ZeroTier 地址，**不是 0.0.0.0** | 公网/局域网都连不上，只有 ZeroTier 成员能连 |
| 防火墙只放行 ZeroTier 网段访问 8000 | 双保险 |
| 强制 `AUTH_MODE=required` + 生成随机 `API_TOKENS` | 接口里有老人健康档案，必须鉴权 |
| 用已有 `deploy.sh` 建用户/venv/systemd/迁数据 | 不重复造轮子 |

### 已知限制

- **我（开发方）连不进去**：本机没有管理员权限装 ZeroTier 服务，无法加入你的网络。所以排障时你需要把 `verify.py` 的输出贴给我。
- **手机必须装 ZeroTier**：老人自己不会装，得家属一次性配好。
- **ZeroTier 免费版限 25 个节点**：家庭/小型机构够用。

---

## C 路：公网（阿里云 ECS）

已备好，但**卡在安全组端口没放行**（22/80/443/8000 全不通，ping 也不通）。

需要你确认：

1. 实例状态还是「运行中」吗？
2. 公网 IP 还是 `121.196.160.179` 吗？（重启可能变）
3. 安全组「入方向」里是否真有一条 `TCP 8000` 且授权对象 `0.0.0.0/0`？
4. 用的是 ECS（安全组）还是轻量应用服务器（叫「防火墙」）？

放开后：

```bash
# 服务器上（Workbench 也行，不需要 22）
git clone --depth 1 https://github.com/Cangmo316/-ai.git /opt/bilin-src
tar -xzf /root/bilin-upload.tar.gz -C /opt/bilin-src/server/   # 含 .env + 数据
bash /opt/bilin-src/server/deploy/deploy.sh
```

上传包在 `E:\UI\.uni-shot\upload\bilin-upload.tar.gz`（0.43MB，含 292 账号 / 241 病例 / 密钥）。

---

## 通用：我拿到地址后怎么接手

给我一个地址，两条命令即可：

```powershell
# 写入客户端配置（会自动先探 /healthz，不通就不写）
powershell -ExecutionPolicy Bypass -File server\deploy\zerotier\apply-address.ps1 `
    -Address http://10.1.1.50:8000 -ApiToken <服务端 API_TOKENS>

# 全链路验证
python server\deploy\zerotier\verify.py http://10.1.1.50:8000 --token <API_TOKENS>
```

`apply-address.ps1` 会写三处（少写一处对应场景就回落到 127.0.0.1 必挂）：

| 文件 | 用途 |
|---|---|
| `.env.production` | App 打包时的默认地址 |
| `.env.production.local` | 打包时注入的接口 token（不进仓库） |
| `.env.development.local` | H5 预览 / 运行到手机 |

---

## 备份（私有化必做）

私有化没有异地容灾，机器坏了数据就没了。

```bash
# SQLite 必须用 .backup，不能 cp（WAL 里还有没落盘的数据）
bash server/deploy/backup.sh

# 挂进 crontab，每天 3:05
5 3 * * * bash /opt/bilin-src/server/deploy/backup.sh

# 再把备份同步到另一块盘/NAS
```

Windows 侧等价的思路：`schtasks` 定时 + 把 `C:\bilin\server\data` 复制到移动硬盘。
