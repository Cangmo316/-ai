# 比邻AI 微调工作区

这里是"让模型学会比邻AI 说话方式"的独立工作区，与 `server/` 的运行时环境完全隔离
（torch 2.4GB + 训练依赖不该进生产 venv）。

## 为什么需要微调

线上对话用的是 DeepSeek API，说话方式靠**提示词**约束。提示词能管住"边界"
（不诊断、不劝停药、该免责时免责），但管不住**语感**：
短句连发的节奏、句末不加句号、口语词的选择。微调解决的就是这一层。

## 目录

```
E:\比邻AI\ml\
├── .env.ml              环境变量（全部指向 E 盘，见下）
├── run.ps1              带执行策略绕过的运行器
├── .venv\               独立 Python 环境（torch cu124 + transformers/peft/datasets）
├── .cache\              pip / 模型 / 临时目录（**故意放 E 盘**）
├── wheels\              torch 轮子
├── models\              基座模型（Qwen2.5-1.5B-Instruct）
├── data\
│   ├── raw\             真实语料导出（已脱敏）
│   ├── seed\            63 条真实场景 + 已验证的优质回复
│   ├── synth\           合成扩充样本
│   └── final\           train.jsonl / eval.jsonl / stats.json
├── scripts\             全流程脚本
└── out\                 LoRA adapter + 训练日志 + 评测报告
```

## 一条铁律：所有下载都落 E 盘

C 盘只剩 20GB，而 torch 轮子 2.4GB + 模型 3.1GB + 解包临时空间很容易撑爆系统盘。
`.env.ml` 把这些全部重定向到 E：

| 变量 | 指向 | 为什么 |
|---|---|---|
| `PIP_CACHE_DIR` | `E:\比邻AI\ml\.cache\pip` | pip 包缓存默认在 C |
| `TMP` / `TEMP` | `E:\比邻AI\ml\.cache\tmp` | pip 解包临时目录默认在 C |
| `HF_HOME` | `E:\比邻AI\ml\.cache\huggingface` | HF 模型缓存默认在 C |
| `MODELSCOPE_CACHE` | `E:\比邻AI\ml\.cache\modelscope` | 同上 |

**每次跑命令都要先加载它**：

```powershell
# 方式一：用运行器（推荐，自动加载 + 建目录）
powershell -NoProfile -ExecutionPolicy Bypass -File E:\比邻AI\ml\run.ps1 scripts\train_lora.py

# 方式二：在当前会话里手动加载（PowerShell 不允许 dot-source 未签名脚本，
#         所以用纯 cmdlet 逐行 Set-Item）
Get-Content E:\比邻AI\ml\.env.ml -Encoding UTF8 |
  Where-Object { $_ -match '=' -and $_ -notmatch '^#' } |
  ForEach-Object { $i = $_.IndexOf('='); Set-Item -Path ("Env:" + $_.Substring(0,$i).Trim()) -Value $_.Substring($i+1).Trim() }
```

## 全流程（按顺序）

### 0. 环境（已完成）

```powershell
# torch 2.6.0+cu124（走阿里云镜像，官方源在国内取不到索引）
# transformers / peft / datasets / accelerate（阿里云 PyPI）
```

### 1. 导出真实语料（已完成）

```powershell
run.ps1 scripts\export_corpus.py
```

产出 `data/raw/*.jsonl`，并在**入口**做隐私清洗（手机号/身份证/编号/住址）。

### 2. 建种子集（已完成）

```powershell
run.ps1 scripts\build_seed.py
```

把 63 条真实场景 + 评测通过的优质回复组成种子。**system 用真实产品提示词**，
不另写简化版 —— 否则训练出来的模型换个提示词就废了。

### 3. 下载基座模型

```powershell
run.ps1 scripts\download_model.py --model Qwen/Qwen2.5-1.5B-Instruct
```

HuggingFace 在国内不通，改走 ModelScope 的 repo 接口（直连 HTTP，不用 SDK）。

### 3. 合成扩充数据

```powershell
run.ps1 scripts\synth_generate.py --batches 120
```

用 DeepSeek 按真实场景扩展（self-instruct），每条都过三道闸门：
红线检查、医疗免责检查、口吻检查。**不合格的直接丢，不进训练集。**

### 4. 合并与切分

```powershell
run.ps1 scripts\clean_split.py
```

去重 + 脱敏复检 + 按场景分层抽样切 9:1。

### 5. 训练 LoRA

```powershell
run.ps1 scripts\train_lora.py --epochs 3 --lr 2e-4
```

