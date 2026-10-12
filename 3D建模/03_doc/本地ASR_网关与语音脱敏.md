# 本地 ASR（按住说话）：网关、脱敏与安全（2026-10-05）

> 用户决定：**走本地 ASR**（引擎可换），并要求**对用户语音数据脱敏、保证数据安全**。
> 本文记录引擎选型约束、实现、以及隐私是如何"做成结构"而不是"靠记得删"。

---

## 1. 引擎选型：为什么不是 faster-whisper

本机实测前提：**Python 3.13.14**（项目 venv 与系统 python 都是）、RTX 4060 Laptop **8GB 显存**、
内存 15.6GB、**没有 ffmpeg**。

| 引擎 | 判定 | 原因 |
|---|---|---|
| `faster-whisper` | ❌ 装不上 | 依赖 `ctranslate2`，而它**没有 Python 3.13 轮子**（[OpenNMT/CTranslate2#1853](https://github.com/OpenNMT/CTranslate2/issues/1853)：`No matching distribution found for ctranslate2<5,>=4.0`）。要用它就得**另装一个 Python 3.10/3.11 环境** |
| **`whisper.cpp`** | ✅ **推荐** | C++ 独立可执行文件，**不依赖 Python 版本**，自带 CUDA 后端，中文可用，模型是单个 `.bin` |
| `sherpa-onnx` | ✅ 备选 | ONNX 系，同样不依赖 Python 版本，模型更小 |

**所以实现上把引擎关在"命令模板"里**：换引擎只改一个环境变量，
**端侧与接口都不用动**（与 TTS 网关同一套模式）。

---

## 2. 不引入新依赖：multipart 用标准库解析

FastAPI 的 `request.form()` 需要 `python-multipart`，而仓库约定**只装四个包**。

改用标准库 `email` 把 body 当 MIME 文档解析。**先实测了二进制保真度**再采用：

```
输入 1039 字节（含 0x00 / 0xFF / CRLF / 连续横线）
解析 1039 字节
逐字节一致: True        ← 音频若被改写是**静默故障**（只会说"听不清"），必须先验证
```

⚠️ 关键细节：**只解析 body**。把整个 HTTP 请求（含请求行）交给 `email` 会被当成单一部分
（实测 `is_multipart=False`），所以要先补最小 MIME 头。

---

## 3. ⚠️ 语音数据的脱敏与安全：靠结构，不靠"记得删"

老人语音是敏感个人信息（PIPL）。本实现把约束固化进代码：

| 措施 | 实现位置 | 说明 |
|---|---|---|
| **绝不持久化** | `privacy.TempAudio` | 只写系统临时目录，**唯一命名**（`uuid4` 前缀，不可预测） |
| **用完即删（含异常路径）** | `TempAudio.__exit__` / `finally` | 成功、失败、超时**都删**，且**连目录一起删** |
| **目录权限收紧** | `os.chmod(dir, 0o700)` + `O_CREAT\|O_EXCL` + `0o600` | POSIX 下同机其他用户读不到录音；避免"先按默认权限建好再改"的窗口 |
| **绝不写日志** | `main.py` 端点 | 只记**字节数**与引擎名；**不记音频内容，也不记识别出的文本** |
| **不留副本** | 端点 | 不复制、不缓存、不重命名留档；转写结果只经本次响应返回 |
| **拒绝超长录音** | 端点 | `MAX_UPLOAD_BYTES = 8MB`，避免大文件长时间停留 |
| **引擎不打印文本** | `privacy.command_suppresses_prints` | whisper.cpp **默认会把识别文本打进日志**——那是老人原话留在系统日志里。`--no-prints` 不是优化而是**隐私要求** |
| **健康检查可核查** | `/healthz` 的 `asrPrivacy` | 报出保留策略、体积上限、是否抑制打印，未抑制则给 `warning` |

### 3.1 测试抓出的一个真泄漏

`CommandAsrProvider.transcribe` 第一版**创建了 workdir 却从不删除** ——
每次识别都在系统临时目录留下一个含**转写文本**的目录。
"端点跑完不留临时目录"这条断言把它抓出来了：

```
AssertionError: Lists differ: ['bilin-asr-ofzsompy'] != []
```

修法：`try/finally` 里 `shutil.rmtree(workdir, ignore_errors=True)`。
**这正是"靠结构而不是靠记得"的意义** —— 如果没有这条断言，
它会一直静默地在磁盘上积累老人的话。

### 3.2 顺带修掉的测试隐患

`tests/test_avatar_voice.py` 用 `asyncio.get_event_loop().run_until_complete(...)`：
**单独跑全绿、全量跑必错**（Python 3.13 下事件循环被别的用例关掉后抛 `RuntimeError`）。
已改为 `asyncio.run()`。同一个坑之前在 `test_qwen_tts.py` 踩过一次。

---

## 4. 接口契约

```
POST /v1/asr/transcribe
  Content-Type: multipart/form-data
  file: <音频>            （只认 name="file"；格式由扩展名/Content-Type 推断）
→ 200 {"ok":true,  "text":"妈 药吃了没", "reason":"", "language":"zh", "engine":"CommandAsrProvider", "bytes":12345}
→ 200 {"ok":false, "text":"", "reason":"未配置语音识别（BILIN_ASR_CMD 或 BILIN_ASR_URL）", ...}
→ 400 畸形请求/空音频      → 413 超过 8MB
```

**失败返 200 而不是 4xx/5xx**：没配 ASR 或引擎失败是**业务结果**，
端侧按 `ok` 字段处理更简单 —— 提示"暂时听不清"，**老人仍可打字**。
语音是增强项，不是唯一入口。

---

## 5. 配置

```bash
# server/.env —— whisper.cpp 示例（注意 --no-prints 是隐私要求，不是可选）
BILIN_ASR_CMD=D:\whisper.cpp\build\bin\Release\main.exe -m D:\whisper.cpp\models\ggml-small.bin -f {audio} -l {language} -nt --no-prints
# 或指向内网 ASR 服务
# BILIN_ASR_URL=http://127.0.0.1:8080/asr
```

验证：`/healthz` 的 `asr` 段应显示 `asrReady: true`，
且 `asrPrivacy.enginePrintsSuppressed: true`（否则会给 warning，说明识别文本会进日志）。

---

## 6. 测试

`cd server; .\.venv\Scripts\python.exe -m unittest tests.test_asr` → **28 项**：

- multipart 二进制逐字节保真 / boundary 大小写与引号 / 畸形输入不抛错 / 只认 `file` 字段
- **`TempAudio`：退出后文件与目录都删除**、**异常路径也删除**、`destroy()` 幂等、目录名唯一
- 引擎输出解析：剥时间戳前缀 / 跳过日志行 / 多行取最后一行
- 降级：没配时 `ok=false` 且有原因、`describe()` 如实报 `asrReady:false`
- 隐私体检：识别 `--no-prints`、未抑制时给 warning、报告保留声明
- 端点：未配时降级、畸形 400、空音频 400、超大 413、**成功路径不留临时文件**

---

## 7. 还没做

1. **端侧录音与上传还没接**：后端接口已就绪，通话页目前仍是打字。
   要做：`uni.getRecorderManager()`（App）/ `MediaRecorder`（H5，需 HTTPS）+ 上传 + 把文本喂给 `ask()`。
2. **VAD 打断**：老人一开口应停掉数字人（`stopAudio()` 已有，缺触发）。
3. **引擎还没实际部署**：whisper.cpp 未安装（本文只保证"配上就能用"）。
4. **HTTPS 要求**：浏览器 `getUserMedia` 只在 HTTPS 或 localhost 可用 ——
   真机联调要 https 或让 App 侧走原生录音。
