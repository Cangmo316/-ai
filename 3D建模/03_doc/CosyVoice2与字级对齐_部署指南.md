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


---

## 6. 已选定路线：阿里云百炼 **Qwen-Audio-TTS**（2026-10-05）

> 用户决定：走托管路线，模型 **Qwen-Audio-3.0-TTS**（文档里的模型名是
> `qwen-audio-3.0-tts-flash`；具体版本名可用 `BILIN_TTS_MODEL` 覆盖）。

### 6.1 契约（照阿里云官方文档，2026-09 更新）

| 项 | 值 |
|---|---|
| 协议 | **WebSocket**：`wss://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference`（新加坡另有域名） |
| Python SDK | `dashscope`，`from dashscope.audio.tts_v2 import SpeechSynthesizer` |
| 字级时间戳开关 | `additional_params={"word_timestamp_enabled": True}` |
| ⚠️ 限制 | **仅在流式输出模式可用** → 必须传 `callback`，不能走非流式的 `call()` |
| 时间戳位置 | `payload.output.sentence.words[]`，每项 `text` / `begin_time` / `end_time`（**毫秒**） |
| 事件类型 | `sentence-begin` / `sentence-synthesis` / **`sentence-end`（带全量 words）** |
| 音频 | 走 `on_data(bytes)` 回调；Python SDK 的 `on_event` **只给 message 字符串、不给音频** |
| 音色 | `longanhuan_v3.6`（文档示例）；**哪些音色支持字级时间戳文档没列全** → 拿到空 words 时降级 |
| 额外能力 | 还支持**音素级**时间戳 `Phoneme{begin_time,end_time,text,tone}`（比字级更细，本轮未用） |

来源：[Qwen-Audio-TTS Python SDK](https://www.alibabacloud.com/help/en/model-studio/qwen-audio-tts-python-sdk)、
[Java SDK（含 Sentence/Word/Phoneme 结构）](https://www.alibabacloud.com/help/en/model-studio/qwen-audio-tts-java-sdk)

### 6.2 与 CosyVoice 路线的**结构差异**（这是本轮最重要的设计判断）

| | CosyVoice（自建） | 百炼 Qwen-Audio-TTS（托管） |
|---|---|---|
| 流程 | **两步**：先合成音频 → 再用 WhisperX/MFA 对齐 | **一步**：同一会话里音频与时间戳一起回来 |
| 对齐依赖 | 需要额外部署对齐工具 | **不需要**（`describe()` 直接报 `alignReady: true`） |
| 环境 | GPU + Python 3.10 + WSL2/Docker | 本机零安装（只要 `pip install dashscope` + API Key） |

所以实现上**不能照搬"先出音频再对齐"**：Qwen 的音频与 words 是**两路回调**，
必须一次收齐。`app/voice/qwen_tts.py` 的 `QwenTtsProvider.synthesize()`
把两者一起返回（`extra.word_segments`），编排层只看"有没有 word_segments"，
**两条路线在编排层是同一段代码**（见 `ChatService._build_lipsync`）。

### 6.3 本轮的落地

| 文件 | 作用 |
|---|---|
| `server/app/voice/qwen_tts.py`（新） | `QwenTtsProvider`：一次调用拿音频 + 字级时间戳；`_extract_words_from_event()` 解析事件；`words_to_segments()` 做单位/键名转换（毫秒→秒、`begin_time`→`start`） |
| `server/app/voice/gateway.py` | 装配优先级：`BILIN_TTS_PROVIDER=qwen` > `BILIN_TTS_URL` > `BILIN_TTS_CMD` > Null；`describe()` 对百炼额外报 `sdkInstalled`/`hasApiKey`/`model`/`voice` |
| `server/app/orchestration/service.py` | 新增 `_build_lipsync()`：**优先真时间戳 → 失败/缺失则回退估算**；`voice` 可注入（默认取全局装配） |
| `server/tests/test_qwen_tts.py`（新 17 项） | 事件解析（含坏数据/驼峰/顶层 words 三种形状）、单位换算、装配优先级、**降级不许静默** |
| `server/tests/test_lipsync_wiring.py`（新 6 项） | **接线断言**：注入假 TTS 验证 lipsync 事件真的走 `tts-aligned` |

**为什么 `dashscope` 故意不写进 `requirements.txt`**：仓库约定"只装四个包、能不装就不装"；
托管路线是可选能力，没装时**明确降级**（`sdkInstalled: false`）而不是让服务起不来。

### 6.4 接线层的"静默失败"防线

口型接错**不会报错**——只是退回估算版、口型不准而已，页面上照常动。
所以专门加了 `tests/test_lipsync_wiring.py`：用假的"带时间戳 TTS"注入编排层，
断言 `source == "tts-aligned"` 且时间轴来自对齐数据（880ms 而非按字数的估算值）。
**没有这条断言，"接上了"和"没接上"从外部看不出区别。**

### 6.5 怎么启用（三步）

```powershell
# 1) 装 SDK（故意不在 requirements 里）
cd server; .\.venv\Scripts\python.exe -m pip install dashscope

# 2) 配置（server/.env；key 只放 .env，进仓库的只有变量名）
#    DASHSCOPE_API_KEY=sk-xxxx
#    BILIN_TTS_PROVIDER=qwen
#    BILIN_TTS_VOICE=longanhuan_v3.6      # 换音色后要复验是否还返回 words
#    BILIN_TTS_MODEL=qwen-audio-3.0-tts-flash

# 3) 验证
cd server; .\.venv\Scripts\python.exe -c "import sys;sys.path.insert(0,'.');from app.voice import gateway;print(gateway.describe())"
#   → 期望 sdkInstalled=True, hasApiKey=True, ttsReady=True, alignReady=True
```

然后发起一次对话，SSE 流里应出现 `event: lipsync` 且 `"source":"tts-aligned"`。

### 6.6 成本与合规（必须一并说清）

- **音频出网 + 按字计费**：与选型文档"自建 GPU 推理"的取向不同，这是**产品取舍**，代码层不评判。
- **老人语音/文本出网**：涉及 PIPL 与《人脸识别技术应用安全管理办法》同一类问题——
  **建议在隐私政策里写明"语音合成由第三方云服务完成"**，并确认老人的知情同意范围。
  （本项目已有"AI 标识常驻""不冒充真人"等红线，这条要一起对齐。）
- **密钥管理**：`DASHSCOPE_API_KEY` 只放 `server/.env`（已 gitignore），任何提交文件里不得出现。

### 6.7 仍然没做的（与路线无关）

1. **音频下发通道**：`TtsProvider` 产出的音频文件**还没有送到端侧播放**。
   端侧取音频带不了 `Authorization` 头（`innerAudioContext.src` / H5 `<audio>` 都不行），
   需 `uni.downloadFile` 先落地或服务端签名 URL。
2. **端侧时钟**仍是 `performance.now()`；接真音频后必须改成**以音频播放时刻为基准**，
   否则音画漂移（`player.start(cues, audioStartMs)` 已留形参）。
3. **通话页仍无对话流入口**，口型目前靠 `window.__blVisionPlayLipsync(cues)` 手工触发。