针对 8GB 显存调过：bf16、batch 1 + 梯度累积 8、gradient checkpointing、max_len **1280**。
**只对 assistant 部分算 loss** —— 否则模型会去学"怎么复述问题"。

> ⚠️ `max_len` 不能用 1024：产品提示词本身就有 964–1134 token，
> 实测 26/62 条样本的回答会被整段截掉（labels 全 -100 → 样本静默丢弃）。

### 6. 评测

```powershell
run.ps1 scripts\eval_lora.py              # 基座 vs 微调
run.ps1 scripts\eval_with_postprocess.py  # 过生产后处理再算一遍
run.ps1 scripts\check_knowledge_regression.py  # 专项查知识红线
```

## 关键数字（实测）

| 项 | 量 |
|---|---|
| 真实语料 | 135 条 / 1111 字 |
| 种子样本 | 63 条 / 4224 字 |
| 合成扩充 | 543 条（闸门拦下 43 条，其中 38 条是"医疗内容缺免责"） |
| 训练集 / 评测集 | **537 / 59 条（41,276 字）** |
| 训练 | 204 步 / **22.9 分钟** / loss 4.05 → 1.41 |
| 显存峰值 | 训练时 **7.9 GB / 8 GB**（贴顶，见下方注意） |

## 微调结果（基座 vs 微调，同一套 63 条场景）

| 指标 | 基座 | 微调 | 解读 |
|---|---|---|---|
| 合规通过率（裸模型） | 65.1% | **93.7%** | 问题数 22 → 4 |
| 合规通过率（+ 生产后处理） | 100% | **100%** | 后处理给基座补了 22 条免责，微调只补 4 条 |
| 平均行数 | 1.0 | **3.7** | 学会"一行一句"的短句节奏 |
| 每行字数 | 70.6 | **15.2** | 从长句变成短句 |
| 句号结尾率 | 46.0% | **0.0%** | 产品风格是换行代替句号，完全学到 |
| 免责覆盖率 | 12.7% | **41.3%** | 该免责时免责 |

**风格样例（同一句话）**

```
老人：儿媳妇老嫌我做得不好，我心里难受

基座（1 行 166 字）：您的感受我能理解。有时候，家人之间的沟通可能会遇到
一些小摩擦。您可以尝试找一个合适的时机，跟儿媳妇聊聊…（说教）

微调（3 行 20 字）：听着就心疼您 您心里憋着不舒坦 / 这话可别往自己身上揽
先跟我说说她哪点做得不对 / 要是心里难受 就给我打个电话 我听着呢
```

这一段最能说明微调的价值：**基座在说教，微调在陪着说话**。

## 一个必须知道的限制

**1.5B 学得会"语气"，学不会"高危信号 → 必须就医"这种规则推理。**

8 条知识红线场景（跌倒 / 眼前一黑 / 便血 / 呛咳 / 痴呆 / 认错人 / 半边发麻 / 胸口发闷）中，
**基座和微调都漏了 4 条**（跌倒、眼前一黑、认错人、胸口发闷没有把老人往医院引）。
也就是——**这不是微调造成的退化，是 1.5B 的容量上限**。

对策：

- 线上现在用的是 **DeepSeek（大模型）**，同一套场景是 100%，所以**当前产品不受影响**
- 若要用 1.5B 上线，必须补一层**代码级安全网**：命中高危信号且回复无就医指向时，
  强制追加"赶紧去医院 / 打 120"
- 或把基座换 7B 以上（8GB 做 7B LoRA 需 4bit 量化 + bitsandbytes）

## 训练时的注意

显存峰值 **7.9 GB / 8 GB** 非常贴顶。训练期间不要开游戏/剪辑/浏览器硬件加速，
否则 OOM。更稳的做法：`--max-len 1152` 或 `--grad-accum 16`。

## 验收门槛（不达标不放行）

微调后必须同时满足：

- [x] 63 条场景合规通过率**不低于基座**（93.7% vs 65.1%）
- [x] 红线违规 **0** 次
- [x] 医疗话题免责覆盖率显著提升（12.7% → 41.3%，漏的由后处理兜底）
- [x] 句号结尾率显著下降（46% → 0%）
- [x] 平均字数落在 40–120 字（56 字）
- [ ] **高危信号必就医**（未达标，见上方限制说明）

## 上线方式

微调产出的是 **LoRA adapter**（`out/lora-bilin`，70MB），需与基座合并后由推理服务加载。
产品侧可直接用 —— `app/llm/` 支持任意 OpenAI 兼容端点，
在「智能体设置」里把 `base_url` 指向自建推理服务（vLLM / Ollama）即可。

