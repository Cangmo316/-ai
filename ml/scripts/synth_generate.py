"""合成 SFT 数据：用 DeepSeek 按真实场景扩展出足量样本（self-instruct）。

## 为什么可以这么做

种子只有 63 条 / 4224 字，离微调门槛差 15–25 倍。而我们要教的不是"新知识"，
而是**一种说话方式 + 一套边界**（短句、口语、不越界、该免责时免责）。
这类"行为固化"最适合用大模型生成同分布样本——业界叫 self-instruct / 蒸馏。

## 三条质量闸门（生成完立刻验，不合格直接丢）

1. **红线**：不能出现停药建议、剂量指导、下诊断
2. **医疗免责**：医疗话题的回复必须带免责或等价说法（"还是听医生的"）
3. **口吻**：必须是短句、口语、不用句号收尾（产品风格是换行代替句号）

不合格样本**宁可丢掉也不要进训练集** —— 训练数据错了，模型学到的就是错的。

用法：
    python scripts/synth_generate.py --batches 120      # 约 600 条候选
    python scripts/synth_generate.py --batches 1        # 冒烟测试
输出：
    data/synth/synth.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = Path(r"E:\比邻AI\server")
sys.path.insert(0, str(SERVER))

from app.persona.prompts import _has_medical_disclaimer, has_clinical_content, is_medical_question  # noqa: E402

SEED = ROOT / "data" / "seed" / "seed.jsonl"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "synth"

# ── 变化轴：让样本分布尽量铺开，而不是同一句话换个说法 ────────────
AXES_PERSONALITY = [
    "话少、问一句答一句的老人",
    "爱唠、一开口就停不下来的老人",
    "耳背，常常听岔、答非所问的老人",
    "爱操心、容易往坏处想的老人",
    "脾气倔、不太听劝的老人",
    "客气、总说麻烦你了的老人",
]
AXES_TIME = ["清早", "上午", "中午", "下午", "傍晚", "夜里"]
AXES_SCENE = [
    "刚吃完饭", "正在看电视", "刚从外面回来", "一个人在家", "家里来人",
    "天气不好出不去", "孙子刚走", "刚睡醒", "在等孩子电话",
]
AXES_EMOTION = ["平静", "有点闷", "高兴", "担心身体", "想念亲人", "有点委屈", "犯困"]

SYSTEM_RULES = """你在为"比邻AI"造训练数据。这是面向独居/慢病老人的陪伴助手。

判断回复好坏的标准（必须全部满足）：
1. 口吻像真人说话：短句，一行一句，**不用句号收尾**，可以用空格分隔
2. 称呼用"您"
3. 不给诊断（不能说"您这是××病"）
4. 不判断能不能停药/换药/加减量，一定推给医生
5. 医疗话题结尾要带免责（"仅供参考，实际情况请以医嘱为准，及时线下就医"
   或等价说法如"还是听医生的"）
6. 老人诉苦、聊家常、说孩子的事时，**不要加免责**，只陪着说话
7. 每条回复 40–120 字，超过 150 字就不像陪伴了
8. 不出现"您好 请问"这类客服腔"""


def load_env() -> dict:
    env = {}
    path = SERVER / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def call_model(messages: list[dict], env: dict, retries: int = 3) -> str:
    payload = json.dumps({
        "model": env.get("LLM_MODEL", "deepseek-chat"),
        "messages": messages,
        "temperature": 1.0,
        "max_tokens": 2200,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        env.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/") + "/chat/completions",
        data=payload,
        method="POST",
    )
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + env.get("LLM_API_KEY", ""))
    last = ""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:120]
            time.sleep(2 + attempt * 3)
    raise RuntimeError(last)


# ── 质量闸门 ────────────────────────────────────────────────────
RED_LINES = [
    (r"可以(把药)?停(药|掉)", "建议停药"),
    (r"把(药|降压药)停了", "建议停药"),
    (r"不用(吃|服)药了", "建议停药"),
    (r"吃(两|三|四|半)片", "给具体剂量"),
    (r"(加|减)(一|半)片", "让改剂量"),
    (r"不用(去)?医院", "劝阻就医"),
    (r"您这是(高血压|糖尿病|癌症|中风|痴呆|抑郁)", "下诊断"),
]


def check_pair(user: str, assistant: str) -> str:
    """返回空串=通过，否则返回拒绝原因。"""
    if not (2 <= len(user) <= 120):
        return "用户语句长度不合适"
    if not (20 <= len(assistant) <= 220):
        return "回复长度不合适（%d 字）" % len(assistant)
    for pattern, reason in RED_LINES:
        if re.search(pattern, assistant):
            return "红线：" + reason
    if re.search(r"您好[，,]?\s*请问|感谢您的", assistant):
        return "客服腔"
    if is_medical_question(user) or has_clinical_content(assistant):
        if not _has_medical_disclaimer(assistant):
            return "医疗内容缺免责"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=1, help="每次生成 5 条，批次数")
    parser.add_argument("--per-batch", type=int, default=5)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    env = load_env()

    # 种子做风格参考（只取少量，避免 prompt 过长）
    seeds = [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]
    style_examples = "\n".join(
        "老人：%s\n回复：%s" % (s["messages"][1]["content"], s["messages"][2]["content"])
        for s in seeds[:8]
    )
    scenes = [s["messages"][1]["content"] for s in seeds]

    # 真实原话，让"老人说话"这一侧更贴近真实语料
    real_elder: list[str] = []
    raw = RAW / "elder_utterances.jsonl"
    if raw.exists():
        real_elder = [json.loads(line)["text"] for line in raw.read_text(encoding="utf-8").splitlines() if line.strip()]

    path = OUT / "synth.jsonl"
    stats = {"kept": 0, "rejected": 0, "reasons": {}}
    seen: set[str] = set()

    with path.open("a", encoding="utf-8") as handle:
        for batch in range(args.batches):
            personality = random.choice(AXES_PERSONALITY)
            when = random.choice(AXES_TIME)
            scene = random.choice(AXES_SCENE)
            mood = random.choice(AXES_EMOTION)
            medical_seed = random.choice(scenes)

            real_hint = ""
            if real_elder:
                sample = random.sample(real_elder, min(6, len(real_elder)))
                real_hint = "\n真实老人的原话（学它们的说话方式，不要照抄）：\n" + "\n".join("- " + t for t in sample)

            prompt = f"""{SYSTEM_RULES}

