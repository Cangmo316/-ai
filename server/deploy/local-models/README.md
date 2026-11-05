# 完全本地部署：模型 + 语音（不需要出网）

> **实测结论（2026-11-05）**：这套方案已经在开发机上跑通并验证。
> 后端切到本地模型后，登录 / 账号 / 会话 / 对话 / SSE 流式**全部通过**，
> healthz 自报 `模型=bilin-qwen`，回复质量保持微调后的风格。
> 具体数字见文末「实测数据」。

| 能力 | 云端方案（现用） | 本地替代 | 是否要改代码 |
|---|---|---|---|
| 对话 | DeepSeek API | **本地推理服务 + 微调的 Qwen2.5-1.5B** | 不改（改 `.env`） |
| 语音识别 | 阿里 DashScope | whisper.cpp | 不改（改 `.env`） |
| 语音合成 | 阿里 Qwen-TTS | Piper | 不改（改 `.env`） |
| 口型对齐 | DashScope 自带时间戳 | 不配则走估算 | 不改 |
| 拍照识药 / 病例 OCR | qwen-vl-max | 无（自动降级为手动录入） | 不改 |

关键前提：`app/llm/`、`app/asr/`、`app/voice/` 都有 Provider 抽象，**换成本地只是换环境变量**。

---

## 路线选择：先看能不能下到二进制

本来首选 Ollama / llama.cpp（量化后更快、内存更省）。但**实测这台机器下载不到任何 release 二进制**：

```
GitHub API                 ✅ 通（能查 release 列表）
GitHub release 资产域名     ❌ 被拦（下载 23MB 的 llama.cpp zip 失败）
ollama.com/download        ❌ 连不上
ghfast.top / ghproxy 镜像   ❌ 不通
```

所以给了**两条路**，按你的网络条件选：

| 路线 | 需要下载 | 量化 | 速度 | 适合 |
|---|---|---|---|---|
| **A 本地推理服务**（本文首推） | 不需要额外下载 | 否（bf16） | GPU 约 30–50 字/秒 | 机器上已有 torch+transformers |
| **B Ollama**（网络允许时更优） | Ollama + 量化工具 | 可 Q4 | 快 3–4 倍、内存减半 | 能下到安装包 |

---

## 路线 A：本地推理服务（零额外下载，已实测）

仓库自带 `ml/scripts/serve_local_model.py`，把合并后的模型包装成 **OpenAI 兼容接口**。
产品侧只要求"OpenAI 兼容"，所以后端改 `.env` 即可切换。

### 1. 准备模型（开发机/服务器都行）

```bash
# 合并 LoRA 到基座（产出 2.89GB 完整权重）
python ml/scripts/merge_and_export.py
# 产物：ml/out/merged-bilin/
```

### 2. 起服务

```bash
python ml/scripts/serve_local_model.py --port 8100
# 看到「监听 http://127.0.0.1:8100/v1（OpenAI 兼容）」就是好了
```

### 3. 冒烟

```bash
curl -s http://127.0.0.1:8100/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"bilin-qwen","messages":[{"role":"user","content":"今天天气不错"}],"max_tokens":60}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['choices'][0]['message']['content'])"
```

### 4. 切后端

```bash
# /etc/bilin/bilin.env
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://127.0.0.1:8100/v1
LLM_MODEL=bilin-qwen
LLM_API_KEY=ollama        # 本地不校验，但字段必须有值
```
```bash
sudo systemctl restart bilin-api
curl -s http://127.0.0.1:8000/healthz | grep -o '"model":"[^"]*"'   # 期望 bilin-qwen
```

### 5. 服务端也要常驻

`serve_local_model.py` 本身也要开机自启，否则后端起来了但模型没起 → 对话报错。

