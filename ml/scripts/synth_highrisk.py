"""定向补齐"高危信号 → 必须就医"的样本（带硬闸门）。

## 上一轮为什么漏了 4 条

跌倒、眼前一黑、认错人、胸口发闷 —— 微调后仍然没把老人往医院引，
而基座同样漏。原因不是数据量不够，是**数据里从来没教过这件事**：
合成的 543 条里，高危场景的回复本来就写得含糊，闸门只查"有没有免责"，
不查"有没有真的让他去看病"。

## 这一轮改两件事

1. **生成时强制**：提示词里写明"高危必须给明确就医指引，不许说年纪大了正常"
2. **入库前硬闸门**：高危场景的回复必须含 就医指向词，且不含正常化短语
   —— 不合格直接丢，绝不"改一改再用"

用法：
    python scripts/synth_highrisk.py --batches 24
输出：
    data/synth/highrisk.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = Path(r"E:\比邻AI\server")
sys.path.insert(0, str(SERVER))

from app.persona.prompts import (  # noqa: E402
    _has_medical_disclaimer,
    is_medical_question,
)

SEED = ROOT / "data" / "seed" / "seed.jsonl"
OUT = ROOT / "data" / "synth"

# ── 高危场景清单：这 8 类是不许含糊的 ──────────────────────────
HIGH_RISK = [
    ("跌倒", "在厕所/卧室/院子里摔了一跤，或者差点摔倒", "要问有没有伤到骨头、要不要拍片、必须让家人知道"),
    ("眼前一黑", "站起来或者走路时突然眼前发黑、头晕站不住", "要让他先坐下别动，并提示去查血压/贫血/心脏"),
    ("认错人", "把邻居、孙子、电视里的人认成别人，或者记不清刚才的事", "不能当'年纪大了正常'，要提示尽早去查认知"),
    ("胸口发闷", "胸口闷、喘不上气、心慌", "要立刻停止活动、马上联系家人或打急救"),
    ("便血", "大便带血，或者黑便", "要尽快去查，不能等"),
    ("呛咳", "喝水吃饭老呛着，或者噎住", "要提示查吞咽功能，反复呛要就医"),
    ("半边发麻", "半边身子发麻、说话不利索、嘴角歪", "要立刻打急救，不能观察"),
    ("忘事", "老忘事、刚说的就忘、找不到家", "要提示去查认知，别用'老了都这样'安慰"),
]

# 入库硬闸门
MUST_SEEK = ("医院", "医生", "急诊", "急救", "120", "去查", "检查", "拍片", "挂号", "门诊")
NORMALIZE = ("年纪大了都这样", "老了都这样", "正常的", "别往坏处想", "这不算病", "没什么大事")
RED_LINES = [
    (r"可以(把药)?停(药|掉)", "建议停药"),
    (r"(加|减)(一|半)片", "改剂量"),
    (r"您这是(高血压|糖尿病|癌症|中风|痴呆|抑郁)", "下诊断"),
]

SYSTEM = """你在为"比邻AI"造训练数据。这是面向独居/慢病老人的陪伴助手。

## 这一批的特殊要求（最重要）

老人在说**高危症状**（跌倒、眼前一黑、认错人、胸闷、便血、呛咳、半边发麻、忘事）。
这类情况**绝对不允许含糊过去**。回复必须做到：

1. **明确给出就医指向**：出现「医院」「医生」「急诊」「急救」「120」「去查」「检查」
   中的至少一个，而且要说得具体（去哪个科、要不要拍片、要不要打 120）
2. **绝对不许正常化**：不能说「年纪大了都这样」「老了都这样」「正常的」
   「别往坏处想」「没什么大事」「这不算病」
3. **先给当下能做的**：坐下别动、别自己起来、先别吃东西、让人陪着
4. **要联系家人**：提醒告诉子女或打给谁
5. 结尾带免责：「仅供参考，实际情况请以医嘱为准，及时线下就医」
6. 口吻：短句、一行一句、不用句号收尾、称呼用「您」

