# 比邻AI — 仓库协作规则

本文件是本仓库内 AI 协作的规则来源。仓库内更深层目录的 AGENTS.md 若有冲突，以更深层为准。

## 硬性规则

1. **单次对话长度不超过 800k**——一段对话的累计上下文不要超过 800k token，以免触顶后丢失上下文。
   接近上限前，先把进度落盘再续接，禁止硬撑到超限：
   - 落盘至少包含：已完成项、未完成项、下一步、踩过的坑（含失败方案与原因）
   - 落盘位置：仓库内文件（方案文档追加章节，或独立任务笔记）
   - 新对话开场先读上一段落盘的任务笔记

## 项目约束（已定决策，勿擅自变更）

- 产品：面向康复养老行业的可视化康养数字人智能体 App，uni-app 多端 + 自建 agent
- **伦理红线**：不模拟已故亲属、不冒充真人、不阻断真人联系、老人可一键停止、不越诊疗边界
- **医疗边界**：不做诊断、不做剂量调整、不做疾病判断；输出仅限「生活提醒与依从性管理」
- 康养计划：agent 基于知识库生成 → **家属确认后生效**
- 3D 渲染：只做端侧方案 A；不做云渲染 B，也不做接口预留
- 抖音热点：不做（仅保留 `content_provider` 抽象）
- 语音：TTS 用 CosyVoice 2；lip-sync 走字级时间戳对齐（非音素级）
- 3D 资产：真人定制资产由用户用 Blender 完成骨骼绑定后交付，当前 `static/` 为空

## 工程约定（沿用既有做法）

- 交流用中文；技术判断给理由，不要只给结论
- 优先开源免费方案；引入付费或受限许可组件前必须先确认
- 提交信息写入 UTF-8 文件后用 `git commit -F` 传入，避免控制台编码导致乱码
- 改动 `server/app/knowledge/guidelines.yaml` 后必须跑 `node server/app/knowledge/validate.mjs`
- **改动 `uni-app/api/`、`uni-app/stores/`、`uni-app/pages/` 或 `tools/mock-server.mjs`
  后必须跑 `npm test`**（仓库根目录；零 npm 依赖，含 SSE 契约 25 + 话术规则 6 + 对话状态机 13 + 计划打卡 10 + 到点提醒 10 + 推送登记 13 + 记忆契约 11 + 鉴权与错误码 10 + 家人端 25 + 捏脸参数面板 20，共 143 项）
- **改 `uni-app/common/face/` 或 `uni-app/pages/face/` 后另外必须跑 `npm run test:face`**：
  它直接读 `uni-app/static/avatar/*.glb`，守住「面板目录 ↔ 参数表 ↔ 适老裁剪 ↔ 真实资产」四者一致
  （参数改名、漏导出、裁剪表与参数表口径分歧都会被抓住）
- **改了 system prompt 或 `tools/check-chat-quality.mjs` 的合规正则后**：
  先 `npm run test:quality`（正反用例锁住误报），再接真模型跑 `npm run quality`（需 `server/.env` 配 key）
- **合规正则有两处，必须同步**：`server/app/style/compliance.py` 与 `tools/check-chat-quality.mjs`
- **计划的家属确认闸门是产品硬约束**：`GET /v1/plans/today` 与任何提醒只能取 `active` 计划；
  改 `server/app/plan/` 后必须确认 `tests/test_plan_engine.py` 里
  「未确认不产生提醒」「过渡期旧计划继续执行」两组用例仍绿
- **家人端（`family/`）与老人端共用 `uni-app/api/` 那一层客户端**（浏览器侧由 `family/uni-shim.js` 补 `uni.request`）；
  改接口层要两端一起验：`node tools/test-family-flows.mjs`（业务语义）与 `node tools/test-family-ui.mjs`（渲染与点击）
- **家人端默认不可见聊天原文**（设计方案 §3.4）：`family/flows.js` 里不许出现会话接口，
  `tools/test-family-flows.mjs` 有一条扫描源码的回归用例守着；要加"看聊天"必须先做老人授权与 consent
- **前后端接口契约的唯一来源是 `uni-app/api/README.md`**——改契约必须同时改三处：
  端侧实现、`tools/mock-server.mjs`、契约文档本身
- 后端未就绪时的联调靶子：`node tools/mock-server.mjs`（实现同一份契约）；
  仓库根 `package.json` 只为 `tools/` 提供 ESM 运行环境与快捷命令，`uni-app/` 工程仍零 npm 依赖
- **改动 `server/app/` 或 `server/tests/` 后必须跑**
  `cd server; .\.venv\Scripts\python.exe -m unittest discover -s tests -t .`（238 项，零测试依赖）
- 跨语言端到端回归：先起 `server/run.py`，再
  `$env:BILIN_TEST_BASE_URL='http://127.0.0.1:8000'; node tools/test-chat-store.mjs; node tools/test-plan-store.mjs; node tools/test-reminder-store.mjs; node tools/test-push-store.mjs; node tools/test-memory-store.mjs; node tools/test-auth.mjs; node tools/test-family-flows.mjs`
- **三层记忆有三条隐私硬约束**（设计方案 §3.4，改 `server/app/memory/` 或 `tools/mock-server.mjs`
  的记忆路由后必须确认 `server/tests/test_memory.py` 与 `node tools/test-memory-store.mjs` 全绿）：
  1. `source=auto`（从聊天自动整理）的记忆 **`visibleToFamily=false`**：`scope=family` 不返回，
     否则"家人端默认看不到聊天原文"会被记忆绕过去
  2. `review=pending`（置信度 < 0.75）**不参与检索、不用于主动话题**，只等家属复核
  3. `autoExtract` **默认关**：开启才算"已告知本人"（服务端记 `consentedAt`）；
     且**端侧不提供记忆写入入口**，写入只能走家人端或对话自动整理
