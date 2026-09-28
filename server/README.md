# 比邻AI · agent 服务（FastAPI）

把 `uni-app` 端接上真实模型的那一层。**接口契约的唯一来源是
[`uni-app/api/README.md`](../uni-app/api/README.md)**——本服务是它的实现，不是它的定义。

---

## 一、现状（P0）

**已实现**

| 能力 | 落点 |
|---|---|
| `POST /v1/chat/stream` SSE 流式对话（meta / token / sticker / done / error） | `app/api/chat.py` + `app/orchestration/service.py` |
| `POST /v1/chat/send` 非流式回复（端侧降级路径） | 同上 |
| `GET /v1/chat/history` 历史消息 | `app/models/message.py` |
| `GET /v1/personas` 人设列表 | `app/persona/prompts.py` |
| `GET /healthz` 自检（密钥脱敏） | `app/main.py` |
| 上下文组装（最近 N 轮） | `app/orchestration/service.py` |
| 人设 system prompt（儿子/女儿/老伴/老友 + 医疗边界 + 伦理红线） | `app/persona/prompts.py` |
| 受控表情 token（`<sticker:xxx>`，白名单外的丢弃，半个标签也不泄露） | `app/orchestration/service.py` |
| 语言风格后处理（句末不加句号 / 句号转换行 / 小数与缩写保护） | `app/style/punctuation.py` |
| SSE 心跳（防端侧 20s 首字节看门狗误杀） | `app/orchestration/service.py` |
| 错误归一化（老人看得懂的话 + retryable） | `app/llm/openai_compat.py`、`app/main.py` |
| OpenAI 兼容模型客户端（含推理模型思维链隔离） | `app/llm/openai_compat.py` |

**未实现**（不藏着，避免误判进度）

- **鉴权**：目前无任何 token 校验，`CORS_ORIGINS=*`，只适合本机/内网联调
- **`clientMsgId` 幂等**：字段收下了但没用来去重（重发会产生重复消息）
- **数据库**：会话与消息全在内存，进程重启即清空（`app/models/message.py` 的接口按落库形态设计）
- **计划卡（`card` 事件）**：端侧与契约都支持，但服务端要等 P1 计划引擎接上
  `app/knowledge/guidelines.yaml` 之后才会真的发
- 三层记忆、内容管线、语音（CosyVoice 2）、数字人驱动、限流、可观测性

**默认假模型**：没配 `LLM_API_KEY` 时走 `FakeProvider`（固定话术、逐字吐字）。
这是刻意的——端侧联调、CI、演示都不该被额度或网络卡住，且假模型也会走完整条风格后处理链路。

---

## 二、快速开始

```powershell
cd server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env          # 填 LLM_API_KEY；不填就是假模型
.\.venv\Scripts\python.exe run.py
```

```bash
# Linux / macOS
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && .venv/bin/python run.py
```

起来之后：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz        # 自检：当前用真模型还是假模型
# 浏览器打开 http://127.0.0.1:8000/docs                # 自动生成的接口文档
```

端侧联调时把 `uni-app/api/config.js` 的 `DEFAULT_BASE_URL` 指到这里（H5 用 `127.0.0.1`、
Android 模拟器用 `10.0.2.2`、真机用局域网 IP，详见 `uni-app/api/README.md` §五）。

---

## 三、接真实模型：只改 `.env` 三行

```ini
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=你的key
LLM_MODEL=deepseek-chat
```

任何提供 `/v1/chat/completions` 流式接口的服务都能直接换（就是选它的理由，避免绑定某家 SDK）：

| 服务 | `LLM_BASE_URL` |
|---|---|
| DeepSeek | `https://api.deepseek.com/v1` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Kimi | `https://api.moonshot.cn/v1` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` |
| 本地 vLLM | `http://127.0.0.1:8000/v1` |
| 本地 Ollama | `http://127.0.0.1:11434/v1` |

**密钥安全**：`.env` 已在 `.gitignore` 里（含 `server/.env.*`），`.env.example` 只放变量名；
`/healthz` 与启动日志只回显 `sk-1****cdef` 这种脱敏形式。**任何情况下不要把 key 写进会提交的文件。**

---

## 四、目录结构