## 输出格式
只输出 JSON 数组：
[{"user": "老人说的话", "assistant": "助手回复"}, ...]"""


def load_env() -> dict:
    env = {}
    for line in (SERVER / ".env").read_text(encoding="utf-8").splitlines():
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
                return json.loads(response.read().decode("utf-8"))["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            last = str(exc)[:100]
            time.sleep(2 + attempt * 2)
    raise RuntimeError(last)


def check(user: str, reply: str) -> str:
    """空串=通过；否则返回拒绝原因。"""
    if not (4 <= len(user) <= 120):
        return "用户语句长度"
    if not (25 <= len(reply) <= 260):
        return "回复长度"
    for pattern, reason in RED_LINES:
        if re.search(pattern, reply):
            return "红线:" + reason
    if not any(word in reply for word in MUST_SEEK):
        return "高危未给就医指引"
    for phrase in NORMALIZE:
        if phrase in reply:
            return "把高危正常化:" + phrase
    if not _has_medical_disclaimer(reply):
        return "缺免责"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=24)
    parser.add_argument("--per-batch", type=int, default=4)
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    env = load_env()
    seeds = [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]
    medical_system = next(
        (s["messages"][0]["content"] for s in seeds if (s.get("meta") or {}).get("persona") == "medical"),
        seeds[-1]["messages"][0]["content"],
    )

    path = OUT / "highrisk.jsonl"
    stats = {"kept": 0, "rejected": 0, "reasons": {}}
    seen: set[str] = set()

    with path.open("a", encoding="utf-8") as handle:
        for batch in range(args.batches):
            name, desc, requirement = HIGH_RISK[batch % len(HIGH_RISK)]
            extra = random.choice([
                "老人一个人在家", "子女不在身边", "刚吃完饭", "夜里起来上厕所", "白天在院子里",
            ])
            prompt = f"""## 这一批的场景：{name}

老人说的是这类情况：{desc}
处境补充：{extra}
这一类的合格回复必须做到：{requirement}

请造 **{args.per_batch} 条**不同的说法（老人表达方式各不相同：有的直说、有的轻描淡写、
有的怕麻烦子女不肯说、有的反复问"要不要紧"）。
每条都必须满足前面【特殊要求】里的 6 条。"""

            try:
                raw = call_model([
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ], env)
            except Exception as exc:  # noqa: BLE001
                print("  [批 %d] 调用失败：%s" % (batch + 1, exc), flush=True)
                continue

            start, end = raw.find("["), raw.rfind("]")
            if start < 0 or end <= start:
                print("  [批 %d] 非 JSON，跳过" % (batch + 1), flush=True)
                continue
            try:
                items = json.loads(raw[start:end + 1])
            except Exception:
                print("  [批 %d] JSON 解析失败，跳过" % (batch + 1), flush=True)
                continue

            kept = 0
            for item in items if isinstance(items, list) else []:
                user = str(item.get("user") or "").strip()
                reply = str(item.get("assistant") or "").strip()
                if not user or not reply:
                    continue
                key = re.sub(r"\s", "", user)[:24]
                if key in seen:
                    stats["rejected"] += 1
                    stats["reasons"]["重复"] = stats["reasons"].get("重复", 0) + 1
                    continue
                reason = check(user, reply)
                if reason:
                    stats["rejected"] += 1
                    stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
                    continue
                seen.add(key)
                handle.write(json.dumps({
                    "messages": [
                        {"role": "system", "content": medical_system},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": reply},
                    ],
                    "meta": {"persona": "medical", "source": "highrisk", "risk": name},
                }, ensure_ascii=False) + "\n")
                handle.flush()
                stats["kept"] += 1
                kept += 1
            print("  [批 %d/%d｜%s] 收 %d 条（累计 %d，丢弃 %d）"
                  % (batch + 1, args.batches, name, kept, stats["kept"], stats["rejected"]), flush=True)

    print("\n=== 汇总 ===")
    print("  保留 %d 条，丢弃 %d 条" % (stats["kept"], stats["rejected"]))
    for reason, count in sorted(stats["reasons"].items(), key=lambda x: -x[1]):
        print("    %-26s %d" % (reason, count))
    print("  输出 %s" % path)


if __name__ == "__main__":
    main()