- **记忆检索的分数口径只有一个入口**：`server/app/memory/retrieval.py` 的 `score()`。
  现在是"标签/词组重合 + 时间衰减"（零依赖、可解释），换向量检索只改这一处
- **对外提供服务前必须开鉴权**：`server/.env` 里设 `AUTH_MODE=required` 并配 `API_TOKENS`（端侧用 `setApiToken()`）；
  否则任何能访问到端口的人都能读健康档案、改计划、发提醒
- **模型 key 只放 `server/.env`**（已 gitignore，含 `server/.env.*`）；
  `server/.env.example` 只放变量名，任何提交文件里不得出现密钥
- 写文件默认 UTF-8 无 BOM（`[System.IO.File]::WriteAllText` + `UTF8Encoding($false)`）
  - **例外：`.ps1` 必须 UTF-8 带 BOM**（`UTF8Encoding($true)`）。Windows PowerShell 5.1
    会把无 BOM 的 UTF-8 当 ANSI(GBK) 解码，含中文的脚本会直接解析失败
    （实测：同一个脚本无 BOM 报 7 处语法错误，带 BOM 为 0 处）
- **原生命令的 stderr 在 PS 5.1 下是个坑**：`$ErrorActionPreference='Stop'` 时命令只要
  往 stderr 写一行就抛终止性错误；改成 `Continue` 也不行，因为 `2>文件` 写进去的是
  PowerShell 格式化后的错误文本（含 `At line` / `CategoryInfo`），不是原始 stderr。
  取外部命令输出请用 `System.Diagnostics.Process`，参考 `tools/backup.ps1`

## 远端仓库

- `origin` —— `git@github.com:Cangmo316/-ai.git`（私有），推送走 SSH over 443
- `localmirror` —— `D:\backup\bilin-ai.git`，本地备份镜像（见下）
- 认证依赖 SSH key `~/.ssh/id_ed25519`（公钥已加到 GitHub，首次推送已完成，远端与本地一致）
- **ssh 必须用 Windows 自带的 OpenSSH**，不要用 Git 自带的 MSYS ssh：
  `git config --global core.sshCommand '"C:/Windows/System32/OpenSSH/ssh.exe"'`
  理由：本机用户目录含中文（`C:\Users\余云飞`），Git 自带的 MSYS ssh 把路径按 GBK 解释，
  找不到 `~/.ssh/` 下的私钥与 known_hosts，报 `Host key verification failed`（即使公钥已授权）；
  Windows OpenSSH 用 UTF-8 解析路径，实测正常。
- 推送：`git push origin main`

## 备份与还原

### 本机环境事实（重要）

- **Git**：已装 Git for Windows 2.55.0 到 `%LOCALAPPDATA%\Programs\Git`（用户级安装，无需
  管理员），用户 PATH 已加入其 `cmd` 目录。此前本机唯一可用的 git 是 Codex 运行时缓存里的
  副本且不在 PATH 中，导致计划任务里备份静默失败；`Resolve-GitExe` 现在按
  「PATH（跳过缓存）→ 常见安装位置 → Codex 缓存」兜底查找，保证任何环境都能跑。
- **网络**：`github.com:443` 被阻断（TCP 不通），HTTPS 推送不可用；`api.github.com`、
  `codeload.github.com`、`gitee.com` 可达。GitHub 推送**走 SSH over 443**：`~/.ssh/config`
  已把 `github.com` 指向 `ssh.github.com:443`。

### 自动备份

Windows 计划任务 **`BilinAI-Backup`**，每日 12:30 运行：推 `localmirror` + 生成 bundle 快照，
日志写在 `D:\backup\backup.log`。查看状态：

    Get-ScheduledTaskInfo -TaskName BilinAI-Backup | Select-Object LastRunTime, LastTaskResult

`LastTaskResult = 0` 为成功。手动触发：`Start-ScheduledTask -TaskName BilinAI-Backup`。

备份落在 **D:\backup**（与项目盘 E: 分离，防单盘故障）：

- `D:\backup\bilin-ai.git` —— 裸镜像，日常增量备份，远端名 `localmirror`。
  刻意不用 `--mirror` 推送：镜像推送会把本地删除与强推同步过去，备份会跟着源一起坏
- `D:\backup\bundles\bilin-ai-*.bundle` —— 不可变单文件快照，可直接拷 U 盘 / 网盘

执行备份（保留最近 20 份快照）：

    powershell -NoProfile -ExecutionPolicy Bypass -File tools\backup.ps1

还原（二选一）：

    git clone D:\backup\bilin-ai.git  E:\restore\bilin-ai
    git clone D:\backup\bundles\bilin-ai-20260927-232459.bundle  E:\restore\bilin-ai

## 必读文档

- `比邻AI_项目设计方案.md`——主方案（产品红线、计划状态机、捏脸/口型架构）
- `比邻AI_医学条目与语音技术选型.md`——知识来源与语音栈
- `比邻AI_数字人资产交付规范.md`——Blender 交付契约与验收清单
- `uni-app/api/README.md`——**前后端接口契约**（SSE 事件表、各端流式能力差异、联调方式）
- `server/README.md`——agent 服务（启动、接模型、测试、已实现/未实现清单）