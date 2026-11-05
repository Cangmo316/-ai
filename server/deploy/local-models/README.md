# 完全本地部署：模型 + 语音（不需要出网）

目标：把「对话 / 语音识别 / 语音合成」三件事全搬到本机，服务器不访问任何外部 API。

| 能力 | 云端方案（现用） | 本地替代 | 是否要改代码 |
|---|---|---|---|
| 对话 | DeepSeek API | **Ollama + 我们微调的 Qwen2.5-1.5B** | 不改（改 `.env`） |
| 语音识别 | 阿里 DashScope | **whisper.cpp** | 不改（改 `.env`） |
| 语音合成 | 阿里 Qwen-TTS | **Piper** | 不改（改 `.env`） |
| 口型对齐 | DashScope 自带时间戳 | 不配则走估算 | 不改 |
| 拍照识药 / 病例 OCR | qwen-vl-max | 无（自动降级为手动录入） | 不改 |

关键前提：`app/llm/`、`app/asr/`、`app/voice/` 都有 Provider 抽象，所以**换成本地只是换环境变量**。

---

## 一、对话模型（Ollama）

### 1. 拿到两个产物

在**开发机**上（本仓库 `ml/`）：

```
ml/out/lora-bilin/        微调出来的 LoRA adapter（70MB）
ml/out/merged-bilin/      LoRA 已合并进基座的完整模型（2.89GB）  ← 用它
```

合并命令（已跑过，重跑也安全）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File E:\比邻AI\ml\run.ps1 scripts\merge_and_export.py
```

### 2. 在服务器上装 Ollama

```bash
# Linux（官方脚本，需要出网；内网机器请用离线包）
curl -fsSL https://ollama.com/install.sh | sh

# 验证
ollama --version
systemctl status ollama
```

> 内网机器：在有网的机器上下 `ollama-linux-amd64.tgz`，拷过去解包到 `/usr/local`，
> 再手工起 `systemd` 服务（`OLLAMA_MODELS` 指向数据盘）。

### 3. 把合并后的模型拷到服务器

```bash
# 2.9GB，建议压缩后再传
# 开发机：
tar -czf merged-bilin.tar.gz merged-bilin/
# 服务器：
scp merged-bilin.tar.gz user@server:/opt/models/
tar -xzf merged-bilin.tar.gz -C /opt/models/
```

### 4. 建模型

`Modelfile` 已在本目录，改一下 `FROM` 路径即可：

```bash
sed -i 's|FROM .*|FROM /opt/models/merged-bilin|' Modelfile
ollama create bilin-qwen -f Modelfile
ollama list                      # 应能看到 bilin-qwen
```

**冒烟**（先确认模型本身能用，再改后端）：

```bash
ollama run bilin-qwen "今天天气不错 我出去走了走"
# 期望：短句、口语、用"您"、句末不加句号
```

### 5. 切后端到本地模型

```bash
sudo vi /etc/bilin/bilin.env
```
```bash
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=bilin-qwen
LLM_API_KEY=ollama
```
```bash
sudo systemctl restart bilin-api
curl -s http://127.0.0.1:8000/healthz | grep -o '"model":"[^"]*"'   # 期望 bilin-qwen
```

### 速度参考（决定硬件）

| 硬件 | 1.5B 全精度(2.9GB) | Q4 量化(~1GB) |
|---|---|---|
| 4 核 CPU / 8G 内存 | 4–8 字/秒 | 8–15 字/秒 |
| RTX 3060 12G | 30+ 字/秒 | 60+ 字/秒 |

> **要更快就跑量化版**：`ml/scripts/merge_and_export.py --quant` 需要 llama.cpp
> （`git clone` 后 `cmake -B build && cmake --build build`），产出 `bilin-Q4_K_M.gguf`，
> 然后把 `Modelfile` 的 `FROM` 指向 gguf 文件即可。

### ⚠️ 必须知道的限制

1.5B 在**我们那 8 条高危医疗场景**里漏了 4 条就医建议（跌倒 / 眼前一黑 / 认错人 / 胸口发闷）。
这不是微调造成的退化——基座同样漏，是 1.5B 的容量上限。

**所以本地模式下，医疗安全完全靠代码规则兜底**（`app/persona/prompts.py` 的
`is_medical_question` + `ensure_medical_notice`）。真要更稳，就上 7B 或保留云端增强。

---

## 二、语音识别（whisper.cpp）

### 1. 装

```bash
# 有网：预编译包（推荐，省去编译）
mkdir -p /opt/apps && cd /opt/apps
curl -L -o whisper.zip https://github.com/ggml-org/whisper.cpp/releases/latest/download/whisper-bin-x64.zip
# 若该 release 没有 x64 包，就自己编译：
#   git clone https://github.com/ggml-org/whisper.cpp
#   cd whisper.cpp && cmake -B build && cmake --build build -j
```

### 2. 下模型

```bash
mkdir -p /opt/models && cd /opt/models
# small 约 466MB，中文够用且速度快；要更准用 medium（1.5GB）
curl -L -o ggml-small.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