```
server/
├── run.py                  启动入口（等价 uvicorn app.main:app）
├── requirements.txt        fastapi / uvicorn / httpx（仅三个依赖）
├── .env.example            环境变量样例（不含密钥）
├── app/
│   ├── main.py             FastAPI 装配、CORS、异常归一化、/healthz
│   ├── config.py           零依赖 .env 解析 + Settings
│   ├── api/chat.py         路由：stream / send / history / personas
│   ├── orchestration/
│   │   ├── service.py      编排：上下文 → 模型 → 表情抽取 → 风格 → 事件 → 落库
│   │   └── events.py       SSE 帧编码（契约落点）
│   ├── llm/
│   │   ├── base.py         LLMProvider 接口 + LLMError
│   │   ├── openai_compat.py OpenAI 兼容客户端（httpx 流式）
│   │   └── fake.py         无 key 时的假模型
│   ├── persona/
│   │   ├── prompts.py      人设卡（4 个）+ system prompt
│   │   └── stickers.py     表情包受控白名单
│   ├── style/punctuation.py 句末去句号（流式后处理）
│   ├── models/message.py   消息模型 + 内存会话存储
│   └── knowledge/          康养条目（已有，25 条草稿，P1 接入）
└── tests/                  53 项单测（标准库 unittest，零测试依赖）
```

---

## 五、测试

```powershell
cd server
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

53 项，四块：

| 文件 | 守什么 |
|---|---|
| `tests/test_style.py` | 句末去句号规则（40 条边界用例 + 流式/整段一致性 + 小数跨片） |
| `tests/test_orchestration.py` | 表情标签切分、事件顺序、落库、上下文、错误路径、心跳 |
| `tests/test_api.py` | HTTP 契约：事件名、字段名、状态码、错误体、密钥脱敏 |
| `tests/test_llm_openai_compat.py` | 上游脏行容错、思维链隔离、401/429/5xx/超时映射 |

**跨语言端到端**（最有价值的一种回归）：让端侧测试直接打这个服务——用同一套端侧断言，
验证「uni-app api 层 → Python 服务 → SSE → 端侧状态机」整条链。

```powershell
# 一个窗口起服务，另一个窗口：
$env:BILIN_TEST_BASE_URL='http://127.0.0.1:8000'
node tools/test-chat-store.mjs
```

---

## 六、几个刻意的工程决定（附理由）

- **不引 `python-dotenv` / `pytest` / ORM**：`.env` 只用得到 `KEY=VALUE`，二十行解析完；
  测试用标准库 `unittest`；数据库选型等 P1 计划引擎一起定。少一个依赖少一个部署坑。
- **风格后处理做成流式**（`StyleStreamer`）：只在全量文本上跑一次后处理就必须攒完整段回复，
  「逐字说话」没了、首响从 1 秒退到好几秒；但逐 token 替换又判不了被切开的 `2.5`。
  做法是**把句号/换行/空白都先扣住**，等下一个字符到了立刻判定——
  既保逐字流，又保证「流式拼出来的文本」与「整段处理」逐字一致。
- **丢弃 `reasoning_content`**：推理模型的思维链不能下发到老人端——听不懂，
  而且可能夹带体检/用药判断的措辞，直接触碰医疗边界。
- **`meta` 事件先于任何模型调用发出**：模型鉴权失败/超时/断流时，端侧已经建好气泡，
  收到 `error` 就能就地提示重发，不会出现「点了发送什么也没有」的空窗。
- **发心跳**：端侧有 20s 首字节看门狗，而推理模型的第一个 content token 可能要等几十秒。
- **错误信息说人话**：`error.message` 会直接显示给老人，所以是「服务器开小差了，一会儿再试」，
  不是 `500 Internal Server Error`。

---

## 七、已知告警

`starlette 1.7` 会提示 `Using httpx with starlette.testclient is deprecated; install httpx2 instead`。
只影响测试客户端，不影响服务运行；等 FastAPI 上游切到 httpx2 再跟进。

---

## 八、下一步

1. **真实模型端到端验证**（拿到 `LLM_API_KEY` 后跑一遍 `/v1/chat/stream`，看话术是否合规范）
2. 鉴权 + `clientMsgId` 幂等 + 稳定错误码表
3. **P1 计划引擎**：读 `app/knowledge/guidelines.yaml` → 生成 `PlanItem` 草稿 → 家属确认 → 调度器
   （同时把 `card` 事件真正用起来）
4. PostgreSQL + Redis（会话落库、调度队列）