```bash
# systemd 单元示例（放 /etc/systemd/system/bilin-model.service）
[Unit]
Description=Bilin local model
After=network.target

[Service]
WorkingDirectory=/opt/bilin/ml
ExecStart=/opt/bilin/ml/.venv/bin/python scripts/serve_local_model.py --port 8100
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

---

## 路线 B：Ollama（网络允许时更优）

### 1. 装 + 导入

```bash
curl -fsSL https://ollama.com/install.sh | sh
# 把 ml/out/merged-bilin 拷到服务器 /opt/models/merged-bilin
sed -i 's|^FROM .*|FROM /opt/models/merged-bilin|' server/deploy/local-models/Modelfile
ollama create bilin-qwen -f server/deploy/local-models/Modelfile
ollama run bilin-qwen "今天天气不错 我出去走了走"
```

### 2. 切后端

```bash
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=bilin-qwen
LLM_API_KEY=ollama
```

### 3. 想更快就量化

```bash
python ml/scripts/merge_and_export.py --quant      # 需要 llama.cpp
# 产出 ml/out/gguf/bilin-q4_k_m.gguf（约 1GB），Modelfile 的 FROM 指向它
ollama create bilin-qwen-q4 -f Modelfile
```

---

## 语音本地化（两条路都一样）

### 识别：whisper.cpp

```bash
mkdir -p /opt/apps && cd /opt/apps
git clone https://github.com/ggml-org/whisper.cpp
cd whisper.cpp && cmake -B build && cmake --build build -j
cp build/bin/whisper-cli /usr/local/bin/

mkdir -p /opt/models && cd /opt/models
# small 约 466MB；中文够用。国内访问 HuggingFace 不稳时可从 ModelScope 镜像取
curl -L -o ggml-small.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

配到后端：
```bash
BILIN_ASR_PROVIDER=command
BILIN_ASR_CMD=whisper-cli -m /opt/models/ggml-small.bin -f {audio} -l zh -otxt -of {out}
```

### 合成：Piper

```bash
mkdir -p /opt/apps/piper && cd /opt/apps/piper
# 从 release 取 piper_amd64.tar.gz 解压（若被墙，用 apt 的 piper 包或 Docker 镜像）
```

配到后端：
```bash
BILIN_TTS_PROVIDER=command
BILIN_TTS_CMD=piper -m /opt/models/zh_CN-huayan-medium.onnx -f {out} < {text}
```

> Piper 不返回字级时间戳，3D 数字人的口型会走 `NullAligner`（按字数估算）。
> 对话与语音播放不受影响，只是口型精度下降。

---

## 实测数据（本机 RTX 4060 Laptop 8G，bf16 未量化）

| 项目 | 结果 |
|---|---|
| 模型加载 | 约 5 秒（2.89GB） |
| 裸服务 · 非流式 | 3.1s / 27 tokens |
| 裸服务 · 流式 | **首帧 2.55s**，39 个分片 |
| 走完整后端（含人设/免责/记忆注入）· 非流式 | **5.3s** |
| 走完整后端 · SSE 流式 | **7.9s / 23 帧** |
| 回复样例 | 「走一走心里就亮堂 / 回来坐会儿 我这儿一直陪着您 / 要是想说话随时喊我」 |
| 风格 | 短句、口语、用"您"、句末不加句号（微调风格保持） |

**纯 CPU 会慢 4–6 倍**（约 4–8 字/秒），老人等一句要十几秒 —— 只适合演示或断网兜底。

---

## 一键检查表

```bash
# 1. 后端自报的 provider
journalctl -u bilin-api -n 50 | grep -E '模型|tts|asr'

# 2. 对话确实走本地模型
curl -s http://127.0.0.1:8000/healthz | grep -o '"model":"[^"]*"'   # bilin-qwen

# 3. 语音能力
curl -s http://127.0.0.1:8000/v1/voice/capabilities

# 4. 断网验证（最关键）
#    拔掉外网（保留局域网/ZeroTier），再发一轮对话。
#    还能正常回话，才算真的离线。
```

---

## 取舍（不粉饰）

**换来的**
- 数据完全不出户（老人健康数据最敏感的诉求）
- 零 API 费用、断网可用

**付出的**
- 对话质量下降（1.5B vs DeepSeek）
- **医疗安全的兜底从"模型+规则"退化成"只靠规则"** ——
  1.5B 在我们那 8 条高危场景里漏了 4 条就医建议（跌倒/眼前一黑/认错人/胸口发闷），
  基座同样漏，是容量上限，不是微调退化
- 视觉能力消失（拍照识药、病例 OCR 变手动）
- 口型精度下降
- 一台常开机器 + 运维责任

**建议用混合**：平时云端（质量高），检测到外网不通时切本地（不断服）。
两种 provider 都在，切换只需改 `.env` 并重启。