> 国内访问 huggingface 常被墙，可换 ModelScope 镜像，或从有网的机器下载后拷进来。

### 3. 试一句

```bash
whisper-cli -m /opt/models/ggml-small.bin -f test.wav -l zh -otxt -of /tmp/out
cat /tmp/out.txt
```

### 4. 配到后端

```bash
BILIN_ASR_PROVIDER=command
BILIN_ASR_CMD=whisper-cli -m /opt/models/ggml-small.bin -f {audio} -l zh -otxt -of {out}
```

`{audio}` 是后端传进来的临时音频路径，`{out}` 是输出前缀（whisper 会写成 `{out}.txt`）。

> 也可以不装本地、直接给一个 HTTP 识别服务：
> `BILIN_ASR_PROVIDER=http` + `BILIN_ASR_URL=http://127.0.0.1:9000/transcribe`
> （请求体与返回格式见 `app/asr/gateway.py` 的 `HttpAsrProvider`）

---

## 三、语音合成（Piper）

### 1. 装

```bash
mkdir -p /opt/apps/piper && cd /opt/apps/piper
curl -L -o piper.tar.gz https://github.com/rhasspy/piper/releases/latest/download/piper_amd64.tar.gz
tar -xzf piper.tar.gz
./piper --help
```

### 2. 下中文音色

```bash
mkdir -p /opt/models && cd /opt/models
# 中文女声（约 63MB）
curl -L -o zh_CN-huayan-medium.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx
curl -L -o zh_CN-huayan-medium.onnx.json \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json
```

### 3. 试一句

```bash
echo "您好 今天天气不错" | ./piper -m /opt/models/zh_CN-huayan-medium.onnx -f /tmp/t.wav
```

### 4. 配到后端

```bash
BILIN_TTS_PROVIDER=command
BILIN_TTS_CMD=piper -m /opt/models/zh_CN-huayan-medium.onnx -f {out} < {text}
```

> **没有字级时间戳**：Piper 不返回每个字的起止时间，所以 3D 数字人的口型会走
> `NullAligner`（按字数估算）。对话与语音播放不受影响，只是口型精度下降。
> 要做到和云端一样的口型，需要额外的强制对齐工具（如 `BILIN_ALIGN_CMD` 接 Montreal Forced Aligner）。

---

## 四、一键检查表

改完 `.env` 重启后，逐项确认：

```bash
# 1. 后端自报的 provider（日志里会打印）
journalctl -u bilin-api -n 50 | grep -E '模型|tts|asr'

# 2. 对话走的是本地模型
curl -s http://127.0.0.1:8000/healthz | grep -o '"model":"[^"]*"'
#   期望 "bilin-qwen"；若还是 deepseek-chat，说明 .env 没生效

# 3. 语音识别
curl -s http://127.0.0.1:8000/v1/voice/capabilities      # asr.ready 应为 true

# 4. 语音合成
curl -s http://127.0.0.1:8000/v1/voice/capabilities      # ttsReady 应为 true

# 5. 断网验证（最关键的一步）
#    拔掉外网（保留 ZeroTier / 局域网），再发一轮对话。
#    如果还能正常回话，说明真的离线了。
```

---

## 五、这套方案的取舍（说清楚，不粉饰）

**换来的**
- 数据完全不出户（老人健康数据最敏感的诉求）
- 零 API 费用，没有按次计费
- 断网可用

**付出的**
- 对话质量下降（1.5B vs DeepSeek）
- 医疗安全的兜底从"模型+规则"退化成"只靠规则"
- 视觉能力基本消失（拍照识药、病例 OCR 变成手动录入）
- 口型精度下降（无字级时间戳）
- 一台常开机器 + 运维责任（备份、断电、故障）

**我的建议**：不要"全本地"或"全云端"二选一，用**混合**：
平时走云端（质量高），检测到外网不通时自动切本地（不断服）。
代码层两种 provider 都在，切换只需改 `.env` 并重启。
