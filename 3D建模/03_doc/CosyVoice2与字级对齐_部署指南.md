# CosyVoice 2 + 字级对齐 部署指南（2026-10-05）

> 目标：把口型从「按字数估算」（`source: estimated`）换成「真 TTS + 真字级对齐」（`source: tts-aligned`）。
> 代码侧**已经做完**（见 §1）；本文件讲**还要部署什么**，以及本机实测的可行性结论。

---

## 1. 代码侧已完成（本轮）

| 模块 | 作用 |
|---|---|
| `server/app/voice/gateway.py`（新） | TTS 与对齐的**可插拔 Provider**：`NullTtsProvider` / `CommandTtsProvider` / `HttpTtsProvider` + `NullAligner` / `CommandAligner` |
| `server/app/avatar/visemes.py` 的 `from_alignment()`（新） | **WhisperX/MFA 对齐结果 → viseme 关键帧**（真时间戳版），与估算版**共用同一契约** |
| `server/app/main.py` 的 `/healthz` | 新增 `voice` 字段，如实报 `ttsReady` / `alignReady` |
| `server/.env.example` | 新增三个环境变量说明 |
| `server/tests/test_avatar_voice.py`（新 27 项） | 守住"契约形状一致"与"**降级不许静默**" |

**关键设计：用命令行/HTTP 而不是 `import cosyvoice`。** 理由：
1. CosyVoice 2 需要 Python 3.10 + `pynini` 等编译依赖，与 agent 服务的
   Python 3.13 + 4 个依赖（fastapi/uvicorn/httpx/PyYAML）**不可能同环境**；
2. 选型文档写的就是"自建推理服务（GPU），与 agent 服务**同机或独立推理节点**"；
3. 进程隔离后 TTS 崩了不会带崩对话服务、GPU 排队也不阻塞 SSE。

**降级链是显式的，且任何一环失败都不中断对话**：

```
CosyVoice 可用 → 真音频 + 真对齐（source: tts-aligned）
   ↓ TTS 失败
无音频、口型估算（source: estimated）
   ↓ 对齐失败（有音频也不算）
有音频但口型仍估算（source: estimated）
```

---

## 2. ⚠️ 本机实测的可行性结论（先说清，别白折腾）

| 前提 | 本机状态 | 影响 |
|---|---|---|
| GPU | **RTX 4060 Laptop 8GB**（`nvidia-smi` 实测 8188 MiB，驱动 592.00） | ✅ CosyVoice2-0.5B 够用（推理约 4~6GB 显存） |
| 内存 | **15.6GB** | ⚠️ 偏紧（模型加载 + PyTorch 常驻会吃 6~10GB），跑起来会明显吃紧 |
| C 盘剩余 | **31.6GB** | ⚠️ 偏紧（PyTorch + CUDA runtime + 模型权重约 8~12GB） |
| WSL2 | **未安装**（`wsl --status` 提示需 `wsl --install`，**要管理员权限**） | ❌ **关键阻塞**：CosyVoice 的文本正则依赖 `pynini`/`WeTextProcessing` **没有 Windows 轮子**，Windows 原生几乎装不上；社区可行路径是 **WSL2 或 Docker(Linux)** |
| CUDA Toolkit（nvcc） | 未安装 | ⚠️ PyTorch 自带 CUDA runtime 可用；但部分编译类依赖需要 nvcc |
| Python | 系统 3.13 / 项目 venv 3.13 | ❌ CosyVoice 要 **3.10**（官方 conda 环境）；且本机**没装 conda** |

**结论：本机"开箱即跑"是不成立的**，需要动系统级环境（装 WSL2/Docker、装 CUDA、装 conda、
下载模型权重），这是一次**有破坏性的长时间操作**（数小时），且 C 盘空间紧张。
所以我**没有**擅自动手装，而是把代码侧做到"配置即可用"，等你决定部署方式。

---

## 3. 三条可选部署路线

### 路线 1：WSL2 + Ubuntu（本机推荐）
```
wsl --install -d Ubuntu-22.04        # 需要管理员权限，装完要重启
# Ubuntu 内：
conda create -n cosyvoice python=3.10 -y
pip install -r CosyVoice/requirements.txt   # 含 pynini（Linux 有轮子）
# 模型权重（约 2GB）下载到 WSL 内
```
然后在本机写一个 `tts_cli.py`（读 `--text-file`、写 `--out`），agent 侧配：
```
BILIN_TTS_CMD=wsl python /home/you/CosyVoice/tts_cli.py --text-file {text} --out {out} --voice {voice}
BILIN_ALIGN_CMD=wsl python /home/you/tools/align_cli.py --audio {audio} --text {text} --out {json}
```

### 路线 2：Docker + NVIDIA Container Toolkit
更干净（不污染系统），但要装 Docker Desktop + WSL2 后端，`--gpus all` 需要 WSL2 就绪。
适合"不想在系统里堆 Python 环境"的场景。

### 路线 3：独立推理节点 / 托管 API（最快见效）
- 自建独立节点：GPU 机器上起 FastAPI，POST `{text, voice}` 返回 `audio/wav`，
  然后配 `BILIN_TTS_URL=http://<节点>:9100/tts` —— **本机零安装**。
- 托管（阿里云百炼 CosyVoice）：**它的 WS 事件里直接带 `sentence.words[]` 字级时间戳**
  （`text/begin_index/end_index/begin_time/end_time`），也就是**连对齐这一步都省了**。
  代价：音频要出网 + 按字计费 + 与"自建 GPU 推理"的取向冲突（选型文档 §2.1）
  + 文档按 v3 系列写，是否覆盖我们要的 CosyVoice 2 音色/复刻模式**未核实**。

> 若走托管路线，`from_alignment()` 可以直接吃 `words[]`（字段名 `text`/`begin_time`/`end_time`
> 需要一个小适配）：给 `CommandAligner` 写个转换脚本把它转成
> `{"word_segments":[{word,start,end}]}` 即可，**端侧与契约完全不用动**。

---

## 4. 配好之后怎么验（三步，都有现成口子）

```powershell
# 1) 服务端：语音链路是否就绪（不配则如实显示 NullTtsProvider）
cd server; .\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'.');from app.voice import gateway;print(gateway.describe())"

# 2) 起服务后看 /healthz 的 voice 字段（ttsReady / alignReady 必须为 true）
curl http://127.0.0.1:8000/healthz

# 3) 端到端：SSE 流里应出现 lipsync 事件且 source 为 tts-aligned
#    （mock 已验证过同一链路，source 为 estimated）
```

端侧渲染不用改：`lipsync.js` 已经只看 `cues` 与时间区间，
`source=tts-aligned` 时它会完全信任服务端时间轴。

---

## 5. 诚实的遗留

1. **没有音频下发通道**。本轮的 `TtsProvider` 只负责**生成音频文件**（给对齐用），
   还**没有**把音频送到端侧播放。单独一张列表：端侧要能带鉴权头取音频
   （`uni.createInnerAudioContext.src` 与 H5 `<audio>` 都**带不了 Authorization**，
   需用 `uni.downloadFile` 先落地或服务端发短期签名 URL）。
2. **端侧时钟仍是自建的**（`performance.now()`）。真音频接入后必须改成
   "以音频播放时刻为基准"，否则**音画会漂移**（`player.start(cues, audioStartMs)` 已留形参）。
3. **通话页还没有对话流入口**，口型目前靠 `window.__blVisionPlayLipsync(cues)` 手工触发。
4. CosyVoice 的**音色复刻**（用老人授权的真人素材做定制音色）涉及肖像/声音授权，
   属产品与合规范畴，本轮未涉及。
