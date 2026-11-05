# 部署到学院服务器（Docker 路线）

给学校机房/实验室服务器用的最短路径。适用于：**你有 sudo、但机房不允许随便装系统包**。

---

## 为什么用 Docker 而不是直接跑

| 顾虑 | 容器怎么解决 |
|---|---|
| 机房不让乱装 Python 包、怕污染系统环境 | 容器内自带 Python 3.12 与全部依赖 |
| 升级要回滚 | 换镜像 tag 即可，`docker compose up -d` 秒回滚 |
| 需要交代"跑了什么服务、占多少端口" | 一个 compose 文件说清楚 |
| 与别的项目抢依赖版本 | 完全隔离 |

---

## 前置条件（给对方 IT 的清单）

| 项 | 要求 | 说明 |
|---|---|---|
| 操作系统 | 任意 Linux（x86_64） | 已在 Docker 镜像里锁定 Python 3.12 |
| Docker | 20.10+ / Compose v2 | `docker compose` 子命令形式 |
| 内存 | **≥ 1GB**（2GB 更稳） | 进程本身约 200MB，SQLite 很轻 |
| 磁盘 | **≥ 2GB** | 代码 3MB + 依赖 ~150MB + 数据（病例图片会慢慢涨） |
| CPU | 1 核可用即可 | 模型在外部 API，服务器不吃算力 |
| 出站网络 | 需能访问 `api.deepseek.com`、`dashscope.aliyuncs.com` | 对话/语音都是外呼；若机房禁止外网，见下方「完全离线」 |
| 入站端口 | 一个 TCP 端口（默认 8000） | 只对校内网/ZeroTier 网段开放，**不要对公网开** |

---

## 部署步骤

```bash
# 1. 拿代码
git clone --depth 1 https://github.com/Cangmo316/-ai.git /opt/bilin
cd /opt/bilin/server

# 2. 准备配置（这一步必须做，否则没有密钥、也谈不上鉴权）
cp .env.example .env
vi .env
```

`.env` 至少要填/确认这几项：

```bash
# 模型（DeepSeek）
LLM_PROVIDER=openai_compat
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxxx            # 必填
LLM_MODEL=deepseek-chat

# 语音（可选，走阿里云）
DASHSCOPE_API_KEY=sk-xxxx
BILIN_TTS_PROVIDER=qwen
BILIN_ASR_PROVIDER=qwen

# 服务
HOST=0.0.0.0                   # 容器内必须 0.0.0.0，对外由防火墙控制
PORT=8000
DATABASE_URL=sqlite:///data/bilin.db

# 鉴权（**公网/校园网必须开**）
AUTH_MODE=required
API_TOKENS=<openssl rand -hex 32 生成>
```

```bash
# 3. 起服务
docker compose up -d --build

# 4. 验证
docker compose ps                       # 状态应为 healthy
curl -s http://127.0.0.1:8000/healthz   # {"ok":true,...}
docker compose logs -f --tail=50
```

```bash
# 5. 数据从现有机器迁过来（可选）
#    SQLite 必须用 .backup 导出，不能 cp（WAL 里还有没落盘的数据）
#    本机： python -c "import sqlite3;s=sqlite3.connect('data/bilin.db');t=sqlite3.connect('bilin-copy.db');s.backup(t)"
scp bilin-copy.db  user@学院服务器:/opt/bilin/server/data/bilin.db
scp -r case_files  user@学院服务器:/opt/bilin/server/case_files
```

---

## 只让校内网/ZeroTier 能访问

容器用 host 网络（原因见 `docker-compose.yml` 注释），所以访问控制靠**宿主机防火墙**：

```bash
# 只放行校内网段（按学校实际网段改）
sudo ufw allow from 10.0.0.0/8 to any port 8000 proto tcp
# 或者只放 ZeroTier 网段
sudo ufw allow from 10.1.1.0/24 to any port 8000 proto tcp
sudo ufw deny 8000/tcp
```

`docker-compose.yml` 里 `HOST=0.0.0.0` **不等于对公网开放** —— 公网能不能进来由防火墙决定。
但如果你不想有任何依赖防火墙的侥幸，可以把 compose 里的 `HOST` 改成服务器的内网 IP。

---

## 完全离线（不连任何外部 API）

如果机房不许出网，就必须换成本地模型，三件事：

1. **对话**：本机起 Ollama，导入我们微调好的模型
   ```bash
   # 在开发机上导出（见 ml/scripts/merge_and_export.py）
   # 把 gguf 与 Modelfile 拷到服务器
   ollama create bilin-qwen -f Modelfile
   ```
   `.env` 改为：
   ```bash
   LLM_PROVIDER=openai_compat
   LLM_BASE_URL=http://127.0.0.1:11434/v1
   LLM_MODEL=bilin-qwen
   LLM_API_KEY=ollama
   ```
2. **语音**：`BILIN_ASR_PROVIDER=command` + whisper.cpp、`BILIN_TTS_PROVIDER=command` + Piper
3. **视觉**（拍照识药/病例 OCR）：**会自动降级**为不可用（`NullVisionProvider`），病例改为手动录入

⚠️ 需要注意：1.5B 模型实测在 8 条高危医疗场景中漏了 4 条就医建议，
所以离线模式下**医疗安全完全靠代码规则兜底**（`ensure_medical_notice` 等）。
不要在这一层奢望模型自己判断。

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 容器起来就退出 | `.env` 里 `DATABASE_URL` 相对路径 + 工作目录不对 | 容器内固定 `/app`，保持 `sqlite:///data/bilin.db` |
| `docker compose ps` 一直是 `starting` | healthcheck 打的是 8000，但 `PORT` 被改成别的 | healthcheck 与 `PORT` 保持一致 |
| 能登录但接口全 401 | 开了 `AUTH_MODE=required` 但客户端没带 `X-API-Token` | 客户端需配 `VITE_API_TOKEN`；或在 App 的「服务器地址」页确认 token |
| 能对话但听不到声音 | 音频签名 URL 的地址错位 | 已用 host 网络规避；若仍出现，检查客户端 baseURL 与端口 |

---

## 未经实测的说明

这套 Docker 文件是**按项目结构写的，但本机没有安装 Docker，未能实际构建验证**。
首次在学院服务器上构建时请留意：

- 镜像构建阶段能否访问 `mirrors.aliyun.com`（已用它替代默认 PyPI）
- `python:3.12-slim` 拉取是否顺畅（机房若配了私有 registry，可改基础镜像来源）

如果构建报错，把 `docker compose build` 的完整输出发我，我按报错改。