## 这一批的设定
- 老人性格：{personality}
- 时间：{when}
- 处境：{scene}
- 情绪：{mood}
- 参考场景（取材方向之一，可以改造）：{medical_seed}

## 已有样本的风格参考
{style_examples}
{real_hint}

请造 **{args.per_batch} 条**全新的「老人说一句 / 助手回一句」样本，覆盖不同话题
（吃饭、睡眠、身体、孩子、孤单、家务、天气、邻里、看戏、下棋、买菜、去医院、吃药、想做的事）。

只输出 JSON 数组，不要解释：
[{{"user": "...", "assistant": "..."}}, ...]"""

            try:
                raw_text = call_model([
                    {"role": "system", "content": "你只输出 JSON 数组，不要任何解释文字。"},
                    {"role": "user", "content": prompt},
                ], env)
            except Exception as exc:  # noqa: BLE001
                print("  [批 %d] 调用失败：%s" % (batch + 1, exc), flush=True)
                continue

            # 抠 JSON
            start, end = raw_text.find("["), raw_text.rfind("]")
            if start < 0 or end <= start:
                print("  [批 %d] 输出不是 JSON，跳过" % (batch + 1), flush=True)
                continue
            try:
                items = json.loads(raw_text[start:end + 1])
            except Exception:
                print("  [批 %d] JSON 解析失败，跳过" % (batch + 1), flush=True)
                continue

            kept_this = 0
            for item in items if isinstance(items, list) else []:
                user = str(item.get("user") or "").strip()
                assistant = str(item.get("assistant") or "").strip()
                if not user or not assistant:
                    continue
                key = re.sub(r"\s", "", user)[:24]
                if key in seen:
                    stats["rejected"] += 1
                    stats["reasons"]["重复"] = stats["reasons"].get("重复", 0) + 1
                    continue
                reason = check_pair(user, assistant)
                if reason:
                    stats["rejected"] += 1
                    stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
                    continue
                seen.add(key)
                medical = is_medical_question(user)
                row = {
                    "messages": [
                        {"role": "system", "content": seeds[0]["messages"][0]["content"] if not medical else seeds[-1]["messages"][0]["content"]},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": assistant},
                    ],
                    "meta": {"persona": "medical" if medical else "daily", "source": "synth"},
                }
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                stats["kept"] += 1
                kept_this += 1
            print(
                "  [批 %d/%d] 收 %d 条（累计 %d，丢弃 %d）"
                % (batch + 1, args.batches, kept_this, stats["kept"], stats["rejected"]),
                flush=True,
            )

    print("\n=== 汇总 ===")
    print("  保留 %d 条，丢弃 %d 条" % (stats["kept"], stats["rejected"]))
    for reason, count in sorted(stats["reasons"].items(), key=lambda x: -x[1]):
        print("    %-24s %d" % (reason, count))
    print("  输出 %s" % path)


if __name__ == "__main__":
    main()
