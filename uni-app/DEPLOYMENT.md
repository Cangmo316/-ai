# 正式部署（让装到手机上的 App 真正能用）

## 为什么打包装到手机后连不上

**三个原因叠在一起，每一个都会导致失败。**

### ① App 里写的是 `127.0.0.1`，而手机上的 `127.0.0.1` 是手机自己

```
uni-app/api/config.js
export const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'
```

| 场景 | `127.0.0.1` 是谁 | 结果 |
|---|---|---|
| H5（浏览器在电脑上） | 你的电脑 | ✅ |
| App + 真机（插着 USB） | 手机自己 + `adb reverse` 转发 | ✅ |
| **打包后的 APK** | **手机自己，没有转发** | ❌ |

开发时那条 `adb reverse tcp:8000 tcp:8000` **只在 USB 调试连接时存在**，
打包安装后没有它。

### ② 后端只监听 `127.0.0.1`

```
server/app/config.py:139   host: str = "127.0.0.1"
server/.env                HOST=127.0.0.1
```

只监听回环地址 = **只接受本机访问**，同一 WiFi 下的手机也连不上。

### ③ Android 9+ 默认禁止明文 HTTP

后端是 `http://`，系统会直接掐断，报错 `net::ERR_CLEARTEXT_NOT_PERMITTED`。
（已在 `manifest.json` 开 `usesCleartextTraffic` 作为局域网联调兜底，
正式对外应当改用 HTTPS 并关掉它。）

---

## 部署步骤

### 第一步：后端上公网服务器

```bash
# 1. 代码放到服务器
git clone git@github.com:Cangmo316/-ai.git && cd -ai/server

# 2. 依赖
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 3. 配置 .env —— 关键三行
HOST=0.0.0.0                 # ← 必须，否则外部访问不到
PORT=8000
AUTH_MODE=required           # ← 正式对外必须开鉴权
API_TOKENS=<一串随机 token>
CORS_ORIGINS=https://你的域名  # ← 别留 *

# 4. 起服务（建议用 systemd 常驻，不要 nohup）
.venv/bin/python run.py
```

⚠️ **`server/data/` 是运行数据**（`bilin.db` 账号与聊天记录、
`llm_overrides.json` 模型配置）。迁移时要单独拷，别只拷代码。

### 第二步：域名 + HTTPS

```bash
# Caddy 最省事：自动申请并续期证书
apt install caddy
# /etc/caddy/Caddyfile
#   api.你的域名 {
#       reverse_proxy 127.0.0.1:8000
#   }
```

用 HTTPS 的两个理由：
1. Android 9+ 对明文 HTTP 的限制（上面 ③）
2. **健康数据与聊天记录不该走明文** —— 这是给老人用的产品

### 第三步：告诉 App 新地址

**只改一个文件，不动源码**：

```
uni-app/.env.production
VITE_API_BASE_URL=https://api.你的域名
```

这个值由 Vite 在**构建时注入**，优先级：

```
运行期覆盖（setBaseURL） → 构建期注入（.env.production） → 源码默认值
```

已实测：构建产物里确实是
`String("https://api.example.com").trim().replace(...) || "http://127.0.0.1:8000"`，
注入生效、兜底保留。

### 第四步：打包

```
HBuilderX\cli.exe pack \
  --project "E:\比邻AI\uni-app" \
  --platform android \
  --config "E:\比邻AI\uni-app\pack-configure.json" \
  --safemode true --isconfusion true
```

产物装到手机上，**在任何网络下都能登录使用**（因为指向的是公网域名）。

---

## 还需要补的一块：App 里没有改服务器地址的入口

`setBaseURL()` 这个函数**已经存在但没有任何页面调用它**。

这本身不算 bug（正式版的地址由 `.env.production` 定死，用户不该也不能改），
但有两个现实问题：

1. **现场排查**：服务器换了地址，得重新打包才能改
2. **局域网测试**：想插着手机连开发机试，也只能重新打包

如果要做，建议放在「我的 → 智能体设置」下面加一栏「服务器地址」，
或者用连点版本号 7 次的隐藏入口。**这是个产品决定，等确认后再动。**

---

## 自检清单

打包前逐条确认：

- [ ] `server/.env` 的 `HOST=0.0.0.0`
- [ ] `AUTH_MODE=required` + `API_TOKENS` 已配（对外必须开鉴权）
- [ ] 域名已解析、HTTPS 证书已生效（`curl https://api.你的域名/healthz`）
- [ ] `.env.production` 的 `VITE_API_BASE_URL` 指向 https 域名
- [ ] `manifest.json` 的 `appid` 已填（当前 `__UNI__193904D`）
- [ ] `pack-configure.json` 的 `appid` 与上面一致（**当前还是占位符，容易漏**）
- [ ] 签名证书已备份（`E:\比邻AI-签名\bilin.keystore`，丢了就无法更新已上架应用）
- [ ] `static/avatar/QDoctor_hires.glb` 已移出（306MB，代码不引用但会被打进包）
